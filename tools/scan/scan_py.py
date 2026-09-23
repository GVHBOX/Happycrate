import ast
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("SCAN_ROOT") or Path(__file__).resolve().parents[2])
FILES = sorted((ROOT / "app").glob("*.py")) + [ROOT / "main.py"]
ALL_SRC = [(p, p.read_text(encoding="utf-8")) for p in FILES]
CORPUS = "\n".join(t for _, t in ALL_SRC)
TEST_TEXT = "\n".join(
    p.read_text(encoding="utf-8", errors="replace")
    for p in (ROOT / "tests").glob("*.py")
)


def iter_own(node):
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(n))


def tuple_arity_report():
    rows = []
    for path, text in ALL_SRC:
        tree = ast.parse(text)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            arities = {}
            for node in iter_own(fn):
                if not isinstance(node, ast.Return) or node.value is None:
                    continue
                v = node.value
                if isinstance(v, ast.Tuple):
                    n = len(v.elts)
                    if any(isinstance(e, ast.Starred) for e in v.elts):
                        continue
                else:
                    n = 1
                arities.setdefault(n, []).append(node.lineno)
            if len(arities) > 1:
                rows.append({
                    "file": path.name,
                    "func": fn.name,
                    "line": fn.lineno,
                    "arities": {str(k): v for k, v in sorted(arities.items())},
                })
    return rows


def module_level_defs():
    out = []
    for path, text in ALL_SRC:
        tree = ast.parse(text)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.append((path.name, node.name, node.lineno, type(node).__name__))
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        out.append((path.name, t.id, node.lineno, "assign"))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                out.append((path.name, node.target.id, node.lineno, "anassign"))
    return out


def dead_code_report():
    init = ROOT / "app" / "__init__.py"
    exported = set()
    if init.exists():
        exported = set(re.findall(
            r'"([A-Za-z_][A-Za-z0-9_]*)"', init.read_text(encoding="utf-8")
        ))
    rows = []
    for fname, name, lineno, kind in module_level_defs():
        if name.startswith("__") and name.endswith("__"):
            continue
        if kind == "ClassDef" or name in exported:
            continue
        pat = r"\b" + re.escape(name) + r"\b"
        n_corpus = len(re.findall(pat, CORPUS))
        n_test = len(re.findall(pat, TEST_TEXT))
        if n_corpus <= 1 and n_test == 0:
            rows.append({
                "file": fname, "name": name, "line": lineno,
                "kind": kind, "corpus_hits": n_corpus, "test_hits": n_test,
            })
    return rows


def dup_definitions():
    by_name = defaultdict(list)
    for path, text in ALL_SRC:
        tree = ast.parse(text)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                by_name[node.name].append((path.name, node.lineno, len(node.body)))
    return {k: v for k, v in by_name.items() if len(v) > 1}


def version_strings():
    pats = [
        (r"\b(\d+\.\d+\.\d+)\b", "semver"),
    ]
    rows = []
    targets = list(FILES)
    targets += [ROOT / "pyproject.toml", ROOT / "README.md", ROOT / "happycrate.spec"]
    targets += [ROOT / "web" / "js" / "api.js", ROOT / "web" / "index.html"]
    for p in targets:
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"1\.\d+\.\d+", text):
            line_no = text[:m.start()].count("\n") + 1
            rows.append({"file": p.name, "line": line_no, "value": m.group(0)})
    return rows


def bare_except_and_swallow():
    rows = []
    for path, text in ALL_SRC:
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    rows.append({"file": path.name, "line": node.lineno, "kind": "bare-except"})
                body = node.body
                if len(body) == 1 and isinstance(body[0], ast.Pass):
                    rows.append({"file": path.name, "line": node.lineno, "kind": "except-pass"})
                if len(body) == 1 and isinstance(body[0], ast.Continue):
                    rows.append({"file": path.name, "line": node.lineno, "kind": "except-continue"})
    return rows


def magic_numbers():
    rows = []
    for path, text in ALL_SRC:
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if isinstance(node.value, bool):
                    continue
                if node.value in (0, 1, 2, -1, 100, 1024, 1000, 0.0, 1.0):
                    continue
                if node.value > 1000000 or node.value < -1000000:
                    continue
                rows.append({"file": path.name, "line": node.lineno, "value": node.value})
    return rows


result = {
    "tuple_arity": tuple_arity_report(),
    "dead_code": dead_code_report(),
    "dup_definitions": dup_definitions(),
    "versions": version_strings(),
    "swallow": bare_except_and_swallow(),
}
if "--magic" in sys.argv:
    result["magic"] = magic_numbers()
print(json.dumps(result, ensure_ascii=False, indent=1))
