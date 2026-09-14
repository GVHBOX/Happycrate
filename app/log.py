from __future__ import annotations

import logging
import logging.handlers
import os
import subprocess
import sys

from . import paths

ROOT_LOGGER = "happycrate"

MAX_BYTES = 1 * 1024 * 1024
BACKUP_COUNT = 3

ENV_LEVEL = "HAPPYCRATE_LOG_LEVEL"

_initialized = False
_file_ok = False

def logs_dir():
    return paths.logs_dir()

def log_path():
    return paths.log_path()

def _resolve_level(explicit: str | int | None) -> int:
    if explicit is not None:
        if isinstance(explicit, int):
            return explicit
        level = logging.getLevelName(str(explicit).upper())
        if isinstance(level, int):
            return level
        return logging.INFO
    env = os.environ.get(ENV_LEVEL)
    if env:
        level = logging.getLevelName(env.upper())
        if isinstance(level, int):
            return level
    return logging.INFO

def _named_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

def setup_logging(level: str | int | None = None,
                  echo_stdout: bool = False) -> bool:
    global _initialized, _file_ok
    if _initialized:
        return _file_ok

    root = logging.getLogger(ROOT_LOGGER)
    root.setLevel(_resolve_level(level))
    root.propagate = False

    for h in list(root.handlers):
        root.removeHandler(h)

    formatter = _named_formatter()

    try:
        directory = logs_dir()
        directory.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            str(log_path()),
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)
        _file_ok = True
    except Exception as exc:
        _file_ok = False
        print(f"[{ROOT_LOGGER}] 日志文件挂载失败：{exc}", file=sys.stderr)

    if echo_stdout:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        root.addHandler(sh)

    if not root.handlers:
        root.addHandler(logging.NullHandler())

    _initialized = True
    return _file_ok

def get_logger(name: str = ROOT_LOGGER) -> logging.Logger:
    if name == ROOT_LOGGER or name.startswith(ROOT_LOGGER + "."):
        full = name
    else:
        full = f"{ROOT_LOGGER}.{name}"
    logger = logging.getLogger(full)
    if not logger.handlers and not logging.getLogger(ROOT_LOGGER).handlers:
        logger.addHandler(logging.NullHandler())
    return logger

def open_logs_dir() -> tuple[bool, str]:
    directory = logs_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"无法创建日志目录：{exc}"

    try:
        if sys.platform == "win32":
            os.startfile(str(directory))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(directory)])
        else:
            subprocess.Popen(["xdg-open", str(directory)])
        return True, f"已打开日志目录：{directory}"
    except Exception as exc:
        return False, f"打开日志目录失败：{exc}"

def current_log_file() -> str:
    try:
        return str(log_path().resolve())
    except OSError:
        return str(log_path())

