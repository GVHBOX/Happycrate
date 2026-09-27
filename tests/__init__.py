import atexit
import os
import shutil
import tempfile
import threading
import time

_TMP = tempfile.mkdtemp(prefix="hc-tests-")

os.environ["HAPPYCRATE_DATA_DIR"] = _TMP

from app import api as api_mod
from app import paths

paths._cache = None


def _cleanup() -> None:
    shutil.rmtree(_TMP, ignore_errors=True)


atexit.register(_cleanup)


def search_threads() -> set:
    return {t for t in threading.enumerate()
            if api_mod.SEARCH_THREAD_PREFIX in t.name}


class SearchThreadMixin:

    def search_threads(self) -> set:
        return search_threads()

    def await_search_threads(self, before=(), timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not (search_threads() - set(before)):
                return
            time.sleep(0.01)
        self.api.cancel_search()
        self.fail("搜索线程没停下来。它会在这个测试的 mock 窗口关闭之后才去调用 "
                  "search_many，那时拿到的是真函数，会向真实站点发请求，"
                  "并被后续测试的 http_get 替身记进它们的断言列表")
