import ast
import json
from collections import defaultdict
from pathlib import Path

FILES = sorted((Path(__file__).resolve().parents[2] / "app").glob("*.py"))
groups = defaultdict(list)

for p in FILES:
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = [
            n for n in fn.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
        ]
        if not body:
            continue
        try:
            key = ast.unparse(ast.Module(body=body, type_ignores=[]))
        except Exception:
            continue
        if len(key) < 40:
            continue
        args = ",".join(a.arg for a in fn.args.args)
        groups[key].append({"file": p.name, "func": fn.name, "line": fn.lineno, "args": args})

out = []
for key, hits in groups.items():
    if len(hits) > 1:
        out.append({"body": key[:120], "hits": hits})

print(json.dumps(out, ensure_ascii=False, indent=1))
