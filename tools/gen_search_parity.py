"""生成 tests/parity/search_cases.json：搜索编排里纯逻辑部分的对照表。

被对照的：
  - core.format_time_relative / core.magnet_of / core._as_int
  - api._relaxed_query（放松检索挑哪个词去掉）
  - api._item_view（推给前端的条目投影）

时间相关的用例把「现在」冻结成一个固定时刻（+08:00），Rust 侧用同一个值，
否则「刚刚 / 今天 / 昨天」这类结果每次跑都不一样。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_search_parity.py
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from unittest import mock

HAPPYCRATE = Path(r"D:\AI\happycrate")
OUT = Path(__file__).resolve().parent.parent / "tests" / "parity" / "search_cases.json"

sys.path.insert(0, str(HAPPYCRATE))

from app import api as api_module  # noqa: E402
from app import core, query  # noqa: E402

FIXED = datetime.datetime(2026, 9, 28, 19, 15, 0, tzinfo=datetime.timezone(
    datetime.timedelta(hours=8)))
FIXED_LOCAL = datetime.datetime(2026, 9, 28, 19, 15, 0)
FIXED_STAMP = int(FIXED.timestamp())


class FrozenDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_LOCAL if tz is None else FIXED.astimezone(tz)


RELATIVE = [
    None, "", "abc", 0, -5, -FIXED_STAMP,
    FIXED_STAMP, FIXED_STAMP - 1, FIXED_STAMP - 59, FIXED_STAMP - 60,
    FIXED_STAMP - 61, FIXED_STAMP - 3599, FIXED_STAMP - 3600,
    FIXED_STAMP - 21599, FIXED_STAMP - 21600,
    FIXED_STAMP - 86399, FIXED_STAMP - 86400, FIXED_STAMP - 86401,
    FIXED_STAMP - 2 * 86400, FIXED_STAMP - 6 * 86400, FIXED_STAMP - 7 * 86400,
    FIXED_STAMP - 30 * 86400,
    FIXED_STAMP + 600,
]

MAGNET_ITEMS = [
    {},
    {"info_hash": ""},
    {"info_hash": "a" * 40},
    {"info_hash": "A" * 40, "title": "标题 空格"},
    {"info_hash": "b" * 40, "magnet": "magnet:?xt=urn:btih:cc"},
    {"info_hash": "d" * 40, "magnet": "MAGNET:?xt=urn:btih:ee"},
    {"info_hash": "f" * 40, "magnet": "http://x"},
    {"info_hash": " " + "1" * 40 + " ", "title": "a&b/c"},
]

AS_INT = [
    None, "", 0, 1, -1, 1.9, -1.9, "5", "5.9", "abc", "  7  ", True, False, [], {},
]

RELAX_QUERIES = [
    "",
    "1080p",
    "电影 1080p x265",
    "葬送的芙莉莲 S01E02 1080p 中字",
    "葬送的芙莉莲 中字 粤语 1080p",
    "abc 1080p 未知词",
    "2024 电影",
    "第3季 动画",
]

RELAX_DROPPED = [[], ["1080p"], ["中字"], ["1080p", "中字"], ["电影"], ["不存在的词"]]

VIEW_ITEMS = [
    {},
    {"info_hash": "a" * 40, "title": "标题", "size": 1073741824,
     "seeders": 5, "leechers": 1, "added": FIXED_STAMP - 300, "source": "nyaa"},
    {"info_hash": "B" * 40, "title": "大写哈希", "size": "2048", "seeders": "7",
     "leechers": "0", "added": "1758", "sources": ["nyaa", "tpb"],
     "magnet": "magnet:?xt=urn:btih:CC"},
    {"info_hash": "c" * 40, "size": 0, "seeders": None, "leechers": None,
     "added": 0, "files": [{"n": "a.mkv", "b": 1048576}, {"n": "", "b": 9},
                           {"n": "c", "s": "1.0 MB"}, {"bad": 1}, 7]},
    {"info_hash": "d" * 40, "files": "not-a-list", "fetch": {"url": "http://x/y"}},
    {"info_hash": "e" * 40, "fetch": {"url": "ftp://x"}},
    {"info_hash": "f" * 40, "sources": [], "source": "mikan", "fetch": {"url": ""}},
]


def main() -> int:
    patch = mock.patch.object(core, "datetime", FrozenDateTime)

    relative = []
    viewed = []
    with patch:
        for value in RELATIVE:
            relative.append({
                "in": value,
                "out": core.format_time_relative(value),
            })
        for item in VIEW_ITEMS:
            viewed.append({"in": item, "out": api_module._item_view(item)})

    relaxed = []
    for text in RELAX_QUERIES:
        for dropped in RELAX_DROPPED:
            parsed = query.parse(text)
            next_query, dropped_word = api_module._relaxed_query(parsed, dropped)
            relaxed.append({
                "text": text,
                "dropped": dropped,
                "next": next_query,
                "word": dropped_word,
            })

    cases = {
        "_scope": (
            "「现在」冻结为 2026-09-28 19:15:00+08:00。"
            "Rust 侧用 `LocalNow{naive, offset}` 表示同一时刻。"
            "`relaxed` 只用内置词表（data_dir 指向空目录）。"
        ),
        "now": {"naive": FIXED_STAMP + 28800, "offset": 28800, "year": 2026},
        "relative": relative,
        "magnet": [
            {"in": item, "out": core.magnet_of(item)} for item in MAGNET_ITEMS
        ],
        "as_int": [{"in": v, "out": core._as_int(v)} for v in AS_INT],
        "relaxed": relaxed,
        "item_view": viewed,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("相对时间 %d · 磁力 %d · 取整 %d · 放松 %d · 投影 %d → %s" % (
        len(relative), len(cases["magnet"]), len(cases["as_int"]),
        len(relaxed), len(viewed), OUT))
    for row in relative[:6]:
        print("  %-14s → %r" % (json.dumps(row["in"]), row["out"]))
    for row in relaxed[:5]:
        print("  放松 %-28s 去掉 %-10s → %r" % (
            row["text"][:28], row["dropped"], row["next"]))
    assert relative and relaxed and viewed, "样本为空"
    return 0


if __name__ == "__main__":
    sys.exit(main())
