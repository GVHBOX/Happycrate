"""后端 Api 方法 ↔ 前端调用集合的唯一判定口径（扫描器与测试都从这里取数）。

以前同一件事有两套标准：tests/test_contract.py 手写一份「前端从不调用」名单，
tools/scan/scan_api.py 各扫各的。结果是 win_min / win_max / win_close 被名单
误判成孤儿 —— 它们其实由 index.html 标题栏的 call(name) 动态派发在用。
口径只有一份之后，两边不可能再互相矛盾。

三类证据全部来自解析，不接受手写名单：

1. 静态调用 —— `web/` 下的 .js / .html 里出现 `pywebview.api.<name>`。
2. 动态派发 —— 先认出「派发器」：单参数函数，函数体里既提到 pywebview、
   又以 `[参数名]` 对 pywebview.api 取属性（`call(name)` 就是这个形状），
   再把 `派发器("字面量")` 的实参算作前端调用。
3. Python 侧调用 —— `app/` 与 `main.py` 里由 `= Api()` 绑定的变量（含同名参数）
   上发起的方法调用。`boot` 就是靠 app/shell.py 的 `bridge.boot()` 自证
   「不由 web 调用」的；那个调用点一旦没，boot 立刻出现在 never_called 里。

解析是启发式的，边界写在注释里而不是假装没有：函数体用花括号配对切，
跳过引号内的内容、不识别正则字面量。误判只会让派发器判定偏宽（取到更长的函数体），
字面量实参是在整个文件上收的，不会因此漏掉调用点。

护栏方向上这里只会比手写名单更严：想躲开 backend_never_called，
要么在 web/ 里真调一次，要么在 Python 侧真调一次，写名字没用了。
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_SUFFIXES = (".js", ".html")

STATIC_CALL = re.compile(r"pywebview\.api\.([A-Za-z_][A-Za-z0-9_]*)")
FUNCTION_FORMS = (
    re.compile(r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)"
               r"\s*\(\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*\)\s*\{"),
    re.compile(r"\b(?:var|let|const)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*function"
               r"\s*\(\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*\)\s*\{"),
)
BRACKEDEX = r"\[\s*%s\s*\]"
FACADE_HEAD = re.compile(r"^    ([A-Za-z_$][A-Za-z0-9_$]*)\s*:\s*"
                         r"(?:function\s*\(|[A-Za-z_$][A-Za-z0-9_$]*,)", re.M)
FACADE_USE = re.compile(r"\bapi\.([A-Za-z_$][A-Za-z0-9_$]*)\b")
API_OBJECT_HEAD = "var api = {"
API_OBJECT_END = "\n  };"


def web_paths(root: Path = ROOT) -> list[Path]:
    web = root / "web"
    return [p for p in sorted(web.rglob("*"))
            if p.suffix in WEB_SUFFIXES and p.is_file()]


def _line(text: str, index: int) -> int:
    return text[:index].count("\n") + 1


def _block_end(text: str, open_brace: int) -> int:
    depth, i, quote = 0, open_brace, ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text)


def _named_functions(text: str):
    for pattern in FUNCTION_FORMS:
        for m in pattern.finditer(text):
            name, param, brace = m.group(1), m.group(2), m.end() - 1
            yield name, param, text[brace:_block_end(text, brace) + 1]


def dispatcher_names(root: Path = ROOT) -> set[str]:
    """找出「把字符串名字转成 pywebview.api 调用」的派发器函数名。"""
    found = set()
    for path in web_paths(root):
        text = path.read_text(encoding="utf-8")
        if "pywebview" not in text:
            continue
        for name, param, body in _named_functions(text):
            if "pywebview" not in body:
                continue
            if re.search(BRACKEDEX % re.escape(param), body):
                found.add(name)
    return found


def dispatch_targets(root: Path = ROOT) -> dict[str, list[str]]:
    """派发器收到的字符串字面量实参：这些名字就是前端在调的。"""
    out: dict[str, list[str]] = {}
    for fn in sorted(dispatcher_names(root)):
        pattern = re.compile(r"(?<![\w.$])%s\s*\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']"
                             % re.escape(fn))
        for path in web_paths(root):
            text = path.read_text(encoding="utf-8")
            for m in pattern.finditer(text):
                out.setdefault(m.group(1), []).append(
                    "%s:%d(dispatch)" % (path.name, _line(text, m.start())))
    return out


def web_call_sites(root: Path = ROOT) -> dict[str, list[str]]:
    """前端调用集合 = 静态 `pywebview.api.x` + 动态派发实参。"""
    out: dict[str, list[str]] = {}
    for path in web_paths(root):
        text = path.read_text(encoding="utf-8")
        for m in STATIC_CALL.finditer(text):
            out.setdefault(m.group(1), []).append(
                "%s:%d" % (path.name, _line(text, m.start())))
    for name, sites in dispatch_targets(root).items():
        out.setdefault(name, []).extend(sites)
    return out


def web_method_names(root: Path = ROOT) -> set[str]:
    return set(web_call_sites(root))


def api_methods(root: Path = ROOT) -> list[dict]:
    tree = ast.parse((root / "app" / "api.py").read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Api":
            for m in node.body:
                if (isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and not m.name.startswith("_")):
                    out.append({"name": m.name, "line": m.lineno,
                                "args": [a.arg for a in m.args.args
                                         if a.arg != "self"]})
    return out


def backend_method_names(root: Path = ROOT) -> set[str]:
    return {r["name"] for r in api_methods(root)}


def _api_instance_names(tree: ast.AST) -> set[str]:
    """`= Api(...)` 绑定的变量名；按名字匹配，所以把它当参数传下去也照样认。"""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            func = node.value.func if isinstance(node.value, ast.Call) else None
            ctor = getattr(func, "attr", None) or getattr(func, "id", None)
            if ctor == "Api":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
    return names


def _python_files(root: Path = ROOT) -> list[Path]:
    return sorted((root / "app").glob("*.py")) + [root / "main.py"]


def python_call_sites(root: Path = ROOT) -> dict[str, list[str]]:
    """Python 侧对 Api 实例的方法调用（boot 的证据在这里，不在名单里）。"""
    wanted = backend_method_names(root)
    out: dict[str, list[str]] = {}
    for path in _python_files(root):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        receivers = _api_instance_names(tree)
        if not receivers:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if (isinstance(fn, ast.Attribute)
                    and isinstance(fn.value, ast.Name)
                    and fn.value.id in receivers
                    and fn.attr in wanted):
                rel = path.relative_to(root).as_posix()
                out.setdefault(fn.attr, []).append("%s:%d(python)" % (rel, node.lineno))
    return out


def never_called(root: Path = ROOT) -> list[dict]:
    """后端公开方法里既不被 web 调、也不被 Python 调的那些。"""
    web = web_call_sites(root)
    py = python_call_sites(root)
    return [dict(r) for r in api_methods(root)
            if r["name"] not in web and r["name"] not in py]


def facade_region(text: str) -> str:
    body = text.split(API_OBJECT_HEAD, 1)[1]
    return body.split(API_OBJECT_END, 1)[0]


def facade_members(root: Path = ROOT) -> dict[str, bool]:
    """HC.api 门面成员 → 是否真的转调后端（成员体内出现 pywebview 就算转调）。

    形状两种都要认：`name: function(){...}` 和 `name: someLocal,`。
    旧口径只匹配前者，于是 onLive / isLive 靠正则盲区蒙混过关。
    """
    text = (root / "web" / "js" / "api.js").read_text(encoding="utf-8")
    region = facade_region(text)
    hits = list(FACADE_HEAD.finditer(region))
    out: dict[str, bool] = {}
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(region)
        out[m.group(1)] = "pywebview" in region[m.start():end]
    return out


def facade_uses(root: Path = ROOT) -> set[str]:
    """api.js 之外真正引用过的 HC.api 成员名（证明门面方法不是幻影）。"""
    out = set()
    for path in web_paths(root):
        if path.name == "api.js":
            continue
        text = path.read_text(encoding="utf-8")
        for m in FACADE_USE.finditer(text):
            out.add(m.group(1))
    return out


def call_report(root: Path = ROOT) -> dict:
    web = web_call_sites(root)
    backend = api_methods(root)
    names = {r["name"] for r in backend}
    py = python_call_sites(root)
    return {
        "backend": backend,
        "backend_count": len(backend),
        "front_count": len(web),
        "dispatchers": sorted(dispatcher_names(root)),
        "dispatch_targets": dispatch_targets(root),
        "web_calls": web,
        "python_calls": py,
        "missing_in_backend": {k: v for k, v in sorted(web.items())
                               if k not in names},
        "backend_never_called": never_called(root),
    }
