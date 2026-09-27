"""零注释检查：守住 AGENTS.md 铁律 1。

核心源码（app/、web/、main.py、tests/）不写注释、不写 docstring，名字起清楚就行。
这条铁律此前完全没有机器强制 —— 而 test_front_hygiene 的引导语扫描还会跳过含 `#` 的行，
等于「往注释里塞引导语」同时躲开两条铁律。

tools/ 不算核心源码，那里的 docstring 与注释照常允许，所以扫描范围里明确排除 tools/。

用法：
  .venv/Scripts/python.exe tools/scan/scan_comment.py

输出 JSON，键为各类命中；空列表 = 全绿。工具指令（# noqa / # type: 等）由运行时读取，算例外。
"""

import ast
import io
import json
import os
import re
import tokenize
from pathlib import Path

ROOT = Path(os.environ.get("SCAN_ROOT") or Path(__file__).resolve().parents[2])
BSLASH = chr(92)
DQ, SQ, BT = chr(34), chr(39), chr(96)

PY_GLOBS = ["app/**/*.py", "tests/**/*.py"]
PY_FILES = ["main.py"]
JS_GLOBS = ["web/**/*.js"]
CSS_GLOBS = ["web/**/*.css"]
HTML_GLOBS = ["web/**/*.html"]

TOOL_DIRECTIVE = re.compile(r"^#\s*(noqa|type:|pragma|ruff:|mypy:|pylint:|isort:|nosec)")


def _files(globs, extra=()):
    out = []
    for pattern in globs:
        out += [p for p in sorted(ROOT.glob(pattern))
                if "__pycache__" not in p.parts and "node_modules" not in p.parts]
    for name in extra:
        p = ROOT / name
        if p.is_file():
            out.append(p)
    return out


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _rows(path, lineno, text):
    return {"file": _rel(path), "line": lineno, "text": text.strip()[:90]}


def py_comments():
    rows = []
    for path in _files(PY_GLOBS, PY_FILES):
        try:
            with io.open(path, encoding="utf-8") as fh:
                tokens = list(tokenize.generate_tokens(fh.readline))
        except (tokenize.TokenError, SyntaxError, UnicodeDecodeError):
            continue
        for tok in tokens:
            if tok.type != tokenize.COMMENT:
                continue
            if TOOL_DIRECTIVE.match(tok.string):
                continue
            rows.append(_rows(path, tok.start[0], tok.string))
    return rows


def py_docstrings():
    rows = []
    for path in _files(PY_GLOBS, PY_FILES):
        try:
            tree = ast.parse(_text(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = getattr(node, "body", [])
            if not body or not isinstance(body[0], ast.Expr):
                continue
            value = body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                label = getattr(node, "name", "<module>")
                rows.append(_rows(path, body[0].lineno, f"{label}: " + value.value.strip()))
    return rows


def _strip_js_strings(text: str) -> str:
    """抹掉字符串与模板字面量的内容，只留结构字符。

    不做这件事的话，代码里的 https:// 会被当成注释起始。
    """
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in (DQ, SQ):
            quote = ch
            i += 1
            while i < n:
                if text[i] == BSLASH:
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            out.append("S")
            continue
        if ch == BT:
            i += 1
            depth = 0
            while i < n:
                if text[i] == BSLASH:
                    i += 2
                    continue
                if depth == 0 and text[i] == BT:
                    i += 1
                    break
                if text[i] == "$" and i + 1 < n and text[i + 1] == "{":
                    depth += 1
                    i += 2
                    continue
                if depth > 0 and text[i] == "}":
                    depth -= 1
                    i += 1
                    continue
                i += 1
            out.append("S")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _has_comment(mark: str, line: str) -> bool:
    at = line.find(mark)
    while at >= 0:
        if at == 0 or line[at - 1] != BSLASH:
            return True
        at = line.find(mark, at + 1)
    return False


def js_comments():
    rows = []
    for path in _files(JS_GLOBS):
        raw_lines = _text(path).splitlines()
        stripped = _strip_js_strings(_text(path)).splitlines()
        for idx, line in enumerate(stripped):
            if _has_comment("//", line) or _has_comment("/*", line):
                rows.append(_rows(path, idx + 1, raw_lines[idx]))
    return rows


def css_comments():
    rows = []
    for path in _files(CSS_GLOBS):
        for idx, line in enumerate(_text(path).splitlines()):
            if "/*" in line or "*/" in line:
                rows.append(_rows(path, idx + 1, line))
    return rows


def html_comments():
    rows = []
    for path in _files(HTML_GLOBS):
        for idx, line in enumerate(_text(path).splitlines()):
            if "<!--" in line or "-->" in line:
                rows.append(_rows(path, idx + 1, line))
    return rows


result = {
    "py_comments": py_comments(),
    "py_docstrings": py_docstrings(),
    "js_comments": js_comments(),
    "css_comments": css_comments(),
    "html_comments": html_comments(),
}
print(json.dumps(result, ensure_ascii=False, indent=1))
