import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"D:\AI\happycrate")
WEB = ROOT / "web"

CSS_FILES = sorted(WEB.rglob("*.css"))
JS_FILES = sorted(WEB.rglob("*.js"))
HTML_FILES = sorted(WEB.rglob("*.html"))

css = {p.name: p.read_text(encoding="utf-8") for p in CSS_FILES}
js = {p.name: p.read_text(encoding="utf-8") for p in JS_FILES}


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    return text


defined = defaultdict(list)
for name, t in css.items():
    for m in re.finditer(r"(?m)^\s*(--[A-Za-z0-9_-]+)\s*:", t):
        defined[m.group(1)].append(name)

used = defaultdict(list)
for name, t in css.items():
    for m in re.finditer(r"var\(\s*(--[A-Za-z0-9_-]+)", t):
        used[m.group(1)].append(name)
for name, t in js.items():
    for m in re.finditer(r"var\(\s*(--[A-Za-z0-9_-]+)", t):
        used[m.group(1)].append(name)
    for m in re.finditer(r"setProperty\(\s*[\"'](--[A-Za-z0-9_-]+)", t):
        defined[m.group(1)].append(name)
        used[m.group(1)].append(name)
for p in HTML_FILES:
    t = p.read_text(encoding="utf-8")
    for m in re.finditer(r"var\(\s*(--[A-Za-z0-9_-]+)", t):
        used[m.group(1)].append(p.name)

orphan_defined = sorted(k for k in defined if k not in used)
orphan_used = sorted(k for k in used if k not in defined)


def top_selectors(text):
    t = strip_comments(text)
    out = []
    buf = ""
    depth = 0
    for ch in t:
        if ch == "{":
            if depth == 0:
                out.append((" ".join(buf.split()), None))
            buf = ""
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
            buf = ""
        elif depth == 0:
            buf += ch
    return out


dup_selectors = {}
for name, t in css.items():
    seen = defaultdict(list)
    offset = 0
    body = strip_comments(t)
    depth = 0
    buf = ""
    line = 1
    start_line = 1
    for ch in body:
        if ch == "\n":
            line += 1
        if ch == "{":
            if depth == 0:
                sel = " ".join(buf.split())
                if sel and not sel.startswith("@"):
                    seen[sel].append(start_line)
            buf = ""
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
            buf = ""
        elif depth == 0:
            if not buf.strip():
                start_line = line
            buf += ch
    dup = {k: v for k, v in seen.items() if len(v) > 1}
    if dup:
        dup_selectors[name] = dup

hard_white = []
bare_z = []
for name, t in css.items():
    for m in re.finditer(r"background(?:-color)?\s*:\s*(#fff\b|#ffffff\b|white\b)", t, re.I):
        hard_white.append({"file": name, "line": t[:m.start()].count("\n") + 1, "text": m.group(0)})
    for m in re.finditer(r"z-index\s*:\s*(-?\d+)", t):
        bare_z.append({"file": name, "line": t[:m.start()].count("\n") + 1, "value": m.group(1)})

print(json.dumps({
    "defined_count": len(defined),
    "used_count": len(used),
    "orphan_defined": orphan_defined,
    "orphan_used": orphan_used,
    "dup_selectors": dup_selectors,
    "hard_white": hard_white,
    "bare_zindex": bare_z,
}, ensure_ascii=False, indent=1))
