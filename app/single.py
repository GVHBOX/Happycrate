from __future__ import annotations

import ctypes
import os
import sys

from . import log

logger = log.get_logger(__name__)

MUTEX_NAME = "happycrate_v1_SingleInstance_7d4a9e2c6b1f8053"

ERROR_ALREADY_EXISTS = 183

_handle = None

_FORCE_INNER = os.environ.get("HAPPYCRATE_FORCE_SINGLE_CHECK") == "1"

def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))

def is_inner_process() -> bool:
    if _FORCE_INNER:
        return True
    level = os.environ.get("_PYI_PARENT_PROCESS_LEVEL")
    if level is None:
        return True
    try:
        return int(level) >= 1
    except ValueError:
        return True

def should_check_single_instance() -> bool:
    if sys.platform != "win32":
        return False
    return is_inner_process()

_kernel32 = None


def _get_kernel32():
    global _kernel32
    if _kernel32 is not None:
        return _kernel32

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    CreateMutexW = kernel32.CreateMutexW
    CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    CreateMutexW.restype = ctypes.c_void_p

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [ctypes.c_void_p]
    CloseHandle.restype = ctypes.c_int

    _kernel32 = (CreateMutexW, CloseHandle)
    return _kernel32

def acquire(name: str = MUTEX_NAME) -> bool:
    global _handle

    if not should_check_single_instance():
        return True

    if _handle is not None:
        return True

    try:
        CreateMutexW, _CloseHandle = _get_kernel32()
        handle = CreateMutexW(None, 0, name)
        if not handle:
            last_error = ctypes.get_last_error()
            logger.warning("CreateMutexW 返回 NULL (last_error=%s)，放行不拦",
                           last_error)
            return True

        last_error = ctypes.get_last_error()
        if last_error == ERROR_ALREADY_EXISTS:
            try:
                _CloseHandle(handle)
            except Exception:
                pass
            logger.info("检测到已有实例（互斥体已存在），本次退出")
            return False

        _handle = handle
        logger.info("单实例互斥体已获取：%s", name)
        return True

    except Exception as exc:
        logger.warning("互斥体获取异常，放行不拦：%s: %s", type(exc).__name__, exc)
        return True

def release() -> bool:
    global _handle
    if _handle is None:
        return False
    try:
        _CreateMutexW, CloseHandle = _get_kernel32()
        CloseHandle(_handle)
        _handle = None
        logger.info("单实例互斥体已释放")
        return True
    except Exception as exc:
        logger.warning("释放互斥体异常：%s: %s", type(exc).__name__, exc)
        _handle = None
        return False

