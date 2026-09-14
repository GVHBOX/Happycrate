from __future__ import annotations

import json
import os
import re
import shutil
import tempfile

from . import log, paths

logger = log.get_logger(__name__)

SOURCES_VERSION = 1
SETTINGS_VERSION = 1

_KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")

CUSTOM_TYPES = ("rss", "json", "html")
ALL_TYPES = ("builtin", *CUSTOM_TYPES)

URL_PLACEHOLDERS = ("{query}", "{page}")

RETIRED_SOURCES = frozenset()

DEFAULT_SOURCES = [
    {"key": "apibay", "label": "海盗湾", "type": "builtin",
     "enabled": True, "timeout": 15, "base": "", "order": 0},
    {"key": "nyaa", "label": "Nyaa", "type": "builtin",
     "enabled": True, "timeout": 15, "base": "", "order": 1},
    {"key": "mikan", "label": "蜜柑计划", "type": "builtin",
     "enabled": True, "timeout": 15, "base": "", "order": 2},
    {"key": "dmhy", "label": "动漫花园", "type": "builtin",
     "enabled": True, "timeout": 15, "base": "", "order": 3},
    {"key": "sukebei", "label": "Sukebei", "type": "builtin",
     "enabled": True, "timeout": 15, "base": "", "order": 4},
    {"key": "eztv", "label": "EZTV", "type": "builtin",
     "enabled": True, "timeout": 15, "base": "", "order": 5},
    {"key": "bitsearch", "label": "BitSearch", "type": "builtin",
     "enabled": True, "timeout": 15, "base": "", "order": 6},
    {"key": "tpb", "label": "TPB镜像", "type": "builtin",
     "enabled": True, "timeout": 15, "base": "", "order": 7},
    {"key": "btdig", "label": "BTDigg", "type": "builtin",
     "enabled": True, "timeout": 15, "base": "", "order": 8},
]

DEFAULT_SETTINGS = {
    "version": SETTINGS_VERSION,
    "min_query_len": 2,
    "max_workers": 8,
    "timeout": 15,
    "default_downloader": "",
    "retries": 1,
    "user_agent": "",
    "proxy": "",
    "ui_font_size": 18,
    "selbar": False,
    "theme": "light",
    "auto_files": True,
}

SETTING_SPECS = {
    "min_query_len": {"type": int, "min": 1, "max": 20},
    "max_workers": {"type": int, "min": 1, "max": 32},
    "timeout": {"type": int, "min": 1, "max": 120},
    "default_downloader": {"type": str},
    "retries": {"type": int, "min": 0, "max": 5},
    "user_agent": {"type": str},
    "proxy": {"type": str},
    "ui_font_size": {"type": int, "min": 12, "max": 24},
    "selbar": {"type": bool},
    "theme": {"type": str},
    "auto_files": {"type": bool},
}

INTERNAL_SETTING_KEYS = frozenset({"migrated_from"})

SETTING_LABELS = {    "min_query_len": "最短关键词",
    "max_workers": "并发数",
    "timeout": "投递/清单超时",
    "default_downloader": "默认下载工具",
    "retries": "重试次数",
    "user_agent": "User-Agent",
    "proxy": "代理",
    "ui_font_size": "界面字号",
    "selbar": "浮动选择条",
    "theme": "主题",
    "auto_files": "自动展开",
}

SOURCE_TIMEOUT_MIN = 1
SOURCE_TIMEOUT_MAX = 120

def clamp_timeout(value, default: int = 15) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(SOURCE_TIMEOUT_MIN, min(SOURCE_TIMEOUT_MAX, num))

def config_path():
    return paths.sources_path()

def settings_path():
    return paths.settings_path()

def health_path():
    return paths.health_path()

def broken_path(path) -> str:
    p = str(path)
    if p.lower().endswith(".json"):
        return p[:-5] + ".broken.json"
    return p + ".broken"

TMP_PREFIX = ".happycrate-tmp-"

def sweep_temp_files(directory) -> int:
    removed = 0
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    for name in names:
        if not name.startswith(TMP_PREFIX):
            continue
        try:
            os.unlink(os.path.join(directory, name))
            removed += 1
        except OSError:
            continue
    if removed:
        logger.info("清理了 %d 个残留临时文件", removed)
    return removed

def atomic_write_json(path, data) -> bool:
    target = os.fspath(path)
    directory = os.path.dirname(target) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=TMP_PREFIX,
                                   suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
            return True
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:
        logger.error("写入 %s 失败：%s", target, exc)
        return False

def _load_json(path, fallback):
    if not os.path.isfile(path):
        return fallback, True, None

    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw, False, None
    except Exception as exc:
        backup = broken_path(path)
        logger.error("配置 %s 解析失败（%s），已备份为 %s 并回退默认",
                     path, exc, backup)
        try:
            shutil.copy2(path, backup)
        except OSError as copy_exc:
            logger.warning("备份损坏配置失败：%s", copy_exc)
        return fallback, True, backup

def defaults() -> dict:
    return {
        "version": SOURCES_VERSION,
        "sources": [dict(s) for s in DEFAULT_SOURCES],
    }

def settings_defaults() -> dict:
    return {
        k: (list(v) if isinstance(v, list) else v)
        for k, v in DEFAULT_SETTINGS.items()
    }

def validate_source(src: dict, existing_keys=None) -> list[str]:
    errs: list[str] = []
    if not isinstance(src, dict):
        return ["配置项格式错误"]

    key = str(src.get("key") or "").strip()
    if not key:
        errs.append("key 不能为空")
    elif not _KEY_RE.match(key):
        errs.append("key 只能包含字母数字下划线，且不能为空")
    elif existing_keys and key in set(existing_keys):
        errs.append(f"key 已存在：{key}")

    label = str(src.get("label") or "").strip()
    if not label:
        errs.append("名称不能为空")

    stype = str(src.get("type") or "").strip()
    if stype not in ALL_TYPES:
        errs.append("type 必须是 builtin / rss / json / html 之一")

    timeout = src.get("timeout", 15)
    try:
        timeout = int(timeout)
        if not (1 <= timeout <= 120):
            errs.append("超时需在 1-120 秒之间")
    except (TypeError, ValueError, OverflowError):
        errs.append("超时必须是整数")

    if stype == "builtin":
        from . import sources as sourcesmod
        if key and key not in sourcesmod.BUILTIN_KEYS:
            errs.append(f"未知内置源 key：{key}")
        base = str(src.get("base") or "").strip()
        if base and not base.lower().startswith(("http://", "https://")):
            errs.append("URL 覆盖必须以 http:// 或 https:// 开头")

    if stype in CUSTOM_TYPES:
        url = str(src.get("url") or "").strip()
        if not url:
            errs.append("URL 模板不能为空")
        else:
            if not url.lower().startswith(("http://", "https://")):
                errs.append("URL 模板必须以 http:// 或 https:// 开头")
            if "{query}" not in url:
                errs.append("URL 模板必须包含 {query} 占位符")
            for ph in re.findall(r"\{[a-z_]*\}", url):
                if ph not in URL_PLACEHOLDERS:
                    errs.append(f"未知占位符 {ph}，可用：{{query}} {{page}}")

        if stype == "json" and not str(src.get("list_path") or "").strip():
            errs.append("json 类型必须填列表路径（如 data.list）")

        for field, label in (("hash_pattern", "哈希"),
                             ("title_pattern", "标题"),
                             ("size_pattern", "体积")):
            value = str(src.get(field) or "").strip()
            if not value:
                continue
            try:
                re.compile(value)
            except re.error as exc:
                errs.append(f"{label}正则无效：{exc}")

        if stype != "html":
            mapping = src.get("map") or {}
            if isinstance(mapping, dict):
                if not str(mapping.get("title") or "").strip():
                    errs.append("字段映射至少要配一个标题字段")

    return errs

class Config:

    def __init__(self, path=None):
        self.path = path or config_path()
        self.data = defaults()
        self.broken = None

    def load(self) -> Config:
        raw, is_default, broken = _load_json(self.path, defaults())
        self.broken = broken
        if is_default:
            self.data = defaults()
        else:
            self.data = self._migrate(raw)
        self._normalize()
        return self

    def _migrate(self, raw) -> dict:
        if not isinstance(raw, dict):
            logger.warning("配置顶层不是对象，回退默认")
            return defaults()
        version = raw.get("version", 1)
        try:
            version = int(version)
        except (TypeError, ValueError):
            version = 1
        if version > SOURCES_VERSION:
            logger.warning("配置版本 %s 高于当前支持的 %s，按当前格式读取",
                           version, SOURCES_VERSION)
        return raw

    def _normalize(self):
        srcs = self.data.get("sources")
        if not isinstance(srcs, list):
            srcs = []

        cleaned: list[dict] = []
        seen_keys: set[str] = set()
        for item in srcs:
            if not isinstance(item, dict):
                continue
            key = (item.get("key") or "").strip()
            if not key or key in seen_keys:
                continue
            if key in RETIRED_SOURCES:
                logger.info("数据源 %s 已下线，从配置中移除", key)
                continue
            seen_keys.add(key)
            entry = dict(item)
            entry["key"] = key
            entry.setdefault("label", key)
            entry.setdefault("type", "builtin")
            entry.setdefault("enabled", True)
            entry["timeout"] = clamp_timeout(entry.get("timeout", 15))
            entry.setdefault("base", "")
            try:
                entry["order"] = int(entry.get("order", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                entry["order"] = 0
            cleaned.append(entry)

        cleaned.sort(key=lambda e: e.get("order", 0))
        for i, entry in enumerate(cleaned):
            entry["order"] = i

        self.data["version"] = SOURCES_VERSION
        self.data["sources"] = cleaned

    def save(self) -> bool:
        self._normalize()
        payload = dict(self.data)
        payload["sources"] = [
            {k: v for k, v in entry.items() if k != "health"}
            for entry in self.sources
        ]
        return atomic_write_json(self.path, payload)

    @property
    def sources(self) -> list[dict]:
        return self.data.get("sources", [])

    def get(self, key: str) -> dict | None:
        for entry in self.sources:
            if entry.get("key") == key:
                return entry
        return None

    def enabled_keys(self) -> list[str]:
        return [e["key"] for e in self.sources if e.get("enabled")]

    def all_keys(self) -> list[str]:
        return [e["key"] for e in self.sources]

    def set_enabled(self, key: str, on: bool) -> bool:
        entry = self.get(key)
        if entry is None:
            return False
        entry["enabled"] = bool(on)
        return True

    def update(self, key: str, **fields) -> bool:
        entry = self.get(key)
        if entry is None:
            return False
        entry.update(fields)
        return True

    def add_source(self, src: dict) -> tuple[bool, list[str]]:
        errs = validate_source(src, existing_keys=self.all_keys())
        if errs:
            return False, errs
        item = dict(src)
        item.setdefault("enabled", True)
        item.setdefault("timeout", 15)
        item["order"] = max([e.get("order", 0) for e in self.sources] or [0]) + 1
        self.sources.append(item)
        self._normalize()
        return True, []

    def remove_source(self, key: str) -> bool:
        entry = self.get(key)
        if entry is None:
            return False
        self.data["sources"] = [e for e in self.sources if e.get("key") != key]
        self._normalize()
        return True

    def order_locked(self) -> bool:
        return bool(self.data.get("orderLocked"))

    def strip_health(self) -> bool:
        removed = False
        for entry in self.sources:
            if "health" in entry:
                entry.pop("health", None)
                removed = True
        if removed:
            self.data["sources"] = self.sources
        return removed

    def set_order_locked(self, on: bool) -> None:
        if on:
            self.data["orderLocked"] = True
            for entry in self.sources:
                entry.pop("demoted", None)
                entry.pop("demoteFrom", None)
        else:
            self.data.pop("orderLocked", None)

    def reset_defaults(self) -> None:
        self.data = defaults()
        self._normalize()

    def next_custom_key(self) -> str:
        existing = set(self.all_keys())
        i = 1
        while f"custom{i}" in existing:
            i += 1
        return f"custom{i}"

    def export_to(self, path) -> bool:
        try:
            payload = dict(self.data)
            payload["sources"] = [
                {k: v for k, v in entry.items() if k != "health"}
                for entry in self.sources
            ]
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            return True
        except OSError as exc:
            logger.error("导出配置失败：%s", exc)
            return False

    def import_from(self, path) -> tuple[bool, str, int, int]:
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception as exc:
            return False, f"读取失败：{exc}", 0, 0

        if isinstance(raw, dict):
            srcs = raw.get("sources")
        else:
            srcs = raw
        if not isinstance(srcs, list) or not srcs:
            return False, "文件里没有 sources 列表", 0, 0

        self.data.pop("orderLocked", None)
        builtin_ok = {"enabled", "timeout", "base", "label"}
        added = updated = 0
        skipped: list[str] = []

        for src in srcs:
            if not isinstance(src, dict):
                skipped.append("(不是对象)")
                continue
            key = str(src.get("key") or "").strip()
            if not key:
                skipped.append("(缺少 key)")
                continue
            cur = self.get(key)

            if cur is not None and cur.get("type") == "builtin":
                for field in builtin_ok:
                    if field in src:
                        cur[field] = src[field]
                if "timeout" in src:
                    cur["timeout"] = clamp_timeout(src["timeout"])
                updated += 1
                continue

            if cur is not None:
                for field, value in src.items():
                    if field in ("key", "health"):
                        continue
                    if field == "type" and value == "builtin":
                        continue
                    cur[field] = value
                if "timeout" in src:
                    cur["timeout"] = clamp_timeout(src["timeout"])
                updated += 1
                continue

            errs = validate_source(src, existing_keys=None)
            if errs:
                skipped.append(f"{key} ({errs[0]})")
                continue
            item = {k: v for k, v in src.items() if k != "health"}
            self.sources.append(item)
            added += 1

        self._normalize()

        msg = f"新增 {added} 个，更新 {updated} 个"
        if skipped:
            msg += f"，跳过 {len(skipped)} 个：{'；'.join(skipped[:3])}"
        return True, msg, added, updated

class Settings:

    def __init__(self, path=None):
        self.path = path or settings_path()
        self.data = settings_defaults()
        self.broken = None

    def load(self) -> Settings:
        raw, _is_default, broken = _load_json(self.path, settings_defaults())
        self.broken = broken
        data = settings_defaults()
        if isinstance(raw, dict):
            for key, value in raw.items():
                if key in SETTING_SPECS:
                    coerced = self._coerce(key, value)
                    if coerced is not None:
                        data[key] = coerced
                elif key in INTERNAL_SETTING_KEYS:
                    data[key] = value
        self.data = data
        return self

    @staticmethod
    def _coerce(key: str, value):
        spec = SETTING_SPECS.get(key)
        if not spec:
            return value
        kind = spec["type"]
        if value is None:
            if kind is int:
                return None
            return ""
        try:
            if kind is int:
                v = int(value)
            elif kind is str:
                v = str(value)
            else:
                v = value
        except (TypeError, ValueError, OverflowError):
            return None
        if kind is int:
            if "min" in spec and v < spec["min"]:
                return None
            if "max" in spec and v > spec["max"]:
                return None
        return v

    def save(self) -> bool:
        self.data["version"] = SETTINGS_VERSION
        return atomic_write_json(self.path, self.data)

    def get(self, key: str, fallback=None):
        if key in self.data:
            return self.data[key]
        if fallback is not None:
            return fallback
        return settings_defaults().get(key)

    def set(self, key: str, value) -> bool:
        if key not in SETTING_SPECS:
            return False
        coerced = self._coerce(key, value)
        if coerced is None:
            return False
        self.data[key] = coerced
        return True

    @staticmethod
    def reason(key: str) -> str:
        spec = SETTING_SPECS.get(key) or {}
        label = SETTING_LABELS.get(key, key)
        if "min" in spec and "max" in spec:
            return f"{label}需在 {spec['min']}-{spec['max']} 之间"
        return f"{label}取值不合法"

    def update(self, **fields) -> list[str]:
        rejected = []
        for key, value in fields.items():
            if not self.set(key, value):
                rejected.append(self.reason(key))
        return rejected

    def reset_defaults(self) -> None:
        self.data = settings_defaults()


HEALTH_WINDOW = 5
EVENT_WINDOW = 20


def _clean_events(value) -> list[dict]:
    out = []
    if not isinstance(value, list):
        return out
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            at = int(item.get("at") or 0)
        except (TypeError, ValueError):
            at = 0
        try:
            code = int(item.get("code") or 0)
        except (TypeError, ValueError):
            code = 0
        try:
            count = int(item.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        try:
            ms = int(item.get("ms") or 0)
        except (TypeError, ValueError):
            ms = 0
        out.append({
            "at": at,
            "outcome": str(item.get("outcome") or ""),
            "code": code,
            "count": count,
            "ms": ms,
            "round": str(item.get("round") or ""),
            "err": str(item.get("err") or ""),
        })
    return out[-EVENT_WINDOW:]


class HealthStore:

    def __init__(self, path=None):
        self.path = path or health_path()
        self.data: dict[str, dict] = {}

    def load(self, legacy_entries=None) -> HealthStore:
        raw, is_default, _broken = _load_json(self.path, {})
        if is_default:
            self.data = {}
            if legacy_entries:
                self._absorb_legacy(legacy_entries)
        elif isinstance(raw, dict):
            entries = raw.get("sources")
            self.data = {}
            if isinstance(entries, dict):
                for key, value in entries.items():
                    if isinstance(value, dict):
                        self.data[str(key)] = self._clean(value)
        else:
            self.data = {}
        return self

    def _absorb_legacy(self, entries) -> None:
        got = False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            h = entry.get("health")
            key = str(entry.get("key") or "")
            if key and isinstance(h, dict):
                self.data[key] = self._clean(h)
                got = True
        if got:
            logger.info("已从 sources.json 接收 %d 条健康度记录", len(self.data))

    @staticmethod
    def _clean(value: dict) -> dict:
        events = _clean_events(value.get("events"))
        outcomes = [str(t) for t in (value.get("outcomes") or [])][-HEALTH_WINDOW:]
        if not outcomes:
            outcomes = [str(t) for t in (value.get("times") or [])][-HEALTH_WINDOW:]
        return {
            "state": str(value.get("state", "na") or "na"),
            "ms": HealthStore._safe_int(value.get("ms"), 0),
            "err": str(value.get("err", "") or ""),
            "times": [str(t) for t in (value.get("times") or [])][-HEALTH_WINDOW:],
            "outcomes": outcomes,
            "events": events,
            "lastOk": HealthStore._safe_int(value.get("lastOk"), 0),
            "lastCount": HealthStore._safe_int(value.get("lastCount"), 0),
        }

    @staticmethod
    def _safe_int(value, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return fallback

    def get(self, key: str) -> dict | None:
        return self.data.get(key)

    def all(self) -> dict[str, dict]:
        return dict(self.data)

    def set(self, key: str, value: dict) -> None:
        self.data[key] = self._clean(value)

    def drop(self, key: str) -> None:
        self.data.pop(key, None)

    def replace(self, data: dict) -> None:
        self.data = {str(k): self._clean(v) for k, v in (data or {}).items()
                     if isinstance(v, dict)}

    def prune(self, keep_keys) -> None:
        keep = set(keep_keys or ())
        for key in list(self.data):
            if key not in keep:
                self.data.pop(key, None)

    def save(self) -> bool:
        return atomic_write_json(self.path, {"version": 1, "sources": self.data})



