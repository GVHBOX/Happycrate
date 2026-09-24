from __future__ import annotations

import sys

from . import log, paths

logger = log.get_logger(__name__)

def copy_to_clipboard(text: str) -> bool:
    if not text:
        return False
    if sys.platform == "win32":
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            return True
        except Exception as exc:
            logger.warning("剪贴板失败：%s", exc)
    return False

def data_dir_info() -> tuple[str, str]:
    d, _mode, label = paths.describe()
    return str(d), label
