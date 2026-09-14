from __future__ import annotations

import concurrent.futures as futures
import json
import os
import threading
import time
import urllib.parse

from . import (APP_TITLE, __version__, config, core, downloaders, log, migrate,
               paths, runtime, sources, store, templates)

logger = log.get_logger(__name__)

HEALTH_WINDOW = 5
SLOW_MS = 5000


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
            "empty": _window_empty(h.get("times")),
        },
    }


def _window_empty(times, err: str = "") -> bool:
    recent = list(times or [])[-HEALTH_WINDOW:]
    if not recent:
        return False
    hit = sum(1 for t in recent if t == "empty")
    miss = sum(1 for t in recent if t == "err")
    if not hit or hit < miss:
        return False
    return recent[-1] == "empty" or hit > len(recent) - hit


def _blank_health() -> dict:
    return {"state": "na", "ms": 0, "err": "", "times": []}



def _err_text(ok: bool, count: int, err: str) -> str:
    if ok and count == 0:
        return "返回 0 条"
    if ok:
        return ""
    low = (err or "").lower()
    if "proxy" in low:
        return "代理不可达"
    if "timed out" in low or "timeout" in low:
        return "超时"
    if "403" in low:
        return "403 拒绝"
    if "503" in low or " 500" in low or "500 " in low:
        return "服务异常"
    if "getaddrinfo" in low or "name or service" in low or "refused" in low:
        return "无法连接"
    return "请求失败"


def _health_text(key: str, ok: bool, count: int, err: str) -> str:
    text = _err_text(ok, count, err)
    if ok and not count:
        src = sources.BY_KEY.get(key)
        if src is not None and src.empty_neutral:
            return ""
    return text


def _state_of(times: list[str], ms: int, err: str = "") -> str:
    recent = times[-HEALTH_WINDOW:]
    if not recent:
        return "na"
    if err and recent[-1] == "err":
        return "err"
    bad = sum(1 for t in recent if t in ("err", "empty"))
    if bad >= 3:
        return "err"
    if ms and ms >= SLOW_MS:
        return "warn"
    return "ok"


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
    ][:8] if isinstance(raw_files, list) else []
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
            times = (health.get(key) or {}).get("times") or []
            window = times[-HEALTH_WINDOW:]
            if len(window) < HEALTH_WINDOW:
                continue
            if all(t in ("err", "empty") for t in window):
                bad.add(key)
            elif all(t == "ok" for t in window):
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

    def save_source(self, entry: dict) -> dict:
        item = dict(entry or {})
        key = str(item.get("key") or "").strip()

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
            return {
                "ok": ok,
                "count": count if ok else 0,
                "ms": ms,
                "errors": [] if ok else [_err_text(ok, count, err)],
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

    def _mark(self, key: str, ok: bool, count: int, ms: int, err: str) -> dict:
        mark = "ok" if ok and (count or not err) else ("empty" if ok else "err")
        with self._health_lock:
            h = self._health_store.data.setdefault(key, _blank_health())
            h["times"] = (h.get("times", []) + [mark])[-HEALTH_WINDOW:]
            if ms:
                h["ms"] = int(ms)
            h["err"] = err if mark != "empty" else ""
            h["state"] = _state_of(h["times"], h.get("ms", 0), err)
            return dict(h)

    def _probe_worker(self, token: int, targets) -> None:
        def one(src):
            if token != self._probe_token:
                return
            ok, ms, count, err = src.probe()
            text = _health_text(src.key, ok, count, err)
            h = self._mark(src.key, ok, count, ms, text)
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
        except Exception as exc:
            return {"ok": False, "files": [],
                    "error": f"{type(exc).__name__}: {exc}"[:180]}
        files = [{"n": r["n"], "s": core.format_size(r.get("b", 0))}
                 for r in rows if r.get("n")][:100]
        if not files:
            return {"ok": False, "files": [], "error": "种子内没有文件清单"}
        return {"ok": True, "files": files, "error": ""}

    def _search_worker(self, token: int, text: str, keys: list[str]) -> None:
        timeout = int(self._settings.get("timeout", 15) or 15)
        min_len = int(self._settings.get("min_query_len", 2) or 2)
        seen: set[str] = set()
        pushed = 0

        def on_source(key, items, err, ms=0):
            if token != self._search_token:
                return
            nonlocal pushed
            count = len(items or [])
            text_err = _health_text(key, not err, count, err)
            self._mark(key, not err, count, ms, text_err)
            payload = json.dumps(
                {"token": token, "key": key, "count": count, "err": text_err},
                ensure_ascii=False,
            )
            self._push(f"window.__onSearchSource && window.__onSearchSource({payload})")

            batch = []
            for it in core.dedupe(items or []):
                h = (it.get("info_hash") or "").lower()
                if h:
                    if h in seen:
                        continue
                    seen.add(h)
                batch.append(_item_view(it))
            if batch:
                pushed += len(batch)
                payload = json.dumps(
                    {"token": token, "key": key, "items": batch},
                    ensure_ascii=False,
                )
                self._push(f"window.__onSearchBatch && window.__onSearchBatch({payload})")

        errors: dict[str, str] = {}
        try:
            result, fatal = core.search(
                text, 1, timeout, keys, min_len=min_len,
                on_source=on_source, batch=token, collect=False,
            )
            if fatal:
                errors[""] = fatal
            for key, msg in (result.errors or {}).items():
                if msg and msg != "已停止":
                    errors[key] = _err_text(False, 0, msg)
        except Exception as exc:
            logger.exception("搜索异常")
            errors[""] = f"{type(exc).__name__}: {exc}"

        if token != self._search_token:
            return

        self._persist_health()
        payload = json.dumps(
            {"token": token, "total": pushed, "errors": errors}, ensure_ascii=False
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
        picked = [
            e for e in self._cfg.sources
            if (self._health_store.get(e.get("key", "")) or {}).get("state") == "err"
            and (not keys or e.get("key") in set(keys))
        ]
        lax = sources.ssl_lax_hosts()
        if not picked and not lax:
            return ""
        out = [f"[happycrate 诊断] {_stamp()}", ""]
        if lax:
            out.append("证书校验")
            out.append("  这些地址证书校验失败，已跳过校验继续取回：")
            for host in lax[:8]:
                out.append(f"  {host}")
            out.append("")
        for e in picked:
            key = e.get("key", "")
            h = self._health_store.get(key) or {}
            times = list(h.get("times", []) or [])
            empty = _window_empty(times)
            out.append(f"> {e.get('label', key)} ({key})")
            out.append(f"  地址  {_addr_of(e)}")
            if empty:
                out.append("  现象  HTTP 200 正常，但解析出 0 条结果")
            else:
                out.append("  现象  " + (h.get("err") or "请求失败"))
            out.append(f"  最近  {' '.join(times) or '无记录'}")
            out.append("  建议  " + ("疑似站点改版，需要改解析代码" if empty else "换镜像地址"))
            out.append("  位置  " + sources.adapter_location(
                key, e.get("type", "builtin")))
            out.append("")
        return "\n".join(out)

    def get_settings(self) -> dict:
        data = self._settings.data or {}
        return {k: data.get(k) for k in config.SETTING_SPECS if k in data}

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
