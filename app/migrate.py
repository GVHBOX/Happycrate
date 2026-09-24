from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from . import config, log, paths

logger = log.get_logger(__name__)

MARK = "migrated_from"
LEGACY_ENV = "CLB_DATA_DIR"
LEGACY_NAMES = ("CLB", "clb")


def _candidates() -> list[Path]:
    out = []
    env = os.environ.get(LEGACY_ENV)
    if env:
        out.append(Path(env).expanduser())
    appdata = os.environ.get("APPDATA")
    if appdata:
        for name in LEGACY_NAMES:
            out.append(Path(appdata) / name / "data")
            out.append(Path(appdata) / name)
    try:
        parent = paths.program_dir().parent
        for name in LEGACY_NAMES:
            out.append(parent / name / "data")
    except Exception:
        pass
    return out


def find_legacy() -> Path | None:
    for path in _candidates():
        try:
            if (path / "sources.json").is_file():
                return path
        except OSError:
            continue
    return None


def _merge_legacy_sources(legacy, cfg) -> int:
    if cfg is None:
        return 0
    try:
        raw = json.loads((legacy / "sources.json").read_text(encoding="utf-8"))
    except Exception:
        return 0
    entries = raw.get("sources") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return 0

    carried = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        current = cfg.get(key)
        if current is None:
            continue
        if "enabled" in entry:
            current["enabled"] = bool(entry.get("enabled"))
            carried += 1
        base = str(entry.get("base") or "").strip()
        if base:
            current["base"] = base
        try:
            current["order"] = int(entry.get("order", 0) or 0)
        except (TypeError, ValueError):
            pass
        try:
            timeout = int(entry.get("timeout", 0) or 0)
        except (TypeError, ValueError):
            timeout = 0
        if 1 <= timeout <= 120:
            current["timeout"] = timeout
    if carried:
        cfg._normalize()
        logger.info("已从旧配置恢复 %d 个数据源的启停与设置", carried)
    return carried


def run(settings, cfg=None) -> dict:
    report = {
        "done": False, "source": "", "settings": 0, "sources": 0, "error": "",
    }

    if settings.data.get(MARK):
        mark = settings.data.get(MARK) or ""
        report["done"] = True
        report["source"] = mark.get("path", "") if isinstance(mark, dict) else str(mark)
        return report

    legacy = find_legacy()
    if legacy is None:
        return report

    try:
        sraw = json.loads((legacy / "settings.json").read_text(encoding="utf-8"))
    except Exception:
        sraw = None
    if isinstance(sraw, dict):
        for key, value in sraw.items():
            if key in config.SETTING_SPECS:
                coerced = settings._coerce(key, value)
                if coerced is not None:
                    settings.data[key] = coerced
                    report["settings"] += 1

    try:
        report["sources"] = _merge_legacy_sources(legacy, cfg)
    except Exception as exc:
        logger.warning("旧数据源配置迁移失败：%s: %s", type(exc).__name__, exc)

    settings.data[MARK] = {
        "path": str(legacy),
        "at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        settings.save()
        report["done"] = True
        report["source"] = str(legacy)
        logger.info("已迁移旧配置：%d 项设置、%d 个数据源（来自 %s）",
                    report["settings"], report["sources"], legacy)
    except Exception as exc:
        report["error"] = f"保存失败：{type(exc).__name__}"
        logger.warning("迁移后保存失败：%s", exc)

    return report
