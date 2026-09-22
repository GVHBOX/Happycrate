from __future__ import annotations

import html as _html
import json
import re
from urllib.parse import quote

from . import log

logger = log.get_logger(__name__)

_DEFAULT_HASH_PATTERN = r"magnet:\?xt=urn:btih:([0-9a-fA-F]{40})"
_DEFAULT_TITLE_PATTERN = r">([^<>]{4,200})\s*<"
_DEFAULT_SIZE_PATTERN = r">([\d.]+\s*[KMGT]i?B)\s*<"

_CONTEXT_WINDOW = 600

MAX_SOURCE_TEXT = 2 * 1024 * 1024
MAX_SOURCE_ITEMS = 300

def render_url(template: str, query: str, page: int) -> str:
    if not template:
        return ""
    out = template.replace("{query}", quote(query or "", safe=""))
    out = out.replace("{page}", str(int(page or 1)))
    return out

def _dig(obj, path):
    if not path:
        return obj
    cur = obj
    for part in str(path).split("."):
        if not part:
            continue
        if part.endswith("[]"):
            part = part[:-2]
        if isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        elif isinstance(cur, (list, tuple)):
            got = []
            for item in cur:
                if isinstance(item, dict) and part in item:
                    got.append(item[part])
            if not got:
                return None
            cur = got
        else:
            return None
    return cur

def _txt(val) -> str:
    if val is None:
        return ""
    if isinstance(val, (list, tuple)):
        val = val[0] if val else ""
    if isinstance(val, dict):
        for k in ("#text", "text", "value", "name"):
            if k in val:
                return _txt(val[k])
        return ""
    return str(val).strip()

def _unescape(text: str) -> str:
    if not text:
        return ""
    return _html.unescape(str(text)).strip()

def _get_first(mapping: dict, *keys) -> str:
    for k in keys:
        v = mapping.get(k)
        if v:
            return str(v)
    return ""

def _make_rss(entry: dict):
    url_tpl = (entry.get("url") or "").strip()
    mapping = entry.get("map") or {}
    f_title = _get_first(mapping, "title", "name")
    f_hash = mapping.get("hash") or ""
    f_size = mapping.get("size") or ""
    f_seeders = mapping.get("seeders") or ""
    f_leechers = mapping.get("leechers") or ""
    f_added = mapping.get("added") or "pubDate"
    f_magnet = mapping.get("magnet") or ""

    def search(query, page=1, timeout=15, base="", batch=None):
        from . import sources as src

        url = render_url(url_tpl, query, page)
        text = src.http_get(url, timeout=timeout, batch=batch,
                            limit=MAX_SOURCE_TEXT, strict=False)

        items: list[dict] = []
        for chunk in src._split_items(text):
            if len(items) >= MAX_SOURCE_ITEMS:
                break
            title = _unescape(src._tags(chunk, f_title)[0]) if f_title else ""
            magnet = _unescape(src._tags(chunk, f_magnet)[0]) if f_magnet else ""
            info_hash = ""
            if f_hash:
                info_hash = _unescape(src._tags(chunk, f_hash)[0])
            if not info_hash and magnet:
                info_hash = src.hash_from_magnet(magnet)
            if not info_hash:
                info_hash = src.hash_from_text(chunk)
            if not title and not info_hash:
                continue

            size_raw = _unescape(src._tags(chunk, f_size)[0]) if f_size else ""
            added_raw = _unescape(src._tags(chunk, f_added)[0]) if f_added else ""
            seeders = src._to_int(src._tags(chunk, f_seeders)[0]) if f_seeders else None

            items.append(src._mk(
                title=title, info_hash=info_hash,
                size=src.parse_size(size_raw),
                seeders=seeders,
                leechers=src._to_int(src._tags(chunk, f_leechers)[0]) if f_leechers else None,
                added=src._ts_from_rfc(added_raw) or None,
                source=entry.get("label") or entry.get("key") or "自定义",
            ))
        return items

    return search

def _make_json(entry: dict):
    url_tpl = (entry.get("url") or "").strip()
    list_path = (entry.get("list_path") or "").strip()
    mapping = entry.get("map") or {}
    f_title = _get_first(mapping, "title", "name")
    f_hash = mapping.get("hash") or ""
    f_size = mapping.get("size") or ""
    f_seeders = mapping.get("seeders") or ""
    f_leechers = mapping.get("leechers") or ""
    f_added = mapping.get("added") or ""
    f_magnet = mapping.get("magnet") or ""

    def search(query, page=1, timeout=15, base="", batch=None):
        from . import sources as src

        url = render_url(url_tpl, query, page)
        text = src.http_get(url, timeout=timeout, batch=batch,
                            limit=MAX_SOURCE_TEXT, strict=False)
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            logger.warning("自定义 JSON 源返回的不是 JSON：%s", str(text)[:120])
            return []

        rows = _dig(data, list_path) if list_path else data
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            return []

        items: list[dict] = []
        for row in rows:
            if len(items) >= MAX_SOURCE_ITEMS:
                break
            if not isinstance(row, dict):
                continue
            title = _txt(_dig(row, f_title)) if f_title else ""
            magnet = _txt(_dig(row, f_magnet)) if f_magnet else ""
            info_hash = _txt(_dig(row, f_hash)) if f_hash else ""
            if not info_hash and magnet:
                info_hash = src.hash_from_magnet(magnet)
            if not info_hash:
                info_hash = src.hash_from_text(json.dumps(row, ensure_ascii=False))
            if not title and not info_hash:
                continue

            size_val = _dig(row, f_size) if f_size else None
            size = src.parse_size(size_val) if size_val is not None else 0
            added_val = _dig(row, f_added) if f_added else None

            items.append(src._mk(
                title=title, info_hash=info_hash, size=size,
                seeders=_to_int_or_none(_dig(row, f_seeders)) if f_seeders else None,
                leechers=_to_int_or_none(_dig(row, f_leechers)) if f_leechers else None,
                added=_added_value(added_val, src),
                source=entry.get("label") or entry.get("key") or "自定义",
            ))
        return items

    return search

def _nearest(pattern, text: str, start: int, end: int) -> str:
    lo = max(0, start - _CONTEXT_WINDOW)
    hi = min(len(text), end + _CONTEXT_WINDOW)
    chunk = text[lo:hi]

    best = None
    best_dist = None
    for m in pattern.finditer(chunk):
        ms = lo + m.start()
        me = lo + m.end()
        if me <= start:
            dist = start - me
        elif ms >= end:
            dist = ms - end
        else:
            dist = 0
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best = m

    if best is None:
        return ""
    if best.groups():
        return _first_group(best.groups() if len(best.groups()) > 1 else best.group(1))
    return _first_group(best.group(0))

def _make_html(entry: dict):
    url_tpl = (entry.get("url") or "").strip()
    hash_pat = (entry.get("hash_pattern") or "").strip() or _DEFAULT_HASH_PATTERN
    title_pat = (entry.get("title_pattern") or "").strip() or _DEFAULT_TITLE_PATTERN
    size_pat = (entry.get("size_pattern") or "").strip() or _DEFAULT_SIZE_PATTERN

    try:
        re_hash = re.compile(hash_pat, re.I)
    except re.error as exc:
        raise ValueError(f"哈希正则无效：{exc}") from exc

    try:
        re_title = re.compile(title_pat, re.I | re.S)
    except re.error as exc:
        raise ValueError(f"标题正则无效：{exc}") from exc

    try:
        re_size = re.compile(size_pat, re.I)
    except re.error as exc:
        raise ValueError(f"体积正则无效：{exc}") from exc

    def search(query, page=1, timeout=15, base="", batch=None):
        from . import sources as src

        url = render_url(url_tpl, query, page)
        text = src.http_get(url, timeout=timeout, batch=batch,
                            limit=MAX_SOURCE_TEXT, strict=False)
        if not isinstance(text, str):
            text = ""

        items: list[dict] = []
        seen: set[str] = set()
        for m in re_hash.finditer(text):
            if len(items) >= MAX_SOURCE_ITEMS:
                break
            h = _first_group(m.group(1) if m.groups() else m.group(0))
            h = str(h).lower()
            if h.startswith("magnet:"):
                h = src.hash_from_magnet(h)
            if not h or h in seen:
                continue
            seen.add(h)

            title = _unescape(_nearest(re_title, text, m.start(), m.end()))
            size_raw = _nearest(re_size, text, m.start(), m.end())

            items.append(src._mk(
                title=title, info_hash=h,
                size=src.parse_size(size_raw),
                source=entry.get("label") or entry.get("key") or "自定义",
            ))
        return items

    return search

def _first_group(value) -> str:
    if isinstance(value, tuple):
        return str(value[0]) if value else ""
    return "" if value is None else str(value)

_BUILDERS = {
    "rss": _make_rss,
    "json": _make_json,
    "html": _make_html,
}

def _to_int_or_none(value):
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None

def _added_value(value, src):
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return float(text)
    return src._ts_from_iso(text)

def build(entry: dict):
    stype = (entry.get("type") or "").strip()
    builder = _BUILDERS.get(stype)
    if builder is None:
        logger.warning("自定义源类型不支持或配置缺 type：%r (key=%s)",
                       stype, entry.get("key"))
        return None
    try:
        return builder(entry)
    except ValueError as exc:
        logger.error("自定义源编译失败 key=%s type=%s: %s",
                     entry.get("key"), stype, exc)
        raise
    except Exception as exc:
        logger.error("自定义源编译失败 key=%s type=%s: %s: %s",
                     entry.get("key"), stype, type(exc).__name__, exc)
        return None

def test_source(entry: dict, query: str = "test", timeout: int = 15):
    fn = build(entry)
    if fn is None:
        return False, 0, "配置无效，无法构造查询函数"
    try:
        items = fn(query, 1, timeout, entry.get("base", "") or "")
    except Exception as exc:
        return False, 0, f"{type(exc).__name__}: {exc}"
    count = len(items or [])
    if count == 0:
        return True, 0, "请求成功，但没有解析到结果：字段映射或正则不匹配"
    return True, count, ""

