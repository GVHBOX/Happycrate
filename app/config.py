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
}

def config_path():
    return paths.sources_path()

def settings_path():
    return paths.settings_path()

def broken_path(path) -> str:
    p = str(path)
    if p.lower().endswith(".json"):
        return p[:-5] + ".broken.json"
    return p + ".broken"

def atomic_write_json(path, data) -> bool:
    target = os.fspath(path)
    directory = os.path.dirname(target) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".happycrate-tmp-",
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
            try:
                entry["timeout"] = int(entry.get("timeout", 15) or 15)
            except (TypeError, ValueError, OverflowError):
                entry["timeout"] = 15
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
        return atomic_write_json(self.path, self.data)

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
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
            return True
        except OSError as exc:
            logger.error("导出配置失败：%s", exc)
            return False

    def import_from(self, path) -> tuple[bool, str, int, int]:
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception as exc:
            return False, f"读取失败：{exc}"

        if isinstance(raw, dict):
            srcs = raw.get("sources")
        else:
            srcs = raw
        if not isinstance(srcs, list) or not srcs:
            return False, "文件里没有 sources 列表"

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
                updated += 1
                continue

            if cur is not None:
                for field, value in src.items():
                    if field == "key":
                        continue
                    if field == "type" and value == "builtin":
                        continue
                    cur[field] = value
                updated += 1
                continue

            errs = validate_source(src, existing_keys=None)
            if errs:
                skipped.append(f"{key} ({errs[0]})")
                continue
            self.sources.append(dict(src))
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
                else:
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
            self.data[key] = value
            return True
        coerced = self._coerce(key, value)
        if coerced is None:
            return False
        self.data[key] = coerced
        return True

    def update(self, **fields) -> list[str]:
        rejected = []
        for key, value in fields.items():
            if not self.set(key, value):
                rejected.append(key)
        return rejected

    def reset_defaults(self) -> None:
        self.data = settings_defaults()


