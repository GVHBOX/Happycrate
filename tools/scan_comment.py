"""零注释检查：守住 AGENTS.md 铁律 1。

核心源码（src/、tests/、web/）不写注释、不写 docstring，名字起清楚就行。
Rust 的 /// 与 //! 都算注释，一样禁止。

tools/ 不算核心源码，那里的 docstring 与注释照常允许，所以扫描范围里排除 tools/。

用法（用本仓库自带 python 或任意 python3 即可，无第三方依赖）：

    python tools/scan_comment.py

输出 JSON，键为各类命中；空列表 = 全绿。
"""

import json
import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("SCAN_ROOT") or Path(__file__).resolve().parents[1])

RS_GLOBS = ["src/**/*.rs", "tests/**/*.rs"]
JS_GLOBS = ["web/**/*.js"]
CSS_GLOBS = ["web/**/*.css"]
HTML_GLOBS = ["web/**/*.html"]

RAW_PREFIX = re.compile(r'(b?r)(#*)(")')
BYTE_STRING = re.compile(r'b"')


def _files(globs):
    out = []
    for pattern in globs:
        out += [
            p
            for p in sorted(ROOT.glob(pattern))
            if "target" not in p.parts and "node_modules" not in p.parts
        ]
    return out


def _row(path, lineno, text):
    return {
        "file": path.relative_to(ROOT).as_posix(),
        "line": lineno,
        "text": text.strip()[:90],
    }


def _skip_plain_string(text, i, lineno):
    n = len(text)
    i += 1
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i + 1, lineno
        if text[i] == "\n":
            lineno += 1
        i += 1
    return i, lineno


def _skip_raw_string(text, i, lineno, hashes):
    n = len(text)
    end_mark = '"' + hashes
    i += len(hashes) + 2
    while i < n:
        if text.startswith(end_mark, i):
            return i + len(end_mark), lineno
        if text[i] == "\n":
            lineno += 1
        i += 1
    return i, lineno


def _char_literal_end(text, i):
    n = len(text)
    j = i + 1
    if j >= n:
        return False
    if text[j] == "\\":
        j += 1
        if j >= n:
            return False
        head = text[j]
        if head == "u":
            close = text.find("}", j)
            if close < 0:
                return False
            j = close + 1
        elif head == "x":
            j += 3
        else:
            j += 1
    else:
        j += 1
    return j < n and text[j] == "'"


def rust_comments(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    rows = []
    i = 0
    lineno = 1
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            lineno += 1
            i += 1
            continue
        raw = RAW_PREFIX.match(text, i)
        if raw:
            i, lineno = _skip_raw_string(text, i, lineno, raw.group(2))
            continue
        if BYTE_STRING.match(text, i):
            i, lineno = _skip_plain_string(text, i + 1, lineno)
            continue
        if ch == '"':
            i, lineno = _skip_plain_string(text, i, lineno)
            continue
        if ch == "'":
            if _char_literal_end(text, i):
                close = text.index("'", i + 1)
                i = close + 1
            else:
                i += 1
            continue
        if text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            rows.append(_row(path, lineno, text[i:end]))
            i = end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            rows.append(_row(path, lineno, text[i:end]))
            lineno += text.count("\n", i, end)
            i = end
            continue
        i += 1
    return rows


def _strip_js_strings(text):
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in ('"', "'", "`"):
            quote = ch
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            out.append("S")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _has_mark(line, mark):
    at = line.find(mark)
    while at >= 0:
        if at == 0 or line[at - 1] != "\\":
            return True
        at = line.find(mark, at + 1)
    return False


def _line_marks(globs, marks):
    rows = []
    for path in _files(globs):
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
        stripped = _strip_js_strings("\n".join(raw)).splitlines()
        for idx, line in enumerate(stripped):
            if any(_has_mark(line, m) for m in marks):
                rows.append(_row(path, idx + 1, raw[idx]))
    return rows


def scan():
    return {
        "rs_comments": [r for p in _files(RS_GLOBS) for r in rust_comments(p)],
        "js_comments": _line_marks(JS_GLOBS, ["//", "/*"]),
        "css_comments": _line_marks(CSS_GLOBS, ["/*"]),
        "html_comments": _line_marks(HTML_GLOBS, ["<!--"]),
    }


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixture-comments"
EXPECTED = {
    "src/clean.rs": set(),
    "src/dirty.rs": {1, 4, 6, 9, 14},
    "tests/dirty.rs": {1},
}


def selfcheck() -> int:
    global ROOT
    ROOT = FIXTURE_ROOT
    got = {}
    for row in scan()["rs_comments"]:
        got.setdefault(row["file"], set()).add(row["line"])
    bad = []
    for name, want in EXPECTED.items():
        have = got.get(name, set())
        if have != want:
            bad.append("%s 期望行 %s，实际 %s" % (name, sorted(want), sorted(have)))
    extra = sorted(set(got) - set(EXPECTED))
    if extra:
        bad.append("多出未预期的文件：%s" % extra)
    for line in bad:
        print("FAIL " + line)
    if bad:
        print("校准件未通过：扫描器可能漏检或误报")
        return 1
    print("校准件通过：clean.rs 零命中，dirty.rs 命中 %d 行" % sum(len(v) for v in EXPECTED.values()))
    return 0


if __name__ == "__main__":
    import sys

    if "--selfcheck" in sys.argv:
        sys.exit(selfcheck())
    print(json.dumps(scan(), ensure_ascii=False, indent=1))
