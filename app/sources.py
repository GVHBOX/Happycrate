from __future__ import annotations

import base64
import concurrent.futures as futures
import html as _html
import json
import math
import re
import socket
import subprocess
import sys
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import log

logger = log.get_logger(__name__)

_DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

MAX_SEARCH_WORKERS = 12

_CANCEL_POLL = 0.1

PROBE_WORD = "test"
PROBE_FALLBACK_WORD = "1080p"

def log_url(url: str) -> str:
    parts = urllib.parse.urlsplit(str(url or ""))
    if not parts.query:
        return str(url or "")
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, "…", parts.fragment))

def log_host(url: str) -> str:
    return urllib.parse.urlsplit(str(url or "")).netloc

_RETRY_STATUS = (429, 500, 502, 503, 504)

_STRICT = ssl.create_default_context()
_LAX = ssl.create_default_context()
_LAX.check_hostname = False
_LAX.verify_mode = ssl.CERT_NONE

_LAX_TTL = 600.0
_LAX_LIMIT = 32

_LAX_HOSTS: dict[str, float] = {}
_LAX_LOCK = threading.Lock()

def ssl_lax_hosts() -> list[str]:
    _expire_lax()
    with _LAX_LOCK:
        return sorted(_LAX_HOSTS)

def ssl_known_lax(url: str) -> bool:
    _expire_lax()
    host = urllib.parse.urlsplit(url).hostname or ""
    with _LAX_LOCK:
        return host in _LAX_HOSTS

def ssl_mark_lax(url: str) -> None:
    host = urllib.parse.urlsplit(url).hostname or url
    now = time.monotonic()
    with _LAX_LOCK:
        _LAX_HOSTS[host] = now + _LAX_TTL
        if len(_LAX_HOSTS) > _LAX_LIMIT:
            stale = sorted(_LAX_HOSTS, key=_LAX_HOSTS.get)
            for name in stale[:len(_LAX_HOSTS) - _LAX_LIMIT]:
                _LAX_HOSTS.pop(name, None)

def _error_text(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    return f"{exc} {reason}" if reason is not None else f"{exc}"

def _cert_failure(exc: BaseException) -> bool:
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    text = _error_text(exc).lower()
    return "certificate_verify_failed" in text or "certificate verify failed" in text

def _demote_ssl(url: str, exc: BaseException) -> None:
    logger.warning("SSL 严格校验失败，临时降级 %ds：%s (%s)",
                   int(_LAX_TTL), url, exc)
    ssl_mark_lax(url)

def reset_ssl_lax() -> None:
    with _LAX_LOCK:
        _LAX_HOSTS.clear()

def _expire_lax() -> None:
    now = time.monotonic()
    with _LAX_LOCK:
        for host in [h for h, until in _LAX_HOSTS.items() if until <= now]:
            _LAX_HOSTS.pop(host, None)

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

class Blocked(Exception):
    pass

BLOCKED_TEXT = "人机验证拦截"

_CAPTCHA_SIGNS = (b"one more step", b"please complete the security check",
                  b"captcha", b"cf-browser-verification", b"just a moment",
                  b"enable javascript and cookies")

def _captcha_text(text: str) -> bool:
    low = (text or "")[:4096].lower()
    if "<html" not in low and "<!doctype" not in low:
        return False
    return any(sign.decode() in low for sign in _CAPTCHA_SIGNS)

def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, TimeoutError):
        return True
    text = _error_text(exc).lower()
    return "timed out" in text or "timeouterror" in text

_CAPTCHA_SCAN_BYTES = 8192

def _http_error_body(exc) -> bytes:
    try:
        return exc.read(_CAPTCHA_SCAN_BYTES) or b""
    except Exception:
        return b""

def _captcha_wall(exc) -> bool:
    if not isinstance(exc, urllib.error.HTTPError):
        return False
    if exc.code not in (403, 429):
        return False
    body = _http_error_body(exc).lower()
    return any(sign in body for sign in _CAPTCHA_SIGNS)

_cancel_epoch = 0
_EPOCH_LOCK = threading.Lock()

def start_batch() -> int:
    global _cancel_epoch
    with _EPOCH_LOCK:
        _cancel_epoch += 1
        return _cancel_epoch

def cancel_batch(token: int) -> None:
    global _cancel_epoch
    with _EPOCH_LOCK:
        if _cancel_epoch <= token:
            _cancel_epoch = token + 1

def _batch_alive(token: int) -> bool:
    with _EPOCH_LOCK:
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

def parse_proxy(raw: str) -> tuple[dict, str]:
    text = (raw or "").strip()
    if not text:
        return {}, ""

    parts = [p for p in (s.strip() for s in text.split(";")) if p]
    if not parts:
        return {}, "代理地址为空"

    def normalize(part: str) -> str:
        return part if "://" in part else "http://" + part

    def reject(part: str) -> str:
        scheme = part.split("://", 1)[0].lower() if "://" in part else ""
        if scheme.startswith("socks"):
            return f"不支持 {scheme} 代理，只支持 HTTP 代理端口"
        return f"代理地址格式无法识别：{part}"

    if len(parts) == 1:
        part = normalize(parts[0])
        low = part.lower()
        if not low.startswith(("http://", "https://")):
            return {}, reject(parts[0])
        if not urllib.parse.urlsplit(part).hostname:
            return {}, f"代理地址缺少主机名：{parts[0]}"
        return {"http": part, "https": part}, ""

    out: dict = {}
    for raw_part in parts:
        part = normalize(raw_part)
        low = part.lower()
        if not low.startswith(("http://", "https://")):
            return {}, reject(raw_part)
        if not urllib.parse.urlsplit(part).hostname:
            return {}, f"代理地址缺少主机名：{raw_part}"
        key = "https" if low.startswith("https://") else "http"
        if key in out:
            return {}, f"代理重复指定同一类型：{raw_part}"
        out[key] = part
    return out, ""

def _manual_proxy() -> dict:
    from . import runtime
    mapping, _err = parse_proxy(runtime.get("proxy", "") or "")
    return mapping

def _opener(url: str, lax: bool = False):
    manual = _manual_proxy()
    if not manual:
        try:
            manual = urllib.request.getproxies() or {}
        except Exception:
            manual = {}

    handlers = [urllib.request.ProxyHandler(manual)]
    if url.lower().startswith("https"):
        handlers.append(urllib.request.HTTPSHandler(
            context=_LAX if lax else _STRICT))
    return urllib.request.build_opener(*handlers)

def _probe_port(addr: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(addr if "//" in addr else "//" + addr)
        host = parts.hostname or ""
        port = parts.port
        if not host or port is None:
            return False
        with socket.socket() as sock:
            sock.settimeout(0.5)
            return sock.connect_ex((host, port)) == 0
    except Exception:
        return False

PROBE_URL = "http://www.gstatic.com/generate_204"
PROBE_TIMEOUT = 1.5
PROBE_CACHE_TTL = 15
_probe_cache = {"key": None, "at": 0.0, "data": None}

def _proxy_works(mapping: dict) -> bool:
    if not mapping:
        return False
    handlers = [urllib.request.ProxyHandler(mapping)]
    opener = urllib.request.build_opener(*handlers)
    try:
        req = urllib.request.Request(PROBE_URL, headers={"User-Agent": _ua()})
        with opener.open(req, timeout=PROBE_TIMEOUT) as resp:
            return resp.status < 400
    except urllib.error.HTTPError as exc:
        return exc.code < 400
    except Exception:
        return False

_TUN_WORDS = ("clash", "mihomo", "wintun", "sing-box", "singbox", "v2ray",
              "tap-windows", "utun", "tunnel")

_TUN_ADAPTER_TTL = 30.0
_tun_cache = {"at": 0.0, "name": None}


def reset_tun_cache() -> None:
    _tun_cache["at"] = 0.0
    _tun_cache["name"] = None


def tun_adapter(force: bool = False) -> str:
    if sys.platform != "win32":
        return ""
    now = time.monotonic()
    if (not force and _tun_cache["name"] is not None
            and now - _tun_cache["at"] < _TUN_ADAPTER_TTL):
        return _tun_cache["name"]
    name = _scan_tun_adapter()
    _tun_cache["at"] = time.monotonic()
    _tun_cache["name"] = name
    return name


def _scan_tun_adapter() -> str:
    try:
        out = subprocess.run(
            ["ipconfig"], capture_output=True, text=True,
            errors="replace", timeout=4,
        ).stdout
    except Exception:
        return ""
    for line in out.splitlines():
        if "适配器" not in line and "adapter" not in line.lower():
            continue
        low = line.lower()
        if any(w in low for w in _TUN_WORDS):
            head = line.split(":", 1)[0]
            m = re.search(r"适配器\s*(.+)$", head) or \
                re.search(r"adapter\s*(.+)$", head, re.I)
            name = (m.group(1) if m else head).strip(" .:")
            if name:
                return name
    return ""


def proxy_status(force: bool = False) -> dict:
    try:
        manual = _manual_proxy()
        system = urllib.request.getproxies() or {}
        if manual:
            mode = "manual"
            addr = manual.get("https") or manual.get("http") or ""
            mapping = manual
        elif system:
            mode = "system"
            addr = system.get("https") or system.get("http") or ""
            mapping = system
        else:
            mode = "none"
            addr = ""
            mapping = {}
        key = (mode, addr)
        now = time.time()
        if (not force and _probe_cache["key"] == key
                and now - _probe_cache["at"] < PROBE_CACHE_TTL):
            return dict(_probe_cache["data"])
        port_ok = _probe_port(addr) if mode != "none" else False
        data = {
            "mode": mode,
            "addr": addr,
            "portOk": port_ok,
            "works": _proxy_works(mapping) if port_ok else False,
            "systemOn": bool(system),
            "tun": tun_adapter() if mode == "none" else "",
            "checkedAt": now,
        }
        _probe_cache["key"] = key
        _probe_cache["at"] = now
        _probe_cache["data"] = dict(data)
        return data
    except Exception:
        return {"mode": "none", "addr": "", "portOk": False, "works": False,
                "systemOn": False, "checkedAt": time.time()}

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

_OVERSEAS_KEYS = frozenset({
    "nyaa", "sukebei", "mikan", "dmhy", "eztv", "bitsearch", "tpb",
})

def _is_timeout_text(err: str) -> bool:
    low = (err or "").lower()
    return "timed out" in low or "timeout" in low or "超时" in (err or "")

NET_FAIL_TEXT = "网络请求失败"
NET_TIMEOUT_TEXT = "网络请求超时"


def _proxy_down_text(addr: str) -> str:
    return f"系统代理 {addr} 连不上"


def proxy_hint_for(errors: dict) -> str:
    p = proxy_info()
    if p:
        addr = p.get("https") or p.get("http") or ""
        return _proxy_down_text(addr)

    keys = [k for k in (errors or {}) if k]
    if not keys:
        return NET_FAIL_TEXT

    timed = [k for k in keys if _is_timeout_text((errors or {}).get(k, ""))]
    overseas = [k for k in timed if k in _OVERSEAS_KEYS]
    if len(overseas) >= 2 and len(overseas) * 2 >= len(keys):
        if tun_adapter():
            return "TUN 模式已接管网络，这些源仍超时：可能被墙或站点故障。"
        return "未检测到代理，这些源需要代理才能访问。"
    if timed:
        return NET_TIMEOUT_TEXT
    return NET_FAIL_TEXT

def proxy_hint() -> str:
    p = proxy_info()
    if not p:
        return NET_FAIL_TEXT
    addr = p.get("https") or p.get("http") or ""
    return _proxy_down_text(addr)

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

MAX_TORRENT_BYTES = 8 * 1024 * 1024

class TooLarge(Exception):
    pass

class ShapeError(Exception):
    pass

def _read_capped(resp, limit: int | None, strict: bool = True) -> bytes:
    if not limit:
        return resp.read()
    chunks = []
    got = 0
    while True:
        chunk = resp.read(min(65536, limit - got + 1))
        if not chunk:
            break
        got += len(chunk)
        if got > limit:
            if strict:
                raise TooLarge(f"响应超过 {limit} 字节上限")
            chunks.append(chunk[:limit - (got - len(chunk))])
            break
        chunks.append(chunk)
    return b"".join(chunks)

def http_get(url: str, timeout: int = 15, referer: str = "",
             data: bytes | None = None,
             headers: dict | None = None,
             retries: int | None = None,
             batch: int | None = None,
             binary: bool = False,
             limit: int | None = None,
             strict: bool = True) -> bytes | str:
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
            with opener.open(req, timeout=timeout) as resp:
                raw = _read_capped(resp, limit, strict)
            if not binary:
                text = _decode(raw)
                if _captcha_text(text):
                    logger.warning("返回验证码页：%s", log_url(url))
                    raise Blocked(BLOCKED_TEXT)
                return text
            return raw

        except TooLarge:
            raise

        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in (403, 429) and _captcha_wall(exc):
                logger.warning("被验证码拦截：%s", log_url(url))
                raise Blocked(BLOCKED_TEXT) from exc
            if exc.code in _RETRY_STATUS and attempt <= retries:
                time.sleep(1.0 * attempt)
                logger.debug("HTTP %s：%s，%d/%d 次重试",
                             exc.code, log_url(url), attempt, retries)
                continue
            logger.debug("HTTP %s：%s（不重试）", exc.code, log_url(url))
            raise

        except SearchCancelled:
            raise

        except Exception as exc:
            last_exc = exc
            if _cert_failure(exc):
                if not use_lax:
                    _demote_ssl(url, exc)
                    use_lax = True
                    attempt -= 1
                    continue
                raise
            if _looks_like_proxy_failure(exc):
                logger.warning("代理不可达（%s）：%s", log_host(url), exc)
                raise ProxyUnreachable(proxy_hint()) from exc
            if _is_timeout(exc):
                logger.debug("请求超时：%s（%ds，不重试）", log_url(url), timeout)
                raise
            if attempt <= retries:
                time.sleep(1.5 * attempt)
                logger.debug("请求失败：%s，%d/%d 次重试", log_url(url), attempt, retries)
                continue
            logger.debug("请求失败：%s (%s: %s)", log_url(url), type(exc).__name__, exc)
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError(f"请求失败：{url}")

def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "gb18030", "big5"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1")

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
            if len(decoded) == 40 and set(decoded) != {"0"}:
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

CN_TZ = timezone(timedelta(hours=8))

def _ts_from_naive_cn(text: str) -> float | None:
    if not text:
        return None
    raw = str(text).strip()
    if raw.endswith("Z") or re.search(r"[+-]\d{2}:?\d{2}$", raw):
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt.replace(tzinfo=CN_TZ).timestamp()

_CN_SLASH_FORMS = ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d")

def _ts_from_cn_slash(text: str) -> float | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    for fmt in _CN_SLASH_FORMS:
        try:
            dt = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return dt.replace(tzinfo=CN_TZ).timestamp()
    return None

def _cn_date(text: str) -> float | None:
    return _ts_from_naive_cn(text) or _ts_from_cn_slash(text)

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
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
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
    "xccl263": "https://www.xccl263.xyz",
    "knaben": "https://api.knaben.org/v1",
}

def base_of(entry_key: str, base: str = "") -> str:
    return _base_of(base, DEFAULT_BASES.get(entry_key, ""))

def _base_of(base: str, default: str) -> str:
    return (base or default).rstrip("/")

_APIBAY_TOKEN_RE = re.compile(r"[\s\-_.:+/|,]+")

KEYWORD_SAMPLE = 12
FUZZY_RATE = 0.2


def keyword_hit_rate(items: list[dict], needles, sample: int = KEYWORD_SAMPLE) -> float:
    wanted = [str(n).strip().lower() for n in (needles or []) if str(n).strip()]
    if not wanted:
        return 1.0
    pool = [it for it in (items or [])[:sample] if isinstance(it, dict)]
    if not pool:
        return 1.0
    hit = 0
    for it in pool:
        title = (it.get("title") or "").lower()
        if any(w in title for w in wanted):
            hit += 1
    return hit / len(pool)


def _apibay_relevant(items: list[dict], query: str) -> bool:
    needle = (query or "").lower().strip()
    if not needle:
        return False
    if not any(ch.isalnum() for ch in needle):
        return False
    tokens = [t for t in _APIBAY_TOKEN_RE.split(needle) if len(t) >= 2]
    if keyword_hit_rate(items, [needle]) > 0:
        return True
    return keyword_hit_rate(items, tokens) > 0

APIBAY_CATS = (100, 200, 300, 400, 500, 600)
APIBAY_MAX_HITS = 600
APIBAY_WORKERS = 6

def _apibay_rows(text: str, source_key: str) -> list[dict]:
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
            source=source_key,
        ))
    return items

def _apibay_url(query: str, root: str, cat: int = 0) -> str:
    url = f"{root}/q.php?q={urllib.parse.quote(query)}"
    if cat:
        url += f"&cat={int(cat)}"
    return url

def _apibay_uncategorised(query: str, root: str, timeout: int,
                          batch) -> list[dict]:
    url = _apibay_url(query, root)
    return _apibay_rows(http_get(url, timeout=timeout, batch=batch), "apibay")

def _apibay_one_cat(root: str, cat: int, query: str, timeout: int,
                    batch) -> list[dict]:
    url = _apibay_url(query, root, cat)
    text = http_get(url, timeout=timeout, batch=batch)
    return _apibay_rows(text, "apibay")

def _apibay_by_cat(query: str, root: str, timeout: int, batch) -> list[dict]:
    pool = futures.ThreadPoolExecutor(
        max_workers=min(len(APIBAY_CATS), APIBAY_WORKERS))
    merged: list[dict] = []
    try:
        jobs = {pool.submit(_apibay_one_cat, root, c, query, timeout, batch): c
                for c in APIBAY_CATS}
        pages: dict[int, list[dict]] = {}
        for job in futures.as_completed(jobs):
            cat = jobs[job]
            try:
                pages[cat] = job.result()
            except Exception as exc:
                logger.debug("apibay 分类 %d 失败：%s", cat, exc)
        for cat in sorted(pages):
            merged.extend(pages[cat])
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return merged

def _search_apibay(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["apibay"])
    items = _apibay_uncategorised(query, root, timeout, batch)

    if not items:
        return []
    if not _apibay_relevant(items, query):
        logger.info("apibay 返回的是兜底列表（%d 条均未命中关键词）", len(items))
        return items

    seen: set[str] = set()
    out: list[dict] = []
    for it in items + _apibay_by_cat(query, root, timeout, batch):
        h = it["info_hash"]
        if h in seen:
            continue
        seen.add(h)
        out.append(it)
        if len(out) >= APIBAY_MAX_HITS:
            break
    return out

NYAA_PAGES = 14
NYAA_MAX_HITS = 1100
NYAA_WORKERS = 6

def _search_nyaa(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    return _nyaa_family(
        query, page, timeout, batch,
        _base_of(base, DEFAULT_BASES["nyaa"]), "nyaa",
        NYAA_PAGES, NYAA_MAX_HITS, NYAA_WORKERS)

SUKEBEI_PAGES = 14
SUKEBEI_MAX_HITS = 1100
SUKEBEI_WORKERS = 6
SUKEBEI_RSS_PAGE = 75

_SUKEBEI_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_SUKEBEI_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
_SUKEBEI_TAG_RE = re.compile(r"<[^>]+>")
_SUKEBEI_HASH_RE = re.compile(r"btih:([0-9a-fA-F]{40})")
_SUKEBEI_TITLE_RE = re.compile(r'href="/view/\d+"[^>]*title="([^"]{2,400})"')
_SUKEBEI_FETCH_RE = re.compile(r'href="(/download/\d+\.torrent)"')

def _sukebei_cell_text(cell: str) -> str:
    return re.sub(r"\s+", " ", _SUKEBEI_TAG_RE.sub(" ", cell)).strip()

def _parse_sukebei_html(page_text: str, root: str,
                        source_key: str = "sukebei") -> list[dict]:
    items: list[dict] = []
    for row in _SUKEBEI_ROW_RE.findall(page_text):
        mag = _SUKEBEI_HASH_RE.search(row)
        if not mag:
            continue
        cells = _SUKEBEI_CELL_RE.findall(row)
        if len(cells) < 8:
            continue
        titled = _SUKEBEI_TITLE_RE.search(row)
        title = _unescape(titled.group(1)) if titled else _sukebei_cell_text(cells[1])
        it = _mk(
            title=title, info_hash=mag.group(1).lower(),
            size=parse_size(_sukebei_cell_text(cells[3])),
            added=_ts_from_naive_cn(_sukebei_cell_text(cells[4]))
            or _ts_from_iso(_sukebei_cell_text(cells[4])),
            seeders=_to_int(_sukebei_cell_text(cells[5])),
            leechers=_to_int(_sukebei_cell_text(cells[6])),
            source=source_key,
        )
        fetch = _SUKEBEI_FETCH_RE.search(row)
        if fetch and root:
            it["fetch"] = {"url": root + fetch.group(1)}
        items.append(it)
    return items

def _nyaa_html_page(root: str, p: int, needle: str, timeout: int, batch,
                    source_key: str) -> list[dict]:
    url = f"{root}/?q={needle}&c=0_0&f=0&s=seeders&o=desc&p={p}"
    return _parse_sukebei_html(
        http_get(url, timeout=timeout, batch=batch), root, source_key)

def _nyaa_family(query: str, page: int, timeout: int, batch, root: str,
                 source_key: str, pages: int, max_hits: int,
                 workers: int) -> list[dict]:
    url = f"{root}/?page=rss&q={urllib.parse.quote(query)}&p={int(page)}"
    rss_failed: Exception | None = None
    try:
        rss = _parse_nyaa_rss(
            http_get(url, timeout=timeout, batch=batch), source_key, root)
    except SearchCancelled:
        raise
    except Exception as exc:
        rss_failed = exc
        rss = []
        logger.debug("%s RSS 失败，改用 HTML 页：%s", source_key, exc)

    seen: set[str] = set()
    items: list[dict] = []
    for it in rss:
        seen.add(it["info_hash"])
        items.append(it)

    if items and len(items) < SUKEBEI_RSS_PAGE:
        return items

    needle = urllib.parse.quote(query)
    collected: dict[int, list[dict]] = {}
    pool = futures.ThreadPoolExecutor(max_workers=min(pages, workers))
    try:
        jobs = {pool.submit(_nyaa_html_page, root, p, needle, timeout, batch,
                            source_key): p
                for p in range(1, pages + 1)}
        for job in futures.as_completed(jobs):
            p = jobs[job]
            try:
                collected[p] = job.result()
            except Exception as exc:
                logger.debug("%s 第 %d 页失败：%s", source_key, p, exc)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if not collected and not items and rss_failed is not None:
        raise rss_failed

    for p in sorted(collected):
        for it in collected[p]:
            h = it["info_hash"]
            if h in seen:
                continue
            seen.add(h)
            items.append(it)
            if len(items) >= max_hits:
                return items
    return items

def _search_sukebei(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    return _nyaa_family(
        query, page, timeout, batch,
        _base_of(base, DEFAULT_BASES["sukebei"]), "sukebei",
        SUKEBEI_PAGES, SUKEBEI_MAX_HITS, SUKEBEI_WORKERS)

def _parse_nyaa_rss(text: str, source_key: str, root: str = "") -> list[dict]:
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
            source=source_key,
        )
        gid = re.search(r"/view/(\d+)", _tags(chunk, "guid")[0])
        if gid and root:
            it["fetch"] = {"url": f"{root}/download/{gid.group(1)}.torrent"}
        items.append(it)
    return items

MIKAN_MAX_HITS = 1000
MIKAN_ROW_RE = re.compile(r"<tr[^>]*js-search-results-row[^>]*>(.*?)</tr>",
                          re.I | re.S)
MIKAN_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
MIKAN_MAGNET_RE = re.compile(
    r'data-magnet="magnet:\?xt=urn:btih:([0-9a-fA-F]{40})', re.I)
MIKAN_TAG_RE = re.compile(r"<[^>]+>")

def _mikan_cell_text(cell: str) -> str:
    return re.sub(r"\s+", " ", _unescape(MIKAN_TAG_RE.sub(" ", cell))).strip()

_MIKAN_EMPTY_SIGNS = ("没有找到", "未找到", "找不到", "no results", "not found")

def _mikan_empty(page_text: str) -> bool:
    low = (page_text or "")[:200000].lower()
    return any(sign in low for sign in _MIKAN_EMPTY_SIGNS)

def _parse_mikan_html(page_text: str, root: str) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for row in MIKAN_ROW_RE.findall(page_text):
        mag = MIKAN_MAGNET_RE.search(row)
        if not mag:
            continue
        h = mag.group(1).lower()
        if h in seen:
            continue
        cells = MIKAN_CELL_RE.findall(row)
        if len(cells) < 4:
            continue
        seen.add(h)
        it = _mk(
            title=_mikan_cell_text(cells[1]),
            info_hash=h,
            size=parse_size(_mikan_cell_text(cells[2])),
            added=_cn_date(_mikan_cell_text(cells[3])),
            source="mikan",
        )
        it["fetch"] = {"url": f"{root}/Home/Episode/{h}"}
        items.append(it)
        if len(items) >= MIKAN_MAX_HITS:
            break
    return items

def _search_mikan(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["mikan"])
    url = (f"{root}/Home/Search?searchstr={urllib.parse.quote(query)}")
    shape_exc: Exception | None = None
    items: list[dict] = []
    try:
        text = http_get(url, timeout=timeout, batch=batch)
    except SearchCancelled:
        raise
    except Exception as exc:
        logger.warning("mikan 搜索页请求失败，退回 RSS：%s", exc)
        return _search_mikan_rss(query, timeout, root, batch)
    try:
        items = _parse_mikan_html(text, root)
    except Exception as exc:
        shape_exc = exc
        logger.warning("mikan 搜索页解析失败，退回 RSS：%s", exc)
    if items:
        return items
    if shape_exc is None and not _mikan_empty(text):
        logger.warning("mikan 搜索页结构与预期不符（没解析出条目也未见空结果提示）")
    return _search_mikan_rss(query, timeout, root, batch)

def _search_mikan_rss(query, timeout, root, batch) -> list[dict]:
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
            added=_ts_from_naive_cn(_tags(chunk, "pubDate")[0])
            or _ts_from_iso(_tags(chunk, "pubDate")[0]),
            source="mikan",
        ))
    return items

DMHY_PAGES = 6
DMHY_MAX_HITS = 500
DMHY_WORKERS = 6

_DMHY_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_DMHY_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
_DMHY_HASH_RE = re.compile(r"btih:([0-9a-fA-F]{40})", re.I)
_DMHY_HASH_B32_RE = re.compile(r"btih:([A-Za-z2-7]{32})")
_DMHY_TAG_RE = re.compile(r"<[^>]+>")
_DMHY_HIDDEN_DATE_RE = re.compile(
    r'<span[^>]*style="display:\s*none;?"[^>]*>\s*(\d{4}/\d{2}/\d{2} \d{2}:\d{2})', re.I)

def _dmhy_cell_text(cell: str) -> str:
    return re.sub(r"\s+", " ", _DMHY_TAG_RE.sub("", cell)).strip()

def _dmhy_pub_date(row: str) -> float | None:
    m = _DMHY_HIDDEN_DATE_RE.search(row)
    if not m:
        return None
    return _ts_from_cn_slash(m.group(1))

def _dmhy_size(cell: str) -> int:
    text = _dmhy_cell_text(cell)
    if not text or text in ("-", "&nbsp;"):
        return 0
    return parse_size(text)

def _dmhy_count(cell: str) -> int | None:
    text = _dmhy_cell_text(cell)
    return int(text) if text.isdigit() else None

def _parse_dmhy_list(page_text: str, root: str) -> tuple[list[dict], int, bool]:
    start = page_text.find('id="topic_list"')
    if start < 0:
        return [], 0, False
    body = page_text[start:]
    tbody = body.find("<tbody")
    if tbody < 0:
        return [], 0, False
    rows = _DMHY_ROW_RE.findall(body[tbody:])

    items: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        mag = _DMHY_HASH_RE.search(row)
        if mag:
            h = mag.group(1).lower()
        else:
            m32 = _DMHY_HASH_B32_RE.search(row)
            if not m32:
                continue
            try:
                h = base64.b32decode(m32.group(1).upper()).hex()
            except Exception:
                continue
        if h in seen:
            continue

        cells = _DMHY_CELL_RE.findall(row)
        if len(cells) < 6:
            continue
        seen.add(h)

        link = re.search(r'href="(/topics/view/[^"]+)"[^>]*>(.*?)</a>',
                         cells[2], re.I | re.S)
        title = _unescape(_DMHY_TAG_RE.sub("", link.group(2))) if link else ""

        it = _mk(
            title=title, info_hash=h,
            size=_dmhy_size(cells[4]),
            seeders=_dmhy_count(cells[5]),
            added=_dmhy_pub_date(row),
            source="dmhy",
        )
        if link:
            it["fetch"] = {"url": root + link.group(1)}
        items.append(it)
    return items, len(rows), True

def _dmhy_page(root: str, p: int, needle: str, timeout: int, batch):
    url = f"{root}/topics/list/page/{p}?keyword={needle}"
    return _parse_dmhy_list(http_get(url, timeout=timeout, batch=batch), root)

def _merge_dmhy(items: list[dict], seen: set[str]) -> list[dict]:
    fresh: list[dict] = []
    for it in items:
        h = it["info_hash"]
        if h in seen:
            continue
        seen.add(h)
        fresh.append(it)
    return fresh

def _search_dmhy(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["dmhy"])
    needle = urllib.parse.quote(query)
    seen: set[str] = set()
    items: list[dict] = []
    pages: dict[int, tuple[list[dict], int, bool]] = {}
    failed: dict[int, Exception] = {}
    pool = futures.ThreadPoolExecutor(max_workers=DMHY_WORKERS)
    try:
        jobs = {pool.submit(_dmhy_page, root, p, needle, timeout, batch): p
                for p in range(1, DMHY_PAGES + 1)}
        for job in futures.as_completed(jobs):
            p = jobs[job]
            try:
                pages[p] = job.result()
            except Exception as exc:
                failed[p] = exc
                logger.debug("DMHY 第 %d 页失败：%s", p, exc)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    for p in sorted(pages):
        items.extend(_merge_dmhy(pages[p][0], seen))
        if len(items) >= DMHY_MAX_HITS:
            break

    if items:
        lost = sorted(set(failed) | {p for p, v in pages.items() if not v[2]})
        if lost:
            logger.warning("DMHY 有 %d/%d 页没拿到结果，可能不全：%s",
                           len(lost), DMHY_PAGES, lost)
        return items[:DMHY_MAX_HITS]
    if any(v[2] for v in pages.values()):
        return []
    if failed:
        raise next(iter(failed.values()))
    if pages and any(v[1] for v in pages.values()):
        return []
    return _search_dmhy_rss(query, timeout, root, batch)

def _search_dmhy_rss(query, timeout, root, batch) -> list[dict]:
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
            source="dmhy",
        )
        guid = _tags(chunk, "guid")[0].strip()
        if guid.startswith("http"):
            it["fetch"] = {"url": guid}
        items.append(it)
    return items

EZTV_PAGES = 15
EZTV_MAX_HITS = 400
EZTV_PAGE_SIZE = 100
EZTV_WORKERS = 6

def _eztv_page(root: str, p: int, timeout: int, batch) -> list[dict]:
    url = f"{root}/api/get-torrents?limit={EZTV_PAGE_SIZE}&page={p}"
    text = http_get(url, timeout=timeout, batch=batch)
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        logger.warning("EZTV 接口返回的不是 JSON：%s", str(text)[:120])
        return []
    rows = data.get("torrents") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []

    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = _text(row.get("title")).strip()
        h = _text(row.get("hash")).strip().lower()
        if not h or not _HASH_HEX_RE.fullmatch(h):
            continue
        out.append(_mk(
            title=title, info_hash=h,
            size=parse_size(row.get("size_bytes") or row.get("size")),
            seeders=_to_int(row.get("seeds")),
            leechers=_to_int(row.get("peers")),
            added=_to_int(row.get("date_released_unix")),
            source="eztv",
        ))
    return out

def _search_eztv(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["eztv"])
    needle = (query or "").lower().strip()
    if not needle:
        return []

    first = _eztv_page(root, 1, timeout, batch)
    pages: dict[int, list[dict]] = {1: first}
    failed: dict[int, Exception] = {}

    if len(first) >= EZTV_PAGE_SIZE:
        rest = list(range(2, EZTV_PAGES + 1))
        pool = futures.ThreadPoolExecutor(max_workers=min(EZTV_WORKERS, len(rest)))
        try:
            jobs = {pool.submit(_eztv_page, root, p, timeout, batch): p
                    for p in rest}
            for job in futures.as_completed(jobs):
                p = jobs[job]
                try:
                    pages[p] = job.result()
                except Exception as exc:
                    failed[p] = exc
                    logger.debug("EZTV 第 %d 页失败：%s", p, exc)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if failed and len(failed) >= len(rest):
            raise next(iter(failed.values()))

    items: list[dict] = []
    seen: set[str] = set()
    for p in sorted(pages):
        for it in pages[p]:
            if needle not in it["title"].lower():
                continue
            h = it["info_hash"]
            if h in seen:
                continue
            seen.add(h)
            items.append(it)
            if len(items) >= EZTV_MAX_HITS:
                items = items[:EZTV_MAX_HITS]
                break
    if failed:
        logger.warning("EZTV 有 %d 页失败，结果可能不全：%s",
                       len(failed), sorted(failed))
    return items

BITSEARCH_PAGES = 2
BITSEARCH_PAGE_SIZE = 100
BITSEARCH_MAX_HITS = 200
BITSEARCH_WORKERS = 2

def _bitsearch_page(root: str, p: int, query: str, timeout: int, batch) -> list[dict]:
    url = (f"{root}/api/v1/search?q={urllib.parse.quote(query)}"
           f"&sort=seeders&page={p}&limit={BITSEARCH_PAGE_SIZE}")
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

    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        h = _text(row.get("infohash")).strip().lower()
        if not _HASH_HEX_RE.fullmatch(h):
            continue
        out.append(_mk(
            title=_text(row.get("title")),
            info_hash=h,
            size=_to_int(row.get("size")) or 0,
            seeders=_to_int(row.get("seeders")),
            leechers=_to_int(row.get("leechers")),
            added=_ts_from_iso(_text(row.get("updatedAt"))),
            source="bitsearch",
        ))
    return out

def _search_bitsearch(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["bitsearch"])
    first_page = max(1, int(page))
    seen: set[str] = set()
    items: list[dict] = []
    ok_pages = 0
    last_exc: Exception | None = None

    targets = list(range(first_page, first_page + BITSEARCH_PAGES))
    pool = futures.ThreadPoolExecutor(max_workers=min(len(targets), BITSEARCH_WORKERS))
    try:
        jobs = {pool.submit(_bitsearch_page, root, p, query, timeout, batch): p
                for p in targets}
        pages: dict[int, list[dict]] = {}
        for job in futures.as_completed(jobs):
            p = jobs[job]
            try:
                pages[p] = job.result()
            except Exception as exc:
                last_exc = exc
                logger.debug("BitSearch 第 %d 页失败：%s", p, exc)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    for p in sorted(pages):
        ok_pages += 1
        for it in pages[p]:
            h = it["info_hash"]
            if h in seen:
                continue
            seen.add(h)
            items.append(it)
            if len(items) >= BITSEARCH_MAX_HITS:
                return items

    if not ok_pages and last_exc is not None:
        raise last_exc
    return items

KNABEN_PAGE_SIZE = 300
KNABEN_PAGES = 7
KNABEN_MAX_HITS = 2100
KNABEN_ORDER = "seeders"
KNABEN_WORKERS = 4

def _knaben_hits(payload) -> list:
    if not isinstance(payload, dict):
        raise ShapeError("knaben 返回的不是对象")
    hits = payload.get("hits")
    if not isinstance(hits, list):
        raise ShapeError("knaben 响应缺少 hits 列表")
    return hits

def _knaben_page(root: str, query: str, start: int, timeout: int,
                 batch) -> list[dict]:
    body = json.dumps({
        "query": query,
        "order_by": KNABEN_ORDER,
        "size": KNABEN_PAGE_SIZE,
        "from": start,
    }).encode("utf-8")
    text = http_get(root, timeout=timeout, batch=batch, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    out: list[dict] = []
    for hit in _knaben_hits(json.loads(text)):
        if not isinstance(hit, dict):
            continue
        h = _text(hit.get("hash")).strip().lower()
        if not _HASH_HEX_RE.fullmatch(h):
            continue
        out.append(_mk(
            title=_text(hit.get("title")),
            info_hash=h,
            size=_to_int(hit.get("bytes")) or 0,
            seeders=_to_int(hit.get("seeders")),
            leechers=_to_int(hit.get("peers")),
            added=_ts_from_iso(_text(hit.get("date"))),
            source="knaben",
        ))
    return out

def _search_knaben(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["knaben"])
    base_start = (max(1, int(page)) - 1) * KNABEN_PAGE_SIZE * KNABEN_PAGES
    starts = [base_start + i * KNABEN_PAGE_SIZE for i in range(KNABEN_PAGES)]

    seen: set[str] = set()
    items: list[dict] = []
    pages: dict[int, list[dict]] = {}
    last_exc: Exception | None = None

    pool = futures.ThreadPoolExecutor(
        max_workers=min(len(starts), KNABEN_WORKERS))
    try:
        jobs = {pool.submit(_knaben_page, root, query, start, timeout, batch): start
                for start in starts}
        for job in futures.as_completed(jobs):
            start = jobs[job]
            try:
                pages[start] = job.result()
            except Exception as exc:
                last_exc = exc
                logger.debug("Knaben from=%d 失败：%s", start, exc)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if not pages and last_exc is not None:
        raise last_exc

    for start in sorted(pages):
        for it in pages[start]:
            h = it["info_hash"]
            if h in seen:
                continue
            seen.add(h)
            items.append(it)
            if len(items) >= KNABEN_MAX_HITS:
                return items
    return items

_TPB_MONTH_DAY_RE = re.compile(r"^(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})$")
_TPB_TODAY_RE = re.compile(r"^today\s+(\d{1,2}):(\d{2})$", re.I)
_TPB_YDAY_RE = re.compile(r"^y-?day\s+(\d{1,2}):(\d{2})$", re.I)
_TPB_TAG_RE = re.compile(r"<[^>]+>")

def _tpb_cell_text(cell: str) -> str:
    return re.sub(r"\s+", " ", _unescape(_TPB_TAG_RE.sub("", cell))).strip()

def _tpb_added(text: str) -> float | None:
    raw = (text or "").strip()
    if not raw:
        return None
    now = datetime.now().astimezone()

    m = _TPB_TODAY_RE.match(raw)
    if m:
        dt = now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                         second=0, microsecond=0)
        return dt.timestamp()

    m = _TPB_YDAY_RE.match(raw)
    if m:
        dt = (now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                          second=0, microsecond=0)
              - timedelta(days=1))
        return dt.timestamp()

    m = _TPB_MONTH_DAY_RE.match(raw)
    if not m:
        return None
    month, day, hour, minute = (int(g) for g in m.groups())
    try:
        dt = now.replace(month=month, day=day, hour=hour, minute=minute,
                         second=0, microsecond=0)
    except ValueError:
        return None
    if dt.timestamp() > now.timestamp() + 86400:
        try:
            dt = dt.replace(year=dt.year - 1)
        except ValueError:
            return None
    return dt.timestamp()

TPB_MIRRORS = (
    "https://thepiratebay10.org",
    "https://thepiratebay10.xyz",
    "https://tpb.party",
    "https://piratebayproxy.live",
)
TPB_PAGES = 20
TPB_MAX_HITS = 600
TPB_WORKERS = 6
TPB_PAGE_SIZE = 30

_TPB_RESULT_MARK = 'id="searchResult"'

def _tpb_parse(text: str) -> list[dict]:
    re_row = re.compile(r"<tr[^>]*>.*?</tr>", re.I | re.S)
    re_cell = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
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

        cells = [_tpb_cell_text(c) for c in re_cell.findall(row)]
        size = parse_size(cells[4]) if len(cells) > 4 else 0
        seeders = _to_int(cells[5]) if len(cells) > 5 else None
        leechers = _to_int(cells[6]) if len(cells) > 6 else None
        added = _tpb_added(cells[2]) if len(cells) > 2 else None

        items.append(_mk(
            title=title, info_hash=h, size=size,
            seeders=seeders, leechers=leechers, added=added,
            source="tpb",
        ))
    return items

def _tpb_fetch(root: str, query: str, page: int, timeout: int, batch,
               retries: int = 0):
    url = f"{root}/search/{urllib.parse.quote(query)}/{int(page)}/99/0"
    return http_get(url, timeout=timeout, retries=retries, batch=batch)

def _search_tpb_mirror(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    if base:
        roots = [base.rstrip("/")]
    else:
        roots = list(TPB_MIRRORS)

    budget = max(1, int(timeout))
    deadline = time.monotonic() + budget
    per_try = max(3, budget // 2)
    net_exc: Exception | None = None
    shape_exc: Exception | None = None

    for root in roots:
        left = int(deadline - time.monotonic())
        if left < 1:
            logger.debug("TPB 镜像轮换时间用尽，跳过 %s", root)
            break
        try:
            text = _tpb_fetch(root, query, page, min(left, per_try), batch)
        except Exception as exc:
            net_exc = exc
            logger.debug("TPB 镜像 %s 请求失败：%s", root, exc)
            continue

        if _TPB_RESULT_MARK not in text:
            shape_exc = ShapeError(f"TPB 镜像 {root} 返回的不是搜索结果页")
            logger.debug("%s", shape_exc)
            continue

        items = _tpb_parse(text)
        if items:
            return _tpb_more_pages(root, query, page, timeout, batch, items)
        if re.search(r"no hits|nothing found", text, re.I):
            return []
        logger.debug("TPB 镜像 %s 结果页没有条目，换下一个", root)

    if net_exc is not None:
        raise net_exc
    if shape_exc is not None:
        raise shape_exc
    return []

def _tpb_more_pages(root: str, query: str, page: int, timeout: int, batch,
                    first: list[dict]) -> list[dict]:
    first_page = max(1, int(page))
    targets = list(range(first_page + 1, first_page + TPB_PAGES))
    seen: set[str] = set()
    items: list[dict] = []
    for it in first:
        seen.add(it["info_hash"])
        items.append(it)
    if len(first) < TPB_PAGE_SIZE:
        return items

    pages: dict[int, list[dict]] = {}
    pool = futures.ThreadPoolExecutor(max_workers=min(len(targets), TPB_WORKERS))
    try:
        jobs = {pool.submit(_tpb_fetch, root, query, p, timeout, batch): p
                for p in targets}
        for job in futures.as_completed(jobs):
            p = jobs[job]
            try:
                text = job.result()
            except Exception as exc:
                logger.debug("TPB 第 %d 页失败：%s", p, exc)
                continue
            if _TPB_RESULT_MARK not in text:
                continue
            pages[p] = _tpb_parse(text)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    for p in sorted(pages):
        for it in pages[p]:
            h = it["info_hash"]
            if h in seen:
                continue
            seen.add(h)
            items.append(it)
            if len(items) >= TPB_MAX_HITS:
                return items
    return items

_BENCODE_MAX_DEPTH = 32

def _bencode_dec(buf: bytes, i: int, depth: int = 0):
    if depth > _BENCODE_MAX_DEPTH:
        raise ValueError("bencode 嵌套过深")
    c = buf[i:i+1]
    if c == b"d":
        i += 1
        out = {}
        while buf[i:i+1] != b"e":
            k, i = _bencode_dec(buf, i, depth + 1)
            v, i = _bencode_dec(buf, i, depth + 1)
            out[k] = v
        return out, i + 1
    if c == b"l":
        i += 1
        out = []
        while buf[i:i+1] != b"e":
            v, i = _bencode_dec(buf, i, depth + 1)
            out.append(v)
        return out, i + 1
    if c == b"i":
        j = buf.index(b"e", i)
        return int(buf[i + 1:j]), j + 1
    j = buf.index(b":", i)
    n = int(buf[i:j])
    if n < 0 or j + 1 + n > len(buf):
        raise ValueError("bencode 字符串长度越界")
    return buf[j + 1:j + 1 + n], j + 1 + n

def decode_torrent_files(data: bytes) -> list[dict]:
    try:
        d, _ = _bencode_dec(data, 0)
    except (ValueError, IndexError, TypeError, RecursionError):
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
        page = http_get(url, timeout=timeout, referer=referer,
                        limit=MAX_TORRENT_BYTES, binary=True)
        m = re.search(rb'href="(//[^"]+\.torrent)"', page)
        if not m:
            return []
        link = m.group(1).decode("latin-1")
        url = "https:" + link if link.startswith("//") else link
    data = http_get(url, timeout=timeout, referer=referer, binary=True,
                    retries=0, limit=MAX_TORRENT_BYTES)
    return decode_torrent_files(data)

XCCL_PAGES = 4
XCCL_MAX_HITS = 200
XCCL_WORKERS = 2

_XCCL_ITEM_SPLIT_RE = re.compile(
    r'<div class="search-item[^"]*">(.*?)(?=<div class="search-item|</body>)',
    re.I | re.S)
_XCCL_HASH_RE = re.compile(r'href="/hash/([0-9a-fA-F]{40})\.html"', re.I)
_XCCL_TITLE_RE = re.compile(r'<a title="([^"]*)"', re.I)
_XCCL_SIZE_RE = re.compile(r"文件大小:\s*<b[^>]*>([^<]+)</b>", re.I)
_XCCL_DATE_RE = re.compile(r"创建时间:[^<]*<b>([^<]+)</b>", re.I)
_XCCL_HEAT_RE = re.compile(r"下载热度:[^<]*<b>([^<]+)</b>", re.I)
_XCCL_DATE_FMT = "%Y-%m-%d"

def _xccl_added(text: str) -> float | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw[:10], _XCCL_DATE_FMT)
    except ValueError:
        return None
    return dt.replace(tzinfo=CN_TZ).timestamp()

def _parse_xccl263(text: str) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()

    for block in _XCCL_ITEM_SPLIT_RE.findall(text):
        mag = _XCCL_HASH_RE.search(block)
        if not mag:
            continue
        h = mag.group(1).lower()
        if h in seen:
            continue
        seen.add(h)

        title = _XCCL_TITLE_RE.search(block)
        size = _XCCL_SIZE_RE.search(block)
        date = _XCCL_DATE_RE.search(block)
        heat = _XCCL_HEAT_RE.search(block)

        items.append(_mk(
            title=_unescape(title.group(1)) if title else "",
            info_hash=h,
            size=parse_size(size.group(1)) if size else 0,
            seeders=_to_int(heat.group(1)) if heat else None,
            added=_xccl_added(date.group(1)) if date else None,
            source="xccl263",
        ))
    return items

def _xccl263_page(root: str, p: int, query: str, timeout: int, batch):
    url = f"{root}/search/kw-{urllib.parse.quote(query)}-{p}.html"
    return _parse_xccl263(http_get(url, timeout=timeout, batch=batch, headers={
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": root + "/",
    }))

def _search_xccl263(query, page=1, timeout=15, base="", batch=None) -> list[dict]:
    root = _base_of(base, DEFAULT_BASES["xccl263"])
    first = max(1, int(page))
    last_exc: Exception | None = None
    pages: dict[int, list[dict]] = {}

    targets = list(range(first, first + XCCL_PAGES))
    pool = futures.ThreadPoolExecutor(max_workers=min(len(targets), XCCL_WORKERS))
    try:
        jobs = {pool.submit(_xccl263_page, root, p, query, timeout, batch): p
                for p in targets}
        for job in futures.as_completed(jobs):
            p = jobs[job]
            try:
                pages[p] = job.result()
            except Exception as exc:
                last_exc = exc
                logger.debug("小草磁力第 %d 页失败：%s", p, exc)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if not pages and last_exc is not None:
        raise last_exc

    seen: set[str] = set()
    items: list[dict] = []
    for p in sorted(pages):
        for it in pages[p]:
            h = it["info_hash"]
            if h in seen:
                continue
            seen.add(h)
            items.append(it)
            if len(items) >= XCCL_MAX_HITS:
                return items
    return items

_BUILTIN_ADAPTERS = {
    "apibay": ("海盗湾", _search_apibay),
    "nyaa": ("Nyaa", _search_nyaa),
    "mikan": ("蜜柑计划", _search_mikan),
    "dmhy": ("动漫花园", _search_dmhy),
    "sukebei": ("Sukebei", _search_sukebei),
    "eztv": ("EZTV", _search_eztv),
    "bitsearch": ("BitSearch", _search_bitsearch),
    "knaben": ("Knaben", _search_knaben),
    "tpb": ("TPB镜像", _search_tpb_mirror),
    "xccl263": ("小草磁力", _search_xccl263),
}

BUILTIN_KEYS = frozenset(_BUILTIN_ADAPTERS)

PAGELESS_KEYS = frozenset({"apibay", "mikan", "dmhy", "eztv"})

BUILTIN_ADAPTER_NAMES = {key: fn.__name__ for key, (_label, fn) in _BUILTIN_ADAPTERS.items()}

def adapter_location(key: str, stype: str = "builtin") -> str:
    if stype == "builtin":
        name = BUILTIN_ADAPTER_NAMES.get(key)
        return f"app/sources.py :: {name}" if name else f"app/sources.py :: (未知内置源 {key})"
    return f"app/templates.py :: _make_{stype}"

class Source:

    __slots__ = (
        "base",
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
                 stype="builtin", base="", order=0, raw=None):
        self.key = key
        self.label = label
        self.func = func
        self.enabled = bool(enabled)
        self.timeout = int(timeout or 15)
        self.stype = stype
        self.base = base or ""
        self.order = int(order or 0)
        self.raw = raw or {}

    def search(self, query, page=1, timeout=None, batch=None):
        if self.key in PAGELESS_KEYS:
            page = 1
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
        except Blocked as exc:
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

def _search_starting(source: Source, query: str, page: int, timeout, batch,
                     on_start):
    if on_start is not None:
        try:
            on_start(source.key)
        except Exception as exc:
            logger.debug("on_start 回调异常：%s", exc)
    return search_one(source, query, page, timeout, batch=batch)

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
    except Blocked as exc:
        ms = int((time.monotonic() - t0) * 1000)
        logger.warning("源 %s：人机验证拦截", source.key)
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

def search_many(query: str, page: int = 1, timeout: int | None = None,
                enabled=None, max_workers: int | None = None,
                on_source=None, batch: int | None = None,
                on_start=None) -> dict:
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
    pool = futures.ThreadPoolExecutor(max_workers=workers)
    try:
        jobs = {}
        for s in picked:
            jobs[pool.submit(_search_starting, s, query, page, timeout, batch,
                             on_start)] = s.key
        pending = set(jobs)
        while pending:
            if batch is not None and not _batch_alive(batch):
                logger.info("搜索已停止，放弃等待剩余 %d 个源", len(pending))
                break
            done, pending = futures.wait(
                pending, timeout=_CANCEL_POLL,
                return_when=futures.FIRST_COMPLETED)
            for job in done:
                key, items, err, ms = job.result()
                results[key] = (items, err, ms)
                if on_source is not None:
                    try:
                        on_source(key, items, err, ms)
                    except Exception as exc:
                        logger.debug("on_source 回调异常：%s", exc)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return results

