import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.downloaders import thunder


class ProtocolDeliveryTest(unittest.TestCase):

    def slept_list(self):
        return []

    def run_delivery(self, count, timeout):
        slept = self.slept_list()
        with mock.patch.object(thunder, "find_exe", lambda: "C:/fake.exe"), \
             mock.patch.object(thunder.subprocess, "Popen",
                               lambda *a, **k: mock.MagicMock()), \
             mock.patch.object(thunder.time, "sleep", lambda s: slept.append(s)):
            result = thunder.ProtocolMethod().deliver(["magnet:?xt=1"] * count,
                                                      timeout)
        return result, slept

    def test_bulk_delivery_stays_within_the_wait_budget(self):
        result, slept = self.run_delivery(100, 15)
        self.assertEqual(result.added, 100)
        self.assertLessEqual(
            sum(slept), thunder._GAP_BUDGET + 0.05,
            "批量投递按固定间隔 sleep，100 个任务要等 5 秒以上，窗口像卡住")

    def test_zero_timeout_skips_the_wait(self):
        _result, slept = self.run_delivery(20, 0)
        self.assertEqual(slept, [], "timeout 为 0 时不该再按固定节奏等")

    def test_short_timeout_shrinks_the_budget(self):
        _result, slept = self.run_delivery(20, 1)
        self.assertLessEqual(sum(slept), 1.05,
                             "等待预算不能超过调用方给的超时")

    def test_single_task_never_waits(self):
        _result, slept = self.run_delivery(1, 15)
        self.assertEqual(slept, [], "只有一个任务时最后一步不该再等")


class ProtocolPacingTest(unittest.TestCase):

    def test_no_zero_gap_across_the_whole_reachable_range(self):
        from app import api as api_mod
        for count in range(2, api_mod.MAGNET_CAP + 1):
            with self.subTest(count=count):
                gaps = thunder._plan_gaps(count, 15)
                self.assertEqual(len(gaps), count - 1)
                self.assertGreaterEqual(
                    min(gaps), thunder._GAP_MIN * 0.999,
                    f"{count} 条时出现 0ms 连发：每条磁力仍会各起一个 "
                    f"thunder.exe，同一瞬间砸给迅雷就会反复识别")

    def test_cap_and_floor_together_leave_no_burst(self):
        from app import api as api_mod
        left = api_mod.MAGNET_CAP - 1
        share = thunder._GAP_BUDGET / left
        self.assertGreaterEqual(
            share, thunder._GAP_MIN,
            f"上限提到 {api_mod.MAGNET_CAP} 之后，固定预算摊到每条已经低于"
            f"节流下限，尾段又会连发；要么降上限，要么调预算或下限")

    def test_planner_never_emits_a_zero_gap_at_any_size(self):
        for count in (2, 31, 32, 100, 401, 1000, 5000, 60000):
            with self.subTest(count=count):
                gaps = thunder._plan_gaps(count, 15)
                self.assertGreater(
                    min(gaps), 0.0,
                    f"{count} 条时规划出了 0ms 间隔。每条磁力都会各起一个 "
                    f"thunder.exe，0ms 连发就是同一瞬间把大量进程砸给迅雷")

    def test_gaps_never_exceed_the_budget(self):
        from app import api as api_mod
        for count in (2, 50, api_mod.MAGNET_CAP - 1, api_mod.MAGNET_CAP):
            with self.subTest(count=count):
                gaps = thunder._plan_gaps(count, 15)
                self.assertLessEqual(
                    sum(gaps), thunder._GAP_BUDGET + 1e-6,
                    "等待总量不能超过预算，否则窗口像卡住")

    def test_pacing_and_budget_only_agree_up_to_the_cap(self):
        from app import api as api_mod
        gaps = thunder._plan_gaps(5000, 15)
        self.assertGreater(
            sum(gaps), thunder._GAP_BUDGET,
            "条数超过上限时，「不连发」与「不超过 2 秒预算」不可能同时满足——"
            "这正是必须在入口处挡住超量提交的原因，光靠节奏是修不好的")

    def test_small_batch_keeps_the_original_rhythm(self):
        gaps = thunder._plan_gaps(10, 15)
        self.assertEqual(gaps[0], thunder._GAP_WARMUP,
                         "开头要留出暖机间隔，让迅雷先把首条接住")
        self.assertAlmostEqual(gaps[-1], thunder._GAP_BATCH, places=6)

    def test_planner_matches_what_deliver_sleeps(self):
        slept = []
        with mock.patch.object(thunder, "find_exe", lambda: "C:/fake.exe"), \
             mock.patch.object(thunder.subprocess, "Popen",
                               lambda *a, **k: mock.MagicMock()), \
             mock.patch.object(thunder.time, "sleep",
                               lambda s: slept.append(s)):
            thunder.ProtocolMethod().deliver(["magnet:?xt=1"] * 50, 15)
        self.assertEqual(slept, thunder._plan_gaps(50, 15),
                         "投递节奏必须直接来自 _plan_gaps，"
                         "两处各算一遍迟早会漂移")


class MagnetCapTest(unittest.TestCase):

    def test_backend_rejects_over_cap_before_touching_downloader(self):
        from app import api as api_mod
        api = api_mod.Api()
        picked = []
        with mock.patch("app.downloaders.pick_default",
                        lambda *a, **k: picked.append(1) or None):
            res = api.deliver(["magnet:?xt=1"] * (api_mod.MAGNET_CAP + 1))
        self.assertFalse(res["ok"])
        self.assertIn(str(api_mod.MAGNET_CAP), res["message"])
        self.assertEqual(picked, [],
                         "超限要在找下载工具之前就挡掉，不能先起进程再说")

    def test_backend_accepts_exactly_the_cap(self):
        from app import api as api_mod
        api = api_mod.Api()
        seen = {}

        class Fake:
            label = "假工具"
            def add(self, items, timeout):
                seen["n"] = len(items)
                return thunder.DeliveryResult(len(items), len(items), [])

        with mock.patch("app.downloaders.pick_default", lambda *a, **k: Fake()):
            res = api.deliver(["magnet:?xt=1"] * api_mod.MAGNET_CAP)
        self.assertTrue(res["ok"])
        self.assertEqual(seen["n"], api_mod.MAGNET_CAP)

    def test_frontend_mirrors_the_same_cap(self):
        import re
        from app import api as api_mod
        js = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        m = re.search(r"var MAGNET_CAP = (\d+);", js)
        self.assertIsNotNone(m, "前端 mock 也要有同样的上限，两种跑法才一致")
        self.assertEqual(int(m.group(1)), api_mod.MAGNET_CAP,
                         "前后端上限必须一致，否则直开网页与真机行为不同")

    def test_frontend_gates_all_three_bulk_actions(self):
        text = (ROOT / "web" / "js" / "views" / "search.js").read_text(
            encoding="utf-8")
        self.assertEqual(
            text.count("if (overCap("), 3,
            "复制磁力、复制标题、发送下载三条批量出口都要拦截，"
            "漏掉任何一条都会把几千条砸给迅雷")
        self.assertIn("HC.MAGNET_CAP", text,
                      "上限要读 api.js 的同一个常量，不能各写各的数字")


class DoubleClickCopyTest(unittest.TestCase):

    def test_double_click_copies_only_that_row(self):
        text = (ROOT / "web" / "js" / "views" / "search.js").read_text(
            encoding="utf-8")
        body = text.split('rowsEl.addEventListener("dblclick"', 1)[1]
        body = body.split("});", 1)[0]
        self.assertNotIn(
            "if (!st.sel[", body,
            "双击必须一律只选中该行再复制。原来是「未选中才重置选区」，"
            "于是先全选再双击某行会把整个选区复制走，看起来像莫名其妙地"
            "复制了一大堆")


class ComDeliveryTest(unittest.TestCase):

    def deliver_with(self, magnets=3, timeout=15, agent=None,
                     dispatch_error=None):
        client = mock.MagicMock()
        if dispatch_error is not None:
            client.Dispatch.side_effect = dispatch_error
        else:
            client.Dispatch.return_value = agent if agent is not None \
                else mock.MagicMock()
        win32com = mock.MagicMock()
        win32com.client = client
        mods = {"pythoncom": mock.MagicMock(),
                "win32com": win32com,
                "win32com.client": client}
        with mock.patch.dict(sys.modules, mods):
            return thunder.ComMethod().deliver(
                ["magnet:?xt=1"] * magnets, timeout)

    def test_partial_addtask_success_is_reported_ok(self):
        agent = mock.MagicMock()
        state = {"n": 0}

        def add_task(magnet, a, b):
            state["n"] += 1
            if state["n"] == 2:
                raise OSError("boom")

        agent.AddTask.side_effect = add_task
        result = self.deliver_with(agent=agent)
        self.assertEqual(result.added, 2)
        self.assertTrue(result.ok,
                        "部分成功若报整体失败，上层会整批换协议方式重投，任务重复")

    def test_commit_failure_after_success_does_not_redispatch(self):
        agent = mock.MagicMock()
        agent.CommitTasks.side_effect = OSError("commit lost")
        result = self.deliver_with(agent=agent)
        self.assertEqual(result.added, 3)
        self.assertTrue(result.ok,
                        "任务已进列表再回退协议方式就是双份任务，"
                        "宁可带错误说明让用户重发，也不能悄悄重投")

    def test_dispatch_failure_leaves_room_for_fallback(self):
        result = self.deliver_with(dispatch_error=OSError("no com"))
        self.assertEqual(result.added, 0)
        self.assertFalse(result.ok)

    def test_hung_com_times_out_instead_of_freezing(self):
        release = threading.Event()
        agent = mock.MagicMock()

        def add_task(magnet, a, b):
            release.wait(5)

        agent.AddTask.side_effect = add_task
        result = self.deliver_with(agent=agent, magnets=1, timeout=1)
        release.set()
        self.assertFalse(result.ok, "COM 挂起不能卡死 js_bridge 线程")
        self.assertIn("无响应", result.errors[0])


class FindExeOwnerTest(unittest.TestCase):

    QB_PATH = r"C:\Program Files\qBittorrent\qbittorrent.exe"
    TB_PATH = r"C:\Thunder\thunder.exe"

    def find_with_cmd(self, cmd):
        fake = mock.MagicMock()

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        fake.OpenKey.return_value = Key()
        fake.QueryValueEx.return_value = (cmd, None)
        with mock.patch.object(thunder, "THUNDER_EXE_CANDIDATES",
                               (r"C:\none\a.exe",)), \
             mock.patch.object(thunder.os.path, "isfile",
                               lambda p: p in (self.QB_PATH, self.TB_PATH)), \
             mock.patch.dict(sys.modules, {"winreg": fake}):
            return thunder.find_exe()

    def test_magnet_protocol_hijack_is_rejected(self):
        got = self.find_with_cmd('"%s" "%%1"' % self.QB_PATH)
        self.assertIsNone(
            got, "magnet 协议被别的程序注册时，不能把对方 exe 当迅雷拉起")

    def test_thunder_owner_is_accepted(self):
        got = self.find_with_cmd('"%s" "%%1"' % self.TB_PATH)
        self.assertEqual(got, self.TB_PATH)


if __name__ == "__main__":
    unittest.main()
