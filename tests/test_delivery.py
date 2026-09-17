import sys
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


if __name__ == "__main__":
    unittest.main()
