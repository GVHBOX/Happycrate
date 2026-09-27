import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
files = sorted((ROOT / "app").glob("*.py")) + [ROOT / "main.py"]
tests = sorted((ROOT / "tests").glob("*.py"))

sources = []
for p in files:
    sources.append(("app/" + p.name if p.parent.name == "app" else p.name, p.read_text(encoding="utf-8")))
for p in tests:
    sources.append(("tests/" + p.name, p.read_text(encoding="utf-8")))


def dead_names():
    """现跑 scan_py.py 拿 dead_code。

    以前是读 scan/py-report.json —— 那是某次手工存盘的快照，没有扫描器回写它，
    内容停在旧版本号上，用它当默认目标清单等于拿一张过期的地图找路。
    """
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "scan" / "scan_py.py")],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", cwd=str(ROOT)).stdout
    return [r["name"] for r in json.loads(out)["dead_code"]]


targets = sys.argv[1:] or dead_names()

for name in targets:
    print("### " + name)
    total = 0
    for label, text in sources:
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"\b" + re.escape(name) + r"\b", line):
                total += 1
                if total <= 8:
                    print("   %s:%s: %s" % (label, i, line.strip()[:95]))
    if total > 8:
        print("   ... 共 %d 处" % total)
    if total == 0:
        print("   (零引用)")
    print()
