import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"

tree = ast.parse((ROOT / "app" / "api.py").read_text(encoding="utf-8"))
backend = []
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == "Api":
        for m in node.body:
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("_"):
                args = [a.arg for a in m.args.args if a.arg != "self"]
                backend.append({"name": m.name, "line": m.lineno, "args": args})

front = {}
for p in sorted(WEB.rglob("*")):
    if p.suffix not in (".js", ".html"):
        continue
    text = p.read_text(encoding="utf-8")
    for m in re.finditer(r"pywebview\.api\.([A-Za-z_][A-Za-z0-9_]*)", text):
        line = text[:m.start()].count("\n") + 1
        front.setdefault(m.group(1), []).append("%s:%d" % (p.name, line))
    for m in re.finditer(r"\bcall\(\s*[\"']([a-z_][a-z0-9_]*)", text):
        line = text[:m.start()].count("\n") + 1
        front.setdefault(m.group(1), []).append("%s:%d(call)" % (p.name, line))

backend_names = {r["name"] for r in backend}
missing = {k: v for k, v in front.items() if k not in backend_names}
unused = [r for r in backend if r["name"] not in front]

print(json.dumps({
    "backend_count": len(backend),
    "front_count": len(front),
    "missing_in_backend": missing,
    "backend_never_called": unused,
}, ensure_ascii=False, indent=1))
