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


def run(cfg, settings) -> dict:
    report = {
        "done": False, "source": "", "added": 0,
        "skipped": 0, "settings": 0, "error": "",
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
        raw = json.loads((legacy / "sources.json").read_text(encoding="utf-8"))
    except Exception as exc:
        report["error"] = f"sources.json 读不了：{type(exc).__name__}"
        logger.warning("旧配置读取失败：%s", exc)
        return report

    have = set(cfg.all_keys())
    entries = raw.get("sources") if isinstance(raw, dict) else raw
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if not key or key in have or str(item.get("type") or "builtin") == "builtin":
                report["skipped"] += 1
                continue
            ok, errors = cfg.add_source(item)
            if ok:
                have.add(key)
                report["added"] += 1
            else:
                report["skipped"] += 1
                logger.warning("旧源 %s 跳过：%s", key, errors)

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

    settings.data[MARK] = {
        "path": str(legacy),
        "at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        cfg.save()
        settings.save()
        report["done"] = True
        report["source"] = str(legacy)
        logger.info("已迁移旧配置：新增 %d 个源 · %d 项设置（来自 %s）",
                    report["added"], report["settings"], legacy)
    except Exception as exc:
        report["error"] = f"保存失败：{type(exc).__name__}"
        logger.warning("迁移后保存失败：%s", exc)

    return report
