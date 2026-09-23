"""量化成人向磁力的召回上限，用于评估各条扩展路径的收益。

用法：
  ./.venv/Scripts/python.exe tools/hc-adult-coverage.py
  ./.venv/Scripts/python.exe tools/hc-adult-coverage.py --query SSIS --pages 10
"""

import argparse
import concurrent.futures
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import sources

HEX40 = re.compile(r"btih:([0-9a-fA-F]{40})")
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
KNABEN_API = "https://api.knaben.org/v1"


def fetch(url, accept="text/html", tries=2, timeout=25):
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": sources._ua(), "Accept": accept,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7"})
            with sources._opener(url, False).open(req, timeout=timeout) as r:
                return r.read(8000000).decode("utf-8", "replace"), None
        except Exception as exc:
            err = f"{type(exc).__name__}: {str(exc)[:60]}"
            time.sleep(0.7)
    return None, err


def sukebei_rows(html):
    out = {}
    for row in ROW_RE.findall(html):
        m = HEX40.search(row)
        if not m:
            continue
        cells = [re.sub(r"\s+", " ", TAG_RE.sub(" ", c)).strip()
                 for c in CELL_RE.findall(row)]
        title = re.search(r'title="([^"]+)"', row)
        out[m.group(1).lower()] = {
            "title": title.group(1) if title else (cells[1] if len(cells) > 1 else ""),
            "size": cells[3] if len(cells) > 3 else "",
            "date": cells[4] if len(cells) > 4 else "",
            "seeders": cells[5] if len(cells) > 5 else "",
            "leechers": cells[6] if len(cells) > 6 else "",
            "downloads": cells[7] if len(cells) > 7 else "",
        }
    return out


def sukebei_pages(query, pages, workers, category="0_0"):
    seen, failed = {}, 0
    t0 = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(
            fetch, f"https://sukebei.nyaa.si/?q={urllib.parse.quote(query)}"
                   f"&c={category}&f=0&p={p}") for p in range(1, pages + 1)]
        for f in concurrent.futures.as_completed(futs):
            html, err = f.result()
            if err:
                failed += 1
                continue
            for h, row in sukebei_rows(html).items():
                seen.setdefault(h, row)
    return seen, (time.monotonic() - t0) * 1000, failed


def sukebei_rss(query, category="0_0"):
    xml, err = fetch(f"https://sukebei.nyaa.si/?page=rss"
                     f"&q={urllib.parse.quote(query)}&c={category}&f=0",
                     "application/rss+xml")
    if err:
        return None, err
    out = {}
    for chunk in re.split(r"<item>", xml)[1:]:
        m = re.search(r"<nyaa:infoHash>([0-9a-fA-F]{40})</nyaa:infoHash>", chunk)
        if not m:
            continue
        def tag(name):
            got = re.search(rf"<nyaa:{name}>([^<]*)</nyaa:{name}>", chunk)
            return got.group(1) if got else ""
        title = re.search(r"<title>(.*?)</title>", chunk, re.S)
        out[m.group(1).lower()] = {
            "title": title.group(1) if title else "",
            "size": tag("size"), "date": "",
            "seeders": tag("seeders"), "leechers": tag("leechers"),
            "downloads": tag("downloads"),
        }
    return out, None


def knaben(query, size=300, frm=0):
    body = json.dumps({"query": query, "order_by": "seeders",
                       "size": size, "from": frm}).encode()
    req = urllib.request.Request(KNABEN_API, data=body, headers={
        "User-Agent": sources._ua(), "Accept": "application/json",
        "Content-Type": "application/json"})
    try:
        with sources._opener(KNABEN_API, False).open(req, timeout=35) as r:
            return json.loads(r.read(20000000).decode("utf-8", "replace"))
    except Exception:
        return None


def knaben_total(query):
    out = knaben(query, size=1, frm=0)
    if not out:
        return None
    return (out.get("total") or {}).get("value")


def knaben_depth(query, pages, workers=3):
    seen = {}
    t0 = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(knaben, query, 300, p * 300) for p in range(pages)]
        for f in concurrent.futures.as_completed(futs):
            out = f.result() or {}
            for h in (out.get("hits") or []):
                hh = (h.get("hash") or "").strip().lower()
                if len(hh) == 40:
                    seen.setdefault(hh, h)
    return seen, (time.monotonic() - t0) * 1000


def adult_share(hits):
    cats = {}
    for h in hits:
        c = str(h.get("category") or "?")
        cats[c] = cats.get(c, 0) + 1
    adult = sum(n for c, n in cats.items() if c.startswith("XXX"))
    return adult, len(hits), sorted(cats.items(), key=lambda kv: -kv[1])[:4]


def report_sukebei(query, pages):
    print(f"\n=== Sukebei：RSS 上限 vs HTML 翻页  (q={query!r}) ===")
    rss, err = sukebei_rss(query)
    if err:
        print(f"  RSS: ERR {err}")
        rss = {}
    else:
        print(f"  RSS       : {len(rss):4d} 条  （换任意关键词都是同一个数，接口硬上限）")
    for w in (2, pages):
        got, ms, failed = sukebei_pages(query, w, w)
        tag = "在 3s 预算内" if ms <= 3000 else "超 3s（软截止会先渲染已到的）"
        print(f"  HTML {w:2d} 页 : {len(got):4d} 条 / {ms:6.0f}ms / 失败 {failed}  {tag}")
    if rss:
        got, _ms, _f = sukebei_pages(query, pages, min(pages, 8))
        both = set(got) & set(rss)
        print(f"  字段一致性: RSS 与 HTML 共有 {len(both)} 条；"
              f"HTML 独有 {len(set(got) - set(rss))} 条，"
              f"RSS 独有 {len(set(rss) - set(got))} 条")
        if both:
            h = sorted(both)[0]
            print(f"  样例 {h[:12]}: RSS seeders={rss[h]['seeders']!r} "
                  f"HTML seeders={got[h]['seeders']!r}  "
                  f"RSS downloads={rss[h]['downloads']!r} "
                  f"HTML downloads={got[h]['downloads']!r}")


def report_knaben(query, pages):
    print(f"\n=== Knaben：分页深度  (q={query!r}) ===")
    total = knaben_total(query)
    print(f"  接口自报总数: {total}")
    out = knaben(query, size=300, frm=0) or {}
    first = [h for h in (out.get("hits") or [])
             if len((h.get("hash") or "").strip()) == 40]
    adult, n, cats = adult_share(first)
    print(f"  第 1 页 300 条: 有效 {n} 条，成人分类 {adult} 条  分布={cats}")
    for w in (1, pages):
        got, ms = knaben_depth(query, w, max(1, min(w, 3)))
        tag = "在 3s 预算内" if ms <= 3000 else "超 3s"
        print(f"  {w:2d} 页并发 : {len(got):4d} 条 / {ms:6.0f}ms  {tag}")


def report_code_forms(codes):
    print("\n=== 番号写法对召回的影响（连字符陷阱）===")
    print(f"  {'写法':16s} {'sukebei':>8s} {'apibay':>8s} {'knaben':>8s}")
    for c in codes:
        xml, _ = fetch(f"https://sukebei.nyaa.si/?page=rss&q={urllib.parse.quote(c)}",
                       "application/rss+xml")
        sk = len(re.findall(r"<item>", xml)) if xml else -1
        try:
            ap = len(sources._search_apibay(c, 1, timeout=25))
        except Exception:
            ap = -1
        kt = knaben_total(c)
        print(f"  {c!r:16s} {sk:8d} {ap:8d} {str(kt):>8s}")


def report_current(query):
    from app import config, core
    print(f"\n=== 当前 app 的完整召回  (q={query!r}) ===")
    cfg = config.Config(str(ROOT / "data" / "sources.json")).load()
    sources.reload_from_config(cfg)
    t0 = time.monotonic()
    result, fatal = core.search(query, 1, None, cfg.enabled_keys(), min_len=2)
    ms = (time.monotonic() - t0) * 1000
    tally = {}
    for it in result.items:
        for s in (it.get("sources") or [it.get("source")]):
            tally[s] = tally.get(s, 0) + 1
    print(f"  合计 {len(result.items)} 条 / {ms:.0f}ms  fatal={fatal!r}")
    for k, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"    {k:14s} {n:4d}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="SSIS")
    ap.add_argument("--pages", type=int, default=10)
    ap.add_argument("--skip-current", action="store_true")
    args = ap.parse_args()

    print(f"出口: {sources.proxy_info() or '直连'}")
    report_sukebei(args.query, args.pages)
    report_knaben(args.query, args.pages)
    report_code_forms([args.query, args.query.replace("-", ""),
                       f"{args.query.split('-')[0] if '-' in args.query else args.query}-1"])
    if not args.skip_current:
        report_current(args.query)


if __name__ == "__main__":
    main()
