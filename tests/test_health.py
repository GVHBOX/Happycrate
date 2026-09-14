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

    def test_empty_window_reports_no_content_not_mirror(self):
        self.feed("nyaa", ["ok", "empty", "empty", "empty", "empty", "empty"])
        key = "nyaa"
        block = self.block_for(self.api.diagnostics(), key)
        self.assertIn("解析代码", block)
        self.assertNotIn("换镜像地址", block,
                         "连得上只是没内容，不该让用户去换地址")

    def test_last_success_does_not_mask_empty_history(self):
        self.feed("mikan", ["empty", "empty", "empty", "empty", "empty", "ok"])
        block = self.block_for(self.api.diagnostics(), "mikan")
        self.assertTrue(block, "mikan 应出现在诊断里")
        self.assertIn("无结果", block,
                      "末次成功把状态洗白后，仍应按窗口里的 empty 保留提示")

    def test_empty_mixed_with_conn_error_reports_mirror(self):
        self.feed("btdig", ["err", "empty", "err", "empty", "empty"])
        block = self.block_for(self.api.diagnostics(), "btdig")
        self.assertIn("换镜像地址", block,
                      "窗口里混着连接失败时，换地址比改解析优先")

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

    def test_diagnostics_carries_per_attempt_detail(self):
        self.feed("tpb", ["empty", "empty"])
        text = self.api.diagnostics()
        self.assertIn("明细", text,
                      "诊断要能交给 agent 判断，必须带每次的码/条数/耗时")
        self.assertIn("ms", text)


class OutcomeClassificationTest(unittest.TestCase):

    def check(self, ok, count, err, ms=0):
        return api_mod.classify(ok, count, err, ms)

    def test_zero_result_is_empty_not_error(self):
        self.assertEqual(self.check(True, 0, ""), ("empty", 0),
                         "连上了只是没内容，不是故障")

    def test_http_codes_are_split(self):
        self.assertEqual(self.check(False, 0, "HTTP Error 403: Forbidden"),
                         ("http403", 403))
        self.assertEqual(self.check(False, 0, "HTTP Error 429: Too Many Requests"),
                         ("http429", 429))
        self.assertEqual(self.check(False, 0, "HTTP Error 503: Unavailable"),
                         ("http5xx", 503))
        self.assertEqual(self.check(False, 0, "HTTP Error 404: Not Found"),
                         ("http4xx", 404))

    def test_legal_block_is_refusal_not_generic_4xx(self):
        self.assertEqual(self.check(False, 0, "HTTP Error 451: Unavailable"),
                         ("http403", 451),
                         "451 是站点主动拒绝，不会自愈，不能当普通 4xx")

    def test_proxy_tunnel_failure_is_network_not_source(self):
        msg = "URLError: <urlopen error Tunnel connection failed: 502 Bad Gateway>"
        self.assertEqual(self.check(False, 0, msg), ("net", 0),
                         "代理返回的 502 不代表源站故障")

    def test_proxy_failure_text_is_distinct(self):
        self.assertEqual(api_mod.outcome_text("http403", 451), "HTTP 451 拒绝")
        self.assertEqual(api_mod.outcome_text("http5xx", 503), "HTTP 503")

    def test_timeout_and_network_are_distinct(self):
        self.assertEqual(self.check(False, 0, "URLError: timed out"),
                         ("timeout", 0))
        self.assertEqual(self.check(False, 0, "socket.timeout: timed out"),
                         ("timeout", 0))
        self.assertEqual(self.check(False, 0, "URLError: getaddrinfo failed"),
                         ("net", 0))

    def test_slow_but_successful_is_not_error(self):
        self.assertEqual(self.check(True, 12, "", 9000), ("slow", 0))
        self.assertEqual(self.check(True, 12, "", 300), ("ok", 0))

    def test_cancelled_search_is_flagged(self):
        self.assertEqual(self.check(False, 0, "已停止"), ("cancel", 0))


class OutcomeStateTest(unittest.TestCase):

    def state(self, outcomes, ms=0):
        return api_mod._state_of(outcomes, ms)

    def test_empty_is_never_red(self):
        self.assertEqual(self.state(["empty"] * 5), "empty",
                         "无结果必须是灰，红色只留给故障和超时")

    def test_timeout_and_net_are_red(self):
        self.assertEqual(self.state(["timeout"]), "err")
        self.assertEqual(self.state(["net"]), "err")
        self.assertEqual(self.state(["http403"]), "err")
        self.assertEqual(self.state(["http5xx"]), "err")

    def test_rate_limit_is_warn(self):
        self.assertEqual(self.state(["http429"]), "warn",
                         "限流会自己恢复，是提示不是故障")

    def test_mostly_empty_with_one_success_warns(self):
        self.assertEqual(self.state(["empty", "empty", "empty", "empty", "ok"]),
                         "warn", "时有时无值得提醒，但不该红")

    def test_three_fatal_in_window_is_red_even_if_last_ok(self):
        self.assertEqual(
            self.state(["timeout", "timeout", "timeout", "ok", "ok"]), "err")

    def test_single_empty_between_successes_is_not_flagged(self):
        self.assertEqual(self.state(["ok", "ok", "ok", "ok", "empty"]), "empty")
        self.assertFalse(api_mod._window_empty(["ok", "ok", "ok", "ok", "empty"]),
                         "偶发一次没结果不该被当成改版")


class RelativeJudgementTest(DataDirCase):

    def setUp(self):
        super().setUp()
        self.api = api_mod.Api()
        self.api.boot()

    def feed_round(self, token, results):
        for key, count in results.items():
            self.api._mark(key, True, count, 100, "", round_id=str(token))

    def block_for(self, text, key):
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("> ") and f"({key})" in line:
                out = []
                for nxt in lines[i + 1:]:
                    if nxt.startswith("> ") or nxt == "":
                        break
                    out.append(nxt)
                return "\n".join(out)
        return ""

    def test_lonely_empty_source_is_suspicious(self):
        self.feed_round(1, {"nyaa": 0, "mikan": 5, "dmhy": 8})
        block = self.block_for(self.api.diagnostics(), "nyaa")
        self.assertIn("本源更像", block,
                      "同轮别人都有结果，只有它没有，才指向源本身")

    def test_all_sources_empty_blames_query(self):
        self.feed_round(1, {"nyaa": 0, "mikan": 0, "dmhy": 0})
        block = self.block_for(self.api.diagnostics(), "nyaa")
        self.assertIn("关键字太冷门", block,
                      "全都搜不到时该怪关键字，不该把源标成故障")

    def test_round_id_is_recorded(self):
        self.feed_round(77, {"nyaa": 0})
        ev = self.api._health_store.get("nyaa")["events"][-1]
        self.assertEqual(ev["round"], "77")


class HealthEventTest(DataDirCase):

    def setUp(self):
        super().setUp()
        self.api = api_mod.Api()
        self.api.boot()

    def test_events_record_code_count_and_ms(self):
        self.api._mark("nyaa", True, 42, 260, "")
        h = self.api._health_store.get("nyaa")
        ev = h["events"][-1]
        self.assertEqual(ev["outcome"], "ok")
        self.assertEqual(ev["count"], 42)
        self.assertEqual(ev["ms"], 260)
        self.assertTrue(ev["at"] > 0)

    def test_last_ok_tracks_most_recent_success(self):
        self.api._mark("nyaa", True, 5, 100, "")
        h = self.api._health_store.get("nyaa")
        self.assertTrue(h["lastOk"] > 0)
        first = h["lastOk"]
        self.api._mark("nyaa", True, 0, 100, "")
        self.assertEqual(self.api._health_store.get("nyaa")["lastOk"], first,
                         "无结果不该刷新上次成功时间")

    def test_cancel_is_not_written_to_health(self):
        self.api._mark("nyaa", True, 3, 100, "")
        before = list(self.api._health_store.get("nyaa")["outcomes"])
        self.api._mark("nyaa", False, 0, 0, "已停止")
        self.assertEqual(self.api._health_store.get("nyaa")["outcomes"], before,
                         "用户主动停止不该污染健康度")

    def test_events_window_is_bounded(self):
        for _ in range(60):
            self.api._mark("nyaa", True, 1, 10, "")
        h = self.api._health_store.get("nyaa")
        self.assertEqual(len(h["events"]), config.EVENT_WINDOW)
        self.assertEqual(len(h["outcomes"]), config.HEALTH_WINDOW)

    def test_legacy_record_without_events_still_loads(self):
        store = config.HealthStore()
        store.replace({"nyaa": {"state": "err", "ms": 90, "err": "超时",
                                "times": ["err", "err"]}})
        row = store.get("nyaa")
        self.assertEqual(row["outcomes"], ["err", "err"],
                         "旧记录没有 outcomes 时应从 times 推断")
        self.assertEqual(row["events"], [])
        self.assertEqual(row["lastOk"], 0)


class DemoteTest(DataDirCase):

    def setUp(self):
        super().setUp()
        self.api = api_mod.Api()
        self.api.boot()

    def order(self):
        return [e["key"] for e in sorted(self.api._cfg.sources,
                                         key=lambda x: x.get("order", 0))]

    def feed(self, key, marks):
        for mark in marks:
            if mark == "ok":
                self.api._mark(key, True, 5, 100, "")
            elif mark == "empty":
                self.api._mark(key, True, 0, 100, "返回 0 条")
            else:
                self.api._mark(key, False, 0, 100, "HTTP 503")
        self.api._persist_health()

    def test_three_of_five_bad_demotes(self):
        start = self.order()
        self.feed("nyaa", ["err", "err", "err", "ok", "ok"])
        self.assertEqual(self.order()[-1], "nyaa",
                         "5 次里坏 3 次即应沉底，不必等到全坏")
        self.assertEqual(sorted(self.order()), sorted(start),
                         "排序不应增删源")

    def test_two_of_five_bad_does_not_demote(self):
        self.feed("nyaa", ["err", "err", "ok", "ok", "ok"])
        self.assertNotEqual(self.order()[-1], "nyaa",
                            "只坏 2 次不该沉底")

    def test_insufficient_history_does_not_demote(self):
        self.feed("nyaa", ["err", "err"])
        self.assertNotEqual(self.order()[-1], "nyaa",
                            "窗口没攒满 5 次前不该动顺序")

    def test_full_recovery_restores_original_slot(self):
        start = self.order()
        self.feed("nyaa", ["err"] * 5)
        self.assertEqual(self.order()[-1], "nyaa")
        self.feed("nyaa", ["ok"] * 5)
        self.assertEqual(self.order(), start,
                         "恢复后应回到原位置，而不是留在末尾之后")

    def test_order_lock_disables_demotion(self):
        self.api.reorder_sources(self.order())
        self.feed("nyaa", ["err"] * 5)
        self.assertNotEqual(self.order()[-1], "nyaa",
                            "用户手动排过序就不该再自动调整")

    def test_demote_is_idempotent(self):
        self.feed("nyaa", ["err"] * 5)
        once = self.order()
        self.feed("nyaa", ["err"] * 2)
        self.assertEqual(self.order(), once)


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
