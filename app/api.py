from __future__ import annotations

import concurrent.futures as futures
import json
import os
import re
import threading
import time
import urllib.parse

from . import (APP_TITLE, __version__, config, core, downloaders, log, migrate,
               paths, runtime, sources, store, templates)

logger = log.get_logger(__name__)

HEALTH_WINDOW = config.HEALTH_WINDOW
EVENT_WINDOW = config.EVENT_WINDOW
FILES_CAP = 200
BAD_MIN = 3
SLOW_MS = 5000

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

OUTCOME_STATE = {
    OUTCOME_OK: "ok",
    OUTCOME_EMPTY: "empty",
    OUTCOME_SLOW: "warn",
    OUTCOME_TIMEOUT: "err",
    OUTCOME_NET: "err",
    OUTCOME_403: "err",
    OUTCOME_5XX: "err",
    OUTCOME_429: "warn",
    OUTCOME_4XX: "warn",
    OUTCOME_CANCEL: "na",
    OUTCOME_PARSE: "warn",
    OUTCOME_451: "err",
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
}

FATAL_OUTCOMES = frozenset({OUTCOME_TIMEOUT, OUTCOME_NET,
                            OUTCOME_403, OUTCOME_5XX})

_HTTP_CODE_RE = re.compile(r"(?:HTTP\s+Error\s+|HTTP\s+)?\b([45]\d{2})\b")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_PARSE_SIGNS = ("jsondecodeerror", "expecting value", "unexpected token",
                "valueerror", "keyerror", "indexerror", "attributeerror",
                "typeerror", "not subscriptable", "has no attribute",
                "cannot unpack", "unsupported operand")


def _addr_of(entry: dict) -> str:
    if entry.get("type") == "builtin":
        if entry.get("addr"):
            return str(entry["addr"])
        return sources.base_of(entry.get("key", ""), entry.get("base") or "")
    return entry.get("addr") or entry.get("url") or ""


def _base_field(key: str, addr: str) -> str:
    addr = (addr or "").strip().rstrip("/")
    if not addr or addr == sources.base_of(key, ""):
        return ""
    return addr


def _to_view(entry: dict, health: dict | None = None) -> dict:
    h = health or entry.get("health") or {}
    outcomes = [o for o in (h.get("outcomes") or []) if o]
    if not outcomes:
        outcomes = [t for t in (h.get("times") or []) if t]
    return {
        "key": entry.get("key", ""),
        "label": entry.get("label", entry.get("key", "")),
        "type": entry.get("type", "builtin"),
        "enabled": bool(entry.get("enabled", True)),
        "timeout": int(entry.get("timeout", 15) or 15),
        "addr": _addr_of(entry),
        "listPath": entry.get("list_path", "") or "",
        "map": entry.get("map") or {},
        "hashPattern": entry.get("hash_pattern", "") or "",
        "titlePattern": entry.get("title_pattern", "") or "",
        "sizePattern": entry.get("size_pattern", "") or "",
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

    if "tunnel" in low or "proxy" in low:
        return OUTCOME_NET, 0

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

    for sign in _PARSE_SIGNS:
        if sign in low:
            return OUTCOME_PARSE, 0

    return OUTCOME_NET, 0


def outcome_text(outcome: str, code: int = 0) -> str:
    if outcome == OUTCOME_403 and code:
        return f"HTTP {code} 拒绝"
    if outcome in (OUTCOME_5XX, OUTCOME_4XX) and code:
        return f"HTTP {code}"
    return OUTCOME_TEXT.get(outcome, "")


def _state_of(outcomes: list[str], ms: int = 0) -> str:
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
    if last in (OUTCOME_SLOW, OUTCOME_429, OUTCOME_4XX, OUTCOME_PARSE):
        return "warn"
    if last == OUTCOME_OK:
        if ms and ms >= SLOW_MS:
            return "warn"
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


def _pattern_fields(item: dict) -> dict:
    out = {}
    for name, camel in (("hash_pattern", "hashPattern"),
                        ("title_pattern", "titlePattern"),
                        ("size_pattern", "sizePattern")):
        value = str(item.get(camel) or item.get(name) or "").strip()
        if value:
            out[name] = value
    return out


def _draft(item: dict) -> dict:
    return {
        "key": item.get("key") or "test",
        "label": item.get("label") or "test",
        "type": item.get("type") or "json",
        "url": _addr_of(item),
        "base": item.get("base", "") or "",
        "list_path": item.get("listPath", "") or "",
        "map": item.get("map") or {},
        "hash_pattern": item.get("hashPattern", "") or item.get("hash_pattern", "") or "",
        "title_pattern": item.get("titlePattern", "") or item.get("title_pattern", "") or "",
        "size_pattern": item.get("sizePattern", "") or item.get("size_pattern", "") or "",
        "timeout": item.get("timeout", 15),
    }


def _item_view(item: dict) -> dict:
    size = item.get("size")
    added = item.get("added")
    names = item.get("sources")
    if not isinstance(names, list) or not names:
        only = item.get("source")
        names = [str(only)] if only else []
    raw_files = item.get("files")
    files = [
        {"n": str(f.get("n") or ""), "s": str(f.get("s") or "")}
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
        "seeders": int(item.get("seeders") or 0),
        "leechers": int(item.get("leechers") or 0),
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

    def boot(self) -> None:
        paths.ensure_dirs()
        config.sweep_temp_files(paths.data_dir())
        self._cfg.load()
        self._settings.load()
        runtime.replace(dict(self._settings.data))
        try:
            self._migration = migrate.run(self._cfg, self._settings)
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

    def next_custom_key(self) -> str:
        return self._cfg.next_custom_key()

    def toggle_source(self, key: str, on: bool) -> bool:
        if not self._cfg.set_enabled(key, bool(on)):
            return False
        self._cfg.save()
        sources.reload_from_config(self._cfg)
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

    def save_source(self, entry: dict) -> dict:
        item = dict(entry or {})
        key = str(item.get("key") or "").strip()
        if key and item.get("isNew") is False and not self._cfg.get(key):
            return {"ok": False, "errors": [f"找不到数据源 {key}"]}

        if key and self._cfg.get(key):
            current = self._cfg.get(key)
            final_type = str(item.get("type") or current.get("type") or "builtin")
            if final_type == "builtin":
                payload = {
                    "label": item.get("label") or current.get("label"),
                    "type": "builtin",
                    "base": _base_field(key, _addr_of(item) or current.get("base", "")),
                    "timeout": item.get("timeout", current.get("timeout", 15)),
                    "enabled": bool(item.get("enabled", current.get("enabled", True))),
                }
            else:
                payload = {
                    "label": item.get("label") or current.get("label"),
                    "type": final_type,
                    "url": _addr_of(item),
                    "list_path": item.get("listPath", "") or "",
                    "map": item.get("map") or {},
                    "timeout": item.get("timeout", current.get("timeout", 15)),
                    "enabled": bool(item.get("enabled", current.get("enabled", True))),
                    **_pattern_fields(item),
                }
            errs = config.validate_source({**current, **payload})
            if errs:
                return {"ok": False, "errors": errs}
            self._cfg.update(key, **payload)
            self._cfg.save()
            sources.reload_from_config(self._cfg)
            return {"ok": True, "errors": []}

        new = {
            "key": key or self._cfg.next_custom_key(),
            "label": item.get("label") or "未命名源",
            "type": item.get("type") or "json",
            "url": _addr_of(item),
            "list_path": item.get("listPath", "") or "",
            "map": item.get("map") or {},
            "timeout": int(item.get("timeout", 15) or 15),
            "enabled": bool(item.get("enabled", True)),
            **_pattern_fields(item),
        }
        ok, errors = self._cfg.add_source(new)
        if ok:
            self._cfg.save()
            sources.reload_from_config(self._cfg)
        return {"ok": ok, "errors": errors}

    def remove_source(self, key: str) -> bool:
        if not self._cfg.remove_source(key):
            return False
        self._health_store.drop(key)
        self._cfg.save()
        sources.reload_from_config(self._cfg)
        return True

    def test_source(self, entry: dict) -> dict:
        item = dict(entry or {})
        if item.get("type") == "builtin":
            src = sources.get(item.get("key", ""))
            if not src:
                return {"ok": False, "count": 0, "errors": ["找不到这个源"]}
            base = _base_field(item.get("key", ""), _addr_of(item))
            draft = sources.Source(
                key=src.key, label=src.label, func=src.func, enabled=True,
                timeout=int(item.get("timeout") or src.timeout),
                base=base or sources.base_of(item.get("key", ""), ""),
            )
            ok, ms, count, err = draft.probe()
            outcome, code = classify(ok, count, err, ms)
            return {
                "ok": ok,
                "count": count if ok else 0,
                "ms": ms,
                "errors": [] if ok else [outcome_text(outcome, code) or "请求失败"],
            }

        draft = _draft(item)
        errors = config.validate_source(draft)
        if errors:
            return {"ok": False, "count": 0, "errors": errors}
        try:
            ok, count, msg = templates.test_source(
                draft, "test", int(draft.get("timeout") or 15))
        except ValueError as exc:
            return {"ok": False, "count": 0, "errors": [str(exc)]}
        return {
            "ok": ok,
            "count": count,
            "errors": [] if ok else [msg or "请求失败"],
        }

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
                "err": str(err or "")[:200],
            })
            h["events"] = events[-EVENT_WINDOW:]
            if ms:
                h["ms"] = int(ms)
            if outcome in (OUTCOME_OK, OUTCOME_SLOW):
                h["lastOk"] = int(time.time())
                h["lastCount"] = int(count or 0)
            h["err"] = outcome_text(outcome, code)
            h["state"] = _state_of(h["outcomes"], h.get("ms", 0))
            return dict(h)

    def _probe_worker(self, token: int, targets) -> None:
        def one(src):
            if token != self._probe_token:
                return
            ok, ms, count, err = src.probe()
            outcome, code = classify(ok, count, err, ms)
            text = outcome_text(outcome, code)
            h = self._mark(src.key, ok, count, ms, err)
            payload = json.dumps({"key": src.key, "state": h["state"], "ms": h["ms"], "err": text},
                                 ensure_ascii=False)
            self._push(f"window.__onProbe && window.__onProbe({payload})")

        workers = max(1, min(8, len(targets)))
        with futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for _ in pool.map(one, targets):
                pass
        self._persist_health()
        self._push("window.__onProbeDone && window.__onProbeDone()")

    def start_search(self, query: str) -> dict:
        text = (query or "").strip()
        min_len = int(self._settings.get("min_query_len", 2) or 2)
        if len(text) < min_len:
            return {"ok": False, "token": 0, "total": 0,
                    "error": f"关键字至少 {min_len} 个字符"}

        keys = sources.enabled_keys()
        if not keys:
            return {"ok": False, "token": 0, "total": 0, "error": "没有启用的数据源"}

        self._search_token = 0
        token = sources.start_batch()
        self._search_token = token
        threading.Thread(
            target=self._search_worker, args=(token, text, keys), daemon=True
        ).start()
        return {"ok": True, "token": token, "total": len(keys), "error": ""}

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

    def _search_worker(self, token: int, text: str, keys: list[str]) -> None:
        min_len = int(self._settings.get("min_query_len", 2) or 2)
        rows: list[dict] = []
        index_of: dict[str, int] = {}

        def on_source(key, items, err, ms=0):
            if token != self._search_token:
                return
            count = len(items or [])
            outcome, code = classify(not err, count, err, ms)
            text_err = outcome_text(outcome, code)
            h = self._mark(key, not err, count, ms, err, round_id=str(token))
            payload = json.dumps(
                {"token": token, "key": key, "count": count, "err": text_err,
                 "outcome": outcome, "state": h.get("state", "na")},
                ensure_ascii=False,
            )
            self._push(f"window.__onSearchSource && window.__onSearchSource({payload})")

            batch = []
            for it in core.dedupe(items or []):
                h = (it.get("info_hash") or "").lower()
                if h:
                    pos = index_of.get(h)
                    if pos is None:
                        index_of[h] = len(rows)
                        rows.append(it)
                    else:
                        rows[pos] = core.dedupe([rows[pos], it])[0]
                batch.append(_item_view(rows[index_of[h]] if h else it))
            if batch:
                payload = json.dumps(
                    {"token": token, "key": key, "items": batch},
                    ensure_ascii=False,
                )
                self._push(f"window.__onSearchBatch && window.__onSearchBatch({payload})")

        errors: dict[str, str] = {}
        try:
            result, fatal = core.search(
                text, 1, None, keys, min_len=min_len,
                on_source=on_source, batch=token, collect=False,
            )
            if fatal:
                errors[""] = fatal
            for key, msg in (result.errors or {}).items():
                if msg and msg != "已停止":
                    _o, code = classify(False, 0, msg)
                    errors[key] = outcome_text(_o, code)
        except Exception as exc:
            logger.exception("搜索异常")
            errors[""] = f"{type(exc).__name__}: {exc}"

        if token != self._search_token:
            return

        self._persist_health()
        payload = json.dumps(
            {"token": token, "total": len(rows), "errors": errors}, ensure_ascii=False
        )
        self._push(f"window.__onSearchDone && window.__onSearchDone({payload})")

    def reset_sources(self) -> bool:
        self._cfg.reset_defaults()
        self._cfg.save()
        self._health_store.replace({})
        sources.reload_from_config(self._cfg)
        return True

    def export_sources(self) -> dict:
        target = os.path.join(str(paths.data_dir()), "happycrate-sources.json")
        if self._cfg.export_to(target):
            return {"ok": True, "path": target}
        return {"ok": False, "path": ""}

    def import_sources(self) -> dict:
        target = os.path.join(str(paths.data_dir()), "happycrate-sources.json")
        if not os.path.isfile(target):
            return {"ok": False, "error": "没有找到可导入的文件"}
        ok, msg, added, updated = self._cfg.import_from(target)
        if ok:
            self._cfg.save()
            sources.reload_from_config(self._cfg)
            return {"ok": True, "added": added, "updated": updated, "message": msg}
        return {"ok": False, "error": msg}

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
            "adapter": sources.adapter_location(key, entry.get("type", "builtin")),
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
            out.append({
                "key": e.get("key", ""),
                "label": e.get("label", e.get("key", "")),
                "addr": _addr_of(e),
                "kind": "empty",
                "detail": f"最近 {min(len([o for o in (h.get('outcomes') or []) if o and o != OUTCOME_CANCEL]), HEALTH_WINDOW)} 次请求均为 0 条",
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

    def proxy_status(self) -> dict:
        return sources.proxy_status()

    def save_settings(self, fields: dict) -> dict:
        proxy = str((fields or {}).get("proxy") or "").strip()
        if proxy and not proxy.lower().startswith(("http://", "https://")):
            return {"ok": False, "errors": ["代理仅支持 http:// 或 https:// 开头"]}
        bad = self._settings.update(**(fields or {}))
        if bad:
            return {"ok": False, "errors": bad}
        self._settings.save()
        runtime.replace(dict(self._settings.data))
        return {"ok": True, "errors": []}

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
