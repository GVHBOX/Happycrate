import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import api as api_mod
from app import config, paths


class DataDirCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hc-health-")
        self.old_env = os.environ.get("HAPPYCRATE_DATA_DIR")
        os.environ["HAPPYCRATE_DATA_DIR"] = self.tmp
        paths._cache = None

    def tearDown(self):
        if self.old_env is None:
            os.environ.pop("HAPPYCRATE_DATA_DIR", None)
        else:
            os.environ["HAPPYCRATE_DATA_DIR"] = self.old_env
        paths._cache = None

    def sources_file(self) -> Path:
        return Path(self.tmp) / "sources.json"

    def health_file(self) -> Path:
        return Path(self.tmp) / "health.json"

    def seed_legacy(self, key: str, health: dict) -> dict:
        data = config.defaults()
        for entry in data["sources"]:
            if entry.get("key") == key:
                entry["health"] = health
                break
        else:
            raise AssertionError(f"默认源里没有 {key}")
        self.sources_file().write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def read_health(self) -> dict:
        return json.loads(self.health_file().read_text(encoding="utf-8"))


class HealthStoreTest(DataDirCase):

    def test_health_moves_out_of_sources_json(self):
        self.seed_legacy("nyaa", {"state": "ok", "ms": 120, "err": "", "times": ["ok"]})
        api_mod.Api().boot()
        cfg = json.loads(self.sources_file().read_text(encoding="utf-8"))
        self.assertFalse(any("health" in e for e in cfg["sources"]),
                         "sources.json 不应再含 health（否则每次搜索都产生 git diff）")
        hp = self.read_health()
        self.assertIn("nyaa", hp["sources"])
        self.assertEqual(hp["sources"]["nyaa"]["ms"], 120)
        self.assertEqual(hp["sources"]["nyaa"]["times"], ["ok"])

    def test_legacy_health_is_not_lost(self):
        self.seed_legacy("nyaa", {"state": "err", "ms": 900, "err": "返回 0 条",
                                  "times": ["empty", "empty", "empty"]})
        api_mod.Api().boot()
        hp = self.read_health()
        self.assertEqual(hp["sources"]["nyaa"]["times"], ["empty"] * 3)
        self.assertEqual(hp["sources"]["nyaa"]["err"], "返回 0 条")

    def test_boot_is_idempotent(self):
        self.seed_legacy("nyaa", {"state": "ok", "ms": 50, "err": "", "times": ["ok", "ok"]})
        api_mod.Api().boot()
        first = self.read_health()
        api_mod.Api().boot()
        second = self.read_health()
        self.assertEqual(first, second)

    def test_search_does_not_dirty_sources_json(self):
        self.seed_legacy("nyaa", {"state": "ok", "ms": 50, "err": "", "times": ["ok"]})
        a = api_mod.Api()
        a.boot()
        before = self.sources_file().read_text(encoding="utf-8")
        a._mark("nyaa", True, 3, 77, "")
        a._persist_health()
        after = self.sources_file().read_text(encoding="utf-8")
        self.assertEqual(before, after,
                         "_persist_health 不应改写 sources.json（health 已独立）")
        hp = self.read_health()
        self.assertIn("ok", hp["sources"]["nyaa"]["times"])

    def test_prune_drops_removed_source(self):
        store = config.HealthStore()
        store.replace({"nyaa": {"state": "ok", "times": ["ok"]},
                       "ghost": {"state": "err", "times": ["err"]}})
        store.prune(["nyaa"])
        self.assertNotIn("ghost", store.all())
        self.assertIn("nyaa", store.all())

    def test_prune_spares_sources_that_never_had_health(self):
        self.seed_legacy("nyaa", {"state": "ok", "ms": 50, "err": "", "times": ["ok"]})
        a = api_mod.Api()
        a.boot()
        hp = self.read_health()
        self.assertEqual(set(hp["sources"]), {"nyaa"},
                         "没有历史记录的源不应被凭空造出 health 条目")
        keys = [r["key"] for r in a.list_sources()]
        self.assertEqual(len(keys), len(config.defaults()["sources"]),
                         "无 health 的源仍必须出现在列表里")
        for row in a.list_sources():
            row["health"]["empty"] = bool(row["health"]["empty"])
            self.assertEqual(row["health"]["state"], "na" if row["key"] != "nyaa" else "ok")

    def test_export_strips_health(self):
        self.seed_legacy("nyaa", {"state": "ok", "ms": 50, "err": "", "times": ["ok"]})
        cfg = config.Config().load()
        out = Path(self.tmp) / "export.json"
        cfg.export_to(out)
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertFalse(any("health" in e for e in payload["sources"]))

    def test_import_ignores_incoming_health(self):
        self.seed_legacy("nyaa", {"state": "ok", "ms": 50, "err": "", "times": ["ok"]})
        incoming = Path(self.tmp) / "incoming.json"
        incoming.write_text(json.dumps({
            "sources": [
                {"key": "nyaa", "label": "Nyaa", "type": "builtin",
                 "health": {"state": "err", "ms": 999, "times": ["err"]}},
                {"key": "brandnew", "label": "新源", "type": "html",
                 "url": "https://example.org/?q={query}",
                 "health": {"state": "err", "ms": 999, "times": ["err"]}},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        cfg = config.Config().load()
        ok, msg, added, updated = cfg.import_from(incoming)
        self.assertTrue(ok, msg)
        self.assertEqual((added, updated), (1, 1), msg)
        fresh = cfg.get("brandnew")
        self.assertIsNotNone(fresh, "新源应被加入")
        self.assertNotIn("health", fresh,
                         "导入不应把外来 health 带进新增源")
        kept = cfg.get("nyaa")
        self.assertEqual(kept["health"]["ms"], 50,
                         "同 key 的导入不该覆盖本机自己的健康度")


class DiagnosticsRootCauseTest(DataDirCase):

    def setUp(self):
        super().setUp()
        self.api = api_mod.Api()
        self.api.boot()

    def feed(self, key, marks):
        for mark in marks:
            if mark == "ok":
                self.api._mark(key, True, 5, 100, "")
            elif mark == "empty":
                self.api._mark(key, True, 0, 100, "返回 0 条")
            else:
                self.api._mark(key, False, 0, 100, "HTTP 503")

    def block_for(self, text, key):
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith(f"> ") and f"({key})" in line:
                out = []
                for nxt in lines[i + 1:]:
                    if nxt.startswith("> ") or nxt == "":
                        break
                    out.append(nxt)
                return "\n".join(out)
        return ""

    def test_empty_window_reports_revision_not_mirror(self):
        self.feed("nyaa", ["ok", "empty", "empty", "empty", "empty", "empty"])
        key = "nyaa"
        block = self.block_for(self.api.diagnostics(), key)
        self.assertIn("疑似站点改版", block)
        self.assertIn("HTTP 200 正常，但解析出 0 条结果", block)
        self.assertNotIn("换镜像地址", block)

    def test_last_success_does_not_mask_empty_history(self):
        self.feed("mikan", ["empty", "empty", "empty", "empty", "empty", "ok"])
        block = self.block_for(self.api.diagnostics(), "mikan")
        self.assertTrue(block, "mikan 应出现在诊断里")
        self.assertIn("疑似站点改版", block,
                      "末次成功把 err 文本清空后，仍应按窗口里的 empty 判根因")

    def test_connection_failure_still_reports_mirror(self):
        self.feed("sukebei", ["err", "err", "err", "err", "err"])
        block = self.block_for(self.api.diagnostics(), "sukebei")
        self.assertIn("换镜像地址", block)
        self.assertNotIn("疑似站点改版", block)

    def test_all_empty_and_err_mix_still_revision(self):
        self.feed("btdig", ["err", "empty", "err", "empty", "empty"])
        block = self.block_for(self.api.diagnostics(), "btdig")
        self.assertIn("疑似站点改版", block)

    def test_window_empty_true_when_empty_dominates(self):
        self.feed("eztv", ["empty", "empty", "empty", "empty", "ok"])
        row = [r for r in self.api.list_sources() if r["key"] == "eztv"][0]
        self.assertTrue(row["health"]["empty"],
                        "5 次里 4 次解析 0 条，1 次成功不足以洗白，仍应按改版报")

    def test_window_empty_cleared_when_success_dominates(self):
        self.feed("bitsearch", ["empty", "empty", "ok", "ok", "ok"])
        row = [r for r in self.api.list_sources() if r["key"] == "bitsearch"][0]
        self.assertFalse(row["health"]["empty"],
                         "成功占多数后不该再判改版")

    def test_view_exposes_empty_flag(self):
        self.feed("nyaa", ["empty", "empty", "empty", "empty", "empty"])
        row = [r for r in self.api.list_sources() if r["key"] == "nyaa"][0]
        self.assertTrue(row["health"]["empty"])

    def test_view_empty_false_for_connection_failure(self):
        self.feed("sukebei", ["err", "err", "err", "err", "err"])
        row = [r for r in self.api.list_sources() if r["key"] == "sukebei"][0]
        self.assertFalse(row["health"]["empty"])

    def test_diagnostics_location_points_to_real_adapter(self):
        self.feed("tpb", ["empty", "empty", "empty", "empty"])
        text = self.api.diagnostics()
        self.assertIn("app/sources.py :: _search_tpb_mirror", text)


class MarkThreadSafetyTest(DataDirCase):

    def setUp(self):
        super().setUp()
        self.api = api_mod.Api()
        self.api.boot()

    def test_concurrent_marks_keep_window_at_limit(self):
        threads = [
            threading.Thread(target=self.api._mark,
                             args=("nyaa", True, 1, 10, ""))
            for _ in range(40)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        h = self.api._health_store.get("nyaa")
        self.assertIsNotNone(h)
        self.assertEqual(len(h["times"]), config.HEALTH_WINDOW)


if __name__ == "__main__":
    unittest.main()
