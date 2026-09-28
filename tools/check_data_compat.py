"""检查「Rust 版写出来的 data 目录，Python 版还读不读得动」。

P4 的验收点：老用户那份真实 `data/` 被 Rust 版读写一轮之后，Python 版必须照样能用。
做法不是比字节（键序会不同），而是**用 Python 自己的 config/settings 去加载**，
再看逐键差异，并且只看「该变的变没变」。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\check_data_compat.py <写到哪> <参照>

第二个参数省略时默认 `D:\\AI\\happycrate\\data`。
退出码 0 = 读得动且只有预期内的差异。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HAPPYCRATE = Path(r"D:\AI\happycrate")
sys.path.insert(0, str(HAPPYCRATE))

from app import config  # noqa: E402

SETTINGS_KEYS_IGNORED = frozenset()
SOURCES_KEYS = ("enabled", "base", "timeout", "order", "label")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    written = Path(argv[0])
    reference = Path(argv[1]) if len(argv) > 1 else HAPPYCRATE / "data"

    problems: list[str] = []

    print("被检查：%s" % written)
    print("参照  ：%s" % reference)
    print()

    for name, loader in (("sources.json", "Config"), ("settings.json", "Settings")):
        if not (written / name).is_file():
            problems.append("%s 不见了" % name)
            continue
        obj = config.Config() if loader == "Config" else config.Settings()
        obj.path = written / name
        try:
            obj.load()
        except Exception as exc:
            problems.append("Python 读 %s 抛异常：%s: %s" % (name, type(exc).__name__, exc))
            continue
        broken = getattr(obj, "broken", None)
        if broken:
            problems.append("Python 认为 %s 坏了，备份成 %s" % (name, broken))
        print("Python 成功加载 %-14s 顶层键 %s" % (name, sorted(obj.data)))

    cfg = config.Config()
    cfg.path = written / "sources.json"
    cfg.load()
    ref = config.Config()
    ref.path = reference / "sources.json"
    ref.load()

    by_key = {entry.get("key"): entry for entry in ref.sources}
    moved = 0
    for entry in cfg.sources:
        old = by_key.get(entry.get("key")) or {}
        for field in SOURCES_KEYS:
            if entry.get(field) != old.get(field):
                moved += 1
                print("  源 %-10s %-8s %r → %r" % (entry.get("key"), field,
                                                   old.get(field), entry.get(field)))
    if [e.get("key") for e in cfg.sources] != [e.get("key") for e in ref.sources]:
        problems.append("数据源顺序/集合跟参照不一样")

    if any("health" in entry for entry in cfg.sources):
        problems.append("sources.json 里残留了 health 字段（Python 会把它剥掉）")

    st = config.Settings()
    st.path = written / "settings.json"
    st.load()
    ref_st = config.Settings()
    ref_st.path = reference / "settings.json"
    ref_st.load()
    for key in sorted(set(st.data) | set(ref_st.data)):
        if key in SETTINGS_KEYS_IGNORED:
            continue
        if st.data.get(key) != ref_st.data.get(key):
            print("  设置 %-20s %r → %r" % (key, ref_st.data.get(key), st.data.get(key)))

    if (written / "health.json").is_file() and (reference / "health.json").is_file():
        same = (written / "health.json").read_bytes() == (reference / "health.json").read_bytes()
        print("health.json 与参照一致：%s" % same)
        if not same:
            print("   （Rust 版不写健康度，这里变了说明有别的东西在动它）")

    print()
    if problems:
        for text in problems:
            print("问题：%s" % text)
        return 1
    print("通过：Python 版读得动，改动都发生在预期内的字段上（源字段 %d 处）" % moved)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
