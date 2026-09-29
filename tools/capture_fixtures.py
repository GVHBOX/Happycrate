"""P0 fixture 采集：让 happycrate 现有的 12 个适配器自己发请求，
把原始响应体与解析结果一起落到 tests/fixtures/。

不重写任何 URL 构造、请求头、POST 体、镜像轮换逻辑——只把 sources.http_get
包一层记录器，所以抓到的 body 与适配器当时看到的完全一致。

用法（必须用 happycrate 的 .venv，因为要 import app 包）：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\capture_fixtures.py
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\capture_fixtures.py nyaa mikan

不清理旧响应体：meta.json 是唯一真相源，回放只看 meta.json 列出的文件，
上一轮遗留的不会被引用，留着无害。

再加一份 fixture：改 QUERIES 或加 --query key=词，重跑该源即可。
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HAPPYCRATE = Path(r"D:\AI\happycrate")
OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

sys.path.insert(0, str(HAPPYCRATE))

from app import sources  # noqa: E402

QUERIES = {
    "apibay": "ubuntu",
    "nyaa": "ubuntu",
    "sukebei": "ubuntu",
    "knaben": "ubuntu",
    "bitsearch": "ubuntu",
    "xccl263": "ubuntu",
    "tpb": "ubuntu",
    "mikan": "frieren",
    "dmhy": "frieren",
    "eztv": "1080p",
    "javbus": "SSIS",
    "javdb": "SSIS-001",
}

TIMEOUT = 20


def sniff_ext(body: bytes) -> str:
    head = body[:400].lstrip().lower()
    if head.startswith(b"{") or head.startswith(b"["):
        return "json"
    if head.startswith(b"<?xml") or b"<rss" in head:
        return "xml"
    if head.startswith(b"<!doctype") or b"<html" in head:
        return "html"
    return "txt"


def encode_request_body(data) -> str | None:
    if data is None:
        return None
    raw = data if isinstance(data, bytes) else str(data).encode("utf-8")
    if not raw:
        return None
    return raw.decode("utf-8", "replace")


def url_slug(url: str) -> str:
    keep = "".join(ch if ch.isalnum() else "-" for ch in url.split("://")[-1])
    keep = "-".join(p for p in keep.split("-") if p)[:60]
    return "%s-%s" % (keep, hashlib.sha1(url.encode("utf-8")).hexdigest()[:6])


def capture_one(key: str, query: str, real_http_get, captured: list) -> dict:
    src = sources.BY_KEY.get(key)
    if src is None:
        return {"key": key, "query": query, "error": "未知源 key"}

    captured.clear()
    started = time.perf_counter()
    err = ""
    items: list = []
    try:
        _, items, err, _ms = sources.search_one(src, query, page=1, timeout=TIMEOUT)
    except Exception as exc:
        err = "%s: %s" % (type(exc).__name__, exc)
    elapsed = int((time.perf_counter() - started) * 1000)

    target = OUT_DIR / key
    target.mkdir(parents=True, exist_ok=True)

    records = []
    for i, (url, body, req_data, req_hdrs) in enumerate(captured, 1):
        raw = body if isinstance(body, bytes) else str(body).encode("utf-8")
        name = "%02d-%s.%s" % (i, url_slug(url), sniff_ext(raw))
        (target / name).write_bytes(raw)
        records.append({
            "n": i,
            "file": name,
            "url": url,
            "request_body": encode_request_body(req_data),
            "headers": req_hdrs if req_hdrs else None,
            "bytes": len(raw),
            "sha1": hashlib.sha1(raw).hexdigest(),
        })

    golden = {
        "key": key,
        "query": query,
        "page": 1,
        "err": err,
        "count": len(items),
        "items": items,
    }
    (target / "golden.json").write_text(
        json.dumps(golden, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    meta = {
        "key": key,
        "query": query,
        "page": 1,
        "timeout": TIMEOUT,
        "elapsed_ms_at_capture": elapsed,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "captured_local": datetime.now().astimezone().isoformat(timespec="seconds"),
        "captures": records,
    }
    (target / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "key": key,
        "query": query,
        "count": len(items),
        "err": err,
        "bodies": len(records),
        "bytes": sum(r["bytes"] for r in records),
        "elapsed_ms": elapsed,
    }


def main(argv: list[str]) -> int:
    overrides = {}
    keys = []
    for arg in argv:
        if arg.startswith("--query="):
            k, _, v = arg[len("--query="):].partition(":")
            overrides[k] = v
        elif not arg.startswith("-"):
            keys.append(arg)

    sources.reload_from_config()
    if not keys:
        keys = list(QUERIES)

    real_http_get = sources.http_get
    captured: list = []

    def recorder(url, *args, **kwargs):
        body = real_http_get(url, *args, **kwargs)
        req_headers = dict(kwargs.get("headers") or {})
        ref = kwargs.get("referer")
        if ref:
            req_headers.setdefault("Referer", ref)
        captured.append((url, body, kwargs.get("data"), req_headers))
        return body

    sources.http_get = recorder
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("%-10s %-10s %6s %6s %9s %8s  %s" %
          ("源", "查询", "条数", "响应", "字节", "耗时ms", "错误"))
    print("-" * 78)

    results = []
    try:
        for key in keys:
            query = overrides.get(key, QUERIES.get(key, "test"))
            row = capture_one(key, query, real_http_get, captured)
            results.append(row)
            print("%-10s %-10s %6s %6s %9s %8s  %s" % (
                row.get("key"), row.get("query"), row.get("count", "-"),
                row.get("bodies", "-"), row.get("bytes", "-"),
                row.get("elapsed_ms", "-"), row.get("err") or row.get("error", "")))
    finally:
        sources.http_get = real_http_get

    ok = [r for r in results if not r.get("err") and not r.get("error")]
    print("-" * 78)
    print("成功 %d / %d，fixture 落到 %s" % (len(ok), len(results), OUT_DIR))

    thumbs = list(OUT_DIR.glob("*/golden.json"))
    assert thumbs, "没有生成任何 golden.json，采集整体失败"
    for g in thumbs:
        blob = json.loads(g.read_text(encoding="utf-8"))
        assert blob["key"] == g.parent.name, "golden 与目录名不一致：%s" % g
    print("自检通过：%d 份 golden.json 可读且与目录一致" % len(thumbs))
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
