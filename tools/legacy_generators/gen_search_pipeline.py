"""生成 tests/parity/search_pipeline.json：整条搜索流水线的金样。

和别的对照表不同，这里对照的**不是函数**，而是一次完整搜索推给前端的**事件序列**
（`__onSearchStart` / `__onSearchSource` / `__onSearchBatch` / `__onSearchDone`）。
做法：把 `sources.http_get` 换成回放器（读 tests/fixtures 里抓下来的真实响应），
再直接调 `Api._search_worker`，把它推出去的每一条 js 记下来。

回放规则（Rust 侧必须一模一样）：
  · 命中 (url, 请求体) → 返回抓到的响应体，先进先出；
  · 没抓到 → 抛 HTTP 404（真实且分支有意义：404 会走到 http4xx/warn 那条路）。

「现在」冻结为 2026-09-28 19:15:00+08:00；系统代理与 TUN 也被固定下来 ——
否则同一份表在不同机器上跑出来的文案不一样。

并发固定 max_workers=1：多线程时事件顺序取决于调度，没法逐条比对。
软截止固定 0（关掉），它天生是时序行为，只在真机 E2E 里验。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_search_pipeline.py
"""

from __future__ import annotations

import datetime
import io
import json
import os
import re
import sys
import urllib.error
from collections import deque
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
OUT = ROOT / "tests" / "parity" / "search_pipeline.json"
SANDBOX = ROOT / ".scratch" / "search-pipeline-data"

HAPPYCRATE = Path(r"D:\AI\happycrate")

os.environ["HAPPYCRATE_DATA_DIR"] = str(SANDBOX)
os.environ["HAPPYCRATE_LOG_DIR"] = str(SANDBOX / "logs")
SANDBOX.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(HAPPYCRATE))

from app import api as api_module  # noqa: E402
from app import config, core, query, runtime, sources  # noqa: E402

FIXED = datetime.datetime(
    2026, 9, 28, 19, 15, 0,
    tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
FIXED_LOCAL = datetime.datetime(2026, 9, 28, 19, 15, 0)
FIXED_STAMP = int(FIXED.timestamp())


class FrozenDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_LOCAL if tz is None else FIXED.astimezone(tz)


JS_RE = re.compile(r"^window\.(__on[A-Za-z]+) && window\.\1\((.*)\)$", re.S)

TIMEOUT = 15

SCENARIOS = [
    {
        "name": "ubuntu_first",
        "keys": ["apibay", "bitsearch", "knaben", "tpb", "xccl263"],
        "text": "ubuntu",
        "keep_dup": False,
        "cancel": False,
        "reuse": False,
    },
    {
        "name": "ubuntu_cached",
        "keys": ["apibay", "bitsearch", "knaben", "tpb", "xccl263"],
        "text": "ubuntu",
        "keep_dup": False,
        "cancel": False,
        "reuse": True,
    },
    {
        "name": "relax_round",
        "keys": ["apibay", "bitsearch", "knaben", "tpb", "xccl263"],
        "text": "ubuntu 1080p",
        "keep_dup": False,
        "cancel": False,
        "reuse": False,
    },
    {
        "name": "cancelled",
        "keys": ["apibay", "bitsearch", "knaben", "tpb", "xccl263"],
        "text": "ubuntu",
        "keep_dup": False,
        "cancel": True,
        "reuse": False,
    },
    {
        "name": "keep_duplicates",
        "keys": ["apibay", "xccl263"],
        "text": "ubuntu",
        "keep_dup": True,
        "cancel": False,
        "reuse": False,
    },
]

FATAL_CASES = [
    ({"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}, "",
     {"nyaa": "TimeoutError: timed out"}),
    ({}, "", {"nyaa": "TimeoutError: timed out", "sukebei": "TimeoutError: timed out"}),
    ({}, "Wintun", {"nyaa": "TimeoutError: timed out", "sukebei": "TimeoutError: timed out"}),
    ({}, "", {"nyaa": "TimeoutError: timed out", "apibay": "TimeoutError: timed out"}),
    ({}, "", {"nyaa": "TimeoutError: timed out", "apibay": "HTTP 500",
              "tpb": "URLError: x", "knaben": "HTTP 404", "mikan": "HTTP 404"}),
    ({}, "", {"nyaa": "TimeoutError: timed out"}),
    ({}, "", {"nyaa": "HTTP 404", "apibay": "HTTP 404"}),
    ({}, "", {"": "网络请求失败", "nyaa": "超时", "sukebei": "超时"}),
    ({}, "", {}),
    ({}, "Wintun", {"nyaa": "超时", "sukebei": "超时", "mikan": "超时", "dmhy": "超时",
                    "eztv": "超时", "tpb": "超时"}),
]


def canonical(body) -> str:
    """与 Rust `tests/golden.rs::canonical_body` 逐字节一致：JSON 规范化后压成一行。"""
    if body is None:
        return ""
    raw = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
    if not raw:
        return ""
    try:
        return json.dumps(json.loads(raw), separators=(",", ":"),
                          sort_keys=True, ensure_ascii=False)
    except ValueError:
        return raw


def load_queues(keys):
    queues: dict[str, deque] = {}
    for key in keys:
        meta = json.loads((FIXTURES / key / "meta.json").read_text(encoding="utf-8"))
        for entry in meta["captures"]:
            body = (FIXTURES / key / entry["file"]).read_bytes().decode("utf-8")
            slot = entry["url"] + "\x01" + canonical(entry.get("request_body"))
            queues.setdefault(slot, deque()).append(body)
    return queues


class Replay:

    def __init__(self, keys):
        self.queues = load_queues(keys)
        self.exhausted: list[str] = []
        self.served = 0

    def __call__(self, url, *args, **kwargs):
        batch = kwargs.get("batch")
        if batch is not None and not sources._batch_alive(batch):
            raise sources.SearchCancelled(url)
        slot = url + "\x01" + canonical(kwargs.get("data"))
        queue = self.queues.get(slot)
        if queue:
            self.served += 1
            return queue.popleft()
        if queue is not None:
            self.exhausted.append(url)
        raise urllib.error.HTTPError(url, 404, "Not Found", None, io.BytesIO(b""))


def build_config(keys):
    cfg = config.Config()
    cfg.data = config.defaults()
    rank = {key: index for index, key in enumerate(keys)}
    for entry in cfg.data["sources"]:
        entry["timeout"] = TIMEOUT
        entry["base"] = ""
        if entry["key"] in rank:
            entry["enabled"] = True
            entry["order"] = rank[entry["key"]]
        else:
            entry["enabled"] = False
            entry["order"] = len(keys) + 10
    return cfg


def new_api(keys, keep_dup):
    api = api_module.Api()
    api._cfg = build_config(keys)
    api._health_store.data.clear()
    api._settings.data = dict(config.settings_defaults())
    api._settings.data.update({
        "min_query_len": 2,
        "keep_duplicates": keep_dup,
        "soft_deadline_ms": 0,
        "max_workers": 1,
        "retries": 0,
        "timeout": TIMEOUT,
    })
    sources.reload_from_config(api._cfg)
    runtime.replace({"max_workers": 1, "user_agent": "happycrate-fixture"})
    pushed: list[str] = []
    api._push = pushed.append
    api._search_cache.clear()
    return api, pushed


def targets_of(api):
    return [
        {"key": entry["key"], "base": entry.get("base", ""),
         "timeout": int(entry.get("timeout", 15) or 15)}
        for entry in api._cfg.sources if entry.get("enabled")
    ]


def hints_of():
    proxy = sources.proxy_hint()
    return {"proxy": proxy, "has_proxy": bool(sources.proxy_info()),
            "tun": sources.tun_adapter()}


def decode_pushes(pushed):
    events = []
    for js in pushed:
        found = JS_RE.match(js)
        if not found:
            raise SystemExit("推送的 js 形状变了：%s" % js[:120])
        events.append({
            "hook": found.group(1),
            "payload": json.loads(found.group(2)),
        })
    events.sort(key=lambda event: event["payload"].get("key", ""))
    return events


def run_scenarios():
    rows = []
    api = None
    replay = None
    for spec in SCENARIOS:
        if not spec["reuse"]:
            api, pushed = new_api(spec["keys"], spec["keep_dup"])
            replay = Replay(spec["keys"])
            sources.http_get = replay
        else:
            pushed = []
            api._push = pushed.append
        assert replay is not None and api is not None

        token = sources.start_batch()
        api._search_token = token
        parsed = query.parse(spec["text"])
        if spec["cancel"]:
            api.cancel_search(token)

        before = replay.served
        api._search_worker(token, spec["text"], list(spec["keys"]), 1, parsed)
        events = decode_pushes(pushed)
        if replay.exhausted:
            raise SystemExit("回放被取空，请求序列与原抓包不一致：%s" % replay.exhausted[:3])

        rows.append({
            "name": spec["name"],
            "text": spec["text"],
            "page": 1,
            "min_len": 2,
            "keep_dup": spec["keep_dup"],
            "soft_deadline_ms": 0,
            "max_workers": 1,
            "token": token,
            "cancel": spec["cancel"],
            "reuse": spec["reuse"],
            "targets": targets_of(api),
            "stamp": api._source_stamp(),
            "entries": [dict(entry) for entry in api._cfg.sources],
            "hints": hints_of(),
            "requests": replay.served - before,
            "events": events,
        })
        print("%-16s token=%-3d 请求 %4d 推送 %4d 事件 %s" % (
            spec["name"], token, replay.served - before, len(pushed),
            _tally(events)))
    return rows


def _tally(events):
    counts: dict[str, int] = {}
    for event in events:
        counts[event["hook"]] = counts.get(event["hook"], 0) + 1
    return " ".join("%s×%d" % (k, v) for k, v in sorted(counts.items())) or "（无）"


def run_fatal():
    rows = []
    for proxy, tun, errors in FATAL_CASES:
        with mock.patch.object(sources, "proxy_info", lambda p=proxy: dict(p)), \
                mock.patch.object(sources, "tun_adapter", lambda t=tun: t):
            rows.append({
                "proxy": proxy,
                "tun": tun,
                "errors": errors,
                "hints": {"proxy": sources.proxy_hint(),
                          "has_proxy": bool(proxy), "tun": tun},
                "out": sources.proxy_hint_for(errors),
            })
    return rows


def main() -> int:
    real_http_get = sources.http_get
    try:
        patch = mock.patch.object(core, "datetime", FrozenDateTime)
        with patch, mock.patch.object(sources, "datetime", FrozenDateTime):
            rows = run_scenarios()
        fatal = run_fatal()
    finally:
        sources.http_get = real_http_get

    cases = {
        "_scope": (
            "整条搜索流水线的事件序列。http_get 换成 tests/fixtures 回放，"
            "冻结现在=2026-09-28 19:15:00+08:00，无系统代理、无 TUN，"
            "max_workers=1、soft_deadline_ms=0（多线程顺序与软截止天生是时序行为，只在真机 E2E 验）。"
            "事件已按 key 稳定排序：跨源之间的先后是竞态（Python 的 on_start 来自工作线程、"
            "on_source 来自主线程），同一个 key 内部的顺序保留原样。"
        ),
        "now": {"naive": FIXED_STAMP + 28800, "offset": 28800, "year": 2026},
        "scenarios": rows,
        "fatal": fatal,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cases, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")

    assert rows, "没有任何场景"
    assert all(row["events"] for row in rows if not row["cancel"]), "非取消场景没有推送"
    assert not any(row["events"] for row in rows if row["cancel"]), "取消场景不该有推送"
    done = [e for e in rows[0]["events"] if e["hook"] == "__onSearchDone"]
    assert len(done) == 1, "首个场景的 onSearchDone 不唯一"
    print("场景 %d · 失败提示 %d → %s（%.1f MB）" % (
        len(rows), len(fatal), OUT, OUT.stat().st_size / 1e6))
    print("首个场景收尾：%s" % json.dumps(done[0]["payload"], ensure_ascii=False)[:220])
    return 0


if __name__ == "__main__":
    sys.exit(main())
