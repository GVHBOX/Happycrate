"""批量评估候选磁力源：连通性、可解析性、成人向覆盖。

加一个源之前先跑它，别靠浏览器打开页面「看着像能用」——本工具走
app.sources 自己的 HTTP 通路（含代理 / UA / 验证码识别 / 超时重试），
浏览器能渲染 JS 挑战不代表适配器拿得到内容。

用法：
  ./.venv/Scripts/python.exe tools/hc-source-candidates.py --list
  ./.venv/Scripts/python.exe tools/hc-source-candidates.py            # 全跑（联网，慢）
  ./.venv/Scripts/python.exe tools/hc-source-candidates.py --only btdig bt4g
  ./.venv/Scripts/python.exe tools/hc-source-candidates.py --query 三上悠亜
  ./.venv/Scripts/python.exe tools/hc-source-candidates.py --dump btdig

判读：
  hash/mag 列非零 = 该站真的吐磁力，值得写适配器。
  0 且 bytes 很小（几百~几千）= 停放域名 / JS 挑战壳 / 跳转页。
  Blocked / 429 = 人机验证，纯 HTTP 通路拿不到，别写。

已定性的站，别再重复投入（2026-09-27 实测，详见
.scratch/reports/adult-sources-2026-09-27.md）：

  BT4G（bt4gprx.com）—— Cloudflare 托管挑战。403 + `cf-mitigated: challenge`。
    换 TLS 指纹、换语言子域、找未保护端点、换镜像全部无效；
    仅首页 200 且无查询能力。真实浏览器 + 已建立信任的 profile 能过，
    但无头模式与全新 profile 都卡在挑战页 —— 想用只能引入浏览器代抓。

  BTDig（btdig.com）—— Google reCAPTCHA + 浏览器指纹，比上面更硬，连真实
    浏览器都要人手点验证码，无法自动化。项目上一轮就是因此移除的
    （见 `git show 4fc9667`）。注意陷阱：它的 `/api/search`、`/ajax`、`/api`、
    `/json`、`/top` 都返回 200，但换个关键词返回的标题逐字相同 —— 是
    catch-all 的 SEO 落地页，不消费 q 参数，不是可用接口。

  torrents-csv.com —— 直连可用（走代理反而 SSL 失败），JSON API 字段齐全，
    但最多 25 条且九种分页参数全无效，与现有源重复度 76%，价值不足。

已接源的检索语义限制（2026-09-27 实测，写适配器时别再踩）：

  xccl263 —— 多词按 AND 匹配。「羽山典子 岡田純菜」站方直接回
    「找到0条结果」，单词则有 5 条。已在适配器里退化成逐词并集。

  JavBus —— 只支持单词检索，多词路径被 WAF 挡成 403（空 body + cf-ray）；
    换成 %20 / + / 官网搜索框自己的 encodeURIComponent 写法都一样，
    真实浏览器打开多词 URL 也是 403 Forbidden。该站也没收录所有演员
    （金沢瞳 用中文名、日文名、假名、/searchstar/ 全查不到，而
    水菜麗→みづなれい 就能查到），0 条未必是我们的问题。

  JavDB —— 部分影片的详情页要求登入（<title> 登入 | JavDB</title>），
    逐条稳定、与查询词无关，番号类通常不用登入。搜索页有结果但详情页
    全是登入墙时，必须报出来而不是返回 0 条。
"""

import argparse
import concurrent.futures
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import sources

HASH_RE = re.compile(r"\b[0-9a-fA-F]{40}\b")
MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:([0-9a-zA-Z]{32,40})", re.I)

QUERY = "SSIS"

CANDIDATES = [
    ("btdig", "https://btdig.com/search?q={q}&p={p}"),
    ("bt4g", "https://bt4gprx.com/search?q={q}&page={p}"),
    ("btsow", "https://btsow.motorcycles/search/{q}"),
    ("x1337", "https://1337x.to/search/{q}/1/"),
    ("limetorrents", "https://www.limetorrents.lol/search/all/{q}/"),
    ("torlock", "https://www.torlock.com/all/torrents/{q}.html"),
    ("magnetdl", "https://www.magnetdl.com/s/{q}/"),
    ("solidtorrents", "https://solidtorrents.to/search?q={q}"),
    ("torrentproject", "https://torrentproject2.com/?t={q}"),
    ("idope", "https://idope.se/torrent-list/{q}/"),
    ("btdb", "https://btdb.eu/search/{q}/"),
    ("glodls", "https://glodls.to/search_results.php?search={q}"),
    ("torrentfunk", "https://www.torrentfunk.com/all/torrents/{q}.html"),
    ("rutor", "https://rutor.info/search/0/0/000/0/{q}"),
    ("rutracker", "https://rutracker.org/forum/tracker.php?nm={q}"),
    ("nnmclub", "https://nnmclub.to/forum/tracker.php?nm={q}"),
    ("pornolab", "https://pornolab.net/forum/tracker.php?nm={q}"),
    ("tokyotosho", "https://www.tokyotosho.info/rss.php?terms={q}"),
    ("javbus", "https://www.javbus.com/search/{q}"),
    ("javdb", "https://javdb.com/search?f=all&q={q}&locale=zh"),
    ("javbus_clone", "https://www.javbus.in/search/{q}"),
    ("avmoo", "https://avmoo.pw/cn/search/{q}"),
    ("avsox", "https://avsox.click/cn/search/{q}"),
    ("jav321", "https://www.jav321.com/search/{q}"),
    ("onejav", "https://onejav.com/search/{q}"),
    ("javgg", "https://javgg.net/search/{q}/"),
    ("sukebei", "https://sukebei.nyaa.si/?q={q}&c=0_0&f=0"),
    ("nyaa", "https://nyaa.si/?q={q}"),
    ("apibay_adult", "https://apibay.org/q.php?q={q}&cat=500"),
    ("sukebei_rss", "https://sukebei.nyaa.si/?page=rss&q={q}&c=0_0&f=0"),
]

ADULT_HINT = ("sukebei", "javbus", "javdb", "pornolab", "avmoo", "avsox",
              "jav321", "onejav", "javgg", "apibay_adult")


def probe(item, query, p=1):
    key, template = item
    url = template.format(q=quote(query), p=p)
    out = {"key": key, "url": url}
    t0 = time.monotonic()
    try:
        text = sources.http_get(url, timeout=20, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;"
                      "q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
        })
        out["ok"] = True
        out["bytes"] = len(text)
        out["hash"] = len(set(h.lower() for h in HASH_RE.findall(text)))
        out["mag"] = len(set(m.lower() for m in MAGNET_RE.findall(text)))
        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
        out["title"] = title.group(1).strip()[:44] if title else ""
        out["text"] = text
    except Exception as exc:
        out["ok"] = False
        out["err"] = f"{type(exc).__name__}: {str(exc)[:58]}"
    out["ms"] = int((time.monotonic() - t0) * 1000)
    return out


def verdict(row) -> str:
    if not row["ok"]:
        return "不可用"
    if row["mag"] or row["hash"]:
        return "★ 出磁力，值得写适配器"
    if row["bytes"] < 8000:
        return "空壳（停放域名 / JS 挑战 / 跳转）"
    return "有内容但没磁力（数据库站或详情页才给）"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--query", default=QUERY)
    ap.add_argument("--dump", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    if args.list:
        for key, template in CANDIDATES:
            print(f"{key:16s} {template}")
        return 0

    picks = [c for c in CANDIDATES if not args.only or c[0] in args.only]
    mark = "" if args.query in ADULT_HINT else f"  （含成人向站点）"
    print(f"出口: {sources.proxy_info() or '直连'}")
    print(f"关键词: {args.query!r}{mark}  候选 {len(picks)} 个\n")

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(args.workers, len(picks)))) as pool:
        rows = list(pool.map(lambda c: probe(c, args.query), picks))

    rows.sort(key=lambda r: (-(r.get("mag") or 0), -(r.get("hash") or 0),
                             not r.get("ok"), r["ms"]))
    print(f"{'key':16s} {'ms':>6s} {'bytes':>8s} {'mag':>4s} {'hash':>5s}  判定")
    print("-" * 88)
    for r in rows:
        if r["ok"]:
            print(f"{r['key']:16s} {r['ms']:6d} {r['bytes']:8d} {r['mag']:4d} "
                  f"{r['hash']:5d}  {verdict(r)}")
        else:
            print(f"{r['key']:16s} {r['ms']:6d} {'-':>8s} {'-':>4s} {'-':>5s}  "
                  f"{r['err']}")

    if args.dump:
        for r in rows:
            if r["key"] == args.dump and r.get("text"):
                out = ROOT / ".scratch" / "tmp" / f"candidate-{args.dump}.html"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(r["text"], encoding="utf-8")
                print(f"\n已写出 {out}（{len(r['text'])} 字符）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
