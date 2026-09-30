"""生成 tests/parity/util_cases.json：把 Python 侧工具函数的行为固化成对照表。

Rust 侧 tests/parity.rs 读同一张表断言相等，用来盯住最容易悄悄跑偏的边界语义
（HTML 实体、\s 折叠、百分号编码、ISO 时间戳）。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_util_parity.py
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sys
import urllib.parse
from pathlib import Path

HAPPYCRATE = Path(r"D:\AI\happycrate")
OUT = Path(__file__).resolve().parent.parent / "tests" / "parity" / "util_cases.json"

sys.path.insert(0, str(HAPPYCRATE))

from app import sources  # noqa: E402

UNESCAPE = [
    "",
    "   ",
    "  a  ",
    "&amp;",
    "&amp;lt;",
    "&lt;b&gt;",
    "&#x30D5;&#x30EA;&#x30FC;&#x30EC;&#x30F3;",
    "&#38;",
    "&#151;",
    "&#x200B;a",
    "&times;&copy;&atilde;",
    "&nbsp;x&nbsp;",
    "a & b",
    "&zzzz;",
    "&#;",
    "&#xZZ;",
    "&#x110000;",
    "&#x2605;",
    "A&B",
    "<![CDATA[  hi  ]]>",
    "<![CDATA[x]]>tail",
    "<![CDATA[unclosed",
    "&Sword;",
    "5 &lt; 6 &amp;&amp; 7 &gt; 6",
]

COLLAPSE = [
    "\t a \n b \r\n",
    "a\u00a0b",
    "\u3000a\u3000",
    "a\x1cb",
    "a\x1fb",
    "   ",
    "single",
    "a\u2028b",
    "  multi   space  ",
]

QUOTE = [
    "",
    "abc XYZ",
    "中文标题",
    "a/b?c=d&e",
    "~._-",
    "%20",
    "Ünïcode",
    'quote"and\'apos',
    "a+b c",
]

TS_ISO = [
    "",
    "   ",
    "2026-09-20T12:00:00+00:00",
    "2026-09-20T12:00:00Z",
    "2026-09-20T12:00:00",
    "2026-09-20",
    "2026-09-20T12:00:00.500+08:00",
    "2026-09-20T12:00:00+0800",
    "garbage",
    "2026-13-01T00:00:00Z",
    "1970-01-01T00:00:00Z",
    "2026-09-20T00:00:00-05:00",
]

TO_INT = [
    None,
    True,
    False,
    0,
    42,
    42.7,
    -3.9,
    "",
    "42",
    "42.7",
    "abc",
    "  7  ",
]


PARSE_SIZE = [
    None,
    True,
    False,
    0,
    42,
    1500000000,
    1500000000.7,
    "",
    "123",
    "  42  ",
    "1.5 GiB",
    "700 MB",
    "1.5MB",
    "1.5mib",
    "0.5 MB",
    "1024 KiB",
    "1e5",
    "-5 MB",
    "0 B",
    "abc",
    "no results",
    "999999999999999999999",
    "1.5 TB",
    "2 PiB",
    "3 MB extra",
    "xyz 7.5 GB abc",
    "1.2.3 MB",
    "<1 KB",
    "1 GiB",
    "1025 GiB",
]

TAG_CHUNKS = [
    "<item><title>Hi</title></item>",
    "<ITEM><TITLE>Case</TITLE></ITEM>",
    '<item id="1"><title>Attr &amp; more</title></item>',
    "<item><items>x</items></item>",
    "<item>no close",
    "<item><title>  spaced  </title><title>second</title></item>",
    "<a:title>ns</a:title>",
]

SPLIT_INPUTS = [
    "<rss><item><a>1</a></item><item><b>2</b></item></rss>",
    "<ITEM>x</ITEM>",
    "<item>x</item><item>y",
    "no items here",
    "<item><item>nested</item></item>",
    "<item>a</item><item>b</item><item>c</item>",
    "",
    "<item></item>",
]


TS_RFC = [
    "",
    "garbage",
    "Sat, 20 Sep 2026 12:00:00 +0000",
    "Sat, 20 Sep 2026 12:00:00",
    "20 Sep 2026 12:00:00 +0800",
    "20 Sep 2026 12:00:00",
    "sat, 20 sep 2026 12:00:00 +0000",
    "Foo, 20 Sep 2026 12:00:00 +0000",
    "Sat 20 Sep 2026 12:00:00 +0000",
    "Sat, 20 Xxx 2026 12:00:00 +0000",
    "Sat, 5 Sep 2026 12:00:00 -0500",
    "20 Sep 26 12:00:00",
    "Sat, 20 Sep 2026 12:00:00 +08:00",
    "Sat, 20 Sep 2026 12:00:00 Z",
    "20 Sep 2026 12:00:00 GMT",
    "Sat, 20 Sep 2026 12:00:00 +0000 extra",
    "Sat, 20 Sep 2026 99:00:00 +0000",
    "Sat, 20 Sep 2026 12:00:00 +080000",
]

TS_CN = [
    "",
    "garbage",
    "2026-09-20T12:00:00",
    "2026-09-20 12:00:00",
    "2026-09-20",
    "2026-09-20T12:00:00Z",
    "2026-09-20T12:00:00+08:00",
    "2026-09-20T12:00:00+0800",
    "2026-09-20T12:00",
    "2026-13-01T00:00:00",
    "  2026-09-20T12:00:00  ",
]

CELLS = [
    "",
    "   ",
    " <b>Hi</b> there ",
    "<td>&amp;</td>",
    'a href="x">T</a>',
    "a<b",
    "a<>b",
    "<b></b>",
    "<br/>x<br/>",
    "2026/09/20 12:00",
    "<td><a>1.5 GiB</a></td>",
]

TITLE_ROWS = [
    '<a href="/view/123" class="x" title="Hello World">y</a>',
    '<a href="/view/123" title="No">z</a>',
    '<a href="/view/123" title="A">z</a>',
    '<a href="/view/abc" title="X">z</a>',
    '<a title="X" href="/view/1">z</a>',
    '<a href="/view/1"x title="Y">',
    '<a href="/view/1" title="First" title="Second">z</a>',
    "no link here",
    '<a href="/view/9" title="">z</a>',
]

TORRENT_ROWS = [
    'href="/download/99.torrent"',
    'href="/download/abc.torrent"',
    'href="/download/1.torrent?x"',
    'x href="/download/7.torrent"',
    'href="/download/0.torrent" and href="/download/5.torrent"',
    "nothing",
]


def _b32(text):
    try:
        return base64.b32decode(text.upper()).hex()
    except (binascii.Error, ValueError):
        return None


def _group(pattern, text):
    m = pattern.search(text)
    return m.group(1) if m else None


HASH_HEX = "f8651444a2c0b3ff7e3da3cbd75da58ef5f09e19"
HASH_B32 = base64.b32encode(bytes.fromhex(HASH_HEX)).decode()
ZERO_HEX = "0" * 40
ZERO_B32 = base64.b32encode(bytes.fromhex(ZERO_HEX)).decode()

TS_CN_SLASH = [
    "",
    "garbage",
    "2026/08/28 05:32",
    "2026/08/28 05:32:45",
    "2026/08/28",
    "2026/ 8/28 05:32",
    "2026/8/28 05:32",
    "  2026/08/28 05:32  ",
    "2026/13/01",
    "2026/08/28 25:00",
    "2026/08/28 extra junk",
    "26/08/28",
    "2026-08-28 05:32",
    "2026/08/28 05:3",
    "2026/08/28 05:32:45:00",
    "2026/02/30",
    "2026/02/29",
    "2024/02/29",
    "2026/04/31",
]

CN_DATE = TS_CN_SLASH + [
    "2026-08-28T05:32:00",
    "2026-08-28 05:32:00",
    "2026-08-28T05:32:00Z",
    "2026-08-28",
]

B32_CASES = [
    "",
    "AAA",
    HASH_B32,
    HASH_B32.lower(),
    ZERO_B32,
    "A" * 32,
    "2" * 32,
    "!" * 32,
    HASH_B32 + "A",
    HASH_B32[:31],
]

HASH_CASES = [
    "",
    HASH_HEX,
    HASH_B32,
    "x" + HASH_HEX,
    HASH_HEX + "y",
    "x" + HASH_B32 + "y",
    ZERO_HEX,
    ZERO_B32,
    "btih:" + HASH_HEX,
    "btih:" + HASH_B32,
    "prefix " + HASH_HEX + " suffix",
    "abc",
    HASH_HEX + HASH_HEX,
    HASH_B32 + HASH_B32,
]

HEX_AFTER_CASES = [
    "",
    "btih:" + HASH_HEX,
    "btih:" + HASH_HEX.upper(),
    "btih:abc",
    "btih:abc btih:" + HASH_HEX,
    "magnet:?xt=urn:btih:" + HASH_HEX + "&dn=x",
    "data-magnet=\"magnet:?xt=urn:btih:" + HASH_HEX,
    "BTIH:" + HASH_HEX,
    "btih:" + HASH_HEX + "ff",
]

CELL_UNESCAPED = [
    "",
    "<b>Hi</b>",
    "<td>&amp;</td>",
    "<td>&lt;i&gt;</td>",
    "<td>  <a>1.5 GiB</a>  </td>",
    "&amp;lt;",
    "<td>2026/08/28 05:32</td>",
    "plain",
]


SIZE_TITLES = [
    "",
    "[1.5 GiB]",
    "(700 MB) extra",
    "【2.0GB】",
    "[ 1.5 GB ]",
    "[1.5GB",
    "1.5GB",
    "[abc]",
    "[1234567890123MB]",
    "[12.5 mib]",
    "[1.5 MB] [2 GB]",
    "no bracket 5 GB",
    "[]",
    "[0 B]",
    "[1e5 MB]",
]


TS_CN_DASH = [
    "",
    "garbage",
    "2026-08-28",
    "2026-08-28 05:32",
    "2026-08-28T05:32:00",
    "2026-8-28",
    "2026-13-01",
    "2026-08-28extra",
    "  2026-08-28  ",
    "2026/08/28",
]


TS_JAVBUS = [
    "",
    "garbage",
    "2026-08-28",
    "2026-08-28 05:32",
    "2026-8-28",
    "2026-13-01",
    "2026-02-30",
    "2024-02-29",
    "2026-08-28extra",
    "  2026-08-28  ",
    "2026/08/28",
]


ADJACENT = [
    "12<b>GB</b>",
    "a<b>b</b>c",
    "1<sup>2</sup>x",
    "<b>a</b><i>b</i>",
    "x<span>1</span>&amp;<span>2</span>y",
    "<td>2026<b>-</b>08</td>",
]


def main() -> int:
    cases = {
        "_scope": (
            "unescape 只覆盖「带分号的命名实体 + 数字实体」。"
            "Python html.unescape 还支持 HTML5 免分号遗留实体（&not -> ¬），"
            "Rust 侧不实现：需要 2231 条实体表，而 12 个源的真实响应里 75041 个实体全部带分号。"
            "若将来出现，金样 diff 会先报警。"
        ),
        "unescape": [{"in": s, "out": sources._unescape(s)} for s in UNESCAPE],
        "collapse": [
            {"in": s, "out": re.sub(r"\s+", " ", s).strip()} for s in COLLAPSE
        ],
        "quote": [
            {"in": s, "out": urllib.parse.quote(s, safe="")} for s in QUOTE
        ],
        "quote_plus": [
            {"in": s, "out": urllib.parse.quote_plus(s, safe="")} for s in QUOTE
        ],
        "ts_from_iso": [
            {"in": s, "out": sources._ts_from_iso(s)} for s in TS_ISO
        ],
        "to_int": [
            {"in": v, "out": sources._to_int(v)} for v in TO_INT
        ],
        "parse_size": [
            {"in": v, "out": sources.parse_size(v)} for v in PARSE_SIZE
        ],
        "tag": [
            {
                "chunk": c,
                "names": ["title", "item", "a:title", "missing", ""],
                "out": sources._tags(c, "title", "item", "a:title", "missing", ""),
            }
            for c in TAG_CHUNKS
        ],
        "split_items": [
            {"in": s, "out": sources._split_items(s)} for s in SPLIT_INPUTS
        ],
        "ts_from_rfc": [{"in": s, "out": sources._ts_from_rfc(s)} for s in TS_RFC],
        "ts_from_naive_cn": [
            {"in": s, "out": sources._ts_from_naive_cn(s)} for s in TS_CN
        ],
        "cell_text_gap_empty": [
            {"in": s, "out": sources._cell_text(s)} for s in CELLS + ADJACENT
        ],
        "cell_text_gap_space": [
            {"in": s, "out": sources._cell_text(s, gap=" ")} for s in CELLS + ADJACENT
        ],
        "find_title_attr": [
            {"in": s, "out": _group(sources._SUKEBEI_TITLE_RE, s)} for s in TITLE_ROWS
        ],
        "find_torrent_path": [
            {"in": s, "out": _group(sources._SUKEBEI_FETCH_RE, s)}
            for s in TORRENT_ROWS
        ],
        "ts_from_cn_slash": [
            {"in": s, "out": sources._ts_from_cn_slash(s)} for s in TS_CN_SLASH
        ],
        "cn_date": [{"in": s, "out": sources._cn_date(s)} for s in CN_DATE],
        "ts_from_cn_ymd": [
            {"in": s, "out": sources._javbus_added(s)} for s in TS_JAVBUS
        ],
        "ts_from_cn_dash": [
            {"in": s, "out": sources._xccl_added(s)} for s in TS_CN_DASH
        ],
        "cell_text_empty_unescaped": [
            {"in": s, "out": sources._cell_text(s, unescape=True)}
            for s in CELL_UNESCAPED + ADJACENT
        ],
        "cell_text_space_unescaped": [
            {"in": s, "out": sources._cell_text(s, gap=" ", unescape=True)}
            for s in CELL_UNESCAPED + ADJACENT
        ],
        "find_hex_after": [
            {
                "in": s,
                "out": (lambda m: m.group(1).lower() if m else None)(
                    re.search(r"btih:([0-9a-fA-F]{40})", s)
                ),
            }
            for s in HEX_AFTER_CASES
        ],
        "b32_to_hex": [{"in": s, "out": _b32(s)} for s in B32_CASES],
        "size_from_title": [
            {"in": s, "out": sources.size_from_title(s)} for s in SIZE_TITLES
        ],
        "find_b32_after": [
            {
                "in": s,
                "out": (lambda m: m.group(1) if m else None)(
                    re.search(r"btih:([A-Za-z2-7]{32})", s)
                ),
            }
            for s in HEX_AFTER_CASES
        ],
        "hash_from_text": [
            {"in": s, "out": sources.hash_from_text(s) or None} for s in HASH_CASES
        ],
        "hash_from_magnet": [
            {"in": s, "out": sources.hash_from_magnet(s) or None} for s in HASH_CASES
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(cases, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    groups = {k: v for k, v in cases.items() if isinstance(v, list)}
    total = sum(len(v) for v in groups.values())
    print("写出 %d 组共 %d 条对照到 %s" % (len(groups), total, OUT))
    for name, rows in sorted(groups.items()):
        print("  %-12s %d 条" % (name, len(rows)))
    assert groups and all(groups.values()), "有分组为空"
    return 0


if __name__ == "__main__":
    sys.exit(main())
