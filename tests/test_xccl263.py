import ast
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config, sources

XCCL_ITEM = """
<div class="search-item detail-width">
<div class="item-title" style="padding-left:4px;">
<h3><span class="cpill fileType1">影视</span>
<a title="{title}" href="/hash/{h}.html" target="_blank">{title}</a></h3>
</div>
<div class="item-list"style="padding-left:4px;">
<ul><li><span class="longtitle">视频.mp4</span>&nbsp;<span class="lightColor">102.4 MB</span></li></ul>
</div>
<div class="item-bar" style="font-size:11px;padding-left:4px;">
<span>文件大小:
<b class="cpill blue-pill">{size}</b>
</span>
<span>创建时间:&nbsp;<b>{date}</b></span>
<span>下载热度:&nbsp;<b>{heat}</b></span>
</div>
</div>
"""


def page(*items) -> str:
    return "<html><body>" + "".join(items) + "</body></html>"


def _source_module():
    import ast
    from pathlib import Path as _Path
    return ast.parse(_Path(sources.__file__).read_text(encoding="utf-8"))


def _call_name(node) -> str:
    return getattr(getattr(node, "func", None), "id", "")


def _keyword_literal(call, name):
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None


def _adapter_source_map() -> dict:
    out = {}
    for node in ast.walk(_source_module()):
        if not isinstance(node, ast.FunctionDef):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            if _call_name(sub) == "_mk":
                got = _keyword_literal(sub, "source")
                if got is not None:
                    out.setdefault(node.name, got)
            elif _call_name(sub) == "_parse_nyaa_rss":
                literals = [a.value for a in sub.args if isinstance(a, ast.Constant)]
                if len(literals) >= 2:
                    out.setdefault(node.name, literals[1])
    return out


def _emitted_source_literals() -> set:
    return {v for v in _adapter_source_map().values()}


class Xccl263ParseTest(unittest.TestCase):

    def test_reads_all_five_fields(self):
        html = page(XCCL_ITEM.format(
            title="Some Movie 1080p", h="a" * 40,
            size="1.96GB", date="2024-05-06", heat="5724"))
        items = sources._parse_xccl263(html)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["info_hash"], "a" * 40)
        self.assertEqual(it["title"], "Some Movie 1080p")
        self.assertEqual(it["size"], sources.parse_size("1.96GB"))
        self.assertEqual(it["seeders"], 5724)
        self.assertIsNotNone(it["added"])
        self.assertTrue(it["magnet"].startswith("magnet:?xt=urn:btih:" + "a" * 40))

    def test_heat_maps_to_seeders_column(self):
        html = page(XCCL_ITEM.format(
            title="x", h="b" * 40, size="1GB", date="2024-01-01", heat="1322"))
        self.assertEqual(sources._parse_xccl263(html)[0]["seeders"], 1322)

    def test_date_is_china_time(self):
        html = page(XCCL_ITEM.format(
            title="x", h="c" * 40, size="1GB", date="2024-01-01", heat="1"))
        expect = sources._ts_from_iso("2024-01-01T00:00:00+08:00")
        self.assertAlmostEqual(sources._parse_xccl263(html)[0]["added"], expect,
                               places=3)

    def test_zero_size_stays_zero(self):
        html = page(XCCL_ITEM.format(
            title="tiny.txt", h="d" * 40, size="0.0MB",
            date="2023-02-01", heat="3371"))
        self.assertEqual(sources._parse_xccl263(html)[0]["size"], 0)

    def test_dedups_repeated_hash(self):
        row = XCCL_ITEM.format(title="same", h="e" * 40,
                               size="1GB", date="2024-01-01", heat="2")
        self.assertEqual(len(sources._parse_xccl263(page(row, row))), 1)

    def test_ignores_blocks_without_hash(self):
        html = page("<div class=\"search-item\"><div>no hash</div></div>")
        self.assertEqual(sources._parse_xccl263(html), [])

    def test_real_empty_page_is_empty(self):
        self.assertEqual(sources._parse_xccl263("<html><body></body></html>"), [])

    def test_source_carries_the_source_key(self):
        html = page(XCCL_ITEM.format(
            title="x", h="f" * 40, size="1GB", date="2024-01-01", heat="1"))
        self.assertEqual(sources._parse_xccl263(html)[0]["source"], "xccl263")

    def test_builtin_adapters_emit_keys_not_labels(self):
        emitted = _emitted_source_literals()
        self.assertTrue(emitted, "没扫到任何 source= 字面量，护栏失效了")
        unknown = sorted(v for v in emitted if v not in sources.BUILTIN_KEYS)
        self.assertEqual(
            unknown, [],
            "内置源写出的 source 必须是自己的 key，界面靠 key 反查名称。"
            "写中文名（或写别的源的 key）会让「来源」列显示成另一回事，"
            "而且两个不同源会显示成同一个名字：" + repr(unknown))

    def test_each_adapter_emits_its_own_key(self):
        by_name = _adapter_source_map()
        wrong = []
        for key, (_label, fn) in sources._BUILTIN_ADAPTERS.items():
            emitted = by_name.get(fn.__name__)
            if emitted is not None and emitted != key:
                wrong.append((key, fn.__name__, emitted))
        self.assertEqual(
            wrong, [],
            "适配器写出的 source 与自己的 key 不一致（key, 函数, 实际写出）："
            + repr(wrong))


class Xccl263SearchTest(unittest.TestCase):

    def test_reads_two_pages_concurrently(self):
        urls = []

        def fake_get(url, **kw):
            urls.append(url)
            n = int(url.rsplit("-", 1)[-1].split(".html")[0])
            return page(XCCL_ITEM.format(
                title=f"row{n}", h=f"{n * 20:040x}",
                size="1GB", date="2024-01-01", heat="1"))

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_xccl263("q", 1, timeout=5)
        self.assertEqual(len(urls), sources.XCCL_PAGES)
        self.assertEqual(len(items), sources.XCCL_PAGES)

    def test_page_number_is_in_url(self):
        urls = []

        def fake_get(url, **kw):
            urls.append(url)
            return page()

        with mock.patch.object(sources, "http_get", fake_get):
            sources._search_xccl263("hello world", 1, timeout=5)
        self.assertEqual(len(urls), sources.XCCL_PAGES)
        for u in urls:
            self.assertIn("/search/kw-hello%20world-", u,
                          f"关键词要编码进路径：{u}")

    def test_raises_when_every_page_fails(self):
        def boom(url, **kw):
            raise OSError("network down")

        with mock.patch.object(sources, "http_get", boom):
            with self.assertRaises(OSError):
                sources._search_xccl263("q", 1, timeout=5)

    def test_partial_failure_still_returns_results(self):
        def half(url, **kw):
            if url.endswith("-2.html"):
                raise OSError("page 2 down")
            return page(XCCL_ITEM.format(
                title="ok", h="a" * 40, size="1GB",
                date="2024-01-01", heat="3"))

        with mock.patch.object(sources, "http_get", half):
            items = sources._search_xccl263("q", 1, timeout=5)
        self.assertEqual(len(items), 1)

    def test_worker_count_is_conservative(self):
        self.assertLessEqual(sources.XCCL_WORKERS, 2,
                             "该站 3 并发就返回 429/522，别加速")


class RetiredSourceTest(unittest.TestCase):

    def test_btdig_is_retired_and_gone_from_code(self):
        self.assertIn("btdig", config.RETIRED_SOURCES)
        self.assertNotIn("btdig", sources.BUILTIN_KEYS)
        self.assertFalse(hasattr(sources, "_search_btdig"))
        self.assertNotIn("btdig", sources.DEFAULT_BASES)

    def test_btdig_dropped_from_existing_config(self):
        cfg = config.Config.__new__(config.Config)
        cfg.broken = None
        cfg.data = {"version": 1, "sources": [
            {"key": "nyaa", "label": "Nyaa", "type": "builtin", "order": 0},
            {"key": "btdig", "label": "BTDigg", "type": "builtin", "order": 1},
        ]}
        cfg._normalize()
        keys = [e["key"] for e in cfg.sources]
        self.assertNotIn("btdig", keys)

    def test_new_builtin_is_added_to_existing_config(self):
        cfg = config.Config.__new__(config.Config)
        cfg.broken = None
        cfg.data = {"version": 1, "sources": [
            {"key": "nyaa", "label": "Nyaa", "type": "builtin", "order": 0},
        ]}
        cfg._normalize()
        self.assertIn("xccl263", [e["key"] for e in cfg.sources])

    def test_added_source_keeps_default_timeout(self):
        cfg = config.Config.__new__(config.Config)
        cfg.broken = None
        cfg.data = {"version": 1, "sources": []}
        cfg._normalize()
        entry = [e for e in cfg.sources if e["key"] == "xccl263"][0]
        default = [s for s in config.DEFAULT_SOURCES
                   if s["key"] == "xccl263"][0]
        self.assertEqual(entry["timeout"], default["timeout"])

    def test_orders_are_renumbered_after_removal(self):
        cfg = config.Config.__new__(config.Config)
        cfg.broken = None
        cfg.data = {"version": 1, "sources": [
            {"key": "a", "type": "builtin", "order": 0},
            {"key": "btdig", "type": "builtin", "order": 1},
            {"key": "b", "type": "builtin", "order": 2},
        ]}
        cfg._normalize()
        self.assertEqual([e["order"] for e in cfg.sources],
                         list(range(len(cfg.sources))))


class Xccl263RegisteredTest(unittest.TestCase):

    def test_in_builtin_adapters(self):
        self.assertIn("xccl263", sources.BUILTIN_KEYS)
        self.assertEqual(sources._BUILTIN_ADAPTERS["xccl263"][0], "小草磁力")

    def test_default_bases_has_host(self):
        self.assertEqual(sources.DEFAULT_BASES["xccl263"],
                         "https://www.xccl263.xyz")

    def test_in_default_sources(self):
        keys = [s["key"] for s in config.DEFAULT_SOURCES]
        self.assertIn("xccl263", keys)

    def test_base_override_wins(self):
        root = sources.base_of("xccl263", "https://mirror.example")
        self.assertEqual(root, "https://mirror.example")


if __name__ == "__main__":
    unittest.main()
