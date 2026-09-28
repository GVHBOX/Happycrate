"""生成 tests/parity/core_cases.json：dedupe 与标题结构评分的对照表。

标题样本取自 12 个源的真实金样（确定性抽样，不用随机），
dedupe 样本既有跨源真实重复项，也有手工构造的边界组。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_core_parity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HAPPYCRATE = Path(r"D:\AI\happycrate")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "parity" / "core_cases.json"

sys.path.insert(0, str(HAPPYCRATE))

from app import core  # noqa: E402

EDGE_TITLES = [
    "",
    "   ",
    "ubuntu-24.04.iso",
    "Movie.2024.1080p.BluRay.x264-GROUP",
    "Show S01E02 2160p WEB-DL DDP5.1 Atmos HDR",
    "Show.S01.1080i.HDTV.MPEG2",
    "【第3集】动画 4K HEVC FLAC",
    "The Matrix 1999 REMUX 7.1 TrueHD",
    "Season 2 Complete 720p x265 AAC",
    "ep12 1080p",
    "EP 045",
    "e7 test",
    "s1",
    "S99E999",
    "第 12 话",
    "第　５　季",
    "abc1984def",
    "abc19845def",
    "x1999y",
    "12000",
    "h.265 vc-1 mpeg-2",
    "bluray webdl webrip remux bdmv",
    "AACDTSFLACDOLBY",
    "no markers at all",
    "1080P UHD 8K",
    "第　５　季",
    "title ¼ test",
    "title Ⅻ test",
    "１２００p",
    "5.1 ＡＡＣ",
    "s０１",
]


def sample_titles(step: int = 1) -> list[str]:
    titles: list[str] = []
    for gold in sorted((ROOT / "tests" / "fixtures").glob("*/golden.json")):
        blob = json.loads(gold.read_text(encoding="utf-8"))
        for item in blob["items"]:
            titles.append(item["title"])
    unique: list[str] = []
    seen: set[str] = set()
    for title in titles:
        if title and title not in seen:
            seen.add(title)
            unique.append(title)
    return unique[::step]


def dedupe_groups() -> list[list[dict]]:
    groups: list[list[dict]] = []
    golds = {}
    for gold in sorted((ROOT / "tests" / "fixtures").glob("*/golden.json")):
        blob = json.loads(gold.read_text(encoding="utf-8"))
        golds[blob["key"]] = blob["items"]

    for key, other in (("apibay", "knaben"), ("tpb", "bitsearch"), ("nyaa", "dmhy")):
        left = golds.get(key) or []
        right = golds.get(other) or []
        hashes = {it["info_hash"] for it in right[:400] if it["info_hash"]}
        picks = [it for it in left if it["info_hash"] in hashes][:3]
        group = list(picks)
        for picked in picks:
            match = next(
                (it for it in right if it["info_hash"] == picked["info_hash"]), None
            )
            if match:
                group.append(match)
        if group:
            groups.append(group)

    groups.append([])
    groups.append([{"title": "no hash at all", "info_hash": "", "size": 100}])
    groups.append([
        {"title": "a", "info_hash": "A" * 40, "size": 100, "seeders": None},
        {"title": "b", "info_hash": "a" * 40, "size": 0, "seeders": 5},
        {"title": "c", "info_hash": "a" * 40, "size": 300, "seeders": 0,
         "leechers": 2, "added": 111},
    ])
    groups.append([
        {"title": "1080p x264", "info_hash": "b" * 40, "size": 0,
         "seeders": 1, "added": 500, "files": [{"n": 1}]},
        {"title": "plain", "info_hash": "b" * 40, "size": 900, "seeders": 9,
         "added": 100, "source": "x"},
        {"title": "2024 1080p x265", "info_hash": "b" * 40, "size": 0,
         "seeders": 3, "added": 700, "fetch": {"url": "u"}},
    ])
    groups.append([
        {"title": "a", "info_hash": "c" * 40, "sources": ["x", "y"]},
        {"title": "b", "info_hash": "c" * 40, "sources": ["y", "z"],
         "source": "w"},
    ])
    groups.append([
        {"title": "a", "info_hash": "d" * 40, "altTitles": ["t1", "t2"]},
        {"title": "t1", "info_hash": "d" * 40, "altTitles": ["t3"]},
    ])
    groups.append([
        {"title": f"T{i}", "info_hash": "e" * 40, "size": i + 1,
         "seeders": i, "added": 1000 - i, "extra": {"k": i}}
        for i in range(12)
    ] + [
        {"title": "alt", "info_hash": "e" * 40, "size": 0, "seeders": -3},
    ])
    return groups


def main() -> int:
    titles = EDGE_TITLES + sample_titles()
    cases = {
        "_scope": (
            "structure_score 的 6 类模式全部手写："
            "其中第 5 条用了前后向断言 (?<!\\d)...(?!\\d)，第 4 条含可选的空白与可选字母，"
            "这些 regex crate 都不支持，只能自己扫。"
            "标题样本取自 12 个源的真实金样，确定性抽样。"
        ),
        "structure_score": [
            {"title": t, "score": core._structure_score(t)} for t in titles
        ],
        "dedupe": [
            {"items": group, "out": core.dedupe([dict(it) for it in group])}
            for group in dedupe_groups()
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("结构评分 %d 条 · dedupe %d 组 → %s" % (
        len(cases["structure_score"]), len(cases["dedupe"]), OUT))
    assert cases["structure_score"] and cases["dedupe"], "样本为空"
    return 0


if __name__ == "__main__":
    sys.exit(main())
