import inspect
import re
import sys
import tempfile
import unittest
from pathlib import Path

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

    def test_custom_type_location_points_to_template(self):
        self.assertEqual(sources.adapter_location("x", "html"),
                         "app/templates.py :: _make_html")



class SafeCallSmokeTest(unittest.TestCase):

    def setUp(self):
        self.api = api_mod.Api()
        self.api._cfg = config.Config(path=tempfile.mktemp(suffix=".json"))
        self.api._cfg.load()
        self.api._settings = config.Settings(path=tempfile.mktemp(suffix=".json"))
        self.api._settings.load()
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


class MutatingCallSmokeTest(unittest.TestCase):

    def setUp(self):
        self.api = api_mod.Api()
        self.api._cfg = config.Config(path=tempfile.mktemp(suffix=".json"))
        self.api._cfg.load()
        self.api._settings = config.Settings(path=tempfile.mktemp(suffix=".json"))
        self.api._settings.load()
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
