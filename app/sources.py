from __future__ import annotations

import base64
import concurrent.futures as futures
import html as _html
import json
import math
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import log

logger = log.get_logger(__name__)

_DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

MAX_SEARCH_WORKERS = 8

PROBE_WORD = "test"
PROBE_FALLBACK_WORD = "1080p"

_RETRY_STATUS = (429, 500, 502, 503, 504)

_STRICT = ssl.create_default_context()
_LAX = ssl.create_default_context()
_LAX.check_hostname = False
_LAX.verify_mode = ssl.CERT_NONE

_LAX_HOSTS: set[str] = set()

def ssl_lax_hosts() -> list[str]:
    return sorted(_LAX_HOSTS)

def ssl_known_lax(url: str) -> bool:
    return (urllib.parse.urlsplit(url).hostname or "") in _LAX_HOSTS

def reset_ssl_lax() -> None:
    _LAX_HOSTS.clear()

_SIZE_RE = re.compile(r"(-?\d{1,12}(?:\.\d{1,4})?)\s*([KMGTP]?)i?[Bb](?![A-Za-z0-9])")
_SIZE_SCAN_LIMIT = 200
_SIZE_UNITS = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3,
               "T": 1024 ** 4, "P": 1024 ** 5}

_HASH_HEX_RE = re.compile(r"\b([0-9a-fA-F]{40})\b")
_HASH_B32_RE = re.compile(r"\b([A-Z2-7]{32})\b")

class ProxyUnreachable(Exception):
    pass

class SearchCancelled(Exception):
    pass

_cancel_epoch = 0

def start_batch() -> int:
    global _cancel_epoch
    _cancel_epoch += 1
    return _cancel_epoch

def cancel_batch(token: int) -> None:
    global _cancel_epoch
    if _cancel_epoch <= token:
        _cancel_epoch = token + 1

def _batch_alive(token: int) -> bool:
    return token == _cancel_epoch

def _ua() -> str:
    import os
    env = os.environ.get("HAPPYCRATE_UA")
    if env:
        return env
    from . import runtime
    return runtime.get("user_agent", "") or _DEFAULT_UA

def _retries() -> int:
    from . import runtime
    try:
        return max(0, int(runtime.get("retries", 1)))
    except (TypeError, ValueError):
        return 1

def _manual_proxy() -> dict:
    from . import runtime
    raw = (runtime.get("proxy", "") or "").strip()
    if not raw:
        return {}

    if ";" in raw:
        out = {}
        for part in raw.split(";"):
            part = part.strip()
            if not part:
                continue
            if part.startswith("http://"):
                out["http"] = part
            elif part.startswith("https://"):
                out["https"] = part
        return out

    return {"http": raw, "https": raw}

def _opener(url: str, lax: bool = False):
    manual = _manual_proxy()
    if not manual:
        return None

    handlers = [urllib.request.ProxyHandler(manual)]
    if url.lower().startswith("https"):
        handlers.append(urllib.request.HTTPSHandler(
            context=_LAX if lax else _STRICT))
    return urllib.request.build_opener(*handlers)

def proxy_info() -> dict:
    manual = _manual_proxy()
    if manual:
        return manual
    try:
        return urllib.request.getproxies() or {}
    except Exception:
        return {}

def _max_workers(len_sources: int) -> int:
    from . import runtime
    try:
        configured = int(runtime.get("max_workers", MAX_SEARCH_WORKERS))
    except (TypeError, ValueError):
        configured = MAX_SEARCH_WORKERS
    configured = max(1, configured)
    return max(1, min(configured, len_sources))

def proxy_hint() -> str:
    p = proxy_info()
    if not p:
        return "网络请求失败，请检查网络连接。"
    addr = p.get("https") or p.get("http") or ""
    return (f"系统代理 {addr} 连不上。若使用 Clash / v2ray 等，"
            f"请确认已启动；或在系统设置里关闭代理后重试。")

def _looks_like_proxy_failure(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return False
    text = f"{exc}"
    if "10061" in text or "10060" in text:
        return True
    if isinstance(exc, (ConnectionRefusedError, ConnectionResetError)):
        return bool(proxy_info())
    if isinstance(exc, urllib.error.URLError):
        inner = getattr(exc, "reason", None)
        if inner is not None and "10061" in f"{inner}":
            return True
    return False

def http_get(url: str, timeout: int = 15, referer: str = "",
             data: bytes | None = None,
             headers: dict | None = None,
             retries: int | None = None,
             batch: int | None = None,
             binary: bool = False) -> str:
    if retries is None:
        retries = _retries()

    hdrs = {
        "User-Agent": _ua(),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if referer:
        hdrs["Referer"] = referer
    if headers:
        hdrs.update(headers)

    attempt = 0
    last_exc: Exception | None = None
    use_lax = ssl_known_lax(url)

    while attempt <= max(0, retries):
        attempt += 1
        if batch is not None and not _batch_alive(batch):
            raise SearchCancelled(url)
        req = urllib.request.Request(url, data=data, headers=hdrs)
        try:
            opener = _opener(url, use_lax)
            if opener is not None:
                with opener.open(req, timeout=timeout) as resp:
                    raw = resp.read()
            else:
                kwargs = {"timeout": timeout}
                if url.lower().startswith("https"):
                    kwargs["context"] = _LAX if use_lax else _STRICT
                with urllib.request.urlopen(req, **kwargs) as resp:
                    raw = resp.read()
            return raw if binary else _decode(raw)

        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in _RETRY_STATUS and attempt <= retries:
                time.sleep(1.0 * attempt)
                logger.debug("HTTP %s：%s，%d/%d 次重试",
                             exc.code, url, attempt, retries)
                continue
            logger.debug("HTTP %s：%s（不重试）", exc.code, url)
            raise

        except ssl.SSLError as exc:
            last_exc = exc
            if not use_lax:
                logger.warning("SSL 严格校验失败，降级到 lax：%s (%s)", url, exc)
                _LAX_HOSTS.add(urllib.parse.urlsplit(url).hostname or url)
                use_lax = True
                attempt -= 1
                continue
            raise

        except SearchCancelled:
            raise

        except Exception as exc:
            last_exc = exc
            if _looks_like_proxy_failure(exc):
                logger.warning("代理不可达（%s）：%s", urllib.parse.urlparse(url).netloc, exc)
                raise ProxyUnreachable(proxy_hint()) from exc
            if attempt <= retries:
                time.sleep(1.5 * attempt)
                logger.debug("请求失败：%s，%d/%d 次重试", url, attempt, retries)
                continue
            logger.debug("请求失败：%s (%s: %s)", url, type(exc).__name__, exc)
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError(f"请求失败：{url}")

def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")

_MAX_PLAUSIBLE_BYTES = 1024 ** 6

def _clamp_size(num: float, unit: str) -> int:
    scaled = num * _SIZE_UNITS.get(unit, 1)
    if not (0 < scaled <= _MAX_PLAUSIBLE_BYTES):
        return 0
    return int(scaled)

def parse_size(value) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (OverflowError, ValueError):
            return 0

    text = str(value).strip()
    if not text:
        return 0

    if len(text) > _SIZE_SCAN_LIMIT:
        text = text[:_SIZE_SCAN_LIMIT]

    m = _SIZE_RE.search(text)
    if m:
        try:
            num = float(m.group(1))
        except (ValueError, OverflowError):
            return 0
        if not math.isfinite(num) or num <= 0:
            return 0
        return _clamp_size(num, (m.group(2) or "").upper())

    try:
        parsed = float(text)
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(parsed) or parsed <= 0:
        return 0
    return _clamp_size(parsed, "")

_SIZE_IN_TITLE_RE = re.compile(
    r"[\[\(【]\s*(\d{1,12}(?:\.\d{1,4})?\s*[KMGTP]i?B)\s*[\]\)】]", re.I)

def size_from_title(title: str) -> int:
    if not title:
        return 0
    m = _SIZE_IN_TITLE_RE.search(str(title))
    if not m:
        return 0
    return parse_size(m.group(1))

def hash_from_magnet(magnet: str) -> str:
    if not magnet:
        return ""
    m = _HASH_HEX_RE.search(magnet)
    if m:
        return m.group(1).lower()

    m = _HASH_B32_RE.search(magnet)
    if m:
        try:
            return base64.b32decode(m.group(1).upper()).hex()
        except Exception:
            return ""
    return ""

def hash_from_text(text: str) -> str:
    if not text:
        return ""
    m = _HASH_HEX_RE.search(text)
    if m:
        return m.group(1).lower()

    for cand in _HASH_B32_RE.findall(text):
        try:
            decoded = base64.b32decode(cand.upper()).hex()
            if len(decoded) == 40:
                return decoded
        except Exception:
            continue
    return ""

def magnet_for(info_hash: str, title: str = "") -> str:
    h = (info_hash or "").strip()
    if not h:
        return ""
    magnet = f"magnet:?xt=urn:btih:{h}"
    if title:
        magnet += "&dn=" + urllib.parse.quote(title, safe="")
    return magnet

def _to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None

def _ts_from_rfc(text: str, fmts=("%a, %d %b %Y %H:%M:%S %z",
                                  "%a, %d %b %Y %H:%M:%S",
                                  "%d %b %Y %H:%M:%S %z",
                                  "%d %b %Y %H:%M:%S")) -> float | None:
    if not text:
        return None
    raw = str(text).strip()
    for fmt in fmts:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return None

def _ts_from_iso(text: str) -> float | None:
    if not text:
        return None
    raw = str(text).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        pass
    try:
        dt = datetime.strptime(raw[:10], "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None

def _unescape(text: str) -> str:
    if not text:
        return ""
    s = str(text).strip()
    if "<![CDATA[" in s:
        s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
    return _html.unescape(s).strip()

def _tags(chunk: str, *names) -> list[str]:
    out: list[str] = []
    for name in names:
        if not name:
            out.append("")
            continue
        pat = re.compile(rf"<{re.escape(name)}[^>]*>(.*?)</{re.escape(name)}>",
                         re.I | re.S)
        m = pat.search(chunk)
        out.append(m.group(1).strip() if m else "")
    return out

def _split_items(xml: str) -> list[str]:
    if not xml:
        return []
    return re.findall(r"<item[^>]*>(.*?)</item>", xml, re.I | re.S)

def _mk(title: str, info_hash: str = "", size=0, seeders=None, leechers=None,
        added=None, source: str = "", files=None) -> dict:
    clean_title = re.sub(r"\s+", " ", _unescape(title or "")).strip()
    h = _text(info_hash).strip().lower()
    item = {
        "title": clean_title,
        "info_hash": h,
        "size": _size_or_zero(size),
        "seeders": seeders,
        "leechers": leechers,
        "added": added,
        "source": source,
        "magnet": magnet_for(h, clean_title) if h else "",
    }
    if files:
        item["files"] = files
    return item

def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""

def _size_or_zero(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0

DEFAULT_BASES = {
    "apibay": "https://apibay.org",
    "nyaa": "https://nyaa.si",
    "mikan": "https://mikanani.me",
    "dmhy": "https://share.dmhy.org",
    "sukebei": "https://sukebei.nyaa.si",
    "eztv": "https://eztvx.to",
    "bitsearch": "https://bitsearch.to",
    "tpb": "https://thepiratebay10.org",
    "btdig": "https://btdig.com",
}

def base_of(entry_key: str, base: str = "") -> str:
    return (base or DEFAULT_BASES.get(entry_key, "")).rstrip("/")

def _base_of(base: str, default: str) -> str:
    return (base or default).rstrip("/")

def _search_apibay(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["apibay"])
    url = f"{root}/q.php?q={urllib.parse.quote(query)}"
    text = http_get(url, timeout=timeout, batch=batch)
    rows = json.loads(text)

    if not isinstance(rows, list):
        return []

    items: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        h = _text(row.get("info_hash")).strip().lower()
        name = _text(row.get("name")).strip()
        if not h or not _HASH_HEX_RE.fullmatch(h) or h == "0" * 40:
            continue
        if name.lower() == "no results":
            continue
        items.append(_mk(
            title=name, info_hash=h,
            size=parse_size(row.get("size")),
            seeders=_to_int(row.get("seeders")),
            leechers=_to_int(row.get("leechers")),
            added=_to_int(row.get("added")),
            source="TPB",
        ))
    return items

def _search_nyaa(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["nyaa"])
    url = f"{root}/?page=rss&q={urllib.parse.quote(query)}&p={int(page)}"
    return _parse_nyaa_rss(
        http_get(url, timeout=timeout, batch=batch), "Nyaa", root)

def _search_sukebei(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["sukebei"])
    url = f"{root}/?page=rss&q={urllib.parse.quote(query)}&p={int(page)}"
    return _parse_nyaa_rss(
        http_get(url, timeout=timeout, batch=batch), "Sukebei", root)

def _parse_nyaa_rss(text: str, label: str, root: str = "") -> list[dict]:
    items: list[dict] = []
    for chunk in _split_items(text):
        title = _unescape(_tags(chunk, "title")[0])
        h = _unescape(_tags(chunk, "nyaa:infoHash")[0]).lower()
        if not h:
            m = re.search(r"[0-9a-f]{40}", chunk, re.I)
            h = m.group(0).lower() if m else ""
        if not h:
            continue
        it = _mk(
            title=title, info_hash=h,
            size=parse_size(_tags(chunk, "nyaa:size")[0]),
            seeders=_to_int(_tags(chunk, "nyaa:seeders")[0]),
            leechers=_to_int(_tags(chunk, "nyaa:leechers")[0]),
            added=_ts_from_rfc(_tags(chunk, "pubDate")[0]),
            source=label,
        )
        gid = re.search(r"/view/(\d+)", _tags(chunk, "guid")[0])
        if gid and root:
            it["fetch"] = {"url": f"{root}/download/{gid.group(1)}.torrent"}
        items.append(it)
    return items

def _search_mikan(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["mikan"])
    url = f"{root}/RSS/Search?searchstr={urllib.parse.quote(query)}"
    text = http_get(url, timeout=timeout, batch=batch)

    items: list[dict] = []
    for chunk in _split_items(text):
        title = _unescape(_tags(chunk, "title")[0])
        h = ""
        m = re.search(r"Home/Episode/([0-9a-fA-F]{40})", chunk)
        if m:
            h = m.group(1).lower()
        if not h:
            h = hash_from_text(chunk)
        if not h:
            continue
        items.append(_mk(
            title=title, info_hash=h,
            size=parse_size(_tags(chunk, "contentLength")[0]),
            added=_ts_from_rfc(_tags(chunk, "pubDate")[0]),
            source="Mikan",
        ))
    return items

def _search_dmhy(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["dmhy"])
    url = f"{root}/topics/rss/rss.xml?keyword={urllib.parse.quote(query)}"
    text = http_get(url, timeout=timeout, batch=batch)

    items: list[dict] = []
    for chunk in _split_items(text):
        title = _unescape(_tags(chunk, "title")[0])
        h = ""
        m = re.search(r'<enclosure[^>]*url="([^"]+)"', chunk, re.I)
        if m:
            h = hash_from_text(m.group(1)) or hash_from_magnet(m.group(1))
        if not h:
            h = hash_from_text(_tags(chunk, "guid")[0])
        if not h:
            h = hash_from_text(chunk)
        if not h:
            continue

        size = parse_size(_tags(chunk, "contentLength")[0])
        if not size:
            size = size_from_title(title)

        it = _mk(
            title=title, info_hash=h, size=size,
            added=_ts_from_rfc(_tags(chunk, "pubDate")[0]),
            source="DMHY",
        )
        guid = _tags(chunk, "guid")[0].strip()
        if guid.startswith("http"):
            it["fetch"] = {"url": guid}
        items.append(it)
    return items

EZTV_PAGES = 5

def _search_eztv(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["eztv"])
    needle = (query or "").lower()
    if not needle:
        return []

    items: list[dict] = []
    seen: set[str] = set()
    for p in range(1, EZTV_PAGES + 1):
        url = f"{root}/api/get-torrents?limit=100&page={p}"
        text = http_get(url, timeout=timeout, batch=batch)
        data = json.loads(text)
        rows = data.get("torrents") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            break
        if not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = _text(row.get("title")).strip()
            if needle not in title.lower():
                continue
            h = _text(row.get("hash")).strip().lower()
            if not h or h in seen:
                continue
            seen.add(h)
            items.append(_mk(
                title=title, info_hash=h,
                size=parse_size(row.get("size_bytes") or row.get("size")),
                seeders=_to_int(row.get("seeds")),
                leechers=_to_int(row.get("peers")),
                added=_to_int(row.get("date_released_unix")),
                source="EZTV",
            ))
    return items

def _search_bitsearch(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["bitsearch"])
    url = (f"{root}/api/v1/search?q={urllib.parse.quote(query)}"
           f"&sort=seeders&page={max(1, int(page))}")
    text = http_get(url, timeout=timeout, batch=batch,
                    headers={"Accept": "application/json"})

    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        logger.warning("BitSearch 返回的不是 JSON：%s", text[:120])
        return []
    if not isinstance(payload, dict):
        return []

    rows = payload.get("results")
    if not isinstance(rows, list):
        return []

    items: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        h = _text(row.get("infohash")).strip().lower()
        if not _HASH_HEX_RE.match(h):
            continue
        items.append(_mk(
            title=_text(row.get("title")),
            info_hash=h,
            size=_to_int(row.get("size")) or 0,
            seeders=_to_int(row.get("seeders")),
            leechers=_to_int(row.get("leechers")),
            added=_ts_from_iso(_text(row.get("updatedAt"))),
            source="BitSearch",
        ))
    return items

def _search_tpb_mirror(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["tpb"])
    url = f"{root}/search/{urllib.parse.quote(query)}/{int(page)}/99/0"
    text = http_get(url, timeout=timeout, batch=batch)

    re_row = re.compile(r"<tr[^>]*>.*?</tr>", re.I | re.S)
    re_magnet = re.compile(r'href="(magnet:\?xt=urn:btih:[0-9a-fA-F]{40})',
                           re.I)
    re_title = re.compile(r'href="[^"]*/torrent/\d+/([^"]+)"[^>]*>(.*?)</a>',
                          re.I | re.S)
    re_tag = re.compile(r"<[^>]+>")

    items: list[dict] = []
    seen: set[str] = set()
    for row in re_row.findall(text):
        mag = re_magnet.search(row)
        if not mag:
            continue
        h = hash_from_magnet(mag.group(1))
        if not h or h in seen:
            continue
        seen.add(h)
        t = re_title.search(row)
        title = _unescape(re_tag.sub("", t.group(2))) if t else ""
        items.append(_mk(title=title, info_hash=h, source="TPB镜像"))
    return items

_BTDIG_SIZE_RE = re.compile(r"([\d.]+)\s*(B|KB|MB|GB|TB)", re.I)

def _bencode_dec(buf: bytes, i: int):
    c = buf[i:i+1]
    if c == b"d":
        i += 1
        out = {}
        while buf[i:i+1] != b"e":
            k, i = _bencode_dec(buf, i)
            v, i = _bencode_dec(buf, i)
            out[k] = v
        return out, i + 1
    if c == b"l":
        i += 1
        out = []
        while buf[i:i+1] != b"e":
            v, i = _bencode_dec(buf, i)
            out.append(v)
        return out, i + 1
    if c == b"i":
        j = buf.index(b"e", i)
        return int(buf[i + 1:j]), j + 1
    j = buf.index(b":", i)
    n = int(buf[i:j])
    return buf[j + 1:j + 1 + n], j + 1 + n

def decode_torrent_files(data: bytes) -> list[dict]:
    try:
        d, _ = _bencode_dec(data, 0)
    except (ValueError, IndexError, TypeError):
        return []
    info = d.get(b"info") if isinstance(d, dict) else None
    if not isinstance(info, dict):
        return []
    out: list[dict] = []
    rows = info.get(b"files")
    if isinstance(rows, list):
        for f in rows:
            if not isinstance(f, dict) or b"length" not in f or b"path" not in f:
                continue
            name = b"/".join(p for p in f[b"path"] if isinstance(p, bytes))
            out.append({"n": name.decode("utf-8", "replace"),
                        "b": int(f[b"length"])})
    elif b"length" in info and b"name" in info:
        out.append({"n": info[b"name"].decode("utf-8", "replace"),
                    "b": int(info[b"length"])})
    return out

def torrent_meta(url: str, timeout: int = 15, referer: str = "") -> list[dict]:
    if not url.lower().endswith(".torrent"):
        page = http_get(url, timeout=timeout, referer=referer)
        m = re.search(r'href="(//[^"]+\.torrent)"', page)
        if not m:
            return []
        link = m.group(1)
        url = "https:" + link if link.startswith("//") else link
    data = http_get(url, timeout=timeout, referer=referer, binary=True, retries=0)
    return decode_torrent_files(data)

_BTDIG_SIZE_MUL = {"B": 1, "KB": 1024, "MB": 1024 ** 2,
                   "GB": 1024 ** 3, "TB": 1024 ** 4}
_BTDIG_AGE_RE = re.compile(
    r"(\d+)\s*(year|month|day|hour|minute|年|个月|天|小时|分钟)", re.I)
_BTDIG_AGE_MUL = {
    "year": 365 * 86400, "month": 30 * 86400, "day": 86400,
    "hour": 3600, "minute": 60,
    "年": 365 * 86400, "个月": 30 * 86400, "天": 86400,
    "小时": 3600, "分钟": 60,
}

def _btdig_size(text: str) -> int:
    m = _BTDIG_SIZE_RE.search(text.strip())
    if not m:
        return 0
    try:
        return int(float(m.group(1)) * _BTDIG_SIZE_MUL[m.group(2).upper()])
    except (TypeError, ValueError, OverflowError, KeyError):
        return 0

def _btdig_age(text: str) -> float | None:
    m = _BTDIG_AGE_RE.search(text.strip())
    if not m:
        return None
    try:
        return max(0.0, time.time() - int(m.group(1)) * _BTDIG_AGE_MUL[m.group(2)])
    except (TypeError, ValueError, OverflowError, KeyError):
        return None

def _btdig_files(block: str) -> list[dict]:
    re_pair = re.compile(
        r'class="file[_-]name"[^>]*>(.*?)</[^>]+>'
        r'(?:(?!file[_-]name).)*?class="file[_-]size"[^>]*>(.*?)<',
        re.I | re.S)
    re_loose = re.compile(
        r'>\s*([^<>]{2,160}?)\s*</[^>]+>\s*(?:<[^>]+>\s*)*'
        r'<span[^>]*class="file[_-]size"[^>]*>\s*([^<]{2,20}?)\s*<',
        re.I | re.S)
    re_tag = re.compile(r"<[^>]+>")
    out: list[dict] = []
    seen: set[str] = set()
    for m in re_pair.findall(block) or re_loose.findall(block):
        name = _unescape(re_tag.sub("", m[0])).strip()
        size = _unescape(re_tag.sub("", m[1])).strip()
        if not name or name in seen:
            continue
        if re.search(r"隐藏|hidden|个文件|files? found", name, re.I):
            continue
        seen.add(name)
        out.append({"n": name, "s": size})
        if len(out) >= 8:
            break
    return out

def _search_btdig(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["btdig"])
    url = (f"{root}/search?q={urllib.parse.quote(query)}"
           f"&p={max(0, int(page) - 1)}&order=0")
    text = http_get(url, timeout=timeout, batch=batch, headers={
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": root + "/",
    })

    re_row = re.compile(
        r'<div class="one_result".*?(?=<div class="one_result"|$)', re.I | re.S)
    re_magnet = re.compile(r'href="(magnet:\?xt=urn:btih:[0-9a-fA-F]{40})', re.I)
    re_title = re.compile(
        r'<div class="torrent_name".*?><a[^>]*>(.*?)</a>', re.I | re.S)
    re_size = re.compile(
        r'<span class="torrent_size"[^>]*>(.*?)</span>', re.I | re.S)
    re_age = re.compile(
        r'<span class="torrent_age"[^>]*>(.*?)</span>', re.I | re.S)
    re_tag = re.compile(r"<[^>]+>")

    items: list[dict] = []
    seen: set[str] = set()
    for row in re_row.findall(text):
        mag = re_magnet.search(row)
        if not mag:
            continue
        h = hash_from_magnet(mag.group(1))
        if not h or h in seen:
            continue
        seen.add(h)
        t = re_title.search(row)
        title = _unescape(re_tag.sub("", t.group(1))) if t else ""
        s = re_size.search(row)
        a = re_age.search(row)
        items.append(_mk(
            title=title,
            info_hash=h,
            size=_btdig_size(_unescape(re_tag.sub("", s.group(1)))) if s else 0,
            seeders=None,
            leechers=None,
            added=_btdig_age(_unescape(re_tag.sub("", a.group(1)))) if a else None,
            source="BTDigg",
            files=_btdig_files(row),
        ))
    return items

_BUILTIN_ADAPTERS = {
    "apibay": ("海盗湾", _search_apibay),
    "nyaa": ("Nyaa", _search_nyaa),
    "mikan": ("蜜柑计划", _search_mikan),
    "dmhy": ("动漫花园", _search_dmhy),
    "sukebei": ("Sukebei", _search_sukebei),
    "eztv": ("EZTV", _search_eztv),
    "bitsearch": ("BitSearch", _search_bitsearch),
    "tpb": ("TPB镜像", _search_tpb_mirror),
    "btdig": ("BTDigg", _search_btdig),
}

BUILTIN_KEYS = frozenset(_BUILTIN_ADAPTERS)

EMPTY_NEUTRAL = frozenset({"eztv"})

class Source:

    __slots__ = (
        "base",
        "empty_neutral",
        "enabled",
        "func",
        "key",
        "label",
        "order",
        "raw",
        "stype",
        "timeout",
    )

    def __init__(self, key, label, func, enabled=True, timeout=15,
                 stype="builtin", base="", order=0, raw=None,
                 empty_neutral=False):
        self.key = key
        self.label = label
        self.func = func
        self.enabled = bool(enabled)
        self.timeout = int(timeout or 15)
        self.stype = stype
        self.base = base or ""
        self.order = int(order or 0)
        self.raw = raw or {}
        self.empty_neutral = bool(empty_neutral)

    def search(self, query, page=1, timeout=None, batch=None):
        return self.func(query, page, timeout or self.timeout, self.base,
                         batch=batch)

    def probe(self, timeout=None):
        t0 = time.monotonic()
        try:
            items = self.search(PROBE_WORD, 1, timeout or self.timeout)
            if not items:
                items = self.search(PROBE_FALLBACK_WORD, 1, timeout or self.timeout)
            ms = int((time.monotonic() - t0) * 1000)
            return True, ms, len(items or []), ""
        except ProxyUnreachable as exc:
            ms = int((time.monotonic() - t0) * 1000)
            return False, ms, 0, str(exc)
        except Exception as exc:
            ms = int((time.monotonic() - t0) * 1000)
            return False, ms, 0, f"{type(exc).__name__}: {exc}"

    def __repr__(self) -> str:
        return f"Source({self.key!r}, {self.stype}, enabled={self.enabled})"

ALL_SOURCES: list[Source] = []
BY_KEY: dict[str, Source] = {}
_config = None

def _build_func(entry: dict):
    stype = (entry.get("type") or "builtin").strip()
    key = entry.get("key") or ""

    if stype == "builtin":
        pair = _BUILTIN_ADAPTERS.get(key)
        if pair is None:
            logger.warning("未知内置源 key=%s", key)
            return None
        return pair[1]

    from . import templates
    try:
        return templates.build(entry)
    except ValueError as exc:
        logger.warning("自定义源 %s 编译失败：%s", key, exc)
        return None

def reload_from_config(cfg=None):
    global _config, ALL_SOURCES, BY_KEY

    if cfg is not None:
        _config = cfg
    elif _config is None:
        from . import config as configmod
        _config = configmod.Config().load()

    built: list[Source] = []
    for entry in _config.sources:
        key = (entry.get("key") or "").strip()
        if not key:
            continue
        func = _build_func(entry)
        if func is None:
            continue
        built.append(Source(
            key=key,
            label=entry.get("label") or key,
            func=func,
            enabled=entry.get("enabled", True),
            timeout=int(entry.get("timeout", 15) or 15),
            stype=entry.get("type", "builtin"),
            base=entry.get("base", "") or "",
            order=int(entry.get("order", 0) or 0),
            raw=entry,
            empty_neutral=key in EMPTY_NEUTRAL,
        ))

    built.sort(key=lambda s: s.order)
    ALL_SOURCES = built
    BY_KEY = {s.key: s for s in built}
    return _config

def enabled_keys() -> list[str]:
    if not ALL_SOURCES:
        reload_from_config()
    return [s.key for s in ALL_SOURCES if s.enabled]

def get(key: str) -> Source | None:
    if not ALL_SOURCES:
        reload_from_config()
    return BY_KEY.get(key)

def search_one(source: Source, query: str, page: int = 1,
               timeout: int | None = None,
               batch: int | None = None):
    t0 = time.monotonic()
    try:
        items = source.search(query, page, timeout, batch=batch)
        ms = int((time.monotonic() - t0) * 1000)
        logger.info("源 %s 返回 %d 条", source.key, len(items or []))
        return source.key, items or [], "", ms
    except SearchCancelled:
        ms = int((time.monotonic() - t0) * 1000)
        logger.info("源 %s：搜索已停止", source.key)
        return source.key, [], "已停止", ms
    except ProxyUnreachable as exc:
        ms = int((time.monotonic() - t0) * 1000)
        logger.warning("源 %s：代理不可用", source.key)
        return source.key, [], str(exc), ms
    except urllib.error.HTTPError as exc:
        ms = int((time.monotonic() - t0) * 1000)
        msg = f"HTTP {exc.code}"
        logger.warning("源 %s：%s", source.key, msg)
        return source.key, [], msg, ms
    except Exception as exc:
        ms = int((time.monotonic() - t0) * 1000)
        msg = f"{type(exc).__name__}: {exc}"
        logger.warning("源 %s 失败：%s", source.key, msg)
        return source.key, [], msg, ms

def search_many(query: str, page: int = 1, timeout: int = 15,
                enabled=None, max_workers: int | None = None,
                on_source=None, batch: int | None = None) -> dict:
    if not ALL_SOURCES:
        reload_from_config()

    keys = set(enabled) if enabled is not None else set(enabled_keys())
    picked = [s for s in ALL_SOURCES if s.key in keys]
    if not picked:
        return {}

    if max_workers is None:
        workers = _max_workers(len(picked))
    else:
        workers = max(1, min(int(max_workers), len(picked)))

    results: dict[str, tuple[list[dict], str, int]] = {}
    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {
            pool.submit(search_one, s, query, page, timeout, batch): s.key
            for s in picked
        }
        for job in futures.as_completed(jobs):
            key, items, err, ms = job.result()
            results[key] = (items, err, ms)
            if on_source is not None:
                try:
                    on_source(key, items, err, ms)
                except Exception as exc:
                    logger.debug("on_source 回调异常：%s", exc)
    return results

