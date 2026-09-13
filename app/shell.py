from __future__ import annotations

import ctypes
import sys
import threading
import time
import webview
import winreg
from pathlib import Path

from . import APP_TITLE, APP_TITLE_FULL, __version__, api, log, single, store

logger = log.get_logger(__name__)

WIDTH = 1341
HEIGHT = 687
MIN_WIDTH = 960
MIN_HEIGHT = 640
BACKGROUND = "#FFFFFF"

WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"


def web_dir() -> Path:
    if getattr(sys, "frozen", False):
        bundle = getattr(sys, "_MEIPASS", "")
        base = Path(bundle) if bundle else Path(sys.executable).resolve().parent
        return base / "web"
    return Path(__file__).resolve().parent.parent / "web"


def index_url() -> str:
    return (web_dir() / "index.html").as_uri()


def has_webview2() -> bool:
    if sys.platform != "win32":
        return True
    subs = (
        "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\" + WEBVIEW2_GUID,
        "SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\" + WEBVIEW2_GUID,
    )
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for sub in subs:
            try:
                winreg.OpenKey(root, sub).Close()
                return True
            except OSError:
                continue
    return False


def alert(text: str) -> None:
    if sys.platform != "win32":
        print(text)
        return
    ctypes.windll.user32.MessageBoxW(0, text, APP_TITLE, 0x10)


READY_TIMEOUT = 3.0
READY_TRIES = 5

HT_LEFT = 10
HT_RIGHT = 11
HT_TOP = 12
HT_TOPLEFT = 13
HT_TOPRIGHT = 14
HT_BOTTOM = 15
HT_BOTTOMLEFT = 16
HT_BOTTOMRIGHT = 17
RESIZE_BORDER = 8

WM_NCHITTEST = 0x84
GWL_WNDPROC = -4

_user32 = None
_EDGE_RESIZERS: list = []

class RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                ("r", ctypes.c_long), ("b", ctypes.c_long)]


def _user32_lib():
    global _user32
    if _user32 is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        u.CallWindowProcW.restype = ctypes.c_ssize_t
        u.CallWindowProcW.argtypes = [ctypes.c_ssize_t, ctypes.c_void_p,
                                      ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        u.DefWindowProcW.restype = ctypes.c_ssize_t
        u.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                     ctypes.c_size_t, ctypes.c_ssize_t]
        _user32 = u
    return _user32


class EdgeResizer:

    def __init__(self, hwnd: int):
        u = _user32_lib()
        self._u = u
        self._hwnd = ctypes.c_void_p(hwnd)
        self._old_proc = u.GetWindowLongPtrW(self._hwnd, GWL_WNDPROC)
        self._callback = u.WNDPROC_TYPE(self._proc)
        new_addr = ctypes.cast(self._callback, ctypes.c_void_p).value
        u.SetWindowLongPtrW(self._hwnd, GWL_WNDPROC,
                            ctypes.c_ssize_t(new_addr))

    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_NCHITTEST:
                code = self._hit(lparam)
                if code is not None:
                    return code
            return self._u.CallWindowProcW(self._old_proc, ctypes.c_void_p(hwnd),
                                           msg, wparam, lparam)
        except Exception:
            try:
                return self._u.DefWindowProcW(ctypes.c_void_p(hwnd), msg,
                                              wparam, lparam)
            except Exception:
                return 0

    def _rect(self):
        rect = RECT()
        if not self._u.GetWindowRect(self._hwnd, ctypes.byref(rect)):
            return None
        return rect

    def _hit(self, lparam):
        try:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        except Exception:
            return None
        rect = self._rect()
        if rect is None:
            return None

        d = RESIZE_BORDER
        left = x - rect.l <= d
        right = rect.r - x <= d
        top = y - rect.t <= d
        bottom = rect.b - y <= d
        if top and left:
            return HT_TOPLEFT
        if top and right:
            return HT_TOPRIGHT
        if bottom and left:
            return HT_BOTTOMLEFT
        if bottom and right:
            return HT_BOTTOMRIGHT
        if left:
            return HT_LEFT
        if right:
            return HT_RIGHT
        if top:
            return HT_TOP
        if bottom:
            return HT_BOTTOM
        return None


def enable_edge_resize() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import webview.platforms.winforms as wf

        u = _user32_lib()
        if not hasattr(u, "WNDPROC_TYPE"):
            u.WNDPROC_TYPE = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
                ctypes.c_size_t, ctypes.c_ssize_t)
            u.GetWindowRect.restype = ctypes.c_int
            u.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        def install():
            try:
                for _ in range(100):
                    time.sleep(0.1)
                    insts = list(getattr(wf.BrowserView, "instances", {}).values())
                    if insts:
                        inst = insts[0]
                        hwnd = int(inst.Handle.ToString())

                        def _apply_padding():
                            try:
                                from System.Windows.Forms import Padding
                                inst.Padding = Padding(
                                    RESIZE_BORDER, RESIZE_BORDER,
                                    RESIZE_BORDER, RESIZE_BORDER)
                                logger.info("窗体热区留白 %dpx", RESIZE_BORDER)
                            except Exception as exc:
                                logger.info("窗体留白失败：%s: %s",
                                            type(exc).__name__, exc)

                        try:
                            from System import Action
                            inst.BeginInvoke(Action(_apply_padding))
                        except Exception as exc:
                            logger.info("窗体留白投递失败：%s: %s",
                                        type(exc).__name__, exc)
                        _EDGE_RESIZERS.append(EdgeResizer(hwnd))
                        logger.info("边缘拉伸钩子已安装 hwnd=%s", hwnd)
                        return
                logger.warning("边缘拉伸：未找到窗口句柄")
            except Exception as exc:
                logger.warning("边缘拉伸安装失败：%s: %s", type(exc).__name__, exc)

        threading.Thread(target=install, daemon=True).start()
        return True
    except Exception as exc:
        logger.info("边缘拉伸不可用：%s: %s", type(exc).__name__, exc)
        return False


def _ensure_bridge(window, url: str) -> bool:
    for attempt in range(READY_TRIES):
        if window.events.loaded.wait(READY_TIMEOUT):
            logger.info("界面桥接就绪（第 %d 次尝试）", attempt + 1)
            return True
        logger.warning("界面桥接未就绪，重新加载（%d/%d）", attempt + 1, READY_TRIES)
        try:
            window.load_url(url)
        except Exception as exc:
            logger.warning("重新加载失败：%s: %s", type(exc).__name__, exc)
    return False


def _on_loaded(bridge, window) -> None:
    result = bridge.selftest()
    if result.get("ok"):
        logger.info("契约自检通过")
        return
    missing = result.get("missing") or []
    logger.error("契约自检失败：%s", missing)
    try:
        window.evaluate_js(
            "window.HC && window.HC.motion && window.HC.motion.toast"
            " && window.HC.motion.toast('接口自检失败：" + ",".join(missing) + "')"
        )
    except Exception:
        pass


def _watch(window, url: str, bridge) -> None:
    if not _ensure_bridge(window, url):
        logger.error("界面桥接多次未就绪，退出")
        alert(
            "界面初始化失败，请重新启动程序。\n\n"
            "如果反复出现，请把这个目录里的日志发给我：\n" + str(log.logs_dir())
        )
        try:
            window.destroy()
        except Exception:
            pass
        return
    _on_loaded(bridge, window)


def run() -> int:
    log.setup_logging()

    if not single.acquire():
        return 0

    bridge = api.Api()
    try:
        bridge.boot()
    except Exception as exc:
        logger.exception("启动失败")
        alert("启动失败：%s: %s\n\n日志目录：%s" % (type(exc).__name__, exc, log.logs_dir()))
        single.release()
        return 1

    logger.info("%s v%s 就绪 · 界面目录 %s", APP_TITLE, __version__, web_dir())

    if not (web_dir() / "index.html").is_file():
        alert("找不到界面文件：%s\n\n程序可能损坏，请重新下载完整压缩包。" % (web_dir() / "index.html"))
        single.release()
        return 1

    if not has_webview2():
        store.copy_to_clipboard(WEBVIEW2_URL)
        alert(
            "这个程序需要 Windows 的 WebView2 运行库才能显示界面。\n\n"
            "下载地址已经复制到剪贴板，粘贴到浏览器打开、装完再双击本程序即可：\n"
            + WEBVIEW2_URL
        )
        single.release()
        return 1

    url = index_url()
    enable_edge_resize()
    window = webview.create_window(
        APP_TITLE_FULL,
        url=url,
        js_api=bridge,
        width=WIDTH,
        height=HEIGHT,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        background_color=BACKGROUND,
        text_select=True,
        frameless=True,
        shadow=False,
    )
    bridge._window = window
    webview.start(_watch, args=(window, url, bridge), debug=False)
    single.release()
    return 0
