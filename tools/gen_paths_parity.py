"""生成 tests/parity/paths_cases.json：数据目录解析的对照表。

`paths._resolve` 直接读环境变量与文件系统，所以生成时把
`program_dir` / `appdata_dir` / `is_writable` / 环境变量全部打桩，
枚举各组合，把 Python 的真实分支结果记下来。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_paths_parity.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

HAPPYCRATE = Path(r"D:\AI\happycrate")
OUT = Path(__file__).resolve().parent.parent / "tests" / "parity" / "paths_cases.json"

sys.path.insert(0, str(HAPPYCRATE))

from app import paths  # noqa: E402

PROGRAM = Path(r"C:\ProgramDir")
PORTABLE = PROGRAM / "data"
APPDATA = Path(r"C:\Users\X\AppData\Roaming\happycrate")
APPDATA_DATA = APPDATA / "data"
ENV_DIR = Path(r"D:\seed\data")

CASES = [
    ("env 指定，可写", {"HAPPYCRATE_DATA_DIR": str(ENV_DIR)}, True, True),
    ("env 指定，便携也可写", {"HAPPYCRATE_DATA_DIR": str(ENV_DIR)}, True, True),
    ("env 指定，无 APPDATA", {"HAPPYCRATE_DATA_DIR": str(ENV_DIR)}, False, False),
    ("env 为空串", {"HAPPYCRATE_DATA_DIR": ""}, True, True),
    ("无 env，便携可写", {}, True, True),
    ("无 env，便携不可写，有 APPDATA", {}, False, True),
    ("无 env，便携不可写，无 APPDATA", {}, False, False),
]


def resolve_once(env: dict, portable_writable: bool, has_appdata: bool) -> dict:
    environ = {k: v for k, v in os.environ.items()
               if k not in ("HAPPYCRATE_DATA_DIR", "APPDATA")}
    environ.update(env)
    with mock.patch.dict(os.environ, environ, clear=True), \
            mock.patch.object(paths, "program_dir", lambda: PROGRAM), \
            mock.patch.object(paths, "is_writable", lambda d: portable_writable), \
            mock.patch.object(
                paths, "appdata_dir", lambda: APPDATA if has_appdata else None
            ):
        directory, mode = paths._resolve()
    return {"dir": str(directory), "mode": mode}


def main() -> int:
    rows = []
    for name, env, writable, has_appdata in CASES:
        got = resolve_once(env, writable, has_appdata)
        rows.append({
            "name": name,
            "env": env.get("HAPPYCRATE_DATA_DIR"),
            "portable_writable": writable,
            "has_appdata": has_appdata,
            **got,
        })

    cases = {
        "_scope": (
            "只对照 _resolve 的分支结果。is_writable 的真实文件系统探测与 "
            "program_dir 的 dev/打包判定是平台行为，不进对照表。"
        ),
        "_inputs": {
            "program": str(PROGRAM),
            "portable": str(PORTABLE),
            "appdata": str(APPDATA),
            "appdata_data": str(APPDATA_DATA),
            "env_dir": str(ENV_DIR),
        },
        "resolve": rows,
        "mode_labels": [
            {"mode": m, "label": paths.MODE_LABELS[m]}
            for m in (paths.MODE_ENV, paths.MODE_PORTABLE, paths.MODE_FALLBACK)
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("目录解析 %d 条 · 模式文案 %d 条 → %s" % (
        len(rows), len(cases["mode_labels"]), OUT))
    for row in rows:
        print("  %-28s → %-8s %s" % (row["name"], row["mode"], row["dir"]))
    assert rows, "样本为空"
    return 0


if __name__ == "__main__":
    sys.exit(main())
