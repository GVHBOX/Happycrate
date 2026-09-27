import ast
import json
from pathlib import Path

src = (Path(__file__).resolve().parents[2] / "app" / "sources.py").read_text(encoding="utf-8")
tree = ast.parse(src)

def load_pageless_funcs() -> set:
    """读出被 `_pageless(...)` 标过的适配器。

    PAGELESS_KEYS 是运行时根据这个标记算出来的，扫描器读同一处标记，
    两边就不会漂移：谁给某个源加上 _pageless，这里立刻跟着认。
    """
    out = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_pageless"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Name):
                out.add(arg.id)
    return out


pageless_funcs = load_pageless_funcs()

rows = []
for fn in ast.walk(tree):
    if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("_search_"):
        continue
    args = [a.arg for a in fn.args.args if a.arg != "self"]
    used = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            used.add(n.id)
    unused = [a for a in args if a not in used]
    if fn.name in pageless_funcs:
        unused = [a for a in unused if a != "page"]
    rows.append({
        "name": fn.name,
        "line": fn.lineno,
        "len": (fn.end_lineno or fn.lineno) - fn.lineno + 1,
        "args": args,
        "unused_args": unused,
    })

print(json.dumps(rows, ensure_ascii=False, indent=1))
