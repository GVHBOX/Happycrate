import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
report = json.load(open(ROOT / "tools" / "scan" / "py-report.json", encoding="utf-8"))
files = sorted((ROOT / "app").glob("*.py")) + [ROOT / "main.py"]
tests = sorted((ROOT / "tests").glob("*.py"))

sources = []
for p in files:
    sources.append(("app/" + p.name if p.parent.name == "app" else p.name, p.read_text(encoding="utf-8")))
for p in tests:
    sources.append(("tests/" + p.name, p.read_text(encoding="utf-8")))

targets = sys.argv[1:] or [r["name"] for r in report["dead_code"]]

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
