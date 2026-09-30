"""生成 tests/parity/api_cases.json：源管理与设置这 8 个命令的对照表。

跳过 Api.boot()：它还会跑旧配置迁移与健康存储加载，那两块要么是 P4、要么已暂缓。
这里只 load 配置与设置，然后逐个跑命令，记下返回值与最终状态。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_api_parity.py
"""

from __future__ import annotations

import json
import os
import urllib.request
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

HAPPYCRATE = Path(r"D:\AI\happycrate")
OUT = Path(__file__).resolve().parent.parent / "tests" / "parity" / "api_cases.json"

sys.path.insert(0, str(HAPPYCRATE))

from app import api as api_module  # noqa: E402
from app import runtime  # noqa: E402
from app import sources as sources_module  # noqa: E402
from app import config as cfg  # noqa: E402
from app import paths  # noqa: E402

SETTINGS_RAW = json.dumps({
    "theme": "dark",
    "min_query_len": 3,
    "timeout": 30,
    "nope": 1,
})

SCENARIOS = [
    ("默认列表", "{}", SETTINGS_RAW, []),
    ("打开某源", "{}", SETTINGS_RAW,
     [{"op": "toggle_source", "key": "javdb", "value": True}]),
    ("关闭某源", "{}", SETTINGS_RAW,
     [{"op": "toggle_source", "key": "nyaa", "value": False}]),
    ("未知源", "{}", SETTINGS_RAW,
     [{"op": "toggle_source", "key": "nope", "value": True}]),
    ("重排两个", "{}", SETTINGS_RAW,
     [{"op": "reorder_sources", "keys": ["nyaa", "apibay"]}]),
    ("重排空表", "{}", SETTINGS_RAW, [{"op": "reorder_sources", "keys": []}]),
    ("重排未知名", "{}", SETTINGS_RAW,
     [{"op": "reorder_sources", "keys": ["nope", "nyaa"]}]),
    ("开启自动排序", "{}", SETTINGS_RAW,
     [{"op": "set_auto_order", "value": True}]),
    ("关闭自动排序", '{"orderLocked": true}', SETTINGS_RAW,
     [{"op": "set_auto_order", "value": False}]),
    ("保存合法值", "{}", SETTINGS_RAW,
     [{"op": "save_settings", "fields": {"timeout": 45}}]),
    ("保存越界值", "{}", SETTINGS_RAW,
     [{"op": "save_settings", "fields": {"timeout": 999}}]),
    ("保存未知键", "{}", SETTINGS_RAW,
     [{"op": "save_settings", "fields": {"nope": 1}}]),
    ("保存一批含坏值", "{}", SETTINGS_RAW,
     [{"op": "save_settings", "fields": {"timeout": 45, "retries": 99}}]),
    ("代理不合法", "{}", SETTINGS_RAW,
     [{"op": "save_settings", "fields": {"proxy": "socks5://127.0.0.1:1080"}}]),
    ("代理合法", "{}", SETTINGS_RAW,
     [{"op": "save_settings",
       "fields": {"proxy": "  http://127.0.0.1:7890  ", "theme": "light"}}]),
    ("空字段", "{}", SETTINGS_RAW, [{"op": "save_settings", "fields": {}}]),
    ("重载词表", "{}", SETTINGS_RAW, [{"op": "reload_query_roles"}]),
    ("自定义地址", json.dumps({
        "sources": [
            {"key": "nyaa", "label": "Nyaa", "base": "https://user:pw@mirror.example/"},
            {"key": "apibay", "base": ""},
        ]
    }), SETTINGS_RAW, []),
]

REDACT = [
    "",
    "http://127.0.0.1:7890",
    "http://user:pw@host:8080/",
    "https://a:b@h",
    "https://a:b@h/x",
    "http://a:b@h, http://c:d@i",
    "ftp://user:pass@ftp.example",
    "//u:p@h",
    "http://no-at-sign/",
    "http://onlyuser@h",
    "http://a:b@ c:d@h",
    "x//a:b@h",
]

TOO_LONG = ["", "a", "a" * 99, "a" * 100, "a" * 101, "中" * 100, "中" * 101, "😀" * 100]


def build(root: Path, index: int, raw_sources, raw_settings):
    directory = root / ("api%02d" % index)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sources.json").write_text(raw_sources, encoding="utf-8")
    (directory / "settings.json").write_text(raw_settings, encoding="utf-8")
    return directory


def enter_env(directory: Path):
    saved_env = os.environ.get(paths.ENV_DATA_DIR)
    saved_cache = paths._cache
    os.environ[paths.ENV_DATA_DIR] = str(directory)
    paths._cache = None
    return saved_env, saved_cache


def leave_env(saved):
    saved_env, saved_cache = saved
    if saved_env is None:
        os.environ.pop(paths.ENV_DATA_DIR, None)
    else:
        os.environ[paths.ENV_DATA_DIR] = saved_env
    paths._cache = saved_cache


def patched(directory: Path):
    replacements = {
        "data_dir": lambda: directory,
        "sources_path": lambda: directory / "sources.json",
        "settings_path": lambda: directory / "settings.json",
        "health_path": lambda: directory / "health.json",
    }
    stack = [mock.patch.object(paths, name, fn) for name, fn in replacements.items()]
    return stack


def main() -> int:
    rows = []
    root = Path(tempfile.mkdtemp(prefix="hc-api-"))
    try:
        for index, (name, raw_sources, raw_settings, ops) in enumerate(SCENARIOS):
            directory = build(root, index, raw_sources, raw_settings)
            stack = patched(directory)
            for patcher in stack:
                patcher.start()
            try:
                api = api_module.Api()
                api._cfg.load()
                api._settings.load()
                results = []
                for op in ops:
                    kind = op["op"]
                    if kind == "toggle_source":
                        results.append(api.toggle_source(op["key"], op["value"]))
                    elif kind == "reorder_sources":
                        results.append(api.reorder_sources(op["keys"]))
                    elif kind == "set_auto_order":
                        results.append(api.set_auto_order(op["value"]))
                    elif kind == "save_settings":
                        results.append(api.save_settings(op["fields"]))
                    elif kind == "reload_query_roles":
                        results.append(api.reload_query_roles())
                rows.append({
                    "name": name,
                    "raw_sources": raw_sources,
                    "raw_settings": raw_settings,
                    "ops": ops,
                    "results": results,
                    "sources_view": api.list_sources(),
                    "get_settings": api.get_settings(),
                    "default_settings": api.default_settings(),
                    "config_data": api._cfg.data,
                    "settings_data": api._settings.data,
                    "last_write_error": api._last_write_error,
                    "order_locked": api._cfg.order_locked(),
                    "saved_sources": json.loads(
                        (directory / "sources.json").read_text(encoding="utf-8")),
                })
            finally:
                for patcher in reversed(stack):
                    patcher.stop()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    info_cases = []
    info_scenarios = [
        ("默认", "{}", '{"proxy": "http://127.0.0.1:7890"}'),
        ("跟随系统", "{}", "{}"),
        ("手动代理带空格", "{}", '{"proxy": "  http://p:1  "}'),
        ("代理为空串", "{}", '{"proxy": ""}'),
        ("设置损坏", "{}", "{"),
        ("锁定排序", '{"orderLocked": true}', '{"proxy": "http://p:1"}'),
        ("源损坏", "[", '{"proxy": "http://p:1"}'),
    ]
    root3 = Path(tempfile.mkdtemp(prefix="hc-info-"))
    try:
        for index, (name, raw_sources, raw_settings) in enumerate(info_scenarios):
            directory = build(root3, index, raw_sources, raw_settings)
            saved = enter_env(directory)
            try:
                api = api_module.Api()
                api._cfg.load()
                api._settings.load()
                runtime.replace(dict(api._settings.data))
                info = api.app_info()
                info_cases.append({
                    "name": name,
                    "raw_sources": raw_sources,
                    "raw_settings": raw_settings,
                    "version": info["version"],
                    "mode": info["mode"],
                    "migratedFrom": info["migratedFrom"],
                    "proxy": info["proxy"],
                    "autoOrder": info["autoOrder"],
                    "recovered_count": len(info["recovered"]),
                    "self_ok": api.selftest()["ok"],
                    "self_missing": api.selftest()["missing"],
                })
            finally:
                leave_env(saved)
                runtime.replace({})
    finally:
        shutil.rmtree(root3, ignore_errors=True)

    proxy_cases = []
    proxy_scenarios = [
        ("都没有", {}, {}, None, None, ""),
        ("只有系统", {}, {"http": "http://s:1", "https": "http://s:2"}, True, True, "TUN0"),
        ("只有系统且端口不通", {}, {"http": "http://s:1"}, False, None, "TUN0"),
        ("手动优先于系统", {"http": "http://m:1"},
         {"https": "http://s:2"}, True, False, ""),
        ("只有手动", {"https": "https://m:9"}, {}, True, True, ""),
        ("手动只有 http 键", {"http": "http://m:1"}, {}, True, True, ""),
        ("系统只有 http 键", {}, {"http": "http://s:1"}, True, True, ""),
        ("手动为空串", {}, {}, None, None, "TUN0"),
    ]
    for name, manual, system, port_ok, works, tun in proxy_scenarios:
        with mock.patch.object(sources_module, "_manual_proxy", lambda m=manual: m),                 mock.patch.object(urllib.request, "getproxies",
                                  lambda s=system: dict(s)),                 mock.patch.object(sources_module, "_probe_port",
                                  lambda a, r=port_ok: bool(r)),                 mock.patch.object(sources_module, "_proxy_works",
                                  lambda m, r=works: bool(r)),                 mock.patch.object(sources_module, "tun_adapter",
                                  lambda f=False, t=tun: t):
            sources_module._probe_cache["key"] = None
            sources_module._probe_cache["at"] = 0.0
            got = sources_module.proxy_status(force=True)
        proxy_cases.append({
            "name": name,
            "manual": manual,
            "system": system,
            "probe_port": port_ok,
            "proxy_works": works,
            "tun_stub": tun,
            "out": {k: v for k, v in got.items() if k != "checkedAt"},
        })

    hex_cases = [
        "", "#", "#fff", "#ffffff", "#FFFFFF", "#8B7FE0", "8B7FE0", "#gggggg",
        "#12345g", " #ffffff ", "#000000", "#ffffffa", "rgb(1,2,3)", "#FfFfFf",
    ]

    cases = {
        "_scope": (
            "跳过 Api.boot()（它会跑旧配置迁移与健康存储加载）。"
            "`reload_from_config` 与搜索缓存清理在 Rust 侧没有对应物——"
            "配置是显式传给调度器的，不走模块全局；搜索缓存属 P3 搜索命令。"
            "`set_auto_order` 里的降级逻辑依赖健康数据，健康已暂缓，无数据时它是空操作。"
            "**JSON 键顺序不比**。"
        ),
        "commands": rows,
        "redact": [{"in": s, "out": api_module._redact(s)} for s in REDACT],
        "too_long": [
            {"in": s, "out": api_module.is_query_too_long(s)} for s in TOO_LONG
        ],
        "spec_keys": list(cfg.SETTING_SPECS.keys()),
        "info": info_cases,
        "proxy": proxy_cases,
        "hex_color": [
            {"in": c, "out": bool(api_module._HEX_COLOR_RE.match(str(c or "").strip()))}
            for c in hex_cases
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("命令 %d 组 · 信息 %d 组 · 脱敏 %d · 长度 %d · 设置项 %d → %s" % (
        len(rows), len(info_cases), len(REDACT), len(TOO_LONG),
        len(cases["spec_keys"]), OUT))
    for row in proxy_cases:
        print("  代理 %-18s → %s" % (row["name"], json.dumps(row["out"], ensure_ascii=False)))
    for row in info_cases:
        print("  信息 %-14s mode=%-8s proxy=%-32s recovered=%d autoOrder=%s" % (
            row["name"], row["mode"], row["proxy"][:32],
            row["recovered_count"], row["autoOrder"]))
    for row in rows:
        print("  %-14s results=%-22s sources=%d locked=%s" % (
            row["name"], str(row["results"])[:22],
            len(row["sources_view"]), row["order_locked"]))
    assert rows and cases["redact"], "样本为空"
    return 0


if __name__ == "__main__":
    sys.exit(main())
