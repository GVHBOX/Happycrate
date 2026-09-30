"""生成 tests/parity/downloaders_cases.json：投递模块里纯逻辑部分的对照表。

投递本身会真的去启动迅雷进程，没法进自动化测试；能进对照表的是
节奏规划（_plan_gaps）· 磁力清洗（_clean）· 结果文案（DeliveryResult.message）。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_downloaders_parity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HAPPYCRATE = Path(r"D:\AI\happycrate")
OUT = Path(__file__).resolve().parent.parent / "tests" / "parity" / "downloaders_cases.json"

sys.path.insert(0, str(HAPPYCRATE))

from app.downloaders import base  # noqa: E402
from app.downloaders import thunder  # noqa: E402

GAPS = [
    (0, 15), (1, 15), (2, 15), (3, 15), (4, 15), (4, 0), (4, -1), (4, 1),
    (5, 2), (10, 2), (10, 3), (10, 0), (100, 15), (100, 2), (2, 0), (2, 1),
    (11, 2), (12, 2), (13, 2), (50, 1),
]

MAGNETS = [
    [],
    [""],
    ["   "],
    ["magnet:?xt=urn:btih:aa"],
    ["MAGNET:?xt=urn:btih:AA"],
    ["magnet:?xt=urn:btih:aa", "magnet:?xt=urn:btih:aa"],
    ["magnet:?xt=urn:btih:aa", "magnet:?xt=urn:btih:bb"],
    ["http://example.com/x"],
    ["  magnet:?xt=urn:btih:cc  "],
    [None],
    [1],
    ["magnet:", "", "  magnet:?xt=urn:btih:dd  ", "http://x"],
]

MESSAGES = [
    (0, 0, [], None),
    (0, 5, [], None),
    (5, 5, [], None),
    (3, 5, [], None),
    (0, 5, [], False),
    (0, 5, ["第一次就失败"], False),
    (0, 5, ["a", "b"], False),
    (3, 5, ["部分失败"], False),
    (5, 5, ["不该出现"], False),
    (1, 1, [], None),
]


def main() -> int:
    cases = {
        "_scope": (
            "只对照纯逻辑。`add()` 会真的启动迅雷进程，不进自动化测试——"
            "它的前置判断（空表 / 超上限 / 找不到工具）靠真机 CDP 验。"
            "`find_exe()` 依赖注册表与本机安装，同样真机验。"
        ),
        "gaps": [
            {"count": c, "timeout": t, "out": thunder._plan_gaps(c, t)} for c, t in GAPS
        ],
        "clean": [
            {"in": m, "out": base._clean(m)} for m in MAGNETS
        ],
        "message": [
            {
                "added": a, "total": t, "errors": e, "ok": ok,
                "out": base.DeliveryResult(a, t, e, "protocol", ok=ok).message(),
            }
            for a, t, e, ok in MESSAGES
        ],
        "exe_candidates": list(thunder.THUNDER_EXE_CANDIDATES),
        "protocol_keys": list(thunder._PROTOCOL_KEYS),
        "protocol_flag": thunder._PROTOCOL_FLAG,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("节奏 %d · 清洗 %d · 文案 %d → %s" % (
        len(cases["gaps"]), len(cases["clean"]), len(cases["message"]), OUT))
    for row in cases["gaps"][:6]:
        print("  gaps(%d, %d) → %s" % (row["count"], row["timeout"], row["out"]))
    for row in cases["messages"] if False else cases["message"]:
        print("  文案 added=%d total=%d ok=%s → %r" % (
            row["added"], row["total"], row["ok"], row["out"]))
    assert cases["gaps"] and cases["clean"] and cases["message"], "样本为空"
    return 0


if __name__ == "__main__":
    sys.exit(main())
