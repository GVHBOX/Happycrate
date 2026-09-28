"""生成 tests/legacy/ 与 tests/parity/migrate_cases.json：老配置迁移的对照表。

老配置（CLB 时代的 data 目录）是**合成的**，不搬用户真实数据进仓库。
合成件故意塞满边角：未知键、越界值、类型不对的 timeout、已下线的源 key、
缺字段、空白 base、真值/假值各种写法。

对照方式：让 Python 的 `migrate.run` 跑一遍，把「迁移后的设置」与「迁移后的源列表」
存成金样；Rust 侧在同一个老目录上跑一遍，逐字段比。

`migrated_from.at` 是当时的时间，比不了也不该比 —— 只校验形状。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_migrate_parity.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "legacy"
OUT = ROOT / "tests" / "parity" / "migrate_cases.json"

HAPPYCRATE = Path(r"D:\AI\happycrate")

SANDBOX = Path(tempfile.mkdtemp(prefix="happycrate-migrate-"))
os.environ["HAPPYCRATE_DATA_DIR"] = str(SANDBOX / "data")
os.environ["HAPPYCRATE_LOG_DIR"] = str(SANDBOX / "logs")
os.environ["CLB_DATA_DIR"] = str(FIXTURES)

sys.path.insert(0, str(HAPPYCRATE))

from app import config, migrate  # noqa: E402

STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

LEGACY_SETTINGS = {
    "theme": "dark",
    "ui_font_size": 16,
    "min_query_len": 5,
    "max_workers": 99,
    "timeout": "abc",
    "sound_volume": 200,
    "keep_duplicates": True,
    "brand": "lilac",
    "progress_look": "{bad json}",
    "selbar": "yes",
    "not_a_setting": 42,
    "default_downloader": "thunder",
}

LEGACY_SOURCES = {
    "version": 1,
    "sources": [
        {"key": "nyaa", "enabled": False, "order": 5, "timeout": 30,
         "base": "https://alt.example/nyaa"},
        {"key": "mikan", "enabled": True, "timeout": 0},
        {"key": "dmhy", "enabled": "yes", "timeout": 121},
        {"key": "btdig", "enabled": True, "order": 9},
        {"key": "tpb", "order": "abc"},
        {"key": "eztv", "enabled": 0},
        {"key": "apibay", "base": "   ", "timeout": "45"},
        {"key": "", "enabled": True},
        "不是对象",
    ],
}


def write_fixtures() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "settings.json").write_text(
        json.dumps(LEGACY_SETTINGS, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (FIXTURES / "sources.json").write_text(
        json.dumps(LEGACY_SOURCES, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def main() -> int:
    write_fixtures()

    settings = config.Settings()
    settings.data = config.settings_defaults()
    cfg = config.Config()
    cfg.data = config.defaults()

    before_settings = dict(settings.data)
    before_sources = [dict(entry) for entry in cfg.sources]

    report = migrate.run(settings, cfg)

    assert report["done"], "迁移没跑起来：%s" % report
    assert report["settings"] > 0 and report["sources"] > 0, "迁移没搬动任何东西"

    after_settings = dict(settings.data)
    at = after_settings.pop(migrate.MARK, None)
    assert isinstance(at, dict) and STAMP.match(str(at.get("at", ""))), "时间戳形状不对"
    assert Path(str(at.get("path"))) == FIXTURES, "记录的来源路径不对"

    changed = sorted(k for k in after_settings
                     if k not in before_settings or after_settings[k] != before_settings.get(k))

    cases = {
        "_scope": (
            "老配置迁移（CLB 时代 → 现在）。老目录是合成的边角样本，"
            "放在 tests/legacy/，测试把 CLB_DATA_DIR 指向它。"
            "`migrated_from` 单独校验：path 必须等于那个老目录，at 只校验形状"
            "（YYYY-MM-DDTHH:MM:SS），不比具体秒。"
        ),
        "report": {
            "done": report["done"],
            "settings": report["settings"],
            "sources": report["sources"],
        },
        "settings": after_settings,
        "changed_settings": changed,
        "sources": [dict(entry) for entry in cfg.sources],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cases, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")

    print("迁移 %d 项设置、%d 个数据源 → %s" % (
        report["settings"], report["sources"], OUT))
    print("被改动的设置键：%s" % ", ".join(changed))
    print("源列表前 4 项：%s" % json.dumps(cases["sources"][:4], ensure_ascii=False))

    shutil.rmtree(SANDBOX, ignore_errors=True)
    assert changed, "样本没覆盖到任何真实改动"
    return 0


if __name__ == "__main__":
    sys.exit(main())
