"""生成 tests/parity/config_cases.json：数据源配置加载 / 规范化 / 保存 / 访问器 的对照表。

每个用例把原始 sources.json 内容写进临时目录，跑 Python 的 Config.load()，
记下规范化之后的完整 data；需要时再跑 save()，记下写回文件的内容。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_config_parity.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HAPPYCRATE = Path(r"D:\AI\happycrate")
OUT = Path(__file__).resolve().parent.parent / "tests" / "parity" / "config_cases.json"

sys.path.insert(0, str(HAPPYCRATE))

from app import config as cfg  # noqa: E402
from app import paths  # noqa: E402

RAW_CASES = [
    ("缺文件", None),
    ("空对象", "{}"),
    ("顶层不是对象", "[]"),
    ("顶层是字符串", '"nope"'),
    ("坏 JSON", "{"),
    ("版本过高", '{"version": 99, "sources": []}'),
    ("version 不是数字", '{"version": "x", "sources": []}'),
    ("sources 不是列表", '{"sources": "nope"}'),
    ("sources 里混垃圾", '{"sources": [null, 5, {}, {"key": ""}, {"key": "nyaa"}]}'),
    ("键要 trim", '{"sources": [{"key": "  nyaa  "}]}'),
    ("重复键只留第一个", '{"sources": [{"key": "a", "label": "第一"}, '
                          '{"key": "a", "label": "第二"}]}'),
    ("已下线源被剔除", '{"sources": [{"key": "btdig"}, {"key": "apibay_adult"}]}'),
    ("超时被夹取", '{"sources": [{"key": "a", "timeout": 999}, '
                    '{"key": "b", "timeout": -5}, {"key": "c", "timeout": "abc"}, '
                    '{"key": "d", "timeout": null}]}'),
    ("order 排序后重编号", '{"sources": [{"key": "a", "order": 5}, '
                            '{"key": "b", "order": 1}, {"key": "c", "order": "abc"}]}'),
    ("缺字段补默认", '{"sources": [{"key": "custom"}]}'),
    ("保留未知字段", '{"sources": [{"key": "custom", "notes": "x", "nested": {"a": 1}}]}'),
    ("保留 health", '{"sources": [{"key": "custom", "health": {"ms": 12, "state": "ok"}}]}'),
    ("orderLocked", '{"orderLocked": true, "sources": [{"key": "a"}]}'),
    ("内置源补齐", '{"sources": [{"key": "nyaa", "enabled": false}]}'),
]

SCENARIOS = [
    ("默认", "{}", []),
    ("锁序", '{"orderLocked": true}', []),
    ("关掉某源", "{}", [{"op": "set_enabled", "key": "javdb", "value": False}]),
    ("打开某源", "{}", [{"op": "set_enabled", "key": "javdb", "value": True}]),
    ("未知源", "{}", [{"op": "set_enabled", "key": "nope", "value": True}]),
    ("上锁并去掉降级标记",
     '{"sources": [{"key": "a", "demoted": true, "demoteFrom": 3,'
     ' "health": {"ms": 1}}]}',
     [{"op": "set_order_locked", "value": True}]),
    ("解锁", '{"orderLocked": true}', [{"op": "set_order_locked", "value": False}]),
    ("清健康", '{"sources": [{"key": "a", "health": {"ms": 1}}, {"key": "b"}]}',
     [{"op": "strip_health"}]),
    ("清健康但本就没有", "{}", [{"op": "strip_health"}]),
]

CLAMP = [
    None, "", "abc", -5, 0, 1, 15, 60, 120, 121, 999, "30", 30.7, True, False, [],
]

BROKEN_NAMES = ["sources.json", "sources.JSON", "sources.txt", "noext"]


def run_scenario(directory: Path, raw: str, ops: list) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "sources.json"
    target.write_text(raw, encoding="utf-8")
    loaded = cfg.Config(target).load()
    results = []
    for op in ops:
        if op["op"] == "set_enabled":
            results.append(loaded.set_enabled(op["key"], op["value"]))
        elif op["op"] == "set_order_locked":
            loaded.set_order_locked(op["value"])
            results.append(None)
        elif op["op"] == "strip_health":
            results.append(loaded.strip_health())
    return {
        "results": results,
        "enabled_keys": loaded.enabled_keys(),
        "all_keys": loaded.all_keys(),
        "order_locked": loaded.order_locked(),
        "has_a": loaded.get("a") is not None,
        "missing_key": loaded.get("nope"),
        "data": loaded.data,
    }


def collect_files() -> dict:
    env = Path(tempfile.mkdtemp(prefix="hc-paths-"))
    saved = paths._cache
    saved_env = os.environ.get(paths.ENV_DATA_DIR)
    saved_log = os.environ.get(paths.ENV_LOG_DIR)
    try:
        os.environ[paths.ENV_DATA_DIR] = str(env)
        os.environ.pop(paths.ENV_LOG_DIR, None)
        paths._cache = None
        got = {
            "env": str(env),
            "data_dir": str(paths.data_dir()),
            "sources": str(paths.sources_path()),
            "settings": str(paths.settings_path()),
            "health": str(paths.health_path()),
            "logs_dir": str(paths.logs_dir()),
            "log_path": str(paths.log_path()),
            "mode": paths.data_mode(),
            "label": paths.describe()[2],
        }
    finally:
        paths._cache = saved
        if saved_env is None:
            os.environ.pop(paths.ENV_DATA_DIR, None)
        else:
            os.environ[paths.ENV_DATA_DIR] = saved_env
        if saved_log is None:
            os.environ.pop(paths.ENV_LOG_DIR, None)
        else:
            os.environ[paths.ENV_LOG_DIR] = saved_log
        shutil.rmtree(env, ignore_errors=True)
    return got


def main() -> int:
    rows = []
    accessors = []
    root = tempfile.mkdtemp(prefix="hc-config-")
    try:
        for index, (name, raw) in enumerate(RAW_CASES):
            directory = Path(root) / ("case%02d" % index)
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / "sources.json"
            if raw is not None:
                target.write_text(raw, encoding="utf-8")
            loaded = cfg.Config(target).load()
            saved = loaded.save()
            saved_data = (
                json.loads(target.read_text(encoding="utf-8")) if saved == "" else None
            )
            rows.append({
                "name": name,
                "raw": raw,
                "data": loaded.data,
                "broken": bool(loaded.broken),
                "save_err": saved,
                "saved": saved_data,
            })
        for index, (name, raw, ops) in enumerate(SCENARIOS):
            got = run_scenario(Path(root) / ("acc%02d" % index), raw, ops)
            accessors.append({"name": name, "raw": raw, "ops": ops, **got})
    finally:
        shutil.rmtree(root, ignore_errors=True)

    files = collect_files()
    cases = {
        "_scope": (
            "对照 data / 写回文件 / 损坏备份 / 访问器 / 数据目录路径。"
            "**JSON 键顺序不比对**——Rust 侧 serde_json 默认按键排序，"
            "Python 保持插入顺序，语义相同但字节不同，比的是解析后的值。"
        ),
        "load": rows,
        "accessors": accessors,
        "files": files,
        "clamp_timeout": [{"in": v, "out": cfg.clamp_timeout(v)} for v in CLAMP],
        "clamp_timeout_custom_default": [
            {"in": v, "default": d, "out": cfg.clamp_timeout(v, d)}
            for v in (None, "abc", 5, 200)
            for d in (1, 30, 120)
        ],
        "broken_path": [
            {"in": n, "out": cfg.broken_path(n)} for n in BROKEN_NAMES
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("加载 %d · 访问器 %d · 夹取 %d · 损坏路径 %d → %s" % (
        len(rows), len(accessors),
        len(cases["clamp_timeout"]) + len(cases["clamp_timeout_custom_default"]),
        len(cases["broken_path"]), OUT))
    print("数据目录：%s（%s / %s）" % (files["data_dir"], files["mode"], files["label"]))
    print("  源文件  :", files["sources"])
    print("  设置文件:", files["settings"])
    print("  健康文件:", files["health"])
    print("  日志    :", files["log_path"])
    for row in accessors:
        print("  %-18s enabled=%2d all=%2d locked=%-5s results=%s" % (
            row["name"], len(row["enabled_keys"]), len(row["all_keys"]),
            row["order_locked"], row["results"]))
    assert rows and accessors and cases["clamp_timeout"], "样本为空"
    return 0


if __name__ == "__main__":
    sys.exit(main())
