from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "happycrate"
DATA_DIRNAME = "data"
LOGS_DIRNAME = "logs"

ENV_DATA_DIR = "HAPPYCRATE_DATA_DIR"
ENV_LOG_DIR = "HAPPYCRATE_LOG_DIR"

MODE_ENV = "env"
MODE_PORTABLE = "portable"
MODE_FALLBACK = "fallback"

MODE_LABELS = {
    MODE_ENV: "环境变量指定",
    MODE_PORTABLE: "便携模式",
    MODE_FALLBACK: "回退模式",
}

_cache: tuple[Path, str] | None = None

def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))

def program_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

def appdata_dir() -> Path | None:
    base = os.environ.get("APPDATA")
    if not base:
        return None
    p = Path(base)
    if not p.is_dir():
        return None
    return p / APP_NAME

def is_writable(directory) -> bool:
    try:
        target = Path(directory).expanduser()
    except (TypeError, ValueError):
        return False
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    try:
        with tempfile.NamedTemporaryFile(dir=target, prefix=".happycrate-wtest-",
                                        delete=True):
            pass
        return True
    except OSError:
        return False

def _env_dir() -> Path | None:
    raw = os.environ.get(ENV_DATA_DIR)
    if not raw:
        return None
    return Path(raw).expanduser()

def _resolve() -> tuple[Path, str]:
    env = _env_dir()
    if env:
        return env, MODE_ENV

    portable = program_dir() / DATA_DIRNAME
    if is_writable(portable):
        return portable, MODE_PORTABLE

    fallback = appdata_dir()
    if fallback:
        return fallback / DATA_DIRNAME, MODE_FALLBACK

    return portable, MODE_FALLBACK

def data_dir() -> Path:
    global _cache
    if _cache is None:
        _cache = _resolve()
    return _cache[0]

def data_mode() -> str:
    data_dir()
    return _cache[1] if _cache else MODE_FALLBACK

def describe() -> tuple[Path, str, str]:
    d = data_dir()
    mode = data_mode()
    return d, mode, MODE_LABELS.get(mode, mode)

def data_file(name: str) -> Path:
    return data_dir() / name

def sources_path() -> Path:
    return data_file("sources.json")

def settings_path() -> Path:
    return data_file("settings.json")

def health_path() -> Path:
    return data_file("health.json")

def logs_dir() -> Path:
    override = os.environ.get(ENV_LOG_DIR)
    if override:
        return Path(override).expanduser()
    return data_dir() / LOGS_DIRNAME

def log_path() -> Path:
    return logs_dir() / "happycrate.log"

def ensure_dirs() -> Path:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
    return d
