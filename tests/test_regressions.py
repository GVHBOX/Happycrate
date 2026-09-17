import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import api as api_mod
from app import config, core, sources, templates


def _same_hash_source(key, title, **extra):
    def fn(query, page=1, timeout=15, base="", batch=None):
        item = {"title": title, "info_hash": "a" * 40, "source": key}
        item.update(extra)
        return [item]
    return sources.Source(key, key.upper(), fn)


class StreamingMergeTest(unittest.TestCase):

    def setUp(self):
        self.orig_all = sources.ALL_SOURCES
        self.orig_by = sources.BY_KEY
        self.tmpdir = tempfile.mkdtemp(prefix="hc-merge-")
        self.api = api_mod.Api()
        self.api._cfg = config.Config(path=Path(self.tmpdir) / "sources.json")
        self.api._cfg.load()
        self.api._settings = config.Settings(path=Path(self.tmpdir) / "settings.json")
        self.api._settings.load()
        self.api._health_store = config.HealthStore(
            path=Path(self.tmpdir) / "health.json")
        sources.reload_from_config(self.api._cfg)

    def tearDown(self):
        sources.ALL_SOURCES = self.orig_all
        sources.BY_KEY = self.orig_by

    def _wire(self, srcs):
        sources.ALL_SOURCES = srcs
        sources.BY_KEY = {s.key: s for s in srcs}

    def _run(self, keys):
        pushed = []
        done = []
        self.api._push = lambda js: (
            pushed.append(json.loads(js.split("__onSearchBatch(", 1)[1].rsplit(")", 1)[0])["items"])
            if "__onSearchBatch" in js else
            (done.append(json.loads(js.split("__onSearchDone(", 1)[1].rsplit(")", 1)[0]))
             if "__onSearchDone" in js else None)
        )
        token = sources.start_batch()
        self.api._search_token = token
        self.api._search_worker(token, "ubuntu", keys)
        return [it for batch in pushed for it in batch], done

    def test_same_hash_is_merged_not_dropped(self):
        self._wire([
            _same_hash_source("poor", "Ubuntu 简繁字幕"),
            _same_hash_source("rich", "Ubuntu 1080p WEB-DL",
                              size=8 * 1024 ** 3, seeders=1200, added=1757848402),
        ])
        rows, _done = self._run(["poor", "rich"])

        self.assertEqual(len(rows), 2, "两个源各推一次，用于更新同一行")
        self.assertEqual(len({r["hash"] for r in rows}), 1,
                         "同一 info_hash 只应占一行")

        final = rows[-1]
        self.assertEqual(sorted(final["sources"]), ["poor", "rich"],
                         "合并后必须记住两个来源")
        self.assertEqual(final["sizeText"], "8.0 GB",
                         "合并后应保留更丰富那条的体积")
        self.assertEqual(final["seeders"], 1200)
        self.assertIn("1080p", final["title"])

    def test_total_counts_rows_not_pushes(self):
        self._wire([
            _same_hash_source("poor", "A"),
            _same_hash_source("rich", "B", size=100),
        ])
        _rows, done = self._run(["poor", "rich"])
        self.assertEqual(done[-1]["total"], 1,
                         "total 应是结果行数，不是推送次数")


class ProxyFatalTest(unittest.TestCase):

    def setUp(self):
        self.orig_all = sources.ALL_SOURCES
        self.orig_by = sources.BY_KEY

    def tearDown(self):
        sources.ALL_SOURCES = self.orig_all
        sources.BY_KEY = self.orig_by

    def test_one_proxy_failure_among_working_sources_is_not_fatal(self):
        def good(query, page=1, timeout=15, base="", batch=None):
            return [{"title": "hit", "info_hash": "c" * 40, "source": "G"}]

        def bad(query, page=1, timeout=15, base="", batch=None):
            raise sources.ProxyUnreachable("系统代理连不上")

        srcs = [sources.Source("g", "G", good), sources.Source("b", "B", bad)]
        sources.ALL_SOURCES = srcs
        sources.BY_KEY = {s.key: s for s in srcs}

        result, fatal = core.search("query", 1, 5, ["g", "b"], collect=False)
        self.assertIsNone(fatal, "有源成功时不该报致命网络错误")
        self.assertIn("b", result.errors)

    def test_all_sources_proxy_failure_is_fatal(self):
        def bad(query, page=1, timeout=15, base="", batch=None):
            raise sources.ProxyUnreachable(sources.proxy_hint())

        srcs = [sources.Source("b1", "B1", bad), sources.Source("b2", "B2", bad)]
        sources.ALL_SOURCES = srcs
        sources.BY_KEY = {s.key: s for s in srcs}

        _result, fatal = core.search("query", 1, 5, ["b1", "b2"], collect=False)
        self.assertIsNotNone(fatal, "所有源都被代理挡住时才该报致命")

    def test_empty_results_do_not_count_as_reached(self):
        def empty(query, page=1, timeout=15, base="", batch=None):
            return []

        def bad(query, page=1, timeout=15, base="", batch=None):
            raise sources.ProxyUnreachable(sources.proxy_hint())

        srcs = [sources.Source("e", "E", empty), sources.Source("b", "B", bad)]
        sources.ALL_SOURCES = srcs
        sources.BY_KEY = {s.key: s for s in srcs}
        _result, fatal = core.search("query", 1, 5, ["e", "b"], collect=False)
        self.assertIsNone(fatal, "连上了只是没内容，不算被代理挡住")


class PerSourceTimeoutTest(unittest.TestCase):

    def setUp(self):
        self.orig_all = sources.ALL_SOURCES
        self.orig_by = sources.BY_KEY

    def tearDown(self):
        sources.ALL_SOURCES = self.orig_all
        sources.BY_KEY = self.orig_by

    def test_search_uses_source_timeout(self):
        seen = {}

        def spy(query, page=1, timeout=15, base="", batch=None):
            seen["timeout"] = timeout
            return []

        src = sources.Source("slow", "慢源", spy, enabled=True, timeout=60)
        sources.ALL_SOURCES = [src]
        sources.BY_KEY = {"slow": src}

        sources.search_many("q", 1, None, enabled=["slow"])
        self.assertEqual(seen["timeout"], 60,
                         "搜索必须用源级超时，否则配置项形同虚设")

    def test_explicit_timeout_still_overrides(self):
        seen = {}

        def spy(query, page=1, timeout=15, base="", batch=None):
            seen["timeout"] = timeout
            return []

        src = sources.Source("slow", "慢源", spy, enabled=True, timeout=60)
        sources.ALL_SOURCES = [src]
        sources.BY_KEY = {"slow": src}

        sources.search_many("q", 1, 12, enabled=["slow"])
        self.assertEqual(seen["timeout"], 12, "显式超时仍应能覆盖源级值")


class JsonAddedValueTest(unittest.TestCase):

    def test_unix_int_is_kept(self):
        self.assertEqual(templates._added_value(1757848402, sources), 1757848402.0)

    def test_unix_string_is_kept(self):
        self.assertEqual(templates._added_value("1757848402", sources), 1757848402.0)

    def test_iso_string_still_parsed(self):
        got = templates._added_value("2025-09-14T12:00:00Z", sources)
        self.assertIsNotNone(got)
        self.assertGreater(got, 1_700_000_000)

    def test_zero_and_negative_rejected(self):
        self.assertIsNone(templates._added_value(0, sources))
        self.assertIsNone(templates._added_value(-5, sources))

    def test_bool_rejected(self):
        self.assertIsNone(templates._added_value(True, sources))

    def test_garbage_returns_none(self):
        self.assertIsNone(templates._added_value("not a date", sources))


class SettingReasonTest(unittest.TestCase):

    def setUp(self):
        self.s = config.Settings(path=tempfile.mktemp(suffix=".json"))
        self.s.load()

    def test_rejected_fields_carry_chinese_reason(self):
        bad = self.s.update(timeout=9999)
        self.assertEqual(len(bad), 1)
        self.assertIn("超时", bad[0])
        self.assertNotEqual(bad[0], "timeout", "不能把英文键名丢给用户看")

    def test_reason_mentions_range(self):
        self.assertIn("1-120", config.Settings.reason("timeout"))

    def test_unknown_key_is_not_stored(self):
        self.assertFalse(self.s.set("自定义垃圾键", {"x": 1}))
        self.assertNotIn("自定义垃圾键", self.s.data)

    def test_migrated_from_survives_load(self):
        path = tempfile.mktemp(suffix=".json")
        Path(path).write_text(json.dumps({
            "timeout": 20,
            "migrated_from": {"path": "D:\\AI\\CLB\\data", "at": "2026-09-12T14:42:45"},
        }, ensure_ascii=False), encoding="utf-8")
        s = config.Settings(path=path).load()
        self.assertEqual(s.get("timeout"), 20)
        self.assertIn("migrated_from", s.data, "迁移标记必须保留，否则会重复迁移")

    def test_save_does_not_write_stray_keys(self):
        path = tempfile.mktemp(suffix=".json")
        self.s.path = path
        self.s.set("垃圾", 1)
        self.s.save()
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertNotIn("垃圾", payload)


class TempFileSweepTest(unittest.TestCase):

    def test_sweep_removes_own_prefix_only(self):
        d = tempfile.mkdtemp(prefix="hc-sweep-")
        (Path(d) / f"{config.TMP_PREFIX}abc.json").write_text("{}", encoding="utf-8")
        (Path(d) / f"{config.TMP_PREFIX}def.json").write_text("{}", encoding="utf-8")
        keep = Path(d) / "sources.json"
        keep.write_text("{}", encoding="utf-8")

        removed = config.sweep_temp_files(d)
        self.assertEqual(removed, 2)
        self.assertTrue(keep.is_file(), "不能删掉真配置")
        self.assertEqual([p.name for p in Path(d).iterdir()], ["sources.json"])

    def test_sweep_on_missing_dir_is_safe(self):
        self.assertEqual(config.sweep_temp_files(
            tempfile.mkdtemp() + os.sep + "nope"), 0)


class Base32FalsePositiveTest(unittest.TestCase):

    def test_all_zero_hash_rejected(self):
        self.assertEqual(sources.hash_from_text("A" * 32), "",
                         "全零 base32 是解码噪声，不是真种子")

    def test_real_base32_still_decoded(self):
        import base64
        raw = bytes.fromhex("b" * 40)
        encoded = base64.b32encode(raw).decode()
        self.assertEqual(sources.hash_from_text(encoded), "b" * 40)

    def test_hex_hash_still_wins(self):
        self.assertEqual(sources.hash_from_text("a" * 40), "a" * 40)


class SslDemotionTest(unittest.TestCase):

    def setUp(self):
        sources.reset_ssl_lax()

    def tearDown(self):
        sources.reset_ssl_lax()

    def test_urlerror_wrapped_cert_error_is_detected(self):
        import ssl
        import urllib.error
        inner = ssl.SSLCertVerificationError("certificate verify failed")
        wrapped = urllib.error.URLError(inner)
        self.assertTrue(sources._cert_failure(wrapped),
                        "urllib 会把 SSLError 包进 URLError，必须能剥开")

    def test_plain_urlerror_is_not_cert_failure(self):
        import urllib.error
        self.assertFalse(sources._cert_failure(
            urllib.error.URLError("getaddrinfo failed")))

    def test_timeout_error_is_not_cert_failure(self):
        self.assertFalse(sources._cert_failure(TimeoutError("timed out")))

    def test_demote_marks_host(self):
        sources._demote_ssl("https://selfsigned.example/a", ssl_error())
        self.assertTrue(sources.ssl_known_lax("https://selfsigned.example/b"))


def ssl_error():
    import ssl
    return ssl.SSLCertVerificationError("certificate verify failed")


class LoadErrorTextBoxTest(unittest.TestCase):

    def test_offline_cert_error_string_is_recognised(self):
        import urllib.error
        exc = urllib.error.URLError(
            "SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed")
        self.assertTrue(sources._cert_failure(exc),
                        "字符串形式的证书错误也要认，不同 Python 包装层不一样")


class AutoOrderToggleTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="hc-autoorder-")
        self.api = api_mod.Api()
        self.api._cfg = config.Config(path=Path(self.tmpdir) / "sources.json")
        self.api._cfg.load()
        self.api._settings = config.Settings(path=Path(self.tmpdir) / "settings.json")
        self.api._settings.load()
        self.api._health_store = config.HealthStore(path=Path(self.tmpdir) / "health.json")

    def test_auto_order_reported_when_never_locked(self):
        self.assertTrue(self.api.app_info()["autoOrder"])

    def test_manual_reorder_locks_and_is_visible(self):
        self.api.reorder_sources(["nyaa", "apibay"])
        self.assertTrue(self.api._cfg.order_locked())
        self.assertFalse(self.api.app_info()["autoOrder"],
                         "锁上之后界面必须能看出自动排序已关")

    def test_turning_auto_order_back_on_unlocks(self):
        self.api.reorder_sources(["nyaa", "apibay"])
        self.api.set_auto_order(True)
        self.assertFalse(self.api._cfg.order_locked())
        self.assertTrue(self.api.app_info()["autoOrder"],
                        "必须能解锁，否则用户被永久困在手动顺序里")

    def test_demotion_resumes_after_unlock(self):
        api = self.api
        for _ in range(api_mod.HEALTH_WINDOW):
            api._mark("nyaa", False, 0, 100, "HTTP 503")
        api.reorder_sources(["nyaa", "apibay"])
        before = [e["key"] for e in api._cfg.sources]
        api._demote_bad()
        self.assertEqual([e["key"] for e in api._cfg.sources], before,
                         "锁定时不该自动降级")
        api.set_auto_order(True)
        self.assertEqual(api._cfg.sources[-1]["key"], "nyaa",
                         "解锁后坏源应被排到最后")


class SaveSourceGuardTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="hc-save-")
        self.api = api_mod.Api()
        self.api._cfg = config.Config(path=Path(self.tmpdir) / "sources.json")
        self.api._cfg.load()
        self.api._settings = config.Settings(path=Path(self.tmpdir) / "settings.json")
        self.api._settings.load()
        self.api._health_store = config.HealthStore(path=Path(self.tmpdir) / "health.json")
        sources.reload_from_config(self.api._cfg)

    def test_editing_missing_key_is_rejected(self):
        result = self.api.save_source({
            "key": "typo_key", "label": "L", "type": "json",
            "url": "https://a.example/s?q={query}", "listPath": "a.b",
            "map": {"title": "t"}, "timeout": 15, "isNew": False,
        })
        self.assertFalse(result.get("ok"),
                         "明确是编辑但 key 不存在时，应当报错而不是静默新建")
        self.assertTrue(result.get("errors"))

    def test_new_source_still_creates(self):
        result = self.api.save_source({
            "key": "custom1", "label": "C1", "type": "json",
            "url": "https://a.example/s?q={query}", "listPath": "a.b",
            "map": {"title": "t"}, "timeout": 15,
        })
        self.assertTrue(result.get("ok"), result.get("errors"))

    def test_explicit_new_flag_allows_creation(self):
        result = self.api.save_source({
            "key": "custom2", "label": "C2", "type": "html",
            "url": "https://a.example/s?q={query}", "timeout": 15, "isNew": True,
        })
        self.assertTrue(result.get("ok"), result.get("errors"))


class FilesCapTest(unittest.TestCase):

    def test_inline_files_are_not_truncated_to_eight(self):
        raw = [{"n": f"f{i}.mkv", "s": "1 MB"} for i in range(20)]
        view = api_mod._item_view({"info_hash": "a" * 40, "title": "t", "files": raw})
        self.assertEqual(len(view["files"]), 20,
                         "内联文件清单不该被悄悄砍到 8 条")

    def test_cap_matches_interface_cap(self):
        raw = [{"n": f"f{i}.mkv", "s": "1 MB"} for i in range(api_mod.FILES_CAP + 50)]
        view = api_mod._item_view({"info_hash": "a" * 40, "title": "t", "files": raw})
        self.assertEqual(len(view["files"]), api_mod.FILES_CAP)


class SourceViewKeysTest(unittest.TestCase):

    def test_view_exposes_pattern_fields(self):
        entry = {"key": "c1", "label": "L", "type": "html",
                 "url": "https://a/", "hash_pattern": "HP",
                 "title_pattern": "TP", "size_pattern": "SP"}
        view = api_mod._to_view(entry)
        self.assertEqual(view["hashPattern"], "HP")
        self.assertEqual(view["titlePattern"], "TP")
        self.assertEqual(view["sizePattern"], "SP")

    def test_view_exposes_health_detail(self):
        health = {"state": "ok", "outcomes": ["ok", "empty"],
                  "lastOk": 1757848402, "lastCount": 7, "events": []}
        view = api_mod._to_view({"key": "c1", "label": "L"}, health)
        self.assertEqual(view["health"]["outcomes"], ["ok", "empty"])
        self.assertEqual(view["health"]["lastOk"], 1757848402)
        self.assertEqual(view["health"]["lastCount"], 7)


if __name__ == "__main__":
    unittest.main()
