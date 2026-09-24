from __future__ import annotations

import concurrent.futures as futures
import json
import os
import re
import threading
import time
import urllib.parse

from . import (APP_TITLE, __version__, config, core, downloaders, log, migrate,
               paths, query, runtime, sources, store)

logger = log.get_logger(__name__)

HEALTH_WINDOW = config.HEALTH_WINDOW
EVENT_WINDOW = config.EVENT_WINDOW
FILES_CAP = 200
BAD_MIN = 3
SLOW_MS = 5000
MAX_QUERY_LEN = 100
MAGNET_CAP = 200
SEARCH_CACHE_TTL = 60.0
SEARCH_CACHE_MAX = 8


_URL_USERINFO_RE = re.compile(r"(?<=//)[^/@\s]+:[^/@\s]+(?=@)")

def _redact(text) -> str:
    return _URL_USERINFO_RE.sub("***", str(text or ""))

def _snapshot_row(row: dict) -> dict:
    snap = dict(row)
    for key in ("sources", "files", "altTitles"):
        value = snap.get(key)
        if isinstance(value, list):
            snap[key] = [dict(v) if isinstance(v, dict) else v for v in value]
    fetch = snap.get("fetch")
    if isinstance(fetch, dict):
        snap["fetch"] = dict(fetch)
    return snap

def is_query_too_long(text: str) -> bool:
    return len(text or "") > MAX_QUERY_LEN


OUTCOME_OK = "ok"
OUTCOME_EMPTY = "empty"
OUTCOME_SLOW = "slow"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_NET = "net"
OUTCOME_403 = "http403"
OUTCOME_429 = "http429"
OUTCOME_5XX = "http5xx"
OUTCOME_4XX = "http4xx"
OUTCOME_CANCEL = "cancel"
OUTCOME_PARSE = "parse"
OUTCOME_451 = "http451"
OUTCOME_BLOCKED = "blocked"
OUTCOME_SHAPE = "shape"
OUTCOME_UNKNOWN = "unknown"

OUTCOME_STATE = {
    OUTCOME_OK: "ok",
    OUTCOME_EMPTY: "empty",
    OUTCOME_SLOW: "ok",
    OUTCOME_TIMEOUT: "err",
    OUTCOME_NET: "err",
    OUTCOME_403: "err",
    OUTCOME_5XX: "err",
    OUTCOME_429: "warn",
    OUTCOME_4XX: "warn",
    OUTCOME_CANCEL: "na",
    OUTCOME_PARSE: "warn",
    OUTCOME_451: "err",
    OUTCOME_BLOCKED: "err",
    OUTCOME_SHAPE: "warn",
    OUTCOME_UNKNOWN: "warn",
}

OUTCOME_TEXT = {
    OUTCOME_OK: "",
    OUTCOME_EMPTY: "无结果",
    OUTCOME_SLOW: "",
    OUTCOME_TIMEOUT: "超时",
    OUTCOME_NET: "无法连接",
    OUTCOME_403: "403 拒绝",
    OUTCOME_429: "429 限流",
    OUTCOME_5XX: "服务异常",
    OUTCOME_4XX: "请求被拒",
    OUTCOME_CANCEL: "",
    OUTCOME_PARSE: "解析失败",
    OUTCOME_451: "451 地区受限",
    OUTCOME_BLOCKED: sources.BLOCKED_TEXT,
    OUTCOME_SHAPE: "结果页结构不符",
    OUTCOME_UNKNOWN: "请求失败",
}

FATAL_OUTCOMES = frozenset({OUTCOME_TIMEOUT, OUTCOME_NET,
                            OUTCOME_403, OUTCOME_5XX, OUTCOME_BLOCKED})

_HTTP_CODE_RE = re.compile(r"(?:HTTP\s+Error\s+|HTTP\s+|状态码\s*)(\d{3})")
_PROXY_SIGN_RE = re.compile(r"(?i)(?:\b(?:proxy|tunnel)\b|系统代理|代理不可达)")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_PARSE_SIGNS = ("jsondecodeerror", "expecting value", "unexpected token",
                "valueerror", "keyerror", "indexerror", "attributeerror",
                "typeerror", "not subscriptable", "has no attribute",
                "cannot unpack", "unsupported operand")
_NET_SIGNS = ("urlerror", "gaierror", "getaddrinfo", "name or service not known",
              "nodename nor servname", "connection refused", "connection reset",
              "connection aborted", "network is unreachable", "no route to host",
              "10061", "10060", "10054", "10051", "目标计算机积极拒绝",
              "由于连接方", "远程主机", "远程计算机", "连接被拒绝",
              "sslerror", "certificate verify", "tlsv1", "eof occurred")


def _addr_of(entry: dict, raw: bool = False) -> str:
    if entry.get("addr"):
        value = str(entry["addr"])
    else:
        value = sources.base_of(entry.get("key", ""), entry.get("base") or "")
    return str(value) if raw else _redact(value)


def _to_view(entry: dict, health: dict | None = None) -> dict:
    h = health or entry.get("health") or {}
    outcomes = [o for o in (h.get("outcomes") or []) if o]
    if not outcomes:
        outcomes = [t for t in (h.get("times") or []) if t]
    return {
        "key": entry.get("key", ""),
        "label": entry.get("label", entry.get("key", "")),
        "enabled": bool(entry.get("enabled", True)),
        "timeout": int(entry.get("timeout", 15) or 15),
        "addr": _addr_of(entry),
        "health": {
            "state": h.get("state", "na"),
            "ms": int(h.get("ms", 0) or 0),
            "err": h.get("err", ""),
            "times": list(h.get("times", []) or []),
            "outcomes": outcomes[-HEALTH_WINDOW:],
            "empty": _window_empty(outcomes),
            "lastOk": int(h.get("lastOk", 0) or 0),
            "lastCount": int(h.get("lastCount", 0) or 0),
        },
    }


def _http_code(err: str) -> int:
    if not err:
        return 0
    match = _HTTP_CODE_RE.search(str(err))
    if not match:
        return 0
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return 0


def classify(ok: bool, count: int, err: str, ms: int = 0) -> tuple[str, int]:
    if ok:
        if not count:
            return OUTCOME_EMPTY, 0
        if ms and ms >= SLOW_MS:
            return OUTCOME_SLOW, 0
        return OUTCOME_OK, 0

    low = (err or "").lower()
    if "已停止" in (err or "") or "cancelled" in low:
        return OUTCOME_CANCEL, 0

    if sources.BLOCKED_TEXT in (err or ""):
        return OUTCOME_BLOCKED, 0

    if "shapeerror" in low:
        return OUTCOME_SHAPE, 0

    code = _http_code(err)
    if code == 451:
        return OUTCOME_451, code
    if code in (401, 403):
        return OUTCOME_403, code
    if code == 429:
        return OUTCOME_429, code
    if 400 <= code < 500:
        return OUTCOME_4XX, code
    if code >= 500:
        return OUTCOME_5XX, code
    if "timed out" in low or "timeout" in low or "timeouterror" in low:
        return OUTCOME_TIMEOUT, 0

    if _PROXY_SIGN_RE.search(str(err or "")):
        return OUTCOME_NET, 0

    for sign in _NET_SIGNS:
        if sign in low:
            return OUTCOME_NET, 0

    for sign in _PARSE_SIGNS:
        if sign in low:
            return OUTCOME_PARSE, 0

    return OUTCOME_UNKNOWN, 0


def outcome_text(outcome: str, code: int = 0) -> str:
    if outcome == OUTCOME_403 and code:
        return f"HTTP {code} 拒绝"
    if outcome in (OUTCOME_5XX, OUTCOME_4XX) and code:
        return f"HTTP {code}"
    return OUTCOME_TEXT.get(outcome, "")


def _state_of(outcomes: list[str]) -> str:
    recent = [o for o in (outcomes or []) if o and o != OUTCOME_CANCEL]
    recent = recent[-HEALTH_WINDOW:]
    if not recent:
        return "na"
    if sum(1 for o in recent if o in FATAL_OUTCOMES) >= BAD_MIN:
        return "err"
    last = recent[-1]
    if last in FATAL_OUTCOMES:
        return "err"
    if last == OUTCOME_EMPTY:
        return "empty"
    if last in (OUTCOME_429, OUTCOME_4XX, OUTCOME_PARSE,
                OUTCOME_SHAPE, OUTCOME_UNKNOWN):
        return "warn"
    if last in (OUTCOME_OK, OUTCOME_SLOW):
        return "warn" if _window_empty(recent) else "ok"
    return OUTCOME_STATE.get(last, "na")


def _window_empty(outcomes: list[str]) -> bool:
    recent = [o for o in (outcomes or []) if o and o != OUTCOME_CANCEL]
    recent = recent[-HEALTH_WINDOW:]
    if not recent:
        return False
    hit = sum(1 for o in recent if o == OUTCOME_EMPTY)
    miss = sum(1 for o in recent if o in FATAL_OUTCOMES)
    if not hit or hit < miss:
        return False
    return hit > len(recent) - hit


def _blank_health() -> dict:
    return {"state": "na", "ms": 0, "err": "", "times": [], "outcomes": [],
            "events": [], "lastOk": 0, "lastCount": 0}


_RELAX_RANK = {
    "QUALITY": 0, "CODEC": 1, "YEAR": 2, "MISC": 3,
    "AUDIO": 4, "LANG": 5, "TYPE": 6, "GENRE": 7,
}

MAX_RELAX_ROUNDS = 2


def _relaxed_query(parsed: dict, dropped=()) -> tuple[str, str]:
    tokens = list(parsed.get("tokens") or [])
    subject = set(parsed.get("subject") or [])
    if len(tokens) <= 1:
        return "", ""

    gone = set(dropped or ())
    droppable = []
    for m in parsed.get("mods") or []:
        droppable.append((_RELAX_RANK.get(m.get("role"), 99), m.get("text")))
    for s in parsed.get("soft") or []:
        droppable.append((_RELAX_RANK.get(s.get("kind"), 99), s.get("text")))
    droppable.sort(key=lambda pair: pair[0])

    for _rank, text in droppable:
        if text not in tokens or text in subject or text in gone:
            continue
        rest = [t for t in tokens if t != text and t not in gone]
        if rest:
            return " ".join(rest), text
    return "", ""


def _item_view(item: dict) -> dict:
    size = item.get("size")
    added = item.get("added")
    names = item.get("sources")
    if not isinstance(names, list) or not names:
        only = item.get("source")
        names = [str(only)] if only else []
    raw_files = item.get("files")
    files = [
        {"n": str(f.get("n") or ""),
         "s": str(f.get("s") or (core.format_size(f.get("b")) if f.get("b") else "") or "")}
        for f in raw_files if isinstance(f, dict) and f.get("n")
    ][:FILES_CAP] if isinstance(raw_files, list) else []
    raw_fetch = item.get("fetch")
    fetch = {}
    if isinstance(raw_fetch, dict):
        u = str(raw_fetch.get("url") or "")
        if u.startswith("http://") or u.startswith("https://"):
            fetch = {"url": u}
    return {
        "hash": (item.get("info_hash") or "").lower(),
        "title": item.get("title") or "",
        "size": int(size or 0),
        "sizeText": core.format_size(size),
        "seeders": core._as_int(item.get("seeders")),
        "leechers": core._as_int(item.get("leechers")),
        "added": int(added or 0),
        "addedText": core.format_time_relative(added),
        "magnet": core.magnet_of(item),
        "sources": [str(n) for n in names if n],
        "files": files,
        "fetch": fetch,
    }


def _migration_source(report) -> str:
    if not isinstance(report, dict):
        return ""
    src = report.get("source") or ""
    if isinstance(src, dict):
        src = src.get("path", "")
    return str(src or "")


def _proxy_desc() -> str:
    try:
        manual = (self_proxy() or "").strip()
    except Exception:
        manual = ""
    if manual:
        return "手动设置 " + manual
    info = sources.proxy_info() or {}
    addr = info.get("https") or info.get("http") or ""
    if not addr:
        return "未检测到代理"
    return "跟随系统 " + addr


def self_proxy() -> str:
    from . import runtime
    return str(runtime.get("proxy", "") or "")


def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Api:

    def __init__(self, window=None):
        self._window = window
        self._cfg = config.Config()
        self._settings = config.Settings()
        self._health_store = config.HealthStore()
        self._health_lock = threading.Lock()
        self._probe_token = 0
        self._search_token = 0
        self._migration: dict = {}
        self._maxed = False
        self._search_cache: dict[str, dict] = {}
        self._search_cache_lock = threading.Lock()

    def boot(self) -> None:
        paths.ensure_dirs()
        config.sweep_temp_files(paths.data_dir())
        self._cfg.load()
        self._settings.load()
        runtime.replace(dict(self._settings.data))
        try:
            self._migration = migrate.run(self._settings)
        except Exception as exc:
            self._migration = {"done": False, "error": f"{type(exc).__name__}: {exc}"}
            logger.warning("旧配置迁移跳过：%s", exc)
        runtime.replace(dict(self._settings.data))
        self._load_health()
        sources.reload_from_config(self._cfg)
        logger.info("%s v%s 启动 · 数据目录 %s", APP_TITLE, __version__, paths.data_dir())

    def _load_health(self) -> None:
        self._health_store.load(self._cfg.sources).prune(
            [e.get("key", "") for e in self._cfg.sources])
        self._cfg.strip_health()
        self._health_store.save()
        self._cfg.save()

    def _demote_bad(self) -> None:
        if self._cfg.order_locked():
            return
        entries = self._cfg.sources
        if len(entries) < 2:
            return

        health = self._health_store.all()
        bad = set()
        good = set()
        for entry in entries:
            key = entry.get("key", "")
            row = health.get(key) or {}
            outcomes = [o for o in (row.get("outcomes") or []) if o and o != OUTCOME_CANCEL]
            window = outcomes[-HEALTH_WINDOW:]
            if len(window) < HEALTH_WINDOW:
                continue
            miss = sum(1 for o in window if o in FATAL_OUTCOMES)
            if miss >= BAD_MIN:
                bad.add(key)
            elif miss == 0 and window[-1] in (OUTCOME_OK, OUTCOME_SLOW):
                good.add(key)

        risen = set()
        for entry in entries:
            key = entry.get("key", "")
            if key in bad and not entry.get("demoted"):
                entry["demoted"] = True
                entry["demoteFrom"] = int(entry.get("order", 0) or 0)
            elif key in good and entry.get("demoted"):
                entry.pop("demoted", None)
                risen.add(key)

        def sort_key(item):
            index, entry = item
            key = entry.get("key", "")
            if key in bad:
                return (1, 0, index)
            if key in risen:
                return (0, int(entry.get("demoteFrom", index) or 0), 0)
            return (0, index, 1)

        ordered = [e for _, e in sorted(enumerate(entries), key=sort_key)]
        if [e.get("key", "") for e in ordered] == [e.get("key", "") for e in entries]:
            return
        for i, entry in enumerate(ordered):
            entry["order"] = i
        self._cfg.data["sources"] = ordered
        sources.reload_from_config(self._cfg)

    def _persist_health(self) -> None:
        self._demote_bad()
        self._health_store.prune([e.get("key", "") for e in self._cfg.sources])
        self._health_store.save()
        self._cfg.save()

    def _push(self, js: str) -> None:
        if not self._window:
            return
        try:
            self._window.evaluate_js(js)
        except Exception as exc:
            logger.debug("推送前端失败：%s", exc)

    def list_sources(self) -> list[dict]:
        return [_to_view(e, self._health_store.get(e.get("key", ""))) for e in self._cfg.sources]

    def toggle_source(self, key: str, on: bool) -> bool:
        if not self._cfg.set_enabled(key, bool(on)):
            return False
        self._cfg.save()
        sources.reload_from_config(self._cfg)
        self._cache_clear()
        return True

    def reorder_sources(self, keys: list[str]) -> bool:
        order = {k: i for i, k in enumerate(keys or [])}
        entries = sorted(
            self._cfg.sources,
            key=lambda e: order.get(e.get("key", ""), len(order)),
        )
        for i, entry in enumerate(entries):
            entry["order"] = i
        self._cfg.data["sources"] = entries
        self._cfg.set_order_locked(True)
        self._cfg.save()
        sources.reload_from_config(self._cfg)
        return True

    def set_auto_order(self, on: bool) -> bool:
        self._cfg.set_order_locked(not on)
        if on:
            self._demote_bad()
        self._cfg.save()
        sources.reload_from_config(self._cfg)
        return True

    def probe_sources(self, keys: list[str] | None = None) -> int:
        targets = [
            s for s in sources.ALL_SOURCES
            if s.enabled and (not keys or s.key in set(keys))
        ]
        if not targets:
            return 0
        self._probe_token += 1
        token = self._probe_token
        threading.Thread(
            target=self._probe_worker, args=(token, targets), daemon=True
        ).start()
        return len(targets)

    def _typical_ms(self, key: str) -> int:
        with self._health_lock:
            h = self._health_store.get(key) or {}
            events = list(h.get("events") or [])
        times = sorted(int(e.get("ms") or 0) for e in events
                       if int(e.get("ms") or 0) > 0
                       and e.get("outcome") in (OUTCOME_OK, OUTCOME_SLOW))
        if not times:
            return 0
        return times[len(times) // 2]

    def _mark(self, key: str, ok: bool, count: int, ms: int, err: str,
              round_id: str = "") -> dict:
        outcome, code = classify(ok, count, err, ms)
        if outcome == OUTCOME_CANCEL:
            return self._health_store.get(key) or _blank_health()
        with self._health_lock:
            h = self._health_store.data.setdefault(key, _blank_health())
            outcomes = list(h.get("outcomes") or [])
            outcomes.append(outcome)
            h["outcomes"] = outcomes[-HEALTH_WINDOW:]
            h["times"] = (list(h.get("times") or []) + [outcome])[-HEALTH_WINDOW:]
            events = list(h.get("events") or [])
            events.append({
                "at": int(time.time()),
                "outcome": outcome,
                "code": code,
                "count": int(count or 0),
                "ms": int(ms or 0),
                "round": str(round_id or ""),
                "err": _redact(err)[:200],
            })
            h["events"] = events[-EVENT_WINDOW:]
            if ms:
                h["ms"] = int(ms)
            if outcome in (OUTCOME_OK, OUTCOME_SLOW):
                h["lastOk"] = int(time.time())
                h["lastCount"] = int(count or 0)
            h["err"] = outcome_text(outcome, code)
            h["state"] = _state_of(h["outcomes"])
            return dict(h)

    def _probe_worker(self, token: int, targets) -> None:
        def one(src):
            if token != self._probe_token:
                return
            ok, ms, count, err = src.probe()
            outcome, code = classify(ok, count, err, ms)
            text = outcome_text(outcome, code)
            h = self._mark(src.key, ok, count, ms, err)
            payload = json.dumps({"key": src.key, "state": h["state"], "ms": h["ms"], "err": text,
                                  "outcome": outcome},
                                 ensure_ascii=False)
            self._push(f"window.__onProbe && window.__onProbe({payload})")

        workers = max(1, min(8, len(targets)))
        try:
            with futures.ThreadPoolExecutor(max_workers=workers) as pool:
                for _ in pool.map(one, targets):
                    pass
        except Exception as exc:
            logger.warning("测速收尾时出错：%s: %s", type(exc).__name__, exc)
        finally:
            self._persist_health()
            self._push("window.__onProbeDone && window.__onProbeDone()")

    def _source_stamp(self) -> str:
        parts = []
        for entry in self._cfg.sources:
            if not entry.get("enabled"):
                continue
            parts.append(":".join((
                str(entry.get("key", "")),
                str(_addr_of(entry, raw=True)),
                str(entry.get("timeout", "")),
            )))
        return ",".join(sorted(parts))

    def _cache_clear(self) -> None:
        with self._search_cache_lock:
            self._search_cache.clear()

    def _cache_take(self, ckey: str) -> dict | None:
        with self._search_cache_lock:
            item = self._search_cache.get(ckey)
            if item is None:
                return None
            if time.time() - item["ts"] > SEARCH_CACHE_TTL:
                self._search_cache.pop(ckey, None)
                return None
            return item

    def _cache_put(self, ckey: str, item: dict) -> None:
        with self._search_cache_lock:
            self._search_cache[ckey] = item
            while len(self._search_cache) > SEARCH_CACHE_MAX:
                oldest = min(self._search_cache,
                             key=lambda k: self._search_cache[k]["ts"])
                self._search_cache.pop(oldest, None)

    def start_search(self, text: str, page: int = 1) -> dict:
        text = (text or "").strip()
        min_len = int(self._settings.get("min_query_len", 2) or 2)
        if len(text) < min_len:
            return {"ok": False, "token": 0, "total": 0,
                    "error": core.min_len_message(min_len)}
        if is_query_too_long(text):
            return {"ok": False, "token": 0, "total": 0,
                    "error": f"关键字最长 {MAX_QUERY_LEN} 个字符"}

        keys = sources.enabled_keys()
        if not keys:
            return {"ok": False, "token": 0, "total": 0, "error": "没有启用的数据源"}

        try:
            start_page = max(1, int(page or 1))
        except (TypeError, ValueError):
            start_page = 1

        parsed = query.parse(text)
        token = sources.start_batch()
        self._search_token = token
        threading.Thread(
            target=self._search_worker, args=(token, text, keys, start_page),
            daemon=True
        ).start()
        return {"ok": True, "token": token, "total": len(keys), "error": "",
                "query": parsed, "page": start_page}

    def cancel_search(self, token=0) -> bool:
        try:
            t = int(token)
        except (TypeError, ValueError):
            t = 0
        if not t:
            t = self._search_token
        self._search_token = 0
        sources.cancel_batch(t)
        return True

    def torrent_files(self, payload: dict) -> dict:
        url = ""
        if isinstance(payload, dict):
            url = str(payload.get("url") or "")
        if not (url.startswith("http://") or url.startswith("https://")):
            return {"ok": False, "files": [], "error": "缺少有效的种子地址"}
        host = urllib.parse.urlparse(url)
        timeout = int(self._settings.get("timeout", 15) or 15)
        try:
            rows = sources.torrent_meta(url, timeout,
                                        referer=f"{host.scheme}://{host.netloc}/")
        except sources.TooLarge:
            return {"ok": False, "files": [], "error": "种子文件过大，已拒绝读取"}
        except Exception as exc:
            return {"ok": False, "files": [],
                    "error": f"{type(exc).__name__}: {exc}"[:180]}
        files = [{"n": r["n"], "s": core.format_size(r.get("b", 0))}
                 for r in rows if r.get("n")][:FILES_CAP]
        if not files:
            return {"ok": False, "files": [], "error": "种子内没有文件清单"}
        return {"ok": True, "files": files, "error": ""}

    def _search_worker(self, token: int, text: str, keys: list[str],
                       page: int = 1) -> None:
        min_len = int(self._settings.get("min_query_len", 2) or 2)
        rows: list[dict] = []
        index_of: dict[str, int] = {}
        tally = {"raw": 0, "dup": 0}
        parsed = query.parse(text)
        subject = parsed.get("subject") or []
        fuzzy_keys = set()
        keep_dup = self._settings.get("keep_duplicates", False) is True
        errors: dict[str, str] = {}
        ok_keys: set[str] = set()
        source_counts: dict[str, int] = {}
        relaxed_used: list[str] = []
        settled_evt = threading.Event()

        all_keys = keys
        ckey = ((parsed.get("text") or text) + "|" + ",".join(sorted(all_keys))
                + "|" + ("k" if keep_dup else "")
                + "|p" + str(int(page) or 1) + "|" + self._source_stamp())
        cached = self._cache_take(ckey)
        retry_keys = list(all_keys)

        if cached:
            rows = [_snapshot_row(r) for r in cached["rows"]]
            for i, row in enumerate(rows):
                ih = (row.get("info_hash") or "").lower()
                if ih and ih not in index_of:
                    index_of[ih] = i
            tally["raw"] = cached["raw"]
            tally["dup"] = cached["dup"]
            ok_keys = set(cached["ok"])
            fuzzy_keys = set(cached["fuzzy"])
            errors = dict(cached["errors"])
            source_counts = dict(cached["source_counts"])
            retry_keys = [k for k in all_keys if k in cached["errors"]]

            batch = [_item_view(r) for r in rows]
            if batch:
                payload = json.dumps(
                    {"token": token, "key": "", "items": batch},
                    ensure_ascii=False,
                )
                self._push(f"window.__onSearchBatch && window.__onSearchBatch({payload})")
            for key in all_keys:
                if key in retry_keys:
                    continue
                count = source_counts.get(key, 0)
                fuzzy = key in fuzzy_keys
                state = "ok" if count else "empty"
                payload = json.dumps(
                    {"token": token, "key": key, "count": count, "err": "",
                     "outcome": state, "state": state, "fuzzy": fuzzy,
                     "cached": True},
                    ensure_ascii=False,
                )
                self._push(f"window.__onSearchSource && window.__onSearchSource({payload})")
            logger.info("命中搜索缓存：%d 行复用，重打 %d 个源",
                        len(rows), len(retry_keys))

        relax_round = {"n": 0}

        def on_source(key, items, err, ms=0):
            if token != self._search_token:
                return
            items = items or []
            count = len(items)
            relaxed_zero = relax_round["n"] > 0 and not err and not count
            if relaxed_zero:
                logger.info("源 %s：放宽轮 0 条不计健康度（放宽词搜不到不算源失败）", key)
                return
            outcome, code = classify(not err, count, err, ms)
            text_err = outcome_text(outcome, code)
            mark = self._mark(key, not err, count, ms, err, round_id=str(token))
            fuzzy = bool(items) and subject and \
                sources.keyword_hit_rate(items, subject) < sources.FUZZY_RATE
            if fuzzy:
                fuzzy_keys.add(key)
            elif items and not err:
                ok_keys.add(key)
            if not err:
                errors.pop(key, None)
            source_counts[key] = count
            payload = json.dumps(
                {"token": token, "key": key, "count": count, "err": text_err,
                 "outcome": outcome, "state": mark.get("state", "na"),
                 "fuzzy": fuzzy},
                ensure_ascii=False,
            )
            self._push(f"window.__onSearchSource && window.__onSearchSource({payload})")

            merged = core.dedupe(items) if not keep_dup else list(items)
            tally["raw"] += count
            tally["dup"] += count - len(merged)

            batch = []
            for it in merged:
                ih = (it.get("info_hash") or "").lower()
                ikey = (ih + "|" + key) if keep_dup and ih else ih
                if ikey:
                    pos = index_of.get(ikey)
                    if pos is None:
                        index_of[ikey] = len(rows)
                        rows.append(it)
                    else:
                        tally["dup"] += 1
                        rows[pos] = core.dedupe([rows[pos], it])[0]
                batch.append(_item_view(rows[index_of[ikey]] if ikey else it))
            if batch:
                payload = json.dumps(
                    {"token": token, "key": key, "items": batch},
                    ensure_ascii=False,
                )
                self._push(f"window.__onSearchBatch && window.__onSearchBatch({payload})")

        def on_start(key: str) -> None:
            if token != self._search_token:
                return
            payload = json.dumps(
                {"token": token, "key": key,
                 "typical_ms": self._typical_ms(key)},
                ensure_ascii=False,
            )
            self._push(f"window.__onSearchStart && window.__onSearchStart({payload})")

        def run_round(qtext: str, subset=None) -> None:
            keys = subset if subset is not None else all_keys
            try:
                result, fatal = core.search(
                    qtext, page, None, keys, min_len=min_len,
                    on_source=on_source, batch=token, collect=False,
                    on_start=on_start,
                )
                if fatal and not rows and not ok_keys:
                    errors[""] = fatal
                for key, msg in (result.errors or {}).items():
                    if msg and msg != "已停止":
                        _o, code = classify(False, 0, msg)
                        errors[key] = outcome_text(_o, code)
            except Exception as exc:
                logger.exception("搜索异常")
                errors[""] = f"{type(exc).__name__}: {exc}"

        def runner() -> None:
            try:
                run_round(text, retry_keys if cached else None)
                rounds = 0
                while rounds < MAX_RELAX_ROUNDS:
                    if token != self._search_token:
                        return
                    exhausted = bool(ok_keys) and ok_keys <= fuzzy_keys
                    if rows and not exhausted:
                        return
                    nxt, dropped = _relaxed_query(parsed, relaxed_used)
                    if not nxt:
                        return
                    rounds += 1
                    relaxed_used.append(dropped)
                    relax_round["n"] = rounds
                    logger.info("放宽关键词重搜：去掉 %s", dropped)
                    run_round(nxt)
            finally:
                settled_evt.set()

        deadline_ms = int(self._settings.get("soft_deadline_ms", 3000) or 0)
        worker = threading.Thread(target=runner, daemon=True)
        worker.start()

        if deadline_ms > 0:
            settled_evt.wait(deadline_ms / 1000.0)
            if not settled_evt.is_set() and rows and token == self._search_token:
                self._push(
                    "window.__onSearchSettled && window.__onSearchSettled("
                    + json.dumps({"token": token}, ensure_ascii=False) + ")")

        settled_evt.wait()

        if token != self._search_token:
            return

        self._cache_put(ckey, {
            "ts": time.time(),
            "rows": [_snapshot_row(r) for r in rows],
            "raw": tally["raw"], "dup": tally["dup"],
            "ok": set(ok_keys), "fuzzy": set(fuzzy_keys),
            "errors": dict(errors),
            "source_counts": dict(source_counts),
        })

        self._persist_health()
        payload = json.dumps(
            {"token": token, "total": len(rows), "errors": errors,
             "raw": tally["raw"], "dup": tally["dup"],
             "fuzzy": sorted(fuzzy_keys),
             "relaxed": "、".join(relaxed_used),
             "kept": keep_dup}, ensure_ascii=False
        )
        self._push(f"window.__onSearchDone && window.__onSearchDone({payload})")

    def diagnostics(self, keys: list[str] | None = None) -> str:
        report = self._diagnostic_report(keys)
        if not report["sources"] and not report["lax"]:
            return ""
        return json.dumps(report, ensure_ascii=False, indent=2)

    def _diagnostic_report(self, keys: list[str] | None = None) -> dict:
        broken, silent, lax = self._scan_health(keys)
        rows = []
        for e, h in broken:
            rows.append(self._diag_row(e, h, "fail"))
        for e, h in silent:
            rows.append(self._diag_row(e, h, "empty"))
        return {
            "at": _stamp(),
            "version": __version__,
            "lax": list(lax[:8]),
            "sources": rows,
        }

    def _diag_row(self, entry: dict, h: dict, kind: str) -> dict:
        key = entry.get("key", "")
        outcomes = [o for o in (h.get("outcomes") or []) if o and o != OUTCOME_CANCEL]
        events = list(h.get("events") or [])[-HEALTH_WINDOW:]
        peers, hits = self._peer_stats(key)
        return {
            "key": key,
            "label": entry.get("label", key),
            "addr": _addr_of(entry),
            "kind": kind,
            "state": h.get("state", "na"),
            "err": h.get("err", ""),
            "lastOk": int(h.get("lastOk", 0) or 0),
            "outcomes": outcomes[-HEALTH_WINDOW:],
            "peers": peers,
            "peerHits": hits,
            "events": [
                {"at": ev.get("at", 0), "outcome": ev.get("outcome", ""),
                 "code": ev.get("code", 0), "count": ev.get("count", 0),
                 "ms": ev.get("ms", 0), "round": ev.get("round", ""),
                 "err": ev.get("err", "")}
                for ev in events
            ],
            "adapter": sources.adapter_location(key),
        }

    def _peer_stats(self, key: str) -> tuple[int, int]:
        events = [e for e in ((self._health_store.get(key) or {}).get("events") or [])
                  if e.get("outcome") == OUTCOME_EMPTY and e.get("round")]
        if not events:
            return 0, 0
        rounds = [e["round"] for e in events[-HEALTH_WINDOW:]]
        peers = 0
        hits = 0
        for other, row in self._health_store.all().items():
            if other == key:
                continue
            seen = False
            got = False
            for ev in (row.get("events") or []):
                if ev.get("round") not in rounds:
                    continue
                seen = True
                if (ev.get("count") or 0) > 0:
                    got = True
            if seen:
                peers += 1
                if got:
                    hits += 1
        return peers, hits

    def source_issues(self) -> list[dict]:
        broken, silent, _lax = self._scan_health()
        out: list[dict] = []
        for e, h in broken:
            out.append({
                "key": e.get("key", ""),
                "label": e.get("label", e.get("key", "")),
                "addr": _addr_of(e),
                "kind": "fail",
                "detail": h.get("err") or "请求失败",
            })
        for e, h in silent:
            peers, hits = self._peer_stats(e.get("key", ""))
            detail = f"最近 {min(len([o for o in (h.get('outcomes') or []) if o and o != OUTCOME_CANCEL]), HEALTH_WINDOW)} 次请求均为 0 条"
            if peers >= 1 and hits == peers:
                detail += f"，同轮其它 {peers} 个源都有结果"
            elif peers >= 1 and hits == 0:
                detail += "，同期其它源也没有结果"
            out.append({
                "key": e.get("key", ""),
                "label": e.get("label", e.get("key", "")),
                "addr": _addr_of(e),
                "kind": "empty",
                "detail": detail,
            })
        return out

    def _scan_health(self, keys=None):
        broken: list[tuple[dict, dict]] = []
        silent: list[tuple[dict, dict]] = []
        for e in self._cfg.sources:
            if keys and e.get("key") not in set(keys):
                continue
            h = self._health_store.get(e.get("key", "")) or {}
            state = h.get("state", "na")
            outcomes = [o for o in (h.get("outcomes") or []) if o and o != OUTCOME_CANCEL]
            last = outcomes[-1] if outcomes else ""
            if state == "err" or last in FATAL_OUTCOMES:
                broken.append((e, h))
            elif _window_empty(outcomes):
                silent.append((e, h))
        return broken, silent, sources.ssl_lax_hosts()

    def get_settings(self) -> dict:
        data = self._settings.data or {}
        return {k: data.get(k) for k in config.SETTING_SPECS if k in data}

    def default_settings(self) -> dict:
        return {k: config.DEFAULT_SETTINGS.get(k) for k in config.SETTING_SPECS}

    def proxy_status(self, force: bool = False) -> dict:
        return sources.proxy_status(force=bool(force))

    def save_settings(self, fields: dict) -> dict:
        proxy = str((fields or {}).get("proxy") or "").strip()
        _mapping, proxy_err = sources.parse_proxy(proxy)
        if proxy_err:
            return {"ok": False, "errors": [proxy_err]}
        bad = self._settings.update(**(fields or {}))
        if bad:
            return {"ok": False, "errors": bad}
        self._settings.save()
        runtime.replace(dict(self._settings.data))
        self._cache_clear()
        return {"ok": True, "errors": []}

    def reload_query_roles(self) -> bool:
        query.reload()
        return True

    def selftest(self) -> dict:
        missing = []
        try:
            view = self.list_sources()
            if not view:
                missing.append("sources 为空")
            else:
                need = ("key", "label", "type", "enabled", "timeout", "addr", "health")
                for field in need:
                    if field not in view[0]:
                        missing.append(field)
        except Exception as exc:
            missing.append(f"{type(exc).__name__}: {exc}")
        return {"ok": not missing, "missing": missing}

    def app_info(self) -> dict:
        d, label = store.data_dir_info()
        return {
            "version": __version__,
            "title": APP_TITLE,
            "dataDir": d,
            "mode": label,
            "logFile": log.current_log_file(),
            "migratedFrom": _migration_source(self._migration),
            "proxy": _proxy_desc(),
            "autoOrder": not self._cfg.order_locked(),
        }

    def open_logs(self) -> bool:
        ok, _msg = log.open_logs_dir()
        return ok

    def win_min(self) -> bool:
        try:
            self._window.minimize()
        except Exception:
            return False
        return True

    def win_max(self) -> bool:
        try:
            if self._maxed:
                self._window.restore()
            else:
                self._window.maximize()
            self._maxed = not self._maxed
        except Exception:
            return False
        return True

    def win_close(self) -> bool:
        try:
            self._window.destroy()
        except Exception:
            return False
        return True

    def set_window_tone(self, color: str) -> bool:
        value = str(color or "").strip()
        if not _HEX_COLOR_RE.match(value):
            return False
        try:
            import webview.platforms.winforms as wf
            from System.Drawing import ColorTranslator
            insts = list(getattr(wf.BrowserView, "instances", {}).values())
            if not insts:
                return False

            def apply():
                try:
                    insts[0].BackColor = ColorTranslator.FromHtml(value)
                except Exception as exc:
                    logger.debug("窗体底色切换失败：%s", exc)

            try:
                from System import Action
                insts[0].BeginInvoke(Action(apply))
            except Exception:
                apply()
            return True
        except Exception as exc:
            logger.debug("窗体底色不可用：%s", exc)
            return False

    def downloaders(self) -> list[dict]:
        out = []
        for d in downloaders.all_downloaders():
            out.append({"key": d.key, "label": d.label, "available": bool(d.available())})
        return out

    def deliver(self, magnets, key: str = "") -> dict:
        items = [str(m) for m in (magnets or []) if m]
        if not items:
            return {"ok": False, "message": "没有可提交的磁力链接"}
        if len(items) > MAGNET_CAP:
            return {"ok": False,
                    "message": f"一次最多提交 {MAGNET_CAP} 条，本次 {len(items)} 条"}

        prefer = str(key or self._settings.get("default_downloader", "") or "")
        target = downloaders.pick_default(prefer, refresh=True)
        if target is None:
            return {"ok": False, "message": "没找到可用的下载工具"}

        try:
            result = target.add(items, timeout=int(self._settings.get("timeout", 15) or 15))
        except Exception as exc:
            logger.warning("投递失败：%s", exc)
            return {"ok": False, "message": f"投递失败：{type(exc).__name__}"}

        return {
            "ok": bool(result.ok),
            "message": result.message(),
            "method": result.method or target.label,
        }
