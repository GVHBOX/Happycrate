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


def backend_methods():
    return {name for name, _ in inspect.getmembers(api_mod.Api, inspect.isfunction)
            if not name.startswith("_")}


class ContractCoverageTest(unittest.TestCase):

    def test_every_frontend_call_exists_on_backend(self):
        missing = sorted(frontend_calls() - backend_methods())
        self.assertEqual(missing, [], f"前端调用了不存在的方法：{missing}")

    def test_every_backend_method_is_reachable(self):
        orphan = sorted(backend_methods() - frontend_calls() - NOT_CALLED_FROM_WEB)
        self.assertEqual(orphan, [], f"后端方法无人调用：{orphan}")

    def test_backend_method_count_is_stable(self):
        self.assertGreaterEqual(len(backend_methods()), 25)


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
