import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import api, sources

TIMEOUT = 20

def settings_proxy() -> str:
    try:
        data = json.loads((ROOT / "data" / "settings.json").read_text(encoding="utf-8"))
    except Exception:
        return ""
    return (data.get("proxy") or "").strip()

def port_state(addr: str) -> str:
    if not addr:
        return "n/a"
    try:
        parts = urllib.parse.urlsplit(addr if "//" in addr else "//" + addr)
        host, port = parts.hostname or "", parts.port
        if not host or port is None:
            return "addr missing host/port"
        with socket.socket() as sock:
            sock.settimeout(1.0)
            return "open" if sock.connect_ex((host, port)) == 0 else "CLOSED"
    except Exception as exc:
        return f"probe-error {exc}"

def describe_environment() -> None:
    configured = settings_proxy()
    print("configured proxy :", repr(configured), "->", port_state(configured))
    try:
        print("getproxies()     :", urllib.request.getproxies())
    except Exception as exc:
        print("getproxies()     : error", exc)
    print("proxy_info()     :", sources.proxy_info())
    print("user agent in use:", sources._ua())
    print("retries setting  :", sources._retries())

def read_body(exc, limit: int = 1200) -> str:
    try:
        return exc.read(limit).decode("utf-8", "replace")
    except Exception:
        return ""

def decode_cloudflare(text: str) -> str:
    try:
        payload = json.loads(text)
    except Exception:
        return ""
    if not isinstance(payload, dict) or not payload.get("cloudflare_error"):
        return ""
    return (f"    cloudflare: error_code={payload.get('error_code')} "
            f"name={payload.get('error_name')} zone={payload.get('zone')}")

def one_request(url: str, label: str, proxy: bool = True) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": sources._ua(),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    if proxy:
        opener = sources._opener(url, False)
    else:
        handlers = [urllib.request.ProxyHandler({})]
        if url.lower().startswith("https"):
            handlers.append(urllib.request.HTTPSHandler(context=sources._STRICT))
        opener = urllib.request.build_opener(*handlers)

    print(f"\n--- {label}")
    print("    url   :", url)
    print("    exit  :", "app path (proxy)" if proxy else "direct, no proxy")
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            body = resp.read(300)
            print("    ->", resp.status, resp.reason, f"{len(body)}B")
            print("    server:", resp.headers.get("Server"))
            print("    body  :", body[:200])
            return {"status": resp.status, "body": body}
    except urllib.error.HTTPError as exc:
        hdr = exc.headers or {}
        body = read_body(exc)
        loc = hdr.get("Location")
        note = "  (Location == request URL: self-redirect loop)" if loc == url else ""
        print("    -> HTTP", exc.code, exc.reason)
        print("    server      :", hdr.get("Server"))
        print("    location    :", loc, note)
        print("    retry-after :", hdr.get("Retry-After"))
        cf = decode_cloudflare(body)
        if cf:
            print(cf)
        if body:
            print("    body        :", body[:300].replace("\n", " "))
        return {"status": exc.code, "body": body, "retry_after": hdr.get("Retry-After")}
    except Exception as exc:
        print("    ->", type(exc).__name__, str(exc)[:160])
        return {"status": None, "err": f"{type(exc).__name__}: {exc}"}

def classify_report(raw: str) -> None:
    outcome, code = api.classify(False, 0, raw)
    print(f"    raw         : {raw[:120]!r}")
    print(f"    classify    : {outcome} {code}")
    print(f"    outcome_text: {api.outcome_text(outcome, code)!r}")

def api_url(base: str, query: str, page: int = 1, limit: int = 100) -> str:
    return (f"{base.rstrip('/')}/api/v1/search?q={urllib.parse.quote(query)}"
            f"&sort=seeders&page={page}&limit={limit}")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--source", default="bitsearch")
    ap.add_argument("--query", default="1080p")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--no-proxy", action="store_true")
    ap.add_argument("--control", action="store_true",
                    help="also probe the other overseas sources as a control group")
    ap.add_argument("--wait", type=int, default=0,
                    help="re-probe the same URL after N seconds (transient vs persistent)")
    ap.add_argument("--classify", action="store_true",
                    help="show how the app labels the resulting error text")
    args = ap.parse_args()

    describe_environment()

    base = sources.DEFAULT_BASES.get(args.source, "https://bitsearch.to")
    url = args.url or api_url(base, args.query, limit=args.limit)

    first = one_request(url, f"target ({args.source})", proxy=not args.no_proxy)

    if args.control:
        print("\n=== control group: same exit, other overseas sources ===")
        for key, probe in (
            ("nyaa", "https://nyaa.si/?page=rss&q=1080p&c=0_0&f=0"),
            ("sukebei", "https://sukebei.nyaa.si/?page=rss&q=1080p&c=0_0&f=0"),
            ("mikan", "https://mikanani.me/RSS/Search?searchstr=1080p"),
            ("eztv", "https://eztvx.to/api/get-torrents?limit=5&page=1"),
        ):
            one_request(probe, key, proxy=not args.no_proxy)

    if args.wait > 0:
        print(f"\nwaiting {args.wait}s before re-probing the same URL ...")
        time.sleep(args.wait)
        second = one_request(url, f"target after {args.wait}s", proxy=not args.no_proxy)
        same = second.get("status") == first.get("status")
        print("\n    verdict:", f"still {second.get('status')} -> persistent"
              if same else f"{first.get('status')} -> {second.get('status')} -> changed")

    if args.classify:
        print("\n=== how the app labels this error ===")
        err = first.get("err")
        if not err and first.get("status"):
            err = f"HTTP Error {first['status']}"
        if err:
            classify_report(err)

    print("\n=== live health record for this source ===")
    try:
        store = json.loads((ROOT / "data" / "health.json").read_text(encoding="utf-8"))
        entry = (store.get("sources") or {}).get(args.source) or {}
        print("   ", json.dumps({k: entry.get(k) for k in
                                 ("state", "ms", "err", "lastOk", "lastCount")},
                                ensure_ascii=False))
    except Exception as exc:
        print("    error:", exc)

if __name__ == "__main__":
    main()
