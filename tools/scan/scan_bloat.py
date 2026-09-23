import ast
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"D:\AI\happycrate")

PY = sorted((ROOT / "app").glob("*.py")) + [ROOT / "main.py"]
JS = sorted((ROOT / "web").rglob("*.js"))
CSS = sorted((ROOT / "web").rglob("*.css"))


def py_functions():
    rows = []
    for p in PY:
        text = p.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                rows.append({
                    "file": p.name, "name": fn.name, "line": fn.lineno,
                    "len": (fn.end_lineno or fn.lineno) - fn.lineno + 1,
                })
    return rows


def js_functions():
    rows = []
    for p in JS:
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(
            r"(?:function\s+([A-Za-z_$][\w$]*)\s*\(|"
            r"([A-Za-z_$][\w$]*)\s*[:=]\s*function\s*\()",
            text,
        ):
            name = m.group(1) or m.group(2)
            start = text[:m.start()].count("\n") + 1
            i = text.find("{", m.end())
            if i < 0:
                continue
            depth = 0
            j = i
            while j < len(text):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            end = text[:j].count("\n") + 1
            rows.append({"file": p.name, "name": name, "line": start, "len": end - start + 1})
    return rows


def duplicate_blocks(min_lines=7):
    hits = defaultdict(list)
    for p in PY + JS:
        lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines()]
        for i in range(len(lines) - min_lines + 1):
            window = lines[i:i + min_lines]
            if sum(1 for l in window if l and not l.startswith(("import ", "from ", "#"))) < min_lines - 1:
                continue
            key = "\n".join(window)
            hits[key].append("%s:%d" % (p.name, i + 1))
    return {k: v for k, v in hits.items() if len(v) > 1}


def repeated_literals():
    counted = defaultdict(lambda: defaultdict(int))
    for p in PY + JS:
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"""["']([^"'\\\n]{12,})["']""", text):
            counted[m.group(1)][p.name] += 1
    return {k: dict(v) for k, v in counted.items() if len(v) > 1}


pyf = sorted(py_functions(), key=lambda r: -r["len"])
jsf = sorted(js_functions(), key=lambda r: -r["len"])

print(json.dumps({
    "py_top": pyf[:14],
    "js_top": jsf[:14],
    "dup_blocks": duplicate_blocks(),
    "cross_file_literals": repeated_literals(),
}, ensure_ascii=False, indent=1))
