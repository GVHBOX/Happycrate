import ast
import json
from pathlib import Path

src = (Path(__file__).resolve().parents[2] / "app" / "sources.py").read_text(encoding="utf-8")
tree = ast.parse(src)

rows = []
for fn in ast.walk(tree):
    if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("_search_"):
        continue
    args = [a.arg for a in fn.args.args if a.arg != "self"]
    used = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            used.add(n.id)
    rows.append({
        "name": fn.name,
        "line": fn.lineno,
        "len": (fn.end_lineno or fn.lineno) - fn.lineno + 1,
        "args": args,
        "unused_args": [a for a in args if a not in used],
    })

print(json.dumps(rows, ensure_ascii=False, indent=1))
