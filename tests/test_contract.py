import ast
import inspect
import re
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import api as api_mod
from app import config, sources

NOT_CALLED_FROM_WEB = {"boot", "win_min", "win_max", "win_close"}

SAFE_CALLS = {
    "app_info": ((), dict),
    "list_sources": ((), list),
    "get_settings": ((), dict),
    "downloaders": ((), list),
    "selftest": ((), dict),
    "diagnostics": (([],), str),
    "cancel_search": ((0,), bool),
    "toggle_source": (("nyaa", True), bool),
    "save_settings": (({"timeout": 15},), dict),
}

MUTATING_CALLS = {
    "reorder_sources": ((["nyaa", "apibay"],), bool),
}


def frontend_calls():
    text = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
    return set(re.findall(r"window\.pywebview\.api\.([A-Za-z_0-9]+)", text))


HC_API_EXEMPT = {"mode", "onSearch", "onProbeDone", "adapterLocation", "adapterName"}


def camel_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def hc_api_methods():
    text = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
    body = text.split("var api = {", 1)[1]
    return set(re.findall(r"^\s{4}([a-zA-Z_][A-Za-z_0-9]*):\s*function", body, re.M))


def backend_methods():
    return {name for name, _ in inspect.getmembers(api_mod.Api, inspect.isfunction)
            if not name.startswith("_")}


class VersionAlignmentTest(unittest.TestCase):

    def version_in(self, rel, pattern):
        text = (ROOT / rel).read_text(encoding="utf-8")
        m = re.search(pattern, text)
        self.assertIsNotNone(m, f"{rel} 里找不到版本号")
        return m.group(1)

    def test_versions_match_across_files(self):
        from app import __version__ as app_version
        pyproject = self.version_in("pyproject.toml", r'version\s*=\s*"([^"]+)"')
        mock = self.version_in("web/js/api.js", r'version:\s*"([^"]+)"')
        self.assertEqual(pyproject, app_version,
                         "pyproject.toml 与 app/__init__.py 版本号不一致")
        self.assertEqual(mock, app_version,
                         "web/js/api.js 的 mock 版本号与后端不一致")

    def test_version_is_three_part(self):
        from app import __version__ as app_version
        self.assertRegex(app_version, r"^\d+\.\d+\.\d+$")


class CredentialHygieneTest(unittest.TestCase):

    def setUp(self):
        import tempfile
        from pathlib import Path
        from app import api as api_mod
        self.api_mod = api_mod
        self.tmpdir = tempfile.mkdtemp(prefix="hc-cred-")
        self.api = api_mod.Api()
        from app import config
        self.api._cfg = config.Config(path=Path(self.tmpdir) / "sources.json")
        self.api._cfg.load()
        self.api._settings = config.Settings(
            path=Path(self.tmpdir) / "settings.json")
        self.api._settings.load()
        self.api._health_store = config.HealthStore(
            path=Path(self.tmpdir) / "health.json")
        self.api._push = lambda js: None
        self.url = "https://user:secret@example.com/api"
        entry = self.api._cfg.get("nyaa")
        entry["base"] = self.url

    def test_list_view_hides_credentials(self):
        row = [r for r in self.api.list_sources() if r["key"] == "nyaa"][0]
        self.assertNotIn("secret", row["addr"],
                         "源列表会显示给用户，地址里的密码不能原样带出去")
        self.assertIn("example.com", row["addr"], "主机部分要保留，用户才认得出是哪个源")

    def test_diagnostics_hides_credentials(self):
        self.api._health_store.data["nyaa"] = {
            "state": "err", "outcomes": ["timeout"] * 5, "err": "超时",
            "events": [], "times": [], "ms": 0, "lastOk": 0, "lastCount": 0,
        }
        report = self.api.diagnostics([])
        self.assertNotIn("secret", report,
                         "诊断会被复制到剪贴板并贴给别人，不能带出代理/源密码")


import re
import unittest

from app import api as api_mod


class CacheInvalidationContractTest(unittest.TestCase):

    CONFIG_MUTATORS = (
        "toggle_source", "save_settings",
    )

    ORDER_ONLY = ("reorder_sources", "set_auto_order")

    def method_body(self, name: str) -> str:
        src = Path(api_mod.__file__).read_text(encoding="utf-8")
        i = src.index(f"def {name}(")
        j = src.index("\n    def ", i + 10)
        return src[i:j]

    def test_config_mutators_clear_the_search_cache(self):
        missing = []
        for name in self.CONFIG_MUTATORS:
            body = self.method_body(name)
            if "sources.reload_from_config" in body and "_cache_clear()" not in body:
                missing.append(name)
        self.assertEqual(
            missing, [],
            "这些方法会改源配置（地址/超时/启停）却不清搜索缓存，"
            "用户改了镜像地址后会继续命中旧结果，看起来像「设置没生效」："
            + repr(missing))

    def test_order_only_mutators_need_no_cache_reset(self):
        for name in self.ORDER_ONLY:
            with self.subTest(method=name):
                body = self.method_body(name)
                self.assertNotIn(
                    "url", body,
                    f"{name} 若开始改地址，就必须同步清缓存")

    def test_cache_key_includes_source_fingerprint(self):
        src = Path(api_mod.__file__).read_text(encoding="utf-8")
        i = src.index("ckey = (")
        block = src[i:i + 320]
        self.assertIn(
            "_source_stamp", block,
            "缓存键要带源指纹，否则改地址、改超时都不会让旧缓存失效")

    def test_stamp_changes_when_source_config_changes(self):
        import tempfile
        from pathlib import Path
        from app import config
        tmp = tempfile.mkdtemp(prefix="hc-stamp-")
        api = api_mod.Api()
        api._cfg = config.Config(path=Path(tmp) / "sources.json")
        api._cfg.load()
        before = api._source_stamp()
        api._cfg.update("apibay", base="https://mirror.test")
        self.assertNotEqual(before, api._source_stamp(),
                            "改了镜像地址，指纹必须变")
        mid = api._source_stamp()
        api._cfg.set_enabled("apibay", False)
        self.assertNotEqual(mid, api._source_stamp(),
                            "停用源后指纹必须变（它不该再参与缓存身份）")



import logging
import tempfile
import unittest
from pathlib import Path

from app import api as api_mod
from app import paths, sources


class NoSideEffectProbeTest(unittest.TestCase):

    def test_writable_probe_leaves_no_directory_behind(self):
        tmp = Path(tempfile.mkdtemp(prefix="hc-probe-"))
        target = tmp / "a" / "b" / "data"
        self.assertFalse(target.exists(), "前置条件：探测前不该存在")
        self.assertTrue(paths.is_writable(target))
        self.assertFalse(
            target.exists(),
            "探测可写性不该留下目录：放在只读位置或 Program Files 下时，"
            "会凭空多出 data/ 甚至多层空目录")
        self.assertFalse((tmp / "a").exists(), "中间层也要一并收回")

    def test_existing_directory_is_not_removed(self):
        tmp = Path(tempfile.mkdtemp(prefix="hc-probe-"))
        keep = tmp / "keep"
        keep.mkdir()
        marker = keep / "keep.txt"
        marker.write_text("x", encoding="utf-8")
        self.assertTrue(paths.is_writable(keep))
        self.assertTrue(marker.is_file(),
                        "已存在的目录与内容不能被探测顺手删掉")


class LogPrivacyTest(unittest.TestCase):

    def test_log_url_drops_the_query(self):
        for url in ("https://nyaa.si/?page=rss&q=%E7%A7%98%E5%AF%86&p=1",
                    "https://apibay.org/q.php?q=secret",
                    "https://mikanani.me/RSS/Search?searchstr=abc"):
            with self.subTest(url=url):
                got = sources.log_url(url)
                self.assertNotIn("q=", got, "查询串不能进日志")
                self.assertNotIn("secret", got)
                self.assertNotIn("%E7", got)
                self.assertIn("…", got, "要留个痕迹表明这里被省略了")

    def test_log_url_keeps_host_and_path(self):
        got = sources.log_url("https://nyaa.si/?page=rss&q=x")
        self.assertIn("nyaa.si", got, "主机要保留，否则日志没法定位是哪个源")

    def test_log_url_leaves_clean_urls_alone(self):
        self.assertEqual(sources.log_url("https://example.com/path"),
                         "https://example.com/path",
                         "没有查询串时别乱改，免得日志不好读")

    def test_no_user_query_reaches_the_log(self):
        tmp = Path(tempfile.mkdtemp(prefix="hc-log-"))
        (tmp / "logs").mkdir()
        root = logging.getLogger("happycrate")
        saved = list(root.handlers)
        for h in list(root.handlers):
            root.removeHandler(h)
        fh = logging.FileHandler(tmp / "logs" / "p.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(fh)
        root.setLevel(logging.DEBUG)
        try:
            sources.logger.debug(
                "请求失败：%s (%s: %s)",
                sources.log_url("https://x.com/s?q=TOP_SECRET"), "URLError", "boom")
            sources.logger.warning(
                "返回验证码页：%s",
                sources.log_url("https://x.com/s?q=TOP_SECRET"))
            fh.flush()
            content = (tmp / "logs" / "p.log").read_text(encoding="utf-8")
        finally:
            root.removeHandler(fh)
            fh.close()
            for h in saved:
                root.addHandler(h)
        self.assertNotIn(
            "TOP_SECRET", content,
            "关键词不能进日志：README 声明「不保留查询记录」，"
            "而 HAPPYCRATE_LOG_LEVEL=DEBUG 是公开入口，开了就会落盘")

    def test_apibay_fallback_log_has_no_query(self):
        src = Path(sources.__file__).read_text(encoding="utf-8")
        i = src.index("apibay 返回的是兜底列表")
        line = src[src.rindex("logger.", 0, i):i + 40]
        self.assertNotIn("query", line,
                         "这条是 INFO 级、默认就落盘，不能带原始关键词")



class ContractCoverageTest(unittest.TestCase):

    def test_every_frontend_call_exists_on_backend(self):
        missing = sorted(frontend_calls() - backend_methods())
        self.assertEqual(missing, [], f"前端调用了不存在的方法：{missing}")

    def test_every_backend_method_is_reachable(self):
        orphan = sorted(backend_methods() - frontend_calls() - NOT_CALLED_FROM_WEB)
        self.assertEqual(orphan, [], f"后端方法无人调用：{orphan}")

    def test_backend_method_count_is_stable(self):
        self.assertGreaterEqual(len(backend_methods()), 25)

    def test_hc_api_methods_have_backend_counterpart(self):
        missing = sorted(
            name for name in hc_api_methods()
            if name not in HC_API_EXEMPT
            and camel_to_snake(name) not in backend_methods()
        )
        self.assertEqual(
            missing, [],
            f"HC.api 暴露了后端没有对应的方法（真机会静默走 mock 分支）：{missing}",
        )

    def test_adapter_location_matches_real_function(self):
        src = (ROOT / "app" / "sources.py").read_text(encoding="utf-8")
        defined = set(re.findall(r"^def (_search_[A-Za-z0-9_]+)", src, re.M))
        wrong = {}
        for key in sources.BUILTIN_KEYS:
            loc = sources.adapter_location(key)
            name = loc.rsplit(" ", 1)[-1]
            if name not in defined:
                wrong[key] = loc
        self.assertEqual(wrong, {}, f"诊断给出的适配器位置不存在：{wrong}")

    def test_adapter_location_covers_every_builtin(self):
        for key in sources.BUILTIN_KEYS:
            with self.subTest(key=key):
                self.assertNotIn("未知内置源", sources.adapter_location(key))

    def test_frontend_adapter_map_matches_backend(self):
        js = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        block = js.split("function adapterName(key){", 1)[1].split("}", 1)[0]
        pairs = dict(re.findall(
            r"([a-z0-9_]+)\s*:\s*\"(_search_[A-Za-z0-9_]+)\"", block))
        expect = sources.BUILTIN_ADAPTER_NAMES
        self.assertEqual(sorted(pairs), sorted(expect),
                         "前端 adapterName 与后端内置源清单不一致，"
                         "新增内置源漏改会显示「未知内置源」")
        for key, name in expect.items():
            with self.subTest(key=key):
                self.assertEqual(pairs.get(key), name,
                                 f"{key} 的适配器函数名两边不一致")


class DynamicDispatchTest(unittest.TestCase):

    def test_titlbar_dispatch_targets_exist_on_backend(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        names = set(re.findall(r'call\("([A-Za-z_0-9]+)"\)', html))
        self.assertTrue(names, "标题栏按钮走 call(name) 动态派发，扫不到就没人管")
        backend = {name for name, _ in inspect.getmembers(
            api_mod.Api, inspect.isfunction) if not name.startswith("_")}
        missing = sorted(names - backend)
        self.assertEqual(
            missing, [],
            "标题栏按钮用 call(name) 派发，后端没有这些方法，点了没反应："
            + repr(missing))

    def test_unknown_key_location_says_unknown(self):
        self.assertIn("未知内置源", sources.adapter_location("x"))



class SafeCallSmokeTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="hc-contract-")
        self.api = api_mod.Api()
        self.api._cfg = config.Config(path=Path(self.tmpdir) / "sources.json")
        self.api._cfg.load()
        self.api._settings = config.Settings(path=Path(self.tmpdir) / "settings.json")
        self.api._settings.load()
        self.api._health_store = config.HealthStore(path=Path(self.tmpdir) / "health.json")
        sources.reload_from_config(self.api._cfg)

    def test_safe_calls_return_expected_type(self):
        for name, (args, expected) in SAFE_CALLS.items():
            with self.subTest(method=name):
                method = getattr(self.api, name)
                result = method(*args)
                self.assertIsInstance(result, expected,
                                      f"{name} 返回 {type(result).__name__}，期望 {expected.__name__}")

    def test_list_sources_have_frontend_contract_fields(self):
        required = {"key", "label", "enabled", "timeout", "addr", "health"}
        for row in self.api.list_sources():
            with self.subTest(key=row.get("key")):
                self.assertTrue(required.issubset(row.keys()),
                                f"缺少字段：{sorted(required - row.keys())}")

    def test_selftest_reports_ok_key(self):
        self.assertIn("ok", self.api.selftest())

    def test_downloaders_entries_have_key_and_label(self):
        for item in self.api.downloaders():
            with self.subTest(item=item):
                self.assertIn("key", item)
                self.assertIn("label", item)

    def test_save_settings_rejects_out_of_range(self):
        result = self.api.save_settings({"timeout": 9999})
        self.assertFalse(result.get("ok"))

    def test_new_settings_roundtrip(self):
        for key, value in (("soft_deadline_ms", 4000),
                           ("keep_duplicates", True),
                           ("progress_style", "flow")):
            with self.subTest(key=key):
                saved = self.api.save_settings({key: value})
                self.assertTrue(saved.get("ok"), f"{key} 应能保存")
                self.assertEqual(self.api.get_settings().get(key), value,
                                 f"{key} 应能读回")

    def test_start_search_success_path_returns_parsed_query(self):
        self.api._settings.set("soft_deadline_ms", 0)
        before = self.search_threads()
        with mock.patch.object(sources, "search_many", lambda *a, **k: {}):
            res = self.api.start_search("ubuntu")
            self.assertTrue(res.get("ok"),
                            "成功路径不能抛异常——参数名遮蔽过 query 模块")
            self.assertIn("query", res)
            self.assertEqual(res["query"].get("subject"), ["ubuntu"])
            self.assertEqual(res["query"].get("browse"), False)
            self.assertIn("token", res)
            self.assertIn("total", res)
            self.await_search_threads(before)

    def search_threads(self):
        return {t for t in threading.enumerate() if "_search_worker" in t.name}

    def await_search_threads(self, before):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not (self.search_threads() - before):
                return
            time.sleep(0.01)
        self.api.cancel_search()
        self.fail("搜索线程没停下来。它会在这个测试的 mock 窗口关闭之后才去调用 "
                  "search_many，那时拿到的是真函数，会向真实站点发请求，"
                  "并被后续测试的 http_get 替身记进它们的断言列表")


class MutatingCallSmokeTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="hc-mutating-")
        self.api = api_mod.Api()
        self.api._cfg = config.Config(path=Path(self.tmpdir) / "sources.json")
        self.api._cfg.load()
        self.api._settings = config.Settings(path=Path(self.tmpdir) / "settings.json")
        self.api._settings.load()
        self.api._health_store = config.HealthStore(path=Path(self.tmpdir) / "health.json")
        sources.reload_from_config(self.api._cfg)

    def test_mutating_calls_return_expected_type(self):
        for name, (args, expected) in MUTATING_CALLS.items():
            with self.subTest(method=name):
                result = getattr(self.api, name)(*args)
                self.assertIsInstance(result, expected,
                                      f"{name} 返回 {type(result).__name__}，期望 {expected.__name__}")

    def test_reorder_locks_manual_order(self):
        self.api.reorder_sources(["nyaa", "apibay"])
        self.assertTrue(self.api._cfg.order_locked())


TERMINAL_STMTS = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def unreachable_statements(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            for i, stmt in enumerate(block[:-1]):
                if isinstance(stmt, TERMINAL_STMTS):
                    yield block[i + 1]


class UnreachableCodeTest(unittest.TestCase):

    def test_no_statement_after_terminal_jump(self):
        found = []
        for path in sorted(ROOT.glob("app/*.py")):
            for stmt in unreachable_statements(path):
                found.append(f"{path.name}:{stmt.lineno} {ast.unparse(stmt)[:60]}")
        self.assertEqual(
            found, [],
            "return/raise 之后还有语句，永远不会执行："
            + repr(found))


class SwitchOnlyPanelTest(unittest.TestCase):

    def test_sources_panel_has_no_edit_or_batch_left(self):
        text = (ROOT / "web" / "js" / "views" / "sources.js").read_text(
            encoding="utf-8")
        for gone in ("editorSource", "btnBatch", "btnDel", "btnReset",
                     "btnExport", "btnImport", "data-edit", "data-del",
                     "data-check"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text,
                                 "数据源面板只保留开关，这些都不该再回来")

    def test_sources_panel_keeps_switch_and_probe(self):
        text = (ROOT / "web" / "js" / "views" / "sources.js").read_text(
            encoding="utf-8")
        for kept in ("data-sw", "btnProbe", "btnAuto", "search"):
            with self.subTest(kept=kept):
                self.assertIn(kept, text,
                              "开关、测速、自动排序、搜索仍然要在")


if __name__ == "__main__":
    unittest.main()
