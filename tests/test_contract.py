import inspect
import re
import sys
import tempfile
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
    "save_source": (({"key": "custom1", "label": "C1", "type": "json",
                      "url": "https://a.example/s?q={query}", "listPath": "data.list",
                      "map": {"title": "title"}, "timeout": 15},), dict),
    "remove_source": (("custom1",), bool),
    "reorder_sources": ((["nyaa", "apibay"],), bool),
    "reset_sources": ((), bool),
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
        self.url = "https://user:secret@example.com/api?q={query}"
        self.api._cfg.add_source({
            "key": "mycred", "label": "带凭据", "type": "json",
            "url": self.url, "list_path": "data", "map": {"title": "t"},
            "timeout": 15,
        })

    def test_list_view_hides_credentials(self):
        row = [r for r in self.api.list_sources() if r["key"] == "mycred"][0]
        self.assertNotIn("secret", row["addr"],
                         "源列表会显示给用户，地址里的密码不能原样带出去")
        self.assertIn("example.com", row["addr"], "主机部分要保留，用户才认得出是哪个源")

    def test_diagnostics_hides_credentials(self):
        self.api._health_store.data["mycred"] = {
            "state": "err", "outcomes": ["timeout"] * 5, "err": "超时",
            "events": [], "times": [], "ms": 0, "lastOk": 0, "lastCount": 0,
        }
        report = self.api.diagnostics([])
        self.assertNotIn("secret", report,
                         "诊断会被复制到剪贴板并贴给别人，不能带出代理/源密码")

    def test_edit_keeps_credentials_on_save(self):
        raw = self.api.source_addr("mycred")
        self.assertEqual(raw, self.url,
                         "编辑源时必须拿到原始地址，否则用户点一下保存"
                         "就把自己的密码覆盖成 ***")
        self.api.save_source({
            "key": "mycred", "label": "带凭据", "type": "json",
            "addr": raw, "listPath": "data", "map": {"title": "t"},
            "timeout": 15, "isNew": False,
        })
        self.assertEqual(self.api._cfg.get("mycred").get("url"), self.url,
                         "保存后配置里的地址必须还是完整的")


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
        pairs = dict(re.findall(r"([a-z0-9]+)\s*:\s*\"(_search_[A-Za-z0-9_]+)\"",
                                block))
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

    def test_custom_type_location_points_to_template(self):
        self.assertEqual(sources.adapter_location("x", "html"),
                         "app/templates.py :: _make_html")



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
        required = {"key", "label", "type", "enabled", "timeout", "addr",
                    "listPath", "map", "hashPattern", "titlePattern",
                    "sizePattern", "health"}
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
        with mock.patch.object(sources, "search_many", lambda *a, **k: {}):
            res = self.api.start_search("ubuntu")
        self.assertTrue(res.get("ok"),
                        "成功路径不能抛异常——参数名遮蔽过 query 模块")
        self.assertIn("query", res)
        self.assertEqual(res["query"].get("subject"), ["ubuntu"])
        self.assertEqual(res["query"].get("browse"), False)
        self.assertIn("token", res)
        self.assertIn("total", res)


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

    def test_save_source_roundtrip(self):
        entry = {"key": "custom1", "label": "C1", "type": "json",
                 "url": "https://a.example/s?q={query}", "listPath": "data.list",
                 "map": {"title": "title"}, "timeout": 15,
                 "hashPattern": "hp", "titlePattern": "tp", "sizePattern": "sp"}
        self.assertTrue(self.api.save_source(entry).get("ok"))
        saved = [s for s in self.api.list_sources() if s["key"] == "custom1"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["hashPattern"], "hp")
        self.assertEqual(saved[0]["titlePattern"], "tp")
        self.assertEqual(saved[0]["sizePattern"], "sp")

    def test_save_source_rejects_invalid(self):
        result = self.api.save_source({"key": "bad", "label": "", "type": "json",
                                       "url": "nope"})
        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("errors"))

    def test_reorder_locks_manual_order(self):
        self.api.reorder_sources(["nyaa", "apibay"])
        self.assertTrue(self.api._cfg.order_locked())


if __name__ == "__main__":
    unittest.main()
