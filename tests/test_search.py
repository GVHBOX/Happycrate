import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import sources


def _blocking(key, query, page, timeout, base="", batch=None):
    time.sleep(3.0)
    return []


def _instant(key, query, page, timeout, base="", batch=None):
    return [{"title": key, "info_hash": (key * 40)[:40]}]


class SearchCancelTest(unittest.TestCase):

    def setUp(self):
        self.orig = sources.ALL_SOURCES

    def tearDown(self):
        sources.ALL_SOURCES = self.orig
        sources.start_batch()

    def _swap(self, func, n=4):
        sources.ALL_SOURCES = [
            sources.Source(key=f"t{i}", label=f"T{i}", func=func)
            for i in range(n)
        ]

    def test_cancel_short_circuits(self):
        self._swap(_blocking)
        token = sources.start_batch()
        threading.Timer(0.4, sources.cancel_batch, [token]).start()
        t0 = time.monotonic()
        res = sources.search_many("test", timeout=5, batch=token)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 1.5, f"取消未短路，耗时 {elapsed:.2f}s")
        self.assertEqual(res, {})

    def test_completes_without_cancel(self):
        self._swap(_instant, 3)
        token = sources.start_batch()
        res = sources.search_many("test", timeout=5, batch=token)
        self.assertEqual(len(res), 3)

    def test_dead_token_skips_immediately(self):
        self._swap(_blocking)
        token = sources.start_batch()
        sources.cancel_batch(token)
        t0 = time.monotonic()
        res = sources.search_many("test", timeout=5, batch=token)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 1.0, f"已取消的批次仍在等待，耗时 {elapsed:.2f}s")
        self.assertEqual(res, {})

    def test_on_source_called_per_source(self):
        self._swap(_instant, 3)
        seen = []
        token = sources.start_batch()
        sources.search_many(
            "test", timeout=5, batch=token,
            on_source=lambda key, items, err, ms: seen.append(key),
        )
        self.assertEqual(sorted(seen), ["t0", "t1", "t2"])


if __name__ == "__main__":
    unittest.main()
