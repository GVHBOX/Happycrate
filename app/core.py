from __future__ import annotations

import math
from datetime import datetime


def _richness(item: dict) -> int:
    score = 0
    if item.get("info_hash"):
        score += 2
    if item.get("size"):
        score += 1
    if item.get("seeders") is not None:
        score += 1
    if item.get("added"):
        score += 1
    if len(item.get("title") or "") > 10:
        score += 1
    return score

def _source_list(item: dict) -> list[str]:
    names = item.get("sources")
    out = [str(n) for n in names if n] if isinstance(names, list) else []
    src = item.get("source")
    if src and src not in out:
        out.append(str(src))
    return out

def dedupe(items: list[dict]) -> list[dict]:
    by_hash: dict[str, dict] = {}
    out: list[dict] = []

    for it in items:
        h = (it.get("info_hash") or "").lower()
        if not h:
            out.append(it)
            continue

        cur = by_hash.get(h)
        if cur is None:
            merged = dict(it)
            merged["sources"] = _source_list(it)
            by_hash[h] = merged
            out.append(merged)
            continue

        for name in _source_list(it):
            if name not in cur["sources"]:
                cur["sources"].append(name)

        richer = it if _richness(it) > _richness(cur) else cur
        poorer = cur if richer is it else it
        for key, value in poorer.items():
            if key == "sources":
                continue
            if value and not cur.get(key):
                cur[key] = value
        for key, value in richer.items():
            if key == "sources":
                continue
            if value:
                cur[key] = value

    return out

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")

def format_size(num) -> str:
    if num is None or num == "":
        return ""
    try:
        value = float(num)
    except (TypeError, ValueError, OverflowError):
        return ""
    if not math.isfinite(value) or value <= 0:
        return ""
    idx = 0
    while value >= 1024 and idx < len(_UNITS) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return f"{value:.0f} {_UNITS[idx]}"
    return f"{value:.1f} {_UNITS[idx]}"

def magnet_of(item: dict) -> str:
    if not item:
        return ""
    existing = item.get("magnet") or ""
    if existing.lower().startswith("magnet:"):
        return existing
    h = (item.get("info_hash") or "").strip()
    if not h:
        return ""
    from . import sources
    return sources.magnet_for(h, item.get("title") or "")

def format_time_relative(ts) -> str:
    if ts is None or ts == "":
        return ""
    try:
        value = float(ts)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""

    try:
        dt = datetime.fromtimestamp(value)
    except (OSError, OverflowError, ValueError):
        return ""

    now = datetime.now()
    delta = now - dt
    secs = delta.total_seconds()

    if secs < 0:
        return "刚刚"
    if secs < 60:
        return "刚刚"
    if secs < 3600:
        return f"{int(secs // 60)} 分钟前"
    if secs < 6 * 3600:
        return f"{int(secs // 3600)} 小时前"

    days = (now.date() - dt.date()).days
    if days == 0:
        return f"今天 {dt.strftime('%H:%M')}"
    if days == 1:
        return f"昨天 {dt.strftime('%H:%M')}"
    if days < 7:
        return f"{days} 天前"
    return dt.strftime("%Y-%m-%d")

class SearchResult:

    def __init__(self):
        self.items: list[dict] = []
        self.errors: dict[str, str] = {}

def search(query: str, page: int, timeout: int | None, enabled,
           min_len: int = 2, on_source=None,
           batch: int | None = None,
           collect: bool = True) -> tuple[SearchResult, str | None]:
    from . import sources

    result = SearchResult()

    if len(query.strip()) < min_len:
        return result, f"关键字至少 {min_len} 个字符"

    by_key = sources.search_many(
        query, page, timeout,
        enabled=enabled, max_workers=None, on_source=on_source,
        batch=batch,
    )

    collected: list[dict] = []
    reached = 0
    for key, (items, err, _ms) in by_key.items():
        if err:
            result.errors[key] = err
        else:
            reached += 1
        if collect and items:
            collected.extend(items)

    if collect:
        result.items = dedupe(collected)

    if not reached and result.errors:
        from . import sources as _s
        if all(_s.proxy_hint() in (e or "") for e in result.errors.values()):
            return result, _s.proxy_hint()
        return result, _s.proxy_hint_for(result.errors)

    return result, None

