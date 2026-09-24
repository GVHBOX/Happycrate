import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import api as api_mod
from app import config, core, query, sources


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

    def test_conservation_adds_up(self):
        self._wire([
            _same_hash_source("a", "A", size=10),
            _same_hash_source("b", "B", size=20),
            _same_hash_source("c", "C", size=30),
        ])
        _rows, done = self._run(["a", "b", "c"])
        last = done[-1]
        self.assertEqual(last["raw"], 3, "三个源各 1 条，原始共 3 条")
        self.assertEqual(last["total"], 1, "同一 hash 合并成 1 行")
        self.assertEqual(last["dup"], 2, "两条是重复")
        self.assertEqual(last["raw"] - last["dup"], last["total"])

    def test_conservation_counts_new_rows(self):
        def make(key, title, **extra):
            def fn(query, page=1, timeout=15, base="", batch=None):
                item = {"title": title, "info_hash": extra.pop("h", "a" * 40),
                        "source": key}
                item.update(extra)
                return [item]
            return fn
        self._wire([
            sources.Source("a", "A", make("a", "A", h="a" * 40), timeout=5),
            sources.Source("b", "B", make("b", "B", h="b" * 40), timeout=5),
            sources.Source("c", "C", make("c", "C", h="a" * 40), timeout=5),
        ])
        _rows, done = self._run(["a", "b", "c"])
        last = done[-1]
        self.assertEqual(last["raw"], 3)
        self.assertEqual(last["total"], 2)
        self.assertEqual(last["dup"], 1)
        self.assertEqual(last["raw"] - last["dup"], last["total"])


class RelaxTest(unittest.TestCase):

    def test_drops_quality_first(self):
        parsed = query.parse("沙丘 4K 2024")
        nxt, dropped = api_mod._relaxed_query(parsed)
        self.assertEqual(dropped, "4k")
        self.assertEqual(nxt, "沙丘 2024")

    def test_never_drops_subject(self):
        nxt, dropped = api_mod._relaxed_query(query.parse("流浪地球"))
        self.assertEqual((nxt, dropped), ("", ""))

    def test_drops_soft_before_giving_up_subject(self):
        parsed = query.parse("流浪地球 4K 中字")
        nxt, dropped = api_mod._relaxed_query(parsed)
        self.assertEqual(dropped, "4k")
        self.assertEqual(nxt, "流浪地球 中字")

    def test_browse_query_relaxes_then_stops(self):
        parsed = query.parse("电影 4K")
        nxt, dropped = api_mod._relaxed_query(parsed)
        self.assertEqual(dropped, "4k")
        self.assertEqual(api_mod._relaxed_query(query.parse(nxt)), ("", ""))

    def test_relax_respects_role_priority(self):
        parsed = query.parse("xxx 4K 中字 x265")
        first = api_mod._relaxed_query(parsed)
        self.assertEqual(first[1], "4k")


class SoftDeadlineTest(unittest.TestCase):

    def setUp(self):
        self.orig_all = sources.ALL_SOURCES
        self.orig_by = sources.BY_KEY
        self.tmpdir = tempfile.mkdtemp(prefix="hc-deadline-")
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

    def test_settled_arrives_before_slow_source(self):
        def slow(query, page=1, timeout=15, base="", batch=None):
            time.sleep(0.8)
            return [{"title": "slow item", "info_hash": "b" * 40, "source": "slow"}]

        def fast(query, page=1, timeout=15, base="", batch=None):
            return [{"title": "fast item", "info_hash": "a" * 40, "source": "fast"}]

        self._wire([
            sources.Source("fast", "FAST", fast, timeout=5),
            sources.Source("slow", "SLOW", slow, timeout=5),
        ])
        self.api._settings.set("soft_deadline_ms", 100)
        events = []
        self.api._push = lambda js: events.append(js)
        token = sources.start_batch()
        self.api._search_token = token
        self.api._search_worker(token, "item", ["fast", "slow"])

        settled = [i for i, e in enumerate(events) if "__onSearchSettled" in e]
        done = [i for i, e in enumerate(events) if "__onSearchDone" in e]
        self.assertEqual(len(settled), 1, "软截止应推送一次 settled")
        self.assertEqual(len(done), 1)
        self.assertLess(settled[0], done[0], "settled 应早于 done")

    def test_zero_deadline_disables_settle(self):
        self._wire([
            sources.Source("fast", "FAST",
                           lambda q, **kw: [{"title": "x", "info_hash": "a" * 40,
                                             "source": "fast"}], timeout=5),
        ])
        self.api._settings.set("soft_deadline_ms", 0)
        events = []
        self.api._push = lambda js: events.append(js)
        token = sources.start_batch()
        self.api._search_token = token
        self.api._search_worker(token, "x", ["fast"])
        self.assertFalse(any("__onSearchSettled" in e for e in events))

    def test_no_results_triggers_relaxed_retry(self):
        calls = []

        def empty_first(query, page=1, timeout=15, base="", batch=None):
            calls.append(query)
            if "4k" in query:
                return []
            return [{"title": "found", "info_hash": "a" * 40, "source": "s"}]

        self._wire([sources.Source("s", "S", empty_first, timeout=5)])
        self.api._settings.set("soft_deadline_ms", 0)
        events = []
        self.api._push = lambda js: events.append(js)
        token = sources.start_batch()
        self.api._search_token = token
        self.api._search_worker(token, "沙丘 4k", ["s"])

        self.assertEqual(calls, ["沙丘 4k", "沙丘"], "应去掉 4k 重搜一次")
        done = [e for e in events if "__onSearchDone" in e]
        self.assertEqual(len(done), 1)
        self.assertIn('"relaxed": "4k"', done[0])


class SearchCacheTest(unittest.TestCase):

    def setUp(self):
        self.orig_all = sources.ALL_SOURCES
        self.orig_by = sources.BY_KEY
        self.tmpdir = tempfile.mkdtemp(prefix="hc-cache-")
        self.api = api_mod.Api()
        self.api._cfg = config.Config(path=Path(self.tmpdir) / "sources.json")
        self.api._cfg.load()
        self.api._settings = config.Settings(path=Path(self.tmpdir) / "settings.json")
        self.api._settings.load()
        self.api._health_store = config.HealthStore(
            path=Path(self.tmpdir) / "health.json")
        sources.reload_from_config(self.api._cfg)
        self.api._settings.set("soft_deadline_ms", 0)

    def tearDown(self):
        sources.ALL_SOURCES = self.orig_all
        sources.BY_KEY = self.orig_by

    def _wire(self, srcs):
        sources.ALL_SOURCES = srcs
        sources.BY_KEY = {s.key: s for s in srcs}

    def _capture(self, text, keys):
        events = []
        self.api._push = lambda js: events.append(js)
        token = sources.start_batch()
        self.api._search_token = token
        self.api._search_worker(token, text, keys)
        return events

    def _done(self, events):
        return [e for e in events if "__onSearchDone" in e]

    def test_hit_reuses_rows_and_retries_failed_only(self):
        calls = {"a": 0, "b": 0}

        def a(query, page=1, timeout=15, base="", batch=None):
            calls["a"] += 1
            return [{"title": "A item", "info_hash": "a" * 40, "source": "a"}]

        def b(query, page=1, timeout=15, base="", batch=None):
            calls["b"] += 1
            if calls["b"] == 1:
                raise RuntimeError("boom")
            return [{"title": "B item", "info_hash": "b" * 40, "source": "b"}]

        self._wire([
            sources.Source("a", "A", a, timeout=5),
            sources.Source("b", "B", b, timeout=5),
        ])

        first = self._capture("query", ["a", "b"])
        self.assertEqual(calls["a"], 1)
        self.assertEqual(calls["b"], 1)
        self.assertIn('"total": 1', self._done(first)[0])
        self.assertIn('"b"', self._done(first)[0], "失败源应记入 errors")

        second = self._capture("query", ["a", "b"])
        self.assertEqual(calls["a"], 1, "成功的源应走缓存，不再请求")
        self.assertEqual(calls["b"], 2, "失败的源应重打")
        self.assertIn('"total": 2', self._done(second)[0], "重打成功后行数增加")
        self.assertTrue(any('"cached": true' in e for e in second),
                        "复用源的事件应带 cached 标记")
        last = self._done(second)[0]
        self.assertIn('"raw": 2', last)
        self.assertIn('"dup": 0', last)

    def test_second_hit_with_no_failures_skips_network(self):
        calls = {"a": 0}

        def a(query, page=1, timeout=15, base="", batch=None):
            calls["a"] += 1
            return [{"title": "A item", "info_hash": "a" * 40, "source": "a"}]

        self._wire([sources.Source("a", "A", a, timeout=5)])
        self._capture("solo", ["a"])
        second = self._capture("solo", ["a"])
        self.assertEqual(calls["a"], 1, "全成功时第二轮不应打任何源")
        self.assertIn('"total": 1', self._done(second)[0])

    def test_expired_cache_researches_everything(self):
        calls = {"a": 0}

        def a(query, page=1, timeout=15, base="", batch=None):
            calls["a"] += 1
            return [{"title": "A item", "info_hash": "a" * 40, "source": "a"}]

        self._wire([sources.Source("a", "A", a, timeout=5)])
        self._capture("old", ["a"])
        with self.api._search_cache_lock:
            for item in self.api._search_cache.values():
                item["ts"] -= api_mod.SEARCH_CACHE_TTL * 2
        self._capture("old", ["a"])
        self.assertEqual(calls["a"], 2, "过期缓存应全量重打")

    def test_cache_keeps_different_queries_apart(self):
        calls = {"a": 0}

        def a(query, page=1, timeout=15, base="", batch=None):
            calls["a"] += 1
            return [{"title": "A " + query, "info_hash": "a" * 40, "source": "a"}]

        self._wire([sources.Source("a", "A", a, timeout=5)])
        self._capture("one", ["a"])
        self._capture("two", ["a"])
        self.assertEqual(calls["a"], 2, "不同关键词不共用缓存")

    def test_cache_snapshot_isolated_from_merge(self):
        def a(query, page=1, timeout=15, base="", batch=None):
            return [{"title": "A item", "info_hash": "a" * 40, "source": "a"}]

        def b(query, page=1, timeout=15, base="", batch=None):
            return [{"title": "A item updated", "info_hash": "a" * 40,
                     "seeders": 99, "source": "b"}]

        self._wire([
            sources.Source("a", "A", a, timeout=5),
            sources.Source("b", "B", b, timeout=5),
        ])
        self._capture("merge", ["a"])
        self._capture("merge", ["a", "b"])
        with self.api._search_cache_lock:
            cached = [v for v in self.api._search_cache.values()]
        row = cached[-1]["rows"][0]
        self.assertIsInstance(row["sources"], list)


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

    def test_view_exposes_health_detail(self):
        health = {"state": "ok", "outcomes": ["ok", "empty"],
                  "lastOk": 1757848402, "lastCount": 7, "events": []}
        view = api_mod._to_view({"key": "c1", "label": "L"}, health)
        self.assertEqual(view["health"]["outcomes"], ["ok", "empty"])
        self.assertEqual(view["health"]["lastOk"], 1757848402)
        self.assertEqual(view["health"]["lastCount"], 7)


_CDATA_HASH = "0123456789abcdef0123456789abcdef01234567"


class MkCleanTest(unittest.TestCase):

    def test_mk_strips_cdata_and_decodes_entities(self):
        got = sources._mk(title="t", info_hash="<![CDATA[" + _CDATA_HASH + "]]>")
        self.assertEqual(got["info_hash"], _CDATA_HASH)
        self.assertEqual(got["magnet"],
                         "magnet:?xt=urn:btih:" + _CDATA_HASH + "&dn=t")
        self.assertEqual(sources._mk(title="t", info_hash="abc&amp;def")["info_hash"],
                         "abc&def")


if __name__ == "__main__":
    unittest.main()
