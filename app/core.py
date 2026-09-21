from __future__ import annotations

import math
import re
from datetime import datetime

_MAX_ALT_TITLES = 8

_STRUCTURE_PATTERNS = (
    re.compile(r"(?i)(?:2160p|1440p|1080p|1080i|720p|480p|4k|uhd|8k)"),
    re.compile(r"(?i)(?:x264|x265|h\.?264|h\.?265|hevc|av1|vc-?1|xvid|mpeg-?2)"),
    re.compile(r"(?i)(?:blu-?ray|bluray|bdrip|brrip|web-?dl|webrip|hdtv|hdrip|dvdrip|remux|bdmv)"),
    re.compile(r"(?i)(?:s\d{1,2}\s*e?\d{0,3}|第\s*\d+\s*[集话季]|season\s*\d+|ep?\s*\d{1,3})"),
    re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)"),
    re.compile(r"(?i)(?:atmos|truehd|dts|ddp|aac|flac|5\.1|7\.1|dolby)"),
)


def _structure_score(title) -> int:
    text = title or ""
    return sum(1 for p in _STRUCTURE_PATTERNS if p.search(text))


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
    return score


def _title_rank(item: dict) -> tuple:
    return (_structure_score(item.get("title")), _richness(item))


def _as_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _merge_peak(values):
    nums = []
    for v in values:
        n = _as_int(v)
        if n is not None:
            nums.append(n)
    return max(nums) if nums else None


def _merge_size(values) -> int:
    nums = []
    for v in values:
        n = _as_int(v)
        if n and n > 0:
            nums.append(n)
    if not nums:
        return 0
    if len(nums) < 3:
        return max(nums)
    nums.sort()
    return nums[len(nums) // 2]


def _merge_earliest(values) -> int:
    nums = []
    for v in values:
        n = _as_int(v)
        if n and n > 0:
            nums.append(n)
    return min(nums) if nums else 0


def _merge_titles(*titles) -> list[str]:
    out: list[str] = []
    for t in titles:
        s = str(t or "").strip()
        if s and s not in out:
            out.append(s)
    return out[:_MAX_ALT_TITLES]

_HANDLED_KEYS = frozenset({
    "sources", "altTitles", "seeders", "leechers", "size", "added", "title",
})


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
            merged["altTitles"] = _merge_titles(it.get("title"))
            by_hash[h] = merged
            out.append(merged)
            continue

        for name in _source_list(it):
            if name not in cur["sources"]:
                cur["sources"].append(name)

        titles = list(cur.get("altTitles") or [])
        titles.append(cur.get("title"))
        titles.append(it.get("title"))
        titles.extend(it.get("altTitles") or [])
        cur["altTitles"] = _merge_titles(*titles)

        if _title_rank(it) > _title_rank(cur):
            cur["title"] = it.get("title")

        cur["seeders"] = _merge_peak([cur.get("seeders"), it.get("seeders")])
        cur["leechers"] = _merge_peak([cur.get("leechers"), it.get("leechers")])
        cur["size"] = _merge_size([cur.get("size"), it.get("size")])
        cur["added"] = _merge_earliest([cur.get("added"), it.get("added")])

        for donor in (it, cur):
            for key, value in donor.items():
                if key in _HANDLED_KEYS:
                    continue
                if value and not cur.get(key):
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

