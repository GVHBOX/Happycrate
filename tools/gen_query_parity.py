"""生成 tests/parity/query_cases.json：关键词解析与放松检索的对照表。

`query.parse` 会读 data/query_roles.json，所以生成时把 data_dir 指到临时空目录，
只用内置词表；另一组专门测词表文件的合并规则。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_query_parity.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

HAPPYCRATE = Path(r"D:\AI\happycrate")
OUT = Path(__file__).resolve().parent.parent / "tests" / "parity" / "query_cases.json"

sys.path.insert(0, str(HAPPYCRATE))

from app import paths, query  # noqa: E402

NORMALIZE = [
    "",
    "   ",
    "1080p",
    "1080P",
    "１０８０Ｐ",
    "ＡＢＣ",
    "４ｋ",
    "ｈ.２６４",
    "ﬁlm",
    "½",
    "²",
    "①",
    "Ⅷ",
    "～",
    "　",
    "ｱｲｳ",
    "a_b+c,d/e|f",
    "  多   空格  ",
    "第 12 话",
    "Ubuntu TÃƒÆ'Ã‚Â¼rkiye",
    "[7³ACG]",
    "MixedCASE 1080P",
]

CONTAINS = [
    ("1080p", "1080p"),
    ("1080px", "1080p"),
    ("x1080p", "1080p"),
    ("11080p", "1080p"),
    ("1080p.", "1080p"),
    (".1080p", "1080p"),
    ("a1080p", "1080p"),
    ("中1080p文", "1080p"),
    ("h.264", "h.264"),
    ("h264", "h.264"),
    ("xh.264", "h.264"),
    ("中字", "中字"),
    ("中文字幕", "中字"),
    ("简体中文", "简体中文"),
    ("abc", "abc"),
    ("ab", "abc"),
    ("abcd", "abc"),
    ("", "abc"),
    ("abc", ""),
    ("film", "film"),
    ("ﬁlm", "film"),
    ("5.1", "5.1"),
    ("7.1", "7.1"),
]

SEASON_TOKENS = [
    "s01e02", "s1e2", "s99e999", "s1", "s01", "s99", "s100", "s1e",
    "第12集", "第1话", "第1話", "第12季", "第0季", "第x集",
    "e5", "ep5", "ep 5", "e123", "e1234", "ep0", "px5",
    "season1", "season12", "season123", "seasons",
    "s1e2x", "第1集x", "第 1 集", "s 1", "e1x",
]

SEASON_TABLE = [(0, 0), (0, 5), (5, 0), (1, 1), (2, 12), (12, 999)]

QUERIES = [
    "",
    "1080p",
    "1080P 电影",
    "电影 1080p",
    "葬送的芙莉莲 1080p",
    "Sousou no Frieren S01E02 1080p x265",
    "第12集 中字",
    "第3季 粤语",
    "season2 双语",
    "ep12 动画",
    "e05 动作",
    "2024 电影",
    "1999 movie 1080p",
    "x265 hevc 10bit",
    "web-dl blu-ray remux",
    "5.1 7.1 atmos",
    "中字 粤语 国语",
    "射击 开放世界 第三人称",
    "合集 完结 batch",
    "ubuntu-24.04.iso",
    "ubuntu 24.04",
    "１２００p 电影",
    "ﬁlm 1080p",
    "[7³ACG] 1080p",
    "  多   空格  1080p  ",
    "a_b+c,d/e|f",
    "1080",
    "1080px",
    "abc123",
    "中1080p文",
    "xyz 未知词 1080p",
    "hd",
    "2k qhd",
    "avc x264",
    "4kuhd 2160p",
]

LOAD_CASES = [
    ("缺文件", None),
    ("坏 JSON", "{"),
    ("顶层不是数组", "[]"),
    ("空对象", "{}"),
    ("新增角色", '{"words": {"EXTRA": ["blu", "ray"]}}'),
    ("覆盖内置角色", '{"words": {"QUALITY": ["onlyme"]}}'),
    ("空列表忽略", '{"words": {"QUALITY": []}}'),
    ("非列表忽略", '{"words": {"QUALITY": "nope"}}'),
    ("词要 trim 转小写", '{"words": {"EXTRA": ["  Big ", "  ", 5]}}'),
    ("变体", '{"variants": {" 4K ": [" FOUR ", ""]}}'),
    ("变体覆盖", '{"variants": {"4k": ["zzz"]}}'),
]


def with_empty_data_dir():
    directory = Path(tempfile.mkdtemp(prefix="hc-query-"))
    return mock.patch.object(paths, "data_dir", lambda: directory), directory


def main() -> int:
    normalize_rows = [
        {"in": s, "out": query.normalize(s)} for s in NORMALIZE
    ]
    contains_rows = [
        {"token": t, "word": w, "out": query._contains(t, w)}
        for t, w in CONTAINS
    ]
    season_rows = [
        {"token": t, "out": query._season_of(t)} for t in SEASON_TOKENS
    ]
    forms_rows = [
        {"s": s, "e": e, "out": query._season_forms({"s": s, "e": e})}
        for s, e in SEASON_TABLE
    ]

    parse_rows = []
    patch, directory = with_empty_data_dir()
    try:
        with patch:
            query.reload()
            for q in QUERIES:
                parsed = query.parse(q)
                parse_rows.append({
                    "in": q,
                    "out": parsed,
                    "needles": query.needles(parsed),
                })
            query.reload()
    finally:
        shutil.rmtree(directory, ignore_errors=True)

    load_rows = []
    for index, (name, raw) in enumerate(LOAD_CASES):
        directory = Path(tempfile.mkdtemp(prefix="hc-roles-"))
        try:
            if raw is not None:
                (directory / query._FILENAME).write_text(raw, encoding="utf-8")
            with mock.patch.object(paths, "data_dir", lambda d=directory: d):
                query.reload()
                table = query._load()
                query.reload()
            load_rows.append({
                "name": name,
                "raw": raw,
                "words": table["words"],
                "variants": table["variants"],
            })
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    cases = {
        "_scope": (
            "`parse` 只用内置词表（data_dir 指向临时空目录）。"
            "**JSON 键顺序不比**，只比解析后的值。"
            "Unicode 的 `\\d` 只覆盖 ASCII + 全角数字，与 Rust 侧一致。"
        ),
        "normalize": normalize_rows,
        "contains": contains_rows,
        "season_of": season_rows,
        "season_forms": forms_rows,
        "parse": parse_rows,
        "load": load_rows,
        "builtin_roles": list(query._BUILTIN_WORDS.keys()),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("归一化 %d · 包含 %d · 季集 %d · 形式 %d · 解析 %d · 词表 %d → %s" % (
        len(normalize_rows), len(contains_rows), len(season_rows),
        len(forms_rows), len(parse_rows), len(load_rows), OUT))
    for row in parse_rows[:6]:
        print("  %-34s subject=%s mods=%d soft=%d" % (
            row["in"][:34], row["out"]["subject"],
            len(row["out"]["mods"]), len(row["out"]["soft"])))
    assert parse_rows and load_rows, "样本为空"
    return 0


if __name__ == "__main__":
    sys.exit(main())
