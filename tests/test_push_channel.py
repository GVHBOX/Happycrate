import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests import SearchThreadMixin
from app import api as api_mod
from app import config, sources


class _Window:

    def __init__(self, fail=False, slow=0.0):
        self.calls = []
        self.threads = set()
        self.spans = []
        self.fail = fail
        self.slow = slow
        self.lock = threading.Lock()

    def evaluate_js(self, js):
        enter = time.monotonic()
        with self.lock:
            self.threads.add(threading.current_thread().name)
            self.calls.append(js)
        if self.slow:
            time.sleep(self.slow)
        with self.lock:
            self.spans.append((enter, time.monotonic()))
        if self.fail:
            raise RuntimeError("evaluate_js unavailable")

    def overlaps(self) -> int:
        spans = sorted(self.spans)
        hits = 0
        for prev, cur in zip(spans, spans[1:]):
            if cur[0] < prev[1]:
                hits += 1
        return hits


class PushChannelTest(SearchThreadMixin, unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="hc-push-")
        self.api = api_mod.Api()
        self.api._cfg = config.Config(path=Path(self.tmpdir) / "sources.json")
        self.api._cfg.load()
        self.api._settings = config.Settings(path=Path(self.tmpdir) / "settings.json")
        self.api._settings.load()
        self.api._health_store = config.HealthStore(
            path=Path(self.tmpdir) / "health.json")
        self.orig_all = sources.ALL_SOURCES
        self.orig_by = sources.BY_KEY

    def tearDown(self):
        sources.ALL_SOURCES = self.orig_all
        sources.BY_KEY = self.orig_by

    def _wire(self, srcs):
        sources.ALL_SOURCES = srcs
        sources.BY_KEY = {s.key: s for s in srcs}

    def test_missing_window_counts_a_drop_instead_of_vanishing(self):
        self.api._window = None
        self.api._push("window.__onSearchDone && window.__onSearchDone({})")
        self.assertEqual(self.api._push_dropped, 1)
        self.assertEqual(self.api._push_failures, 0)

    def test_evaluate_js_failure_is_counted_and_stays_contained(self):
        win = _Window(fail=True)
        self.api._window = win
        self.api._push("window.__onSearchStart && window.__onSearchStart({})")
        self.assertEqual(len(win.calls), 1)
        self.assertEqual(self.api._push_failures, 1)
        self.assertEqual(self.api._push_dropped, 0)

    def test_counters_reach_the_ai_layer(self):
        self.api._window = _Window(fail=True)
        self.api._push("x")
        report = self.api._diagnostic_report()
        self.assertEqual(report["pushFailures"], 1)
        self.assertEqual(report["pushDropped"], 0)

    def test_diagnostics_is_not_silent_when_only_push_failed(self):
        self.api._window = _Window(fail=True)
        self.api._push("x")
        self.assertIn("pushFailures", self.api.diagnostics([]))

    def test_twenty_four_concurrent_pushes_all_arrive(self):
        win = _Window()
        self.api._window = win
        threads = [threading.Thread(target=self.api._push,
                                    args=("window.__onSearchSource && x",))
                   for _ in range(24)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(win.calls), 24)
        self.assertEqual(self.api._push_failures, 0)

    def test_concurrent_pushes_never_enter_evaluate_js_together(self):
        win = _Window(slow=0.01)
        self.api._window = win
        threads = [threading.Thread(target=self.api._push, args=("x",))
                   for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(win.calls), 8)
        self.assertEqual(
            win.overlaps(), 0,
            "两条推送同时进 evaluate_js：后端到前端这条唯一通道没有互斥，"
            f"是否安全目前押在 pywebview 内部行为上（实测 {win.overlaps()} 处重叠）")

    def test_real_push_path_runs_during_a_search(self):
        def fast(query, page=1, timeout=15, base="", batch=None):
            return [{"title": "a", "info_hash": "a" * 40, "source": "fast"}]

        def slow(query, page=1, timeout=15, base="", batch=None):
            time.sleep(0.03)
            return [{"title": "b", "info_hash": "b" * 40, "source": "slow"}]

        self._wire([
            sources.Source("fast", "FAST", fast, timeout=5),
            sources.Source("slow", "SLOW", slow, timeout=5),
        ])
        win = _Window()
        self.api._window = win
        before = self.search_threads()
        token = sources.start_batch()
        self.api._search_token = token
        self.api._search_worker(token, "ubuntu", ["fast", "slow"])
        self.await_search_threads(before)

        started = [c for c in win.calls if "__onSearchStart" in c]
        sources_pushed = [c for c in win.calls if "__onSearchSource" in c]
        self.assertEqual(
            len(started), 2,
            "两个源各应收到一次 start；少了就是推送在真实路径上被吞掉")
        self.assertEqual(len(sources_pushed), 2)
        self.assertIn("__onSearchDone", "".join(win.calls))
        self.assertEqual(self.api._push_failures, 0)
        self.assertEqual(self.api._push_dropped, 0)

    def test_search_pushes_come_from_workers_not_only_the_caller(self):
        def one(query, page=1, timeout=15, base="", batch=None):
            return [{"title": "a", "info_hash": "a" * 40, "source": "one"}]

        def two(query, page=1, timeout=15, base="", batch=None):
            time.sleep(0.02)
            return [{"title": "b", "info_hash": "b" * 40, "source": "two"}]

        self._wire([
            sources.Source("one", "ONE", one, timeout=5),
            sources.Source("two", "TWO", two, timeout=5),
        ])
        win = _Window()
        self.api._window = win
        before = self.search_threads()
        token = sources.start_batch()
        self.api._search_token = token
        self.api._search_worker(token, "ubuntu", ["one", "two"])
        self.await_search_threads(before)

        self.assertGreaterEqual(len(win.calls), 4)
        self.assertGreaterEqual(
            len(win.threads), 2,
            "start 由池线程推、source/done 由调用线程推，两条线程同时进 evaluate_js "
            "才是这条边的真实暴露面；只剩一条说明推送其实已被串行化（U1 要的答案）")


if __name__ == "__main__":
    unittest.main()
