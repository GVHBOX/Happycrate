import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import api as api_mod
from app import sources

REAL_TITLES = [
    "Spider-Man: Brand New Day 2026.1080p.HQ Pre.Multi.AAC 2.0.x264",
    "Obsession.2026.1080p.AMZN.WEB-DL.DDP5.1.H264.MP4-BTM",
    "Ted Lasso S04E07 Yes and Baby 1080p ATVP WEB-DL DDP5 1 Atmos H",
]


def apibay_payload(titles, seed=1):
    return json.dumps([
        {"id": str(i + seed), "name": t, "info_hash": f"{i + seed:040x}",
         "size": "1000000", "seeders": "10", "leechers": "1",
         "added": "1700000000", "category": "207"}
        for i, t in enumerate(titles)
    ])


class ApibayRelevanceTest(unittest.TestCase):

    def search(self, query, titles):
        with mock.patch.object(sources, "http_get",
                               lambda url, **kw: apibay_payload(titles)):
            return sources._search_apibay(query, 1, 5)

    def test_keeps_results_that_contain_keyword(self):
        items = self.search("1080p", REAL_TITLES)
        self.assertEqual(len(items), 3)

    def test_keeps_case_insensitive_match(self):
        self.assertEqual(len(self.search("SPIDER-MAN", REAL_TITLES)), 3)
        self.assertEqual(len(self.search("spider-man", REAL_TITLES)), 3)

    def test_drops_fallback_list_when_keyword_ignored(self):
        items = self.search("流浪地球", REAL_TITLES)
        self.assertEqual(items, [],
                         "apibay 对中文词返回的是热门兜底列表，必须按无结果处理")

    def test_drops_fallback_for_symbols(self):
        for q in ("...", "%", "李", "進撃の巨人"):
            with self.subTest(q=q):
                self.assertEqual(self.search(q, REAL_TITLES), [])

    def test_token_match_accepts_partial_words(self):
        self.assertEqual(len(self.search("Spider-Man", REAL_TITLES)), 3)

    def test_short_ascii_token_still_matches(self):
        titles = ["Ubuntu 24.04 desktop amd64 iso"]
        self.assertEqual(len(self.search("ubuntu", titles)), 1)

    def test_no_placeholder_row_leaks(self):
        payload = json.dumps([{"id": "0", "name": "No results returned",
                               "info_hash": "0" * 40, "size": "0",
                               "seeders": "0", "leechers": "0",
                               "added": "0", "category": "0"}])
        with mock.patch.object(sources, "http_get", lambda url, **kw: payload):
            self.assertEqual(sources._search_apibay("1080p", 1, 5), [])

    def test_returns_empty_unchanged_when_source_is_empty(self):
        with mock.patch.object(sources, "http_get", lambda url, **kw: "[]"):
            self.assertEqual(sources._search_apibay("流浪地球", 1, 5), [])


class QueryLengthTest(unittest.TestCase):

    def test_limit_is_reasonable(self):
        self.assertGreaterEqual(api_mod.MAX_QUERY_LEN, 32)
        self.assertLessEqual(api_mod.MAX_QUERY_LEN, 500)

    def test_within_limit_passes(self):
        self.assertFalse(api_mod.is_query_too_long("x" * api_mod.MAX_QUERY_LEN))

    def test_over_limit_is_rejected(self):
        self.assertTrue(api_mod.is_query_too_long(
            "x" * (api_mod.MAX_QUERY_LEN + 1)))

    def test_empty_is_not_length_error(self):
        self.assertFalse(api_mod.is_query_too_long(""))

    def test_name_says_what_the_result_means(self):
        self.assertFalse(hasattr(api_mod, "validate_query_length"),
                         "旧名字读起来是「校验通过」，实际返回 True 表示超长")
        self.assertRegex(
            (ROOT / "app" / "api.py").read_text(encoding="utf-8"),
            r"if is_query_too_long\(text\):",
            "调用点要跟着改名，否则 if 的语义是反的")

    def test_start_search_rejects_over_long_before_hitting_sources(self):
        api = api_mod.Api()
        api._settings.data["min_query_len"] = 2
        called = []

        def boom(*a, **kw):
            called.append(1)
            return {}

        with mock.patch.object(sources, "search_many", boom):
            res = api.start_search("x" * (api_mod.MAX_QUERY_LEN + 1))
        self.assertFalse(res["ok"])
        self.assertIn("最长", res["error"])
        self.assertEqual(called, [], "超长关键词不该打到源站")

    def test_frontend_mirrors_the_same_limit(self):
        js = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        m = re.search(r"var MAX_QUERY_LEN = (\d+);", js)
        self.assertIsNotNone(m, "前端的 mock 也要有长度上限，两种跑法才一致")
        self.assertEqual(int(m.group(1)), api_mod.MAX_QUERY_LEN,
                         "前后端上限必须一致，否则直开网页与真机行为不同")


class PaginationRealityTest(unittest.TestCase):

    def test_app_only_ever_requests_first_page(self):
        src = (ROOT / "app" / "api.py").read_text(encoding="utf-8")
        self.assertIn("text, 1, None, keys", src,
                      "应用固定只搜第一页；若将来加翻页，需先确认哪些源真的支持")

    def test_nyaa_pagination_note(self):
        src = (ROOT / "app" / "sources.py").read_text(encoding="utf-8")
        block = src.split("def _search_nyaa", 1)[1][:400]
        self.assertIn("p={int(page)}", block,
                      "nyaa 的分页参数要照实传；源站当前忽略它，但不是我们的 bug")


if __name__ == "__main__":
    unittest.main()


class NoProxyDiagnosisTest(unittest.TestCase):

    KEYS = ["nyaa", "apibay", "mikan", "dmhy", "sukebei",
            "eztv", "bitsearch", "tpb", "xccl263"]

    def hint(self, errors, proxy):
        with mock.patch.object(sources, "proxy_info", lambda: proxy):
            return sources.proxy_hint_for(errors)

    def test_no_proxy_plus_widespread_timeout_names_the_cause(self):
        errors = {k: "URLError: <urlopen error timed out>" for k in self.KEYS}
        msg = self.hint(errors, {})
        self.assertIn("未检测到代理", msg)
        self.assertIn("代理", msg)

    def test_configured_proxy_still_gets_its_own_message(self):
        errors = {k: "URLError: <urlopen error timed out>" for k in self.KEYS}
        msg = self.hint(errors, {"https": "http://127.0.0.1:7890"})
        self.assertIn("127.0.0.1:7890", msg)
        self.assertNotIn("未检测到代理", msg)

    def test_single_overseas_timeout_is_not_blamed_on_proxy(self):
        errors = {"nyaa": "timed out", "apibay": "HTTP 500", "mikan": "HTTP 500"}
        msg = self.hint(errors, {})
        self.assertNotIn("未检测到代理", msg,
                         "只有一个源超时说明不了缺代理，别误导用户")

    def test_server_errors_do_not_mention_proxy(self):
        errors = {k: "HTTP 500" for k in self.KEYS}
        self.assertNotIn("未检测到代理", self.hint(errors, {}))

    def test_chinese_timeout_text_is_recognized(self):
        errors = {k: "超时" for k in self.KEYS}
        self.assertIn("未检测到代理", self.hint(errors, {}))

    def test_empty_errors_fall_back_to_generic(self):
        self.assertEqual(self.hint({}, {}), "网络请求失败，请检查网络连接。")

    def test_overseas_set_covers_the_known_walled_sources(self):
        for key in ("nyaa", "sukebei", "mikan", "dmhy", "eztv", "bitsearch", "tpb"):
            self.assertIn(key, sources._OVERSEAS_KEYS)

    def test_search_surfaces_the_hint_as_fatal(self):
        from app import core
        errors = {k: "URLError: timed out" for k in self.KEYS}

        def fake_many(*a, **kw):
            return {k: ([], "URLError: <urlopen error timed out>", 1)
                    for k in self.KEYS}

        with mock.patch.object(sources, "search_many", fake_many):
            with mock.patch.object(sources, "proxy_info", lambda: {}):
                _res, fatal = core.search("1080p", 1, None, self.KEYS, min_len=2)
        self.assertIsNotNone(fatal, "全源超时且无代理时必须给出整体提示")
        self.assertIn("未检测到代理", fatal)


class ProxyParseTest(unittest.TestCase):

    def parse(self, raw):
        return sources.parse_proxy(raw)

    def test_empty_is_allowed(self):
        self.assertEqual(self.parse(""), ({}, ""))

    def test_single_http_applies_to_both(self):
        m, err = self.parse("http://127.0.0.1:7890")
        self.assertEqual(err, "")
        self.assertEqual(m["http"], "http://127.0.0.1:7890")
        self.assertEqual(m["https"], "http://127.0.0.1:7890")

    def test_scheme_is_completed_when_missing(self):
        m, err = self.parse("127.0.0.1:7890")
        self.assertEqual(err, "")
        self.assertEqual(m["http"], "http://127.0.0.1:7890")

    def test_split_pair_is_kept_whole(self):
        m, err = self.parse("http://a:7890;https://b:7891")
        self.assertEqual(err, "")
        self.assertEqual(m, {"http": "http://a:7890", "https": "https://b:7891"})

    def test_duplicate_type_is_rejected_not_silently_overwritten(self):
        m, err = self.parse("http://a:7890;http://b:7891")
        self.assertEqual(m, {})
        self.assertIn("重复", err, "旧实现会静默丢掉前一段，必须改成明确报错")

    def test_socks_is_rejected_with_actionable_reason(self):
        for raw in ("socks5://127.0.0.1:7891", "socks4://127.0.0.1:7891",
                    "socks://127.0.0.1:7891"):
            with self.subTest(raw=raw):
                m, err = self.parse(raw)
                self.assertEqual(m, {})
                self.assertIn("HTTP", err, "要告诉用户改填 HTTP 端口")

    def test_socks_inside_pair_is_also_rejected(self):
        m, err = self.parse("http://a:7890;socks5://b:7891")
        self.assertEqual(m, {})
        self.assertIn("socks", err)

    def test_unknown_scheme_is_rejected(self):
        m, err = self.parse("ftp://127.0.0.1:7890")
        self.assertEqual(m, {})
        self.assertIn("无法识别", err)

    def test_missing_host_is_rejected(self):
        m, err = self.parse("http://")
        self.assertEqual(m, {})
        self.assertIn("主机名", err)

    def test_trailing_semicolon_is_tolerated(self):
        m, err = self.parse("http://127.0.0.1:7890;")
        self.assertEqual(err, "")
        self.assertEqual(m["http"], "http://127.0.0.1:7890")

    def test_whitespace_is_trimmed(self):
        m, err = self.parse("  http://127.0.0.1:7890  ")
        self.assertEqual(err, "")
        self.assertEqual(m["http"], "http://127.0.0.1:7890")

    def test_manual_proxy_returns_what_parse_produced(self):
        from app import runtime
        runtime.replace({"proxy": "http://a:7890;https://b:7891"})
        try:
            self.assertEqual(sources._manual_proxy(),
                             {"http": "http://a:7890", "https": "https://b:7891"})
        finally:
            runtime.replace({"proxy": ""})

    def test_manual_proxy_drops_invalid_rather_than_misrouting(self):
        from app import runtime
        runtime.replace({"proxy": "socks5://127.0.0.1:7891"})
        try:
            self.assertEqual(sources._manual_proxy(), {},
                             "解析失败时不能把坏地址当成代理用")
        finally:
            runtime.replace({"proxy": ""})

    def test_save_settings_rejects_the_same_inputs(self):
        from app import api as api_mod
        api = api_mod.Api()
        for raw in ("socks5://127.0.0.1:7891", "http://a:1;http://b:2",
                    "ftp://x:1"):
            with self.subTest(raw=raw):
                res = api.save_settings({"proxy": raw})
                self.assertFalse(res["ok"])
                self.assertTrue(res["errors"])

    def test_save_settings_accepts_valid_input(self):
        from app import api as api_mod
        api = api_mod.Api()
        res = api.save_settings({"proxy": "http://127.0.0.1:7890"})
        self.assertTrue(res["ok"], res)

    def test_save_settings_accepts_empty(self):
        from app import api as api_mod
        api = api_mod.Api()
        self.assertTrue(api.save_settings({"proxy": ""})["ok"])


class ProxyStatusTest(unittest.TestCase):

    def test_status_reports_whether_proxy_really_works(self):
        with mock.patch.object(sources, "_manual_proxy", lambda: {}), \
             mock.patch.object(sources.urllib.request, "getproxies",
                               lambda: {"https": "http://127.0.0.1:7890"}), \
             mock.patch.object(sources, "_probe_port", lambda a: True), \
             mock.patch.object(sources, "_proxy_works", lambda m: False):
            st = sources.proxy_status()
        self.assertTrue(st["portOk"])
        self.assertFalse(st["works"],
                         "端口通但代理不转发请求，必须暴露出来而不是显示正常")

    def test_works_true_when_proxy_actually_forwards(self):
        with mock.patch.object(sources, "_manual_proxy",
                               lambda: {"http": "http://x:1"}), \
             mock.patch.object(sources, "_probe_port", lambda a: True), \
             mock.patch.object(sources, "_proxy_works", lambda m: True):
            st = sources.proxy_status()
        self.assertTrue(st["works"])

    def test_no_proxy_skips_the_network_probe(self):
        called = []
        with mock.patch.object(sources, "_manual_proxy", lambda: {}), \
             mock.patch.object(sources.urllib.request, "getproxies", lambda: {}), \
             mock.patch.object(sources, "_proxy_works",
                               lambda m: called.append(m) or True):
            st = sources.proxy_status()
        self.assertEqual(st["mode"], "none")
        self.assertFalse(st["works"])
        self.assertEqual(called, [], "没配代理就不该去试探")

    def test_dead_port_skips_the_http_probe(self):
        called = []
        with mock.patch.object(sources, "_manual_proxy",
                               lambda: {"http": "http://127.0.0.1:65530"}), \
             mock.patch.object(sources, "_probe_port", lambda a: False), \
             mock.patch.object(sources, "_proxy_works",
                               lambda m: called.append(m) or False):
            st = sources.proxy_status(force=True)
        self.assertFalse(st["portOk"])
        self.assertEqual(called, [],
                         "端口都不通就不必再发 HTTP 探测，那是多等一个超时")

    def test_status_is_reused_within_the_ttl(self):
        called = []
        with mock.patch.object(sources, "_manual_proxy",
                               lambda: {"http": "http://127.0.0.1:65531"}), \
             mock.patch.object(sources, "_probe_port", lambda a: True), \
             mock.patch.object(sources, "_proxy_works",
                               lambda m: called.append(m) or True):
            sources.proxy_status(force=True)
            sources.proxy_status()
            sources.proxy_status()
        self.assertEqual(len(called), 1,
                         "设置页每次重绘都真探测一次会让界面冻结，结果要在 TTL 内复用")

    def test_force_bypasses_the_cache(self):
        called = []
        with mock.patch.object(sources, "_manual_proxy",
                               lambda: {"http": "http://127.0.0.1:65532"}), \
             mock.patch.object(sources, "_probe_port", lambda a: True), \
             mock.patch.object(sources, "_proxy_works",
                               lambda m: called.append(m) or True):
            sources.proxy_status(force=True)
            sources.proxy_status(force=True)
        self.assertEqual(len(called), 2, "手动点重新检测必须真的重测")

    def test_probe_timeout_stays_short(self):
        self.assertLessEqual(sources.PROBE_TIMEOUT, 2,
                             "proxy_status 跑在界面线程上，超时放长就是卡住窗口")

    def test_frontend_recheck_forces_a_fresh_probe(self):
        js = (ROOT / "web" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
        self.assertRegex(js, r"#btnNetRecheck\"\)\.onclick[\s\S]{0,80}netCheck\(true\)",
                         "重新检测按钮必须绕过缓存，否则点了也没变化")

    def test_first_check_waits_for_paint(self):
        js = (ROOT / "web" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
        self.assertRegex(js, r"setTimeout\(netCheck",
                         "自动检测要延到首帧之后，否则设置页会白一下才出来")

    def test_frontend_reads_the_works_field(self):
        js = (ROOT / "web" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
        self.assertIn("data.works", js,
                      "后端给了 works，前端不读就白做")

    def test_frontend_has_its_own_false_positive_message(self):
        js = (ROOT / "web" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
        self.assertIn("没有转发请求", js)

    def test_mock_proxy_status_carries_works(self):
        js = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        block = js.split("proxyStatus: function", 1)[1].split("},", 1)[0]
        self.assertIn("works:", block,
                      "mock 少了 works，浏览器直开时设置页会误报代理不工作")

    def test_mock_proxy_error_matches_backend_rules(self):
        js = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        self.assertIn("function mockProxyError", js)
        for token in ("socks", "重复", "无法识别"):
            self.assertIn(token, js, f"mock 校验要和后端一样拦下 {token}")


class SlowHintRemovedTest(unittest.TestCase):

    def test_slow_outcome_maps_to_healthy(self):
        from app import api as api_mod
        self.assertEqual(api_mod.OUTCOME_STATE["slow"], "ok")

    def test_classify_still_records_slow_for_diagnostics(self):
        from app import api as api_mod
        self.assertEqual(api_mod.classify(True, 12, "", 9000)[0], "slow",
                         "慢的事实要留给诊断，只是不再当成界面警告")

    def test_frontend_has_no_slow_label(self):
        src = (ROOT / "web" / "js" / "views" / "search.js").read_text(encoding="utf-8")
        self.assertNotIn('"慢"', src, "逐源进度条不该再显示「慢」")

    def test_frontend_semantic_map_agrees(self):
        src = (ROOT / "web" / "js" / "views" / "sources.js").read_text(encoding="utf-8")
        block = src.split("var SEMANTIC = {", 1)[1].split("};", 1)[0]
        self.assertRegex(block, r"slow:\s*\"ok\"")


class SelbarDefaultTest(unittest.TestCase):

    def test_backend_default_is_off(self):
        from app import config
        self.assertFalse(config.DEFAULT_SETTINGS["selbar"])

    def test_search_view_defaults_off(self):
        src = (ROOT / "web" / "js" / "views" / "search.js").read_text(encoding="utf-8")
        self.assertIn("selbarOn: false", src)

    def test_only_explicit_true_enables_it(self):
        src = (ROOT / "web" / "js" / "views" / "search.js").read_text(encoding="utf-8")
        self.assertIn("s.selbar === true", src,
                      "旧写法 s.selbar !== false 会把任何非 false 值当成开启")

    def test_settings_page_defaults_off(self):
        src = (ROOT / "web" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
        self.assertIn("var selbarOn = false;", src)
        self.assertIn("settings.selbar === true", src)

    def test_mock_default_is_off(self):
        src = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        self.assertRegex(src, r"selbar:\s*false")
