"""生成 tests/parity/settings_cases.json：设置读写与取值强转的对照表。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_settings_parity.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HAPPYCRATE = Path(r"D:\AI\happycrate")
OUT = Path(__file__).resolve().parent.parent / "tests" / "parity" / "settings_cases.json"

sys.path.insert(0, str(HAPPYCRATE))

from app import config as cfg  # noqa: E402

INPUTS = [
    None, True, False, 0, 1, 5, 13, 100, 999, -3, 3.7, "3", "3.7", "abc", "",
    "  1  ", "TRUE", "Yes", "on", "off", "light",
]

RAW_CASES = [
    ("缺文件", None),
    ("空对象", "{}"),
    ("顶层不是对象", "[]"),
    ("坏 JSON", "{"),
    ("未知键被丢弃", '{"min_query_len": 5, "nope": 1, "another": "x"}'),
    ("内部键保留", '{"migrated_from": "v0"}'),
    ("越界保持默认", '{"timeout": 999, "max_workers": 0}'),
    ("类型不对保持默认", '{"timeout": "abc", "sound": 5}'),
    ("字符串数字能收", '{"timeout": "30", "retries": "2"}'),
    ("布尔词能收", '{"sound": "true", "selbar": "on", "auto_files": "no"}'),
    ("字号取最近档", '{"ui_font_size": 16}'),
    ("字号越界", '{"ui_font_size": 99}'),
    ("null 处理", '{"timeout": null, "sound": null, "theme": null}'),
    ("全部字段", json.dumps(cfg.settings_defaults())),
]

UPDATE_CASES = [
    [("timeout", 30)],
    [("timeout", 999)],
    [("timeout", 30), ("sound", False)],
    [("timeout", 999), ("sound", False)],
    [("nope", 1)],
    [("ui_font_size", 16)],
    [("ui_font_size", 99)],
    [("retries", "2")],
    [("progress_look", "{}")],
]


def main() -> int:
    rows = []
    root = tempfile.mkdtemp(prefix="hc-settings-")
    try:
        for index, (name, raw) in enumerate(RAW_CASES):
            directory = Path(root) / ("case%02d" % index)
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / "settings.json"
            if raw is not None:
                target.write_text(raw, encoding="utf-8")
            loaded = cfg.Settings(target).load()
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
    finally:
        shutil.rmtree(root, ignore_errors=True)

    keys = sorted(cfg.SETTING_SPECS)
    coerce_rows = []
    for key in keys:
        for value in INPUTS:
            coerce_rows.append({
                "key": key,
                "in": value,
                "out": cfg.Settings._coerce(key, value),
            })

    update_rows = []
    for index, fields in enumerate(UPDATE_CASES):
        directory = Path(root) / ("upd%02d" % index)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "settings.json"
        loaded = cfg.Settings(target).load()
        rejected = loaded.update(**dict(fields))
        update_rows.append({
            "fields": [[k, v] for k, v in fields],
            "rejected": rejected,
            "data": loaded.data,
        })

    fresh = cfg.Settings(Path(root) / "missing" / "settings.json").load()

    cases = {
        "_scope": (
            "**强转只覆盖标量输入**：Python 的 str([1,2]) 得到 '[1, 2]'（带空格、单引号），"
            "serde_json 得到 '[1,2]'，两边 repr 规则不同。真实路径不会把数组/对象写进"
            "设置项（progress_look 存的是 JSON **字符串**），故不比这一类。"
            "JSON 键顺序同样不比，只比解析后的值。"
        ),
        "load": rows,
        "coerce": coerce_rows,
        "update": update_rows,
        "reason": [
            {"key": k, "out": cfg.Settings.reason(k)} for k in keys + ["nope"]
        ],
        "get": [
            {"key": k, "out": fresh.get(k), "with_fallback": fresh.get(k, "FB")}
            for k in ["timeout", "theme", "migrated_from", "nope", "version"]
        ],
        "defaults": cfg.settings_defaults(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("加载 %d · 强转 %d · 批量更新 %d · 拒绝文案 %d → %s" % (
        len(rows), len(coerce_rows), len(update_rows), len(cases["reason"]), OUT))
    for row in rows:
        print("  %-16s broken=%-5s save=%r" % (row["name"], row["broken"], row["save_err"]))
    for row in update_rows:
        print("  update %-28s rejected=%s" % (
            str(row["fields"])[:28], row["rejected"]))
    assert rows and coerce_rows and update_rows, "样本为空"
    return 0


if __name__ == "__main__":
    sys.exit(main())
