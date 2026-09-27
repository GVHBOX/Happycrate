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


def is_overload(node) -> bool:
    """@overload 是类型声明，同一个函数名会有两三个签名 + 一个实现。

    它们不是重复定义，判断时一律跳过。
    """
    for dec in getattr(node, "decorator_list", []):
        if getattr(dec, "id", None) == "overload":
            return True
        if getattr(dec, "attr", None) == "overload":
            return True
    return False


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
            if is_overload(node):
                continue
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
    """同名只在「同一个文件里出现两次」才算重复。

    跨文件同名（migrate.run / shell.run、runtime.get / sources.get）是通用词
    撞名，语义毫无关系，报出来只会污染基线。
    """
    by_key = defaultdict(list)
    for path, text in ALL_SRC:
        tree = ast.parse(text)
        for node in tree.body:
            if is_overload(node):
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                by_key[(path.name, node.name)].append(
                    (path.name, node.lineno, len(node.body)))
    return {name: rows for (_file, name), rows in by_key.items() if len(rows) > 1}


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


def walk_with_loop(node, in_loop=False):
    """遍历节点，同时告诉调用方「这个节点是不是在循环体内」。"""
    for child in ast.iter_child_nodes(node):
        child_loop = in_loop or isinstance(child, (ast.For, ast.AsyncFor, ast.While))
        yield child, child_loop
        yield from walk_with_loop(child, child_loop)


def _swallow_kind(handler) -> str | None:
    body = handler.body
    if len(body) != 1:
        return None
    if isinstance(body[0], ast.Pass):
        return "except-pass"
    if isinstance(body[0], ast.Continue):
        return "except-continue"
    return None


def _try_with_tail(tree) -> set:
    """找出「后面还跟着同级语句」的 Try —— 说明失败后还有别的处理。"""
    out = set()
    for parent in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            block = getattr(parent, attr, None)
            if not isinstance(block, list):
                continue
            for i, stmt in enumerate(block):
                if isinstance(stmt, ast.Try) and i < len(block) - 1:
                    out.add(id(stmt))
    return out


def bare_except_and_swallow():
    """分两堆返回。

    swallow：真吞 —— 捕获后什么都不做就过去了，问题被静默埋掉。
    swallow_try_next：候选尝试 —— 在循环里跳下一个候选（多编码 / 多格式解析），
    或失败后后面还接着别的处理。这类是正常控制流，不是缺陷，
    单独放一堆供查看，但不计入问题数。
    """
    swallow = []
    try_next = []
    for path, text in ALL_SRC:
        tree = ast.parse(text)
        owner = {}
        for node, in_loop in walk_with_loop(tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    owner[id(handler)] = (node, in_loop)
        tail = _try_with_tail(tree)

        for node, in_loop in walk_with_loop(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            hit = {"file": path.name, "line": node.lineno}
            if node.type is None:
                swallow.append(dict(hit, kind="bare-except"))
                continue
            kind = _swallow_kind(node)
            if kind is None:
                continue
            info = owner.get(id(node))
            owner_loop = info[1] if info else in_loop
            has_tail = info is not None and id(info[0]) in tail
            if owner_loop or has_tail:
                try_next.append(dict(hit, kind=kind, reason=(
                    "loop" if owner_loop else "fallthrough")))
            else:
                swallow.append(dict(hit, kind=kind))
    return {"swallow": swallow, "swallow_try_next": try_next}


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


swallow = bare_except_and_swallow()

result = {
    "tuple_arity": tuple_arity_report(),
    "dead_code": dead_code_report(),
    "dup_definitions": dup_definitions(),
    "versions": version_strings(),
    "swallow": swallow["swallow"],
    "swallow_try_next": swallow["swallow_try_next"],
}
if "--magic" in sys.argv:
    result["magic"] = magic_numbers()
print(json.dumps(result, ensure_ascii=False, indent=1))
