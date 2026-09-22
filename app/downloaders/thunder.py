from __future__ import annotations

import os
import re
import subprocess
import sys
import time

from .. import log
from .base import DeliveryResult, Downloader, Method

logger = log.get_logger(__name__)

THUNDER_EXE_CANDIDATES = (
    r"C:\Program Files (x86)\Thunder Network\Thunder\program\thunder.exe",
    r"C:\Program Files\Thunder Network\Thunder\program\thunder.exe",
    r"C:\Program Files (x86)\Thunder Network\Thunder\Thunder.exe",
)

_PROTOCOL_KEYS = (
    r"magnet\shell\open\command",
    r"thunder\shell\open\command",
)

_RE_QUOTED = re.compile(r'"([^"]+\.exe)"')
_RE_BARE = re.compile(r"([A-Za-z]:\\[^\s]+\.exe)")

COM_PROGID = "ThunderAgent.Agent.1"

_PROTOCOL_FLAG = "-StartType:magnet"

_GAP_WARMUP = 0.2
_GAP_BATCH = 0.05
_GAP_MIN = 0.005
_GAP_BUDGET = 2.0
_WARMUP_TASKS = 3

def _plan_gaps(count: int, timeout: int) -> list[float]:
    if count <= 1:
        return []
    budget = max(0.0, min(_GAP_BUDGET, float(timeout or 0)))
    if budget <= 0:
        return []

    left = count - 1
    warm = min(_WARMUP_TASKS, left)
    ideal = warm * _GAP_WARMUP + (left - warm) * _GAP_BATCH
    if ideal <= budget:
        return [_GAP_WARMUP] * warm + [_GAP_BATCH] * (left - warm)

    share = budget / left
    return [max(_GAP_MIN, share)] * left

def find_exe() -> str | None:
    for candidate in THUNDER_EXE_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate

    if sys.platform != "win32":
        return None

    try:
        import winreg
    except ImportError:
        return None

    for proto in _PROTOCOL_KEYS:
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, proto) as key:
                cmd = winreg.QueryValueEx(key, "")[0]
        except OSError:
            continue
        except Exception as exc:
            logger.debug("读注册表 %s 异常：%s", proto, exc)
            continue

        match = _RE_QUOTED.search(cmd) or _RE_BARE.search(cmd)
        if match:
            path = match.group(1)
            if os.path.isfile(path):
                return path

    return None

def com_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False

    try:
        pythoncom.CoInitialize()
        try:
            win32com.client.Dispatch(COM_PROGID)
            return True
        finally:
            pythoncom.CoUninitialize()
    except Exception as exc:
        logger.debug("迅雷 COM 不可用：%s: %s", type(exc).__name__, exc)
        return False

class ComMethod(Method):

    key = "com"
    label = "COM 接口"

    def available(self) -> bool:
        return com_available()

    def deliver(self, magnets: list[str], timeout: int) -> DeliveryResult:
        if sys.platform != "win32":
            return DeliveryResult(0, len(magnets), ["仅支持 Windows"])

        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            return DeliveryResult(0, len(magnets), [f"缺少 pywin32：{exc}"])

        added = 0
        errors: list[str] = []
        try:
            pythoncom.CoInitialize()
            try:
                agent = win32com.client.Dispatch(COM_PROGID)
                for magnet in magnets:
                    try:
                        agent.AddTask(magnet, "", "")
                        added += 1
                    except Exception as exc:
                        logger.debug("COM AddTask 单条失败：%s", exc)
                        errors.append(f"AddTask：{exc}")
                agent.CommitTasks()
            finally:
                pythoncom.CoUninitialize()
        except Exception as exc:
            return DeliveryResult(added, len(magnets),
                                  [*errors, f"{type(exc).__name__}: {exc}"],
                                  self.key, ok=False)

        if added:
            logger.info("迅雷 COM 批量提交成功：%d/%d", added, len(magnets))
        return DeliveryResult(added, len(magnets), errors, self.key)

class ProtocolMethod(Method):

    key = "protocol"
    label = "协议拉起"

    def available(self) -> bool:
        return sys.platform == "win32" and find_exe() is not None

    def deliver(self, magnets: list[str], timeout: int) -> DeliveryResult:
        exe = find_exe()
        if not exe:
            return DeliveryResult(0, len(magnets), ["未找到迅雷主程序"], self.key)

        logger.info("迅雷批量下载：%d 个任务，exe=%s", len(magnets), exe)

        added = 0
        errors: list[str] = []
        gaps = _plan_gaps(len(magnets), timeout)
        for i, magnet in enumerate(magnets):
            try:
                subprocess.Popen([exe, magnet, _PROTOCOL_FLAG],
                                 close_fds=True)
                added += 1
                if i < len(gaps):
                    time.sleep(gaps[i])
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

        if added:
            logger.info("迅雷协议方式提交成功：%d/%d", added, len(magnets))
            return DeliveryResult(added, len(magnets), errors, self.key)

        logger.error("迅雷协议方式全部失败，首个错误：%s",
                     errors[0] if errors else "未知")
        return DeliveryResult(0, len(magnets),
                              errors or ["迅雷主程序启动失败"], self.key)

class Thunder(Downloader):

    key = "thunder"
    label = "迅雷"
    protocol = "magnet:"

    def _all_methods(self) -> list[Method]:
        return [ComMethod(), ProtocolMethod()]

