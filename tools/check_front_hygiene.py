"""铁律 2 机器强制检查：界面不加说明字。

只写「它是什么」和「出了什么问题」，不写「怎么用」。禁止解释性与引导性文字。
示范格式用 placeholder，不加说明行。

用法：
    python tools/check_front_hygiene.py
    python tools/check_front_hygiene.py --selfcheck
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

BANNED_WORDS = (
    "点击", "请选择", "您可以", "建议", "试试", "请注意",
    "使用方法", "该字段", "点击这里", "请先", "请再", "请把",
    "请确认", "请检查", "请重新", "填写代理", "打开系统代理",
    "换一个", "先启用", "重新搜索", "需要换", "换成", "然后在",
    "即可", "如果反复", "发给我", "粘贴到", "留空用", "怎么用",
)


def scan_hygiene(web_dir: Path) -> list[str]:
    errors = []
    for p in sorted(web_dir.rglob("*")):
        if p.suffix not in (".js", ".html"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            for banned in BANNED_WORDS:
                if banned in line:
                    errors.append(f"{p.name}:{line_no} 命中禁止引导词 '{banned}': {line.strip()}")
    return errors


def selfcheck() -> int:
    clean_sample = 'var s = "没有找到结果"; input.placeholder = "http://127.0.0.1:7890";'
    dirty_samples = [
        'var s = "点击这里重试";',
        'var s = "请确认代理设置";',
        'input.placeholder = "留空用默认";',
    ]
    for banned in BANNED_WORDS:
        if banned in clean_sample:
            print(f"Selfcheck FAILED: clean sample falsely hit banned word {banned}")
            return 1
    found_count = 0
    for dirty in dirty_samples:
        if any(banned in dirty for banned in BANNED_WORDS):
            found_count += 1
    if found_count != len(dirty_samples):
        print(f"Selfcheck FAILED: dirty samples not all caught ({found_count}/{len(dirty_samples)})")
        return 1
    print("Selfcheck PASS: 铁律 2 扫描器校准通过")
    return 0


def main(argv: list[str]) -> int:
    if "--selfcheck" in argv:
        return selfcheck()
    errors = scan_hygiene(WEB)
    if errors:
        print(f"FAILED: 发现 {len(errors)} 处铁律 2 违规:")
        for err in errors:
            print("  ", err)
        return 1
    print("OK: 铁律 2 界面检查通过，零违规")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
