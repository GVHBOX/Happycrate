"""一键全检：把散在四处的检查串成一条命令。

之前全检要手动敲四五种命令（单测 / 7 个扫描器 / mypy / 反向注入 / E2E），
漏跑哪一项全凭记忆。这个脚本把它们串起来，每项单独计时。

用法：
  .venv/Scripts/python.exe tools/check-all.py              # 快检：单测 + 7 扫描器 + dist + mypy
  .venv/Scripts/python.exe tools/check-all.py --full       # 加 E2E
  .venv/Scripts/python.exe tools/check-all.py --guard      # 加反向注入（约 5min）
  .venv/Scripts/python.exe tools/check-all.py --all        # 全跑
  .venv/Scripts/python.exe tools/check-all.py --update-baseline

关于基线：扫描器报出来的历史遗留项记在 `scan/baseline.json`。
只有「基线之外的新增项」才让退出码非 0 —— 否则脚本天天飘红，
最后会跟没人跑的护栏一样被习惯性忽略。想重设基线就跑 --update-baseline。
"""

import ast
import filecmp
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
SCAN = ROOT / "tools" / "scan"
BASELINE = SCAN / "baseline.json"
DIST = ROOT / "dist" / "happycrate" / "_internal"
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIX = {".pyc", ".pyo"}

# 写进基线文件开头，免得下轮看到一堆条目不知道哪些是真债
BASELINE_NOTE = (
    "这里的项是「扫描器当前就会报、且已知不是缺陷」的清单，"
    "只有清单之外的新增项才会让 check-all 退出码非 0。\n"
    "已经改成由扫描器自己排除的（不再压在这里）：\n"
    "· scan_adapter 的 unused page —— 读源码里的 _pageless 标记，"
    "与 PAGELESS_KEYS 同一个真相源；\n"
    "· scan_py 的 dup_definitions —— 只在同一个文件内判重，"
    "跨文件同名（run/get）不再算重复；\n"
    "· scan_api 的 boot —— 由 scan/api_contract.py 解析 Python 侧调用点"
    "（app/shell.py 的 bridge.boot()），前端调用集合的口径扫描器与测试共用一份；\n"
    "· swallow —— 循环内跳候选、或失败后还有后续处理的，归到 "
    "swallow_try_next（可查但不计数），只有真静默吞的才算问题。"
)

# keys: 只关心这几个键（其余是统计数字或常态输出，不是缺陷）
# pick: 脚本输出是裸列表时，用它挑出真正有问题的元素
SCANNERS = [
    {"script": "scan_py.py",
     "keys": ("tuple_arity", "dead_code", "dup_definitions", "swallow")},
    {"script": "scan_css.py",
     "keys": ("orphan_defined", "orphan_used", "dup_selectors",
              "hard_white", "bare_zindex")},
    {"script": "scan_api.py",
     "keys": ("missing_in_backend", "backend_never_called")},
    {"script": "scan_bloat.py", "keys": ("dup_blocks",)},
    {"script": "scan_dupfunc.py", "pick": lambda p: list(p)},
    {"script": "scan_adapter.py",
     "pick": lambda p: [r for r in p if r.get("unused_args")]},
    {"script": "scan_comment.py",
     "keys": ("py_comments", "py_docstrings", "js_comments",
              "css_comments", "html_comments")},
]


def run(cmd, cwd=ROOT, timeout=900):
    """跑一条命令，返回 (退出码, 输出, 秒数)。

    子进程强制 UTF-8 输出：中文 Windows 上管道默认走 GBK，
    扫描器把源码里的中文带出来时会被折成乱码。
    """
    started = time.perf_counter()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           env=env)
        return r.returncode, (r.stdout or "") + (r.stderr or ""), \
            time.perf_counter() - started
    except subprocess.TimeoutExpired:
        return 124, f"超时 {timeout}s", time.perf_counter() - started
    except OSError as exc:
        return 127, str(exc), time.perf_counter() - started


def scanner_findings(spec, payload):
    """把扫描器的 JSON 输出归一成一组可比对的字符串。"""
    out = []
    if "pick" in spec:
        for item in spec["pick"](payload):
            out.append(json.dumps(item, sort_keys=True, ensure_ascii=False))
        return out
    for key in spec["keys"]:
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, list):
            for item in value:
                out.append(key + "|" + json.dumps(item, sort_keys=True,
                                                  ensure_ascii=False))
        elif isinstance(value, dict):
            for sub, subval in value.items():
                out.append(key + "|" + sub + "|" +
                           json.dumps(subval, sort_keys=True, ensure_ascii=False))
    return out


def run_scanners():
    """跑全部扫描器，返回 (每项的 findings, 耗时明细)。"""
    found, detail = {}, []
    for spec in SCANNERS:
        path = SCAN / spec["script"]
        code, out, secs = run([str(PY), str(path)])
        if code != 0:
            found[spec["script"]] = [f"脚本自己崩了（exit {code}）"]
            detail.append((spec["script"], secs, 1))
            continue
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            head = out.strip().splitlines()[:1]
            found[spec["script"]] = ["输出不是 JSON：" + (head[0] if head else "")]
            detail.append((spec["script"], secs, 1))
            continue
        items = scanner_findings(spec, payload)
        if items:
            found[spec["script"]] = items
        detail.append((spec["script"], secs, len(items)))
    return found, detail


def type_check():
    """跑 mypy（配置在 pyproject 的 [tool.mypy]，只管 app/ 与 main.py）。

    没装 mypy 时这一步算「跳过」而不是失败：护栏不该因为谁少装了 dev 依赖
    就把提交卡死，但跳过要在输出里看得见，否则会误以为查过了。
    """
    code, out, secs = run([str(PY), "-m", "mypy"])
    if "No module named mypy" in out or "Cannot find module" in out:
        return "absent", out.strip().splitlines()[-1:], secs
    lines = [l for l in out.splitlines() if re.search(r":(error|warning):", l)]
    if code != 0 and not lines:
        lines = [l for l in out.strip().splitlines() if l.strip()][-6:]
    return ("ok" if code == 0 else "fail"), lines, secs


def walk(root: Path):
    if not root.is_dir():
        return []
    return [p for p in sorted(root.rglob("*"))
            if p.is_file()
            and not any(part in SKIP_DIRS for part in p.parts)
            and p.suffix not in SKIP_SUFFIX]


def dist_drift():
    """只读比对 app/ 与 web/ 和 dist 里的副本，返回 [(相对路径, 原因)]。

    这里刻意不调用 sync-dist.py —— 检查必须无副作用，
    否则「跑一次全检」会顺手把 dist 改掉，出问题分不清是谁改的。
    """
    if not DIST.is_dir():
        return []
    drift = []
    for name in ("app", "web"):
        src_root, dst_root = ROOT / name, DIST / name
        if not dst_root.is_dir():
            drift.append((name, "dist 里没有这个目录，先打包一次"))
            continue
        for path in walk(src_root):
            rel = path.relative_to(src_root)
            target = dst_root / rel
            if not target.exists():
                drift.append((f"{name}/{rel}", "dist 里缺这个文件"))
            elif not filecmp.cmp(path, target, shallow=False):
                drift.append((f"{name}/{rel}", "内容与源码不一致"))
        wanted = {p.relative_to(src_root) for p in walk(src_root)}
        for target in walk(dst_root):
            rel = target.relative_to(dst_root)
            if rel not in wanted:
                drift.append((f"{name}/{rel}", "源码里已经没有这个文件（僵尸）"))
    return drift


def load_baseline():
    if not BASELINE.is_file():
        return {}
    try:
        raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"基线文件坏了，按空基线处理：{BASELINE}")
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def guard_case_count() -> int:
    """数反向注入有几条 —— 写死的数字会跟 guard-regression.py 漂移。"""
    source = (ROOT / "tools" / "guard-regression.py").read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if (isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "CASES"):
            return len(node.value.elts)
    return 0


def data_snapshot() -> dict:
    """给真实数据目录里的 json 拍一张 md5 快照。

    测试必须在隔离目录里跑（tests/__init__.py 负责把 HAPPYCRATE_DATA_DIR
    指到临时目录）。这里比对跑测试前后的快照，就能发现「哪个测试写了用户的
    真配置」—— data/ 被 .gitignore 排除，光看 git status 永远发现不了。

    快照取 (md5, mtime_ns) 两个值：只比 md5 抓不到「写回去的内容跟原来一模
    一样」这种情况（典型就是被测试覆写过的文件再覆写一次），得靠 mtime。
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app import paths

    directory = paths.data_dir()
    snap = {}
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                st = path.stat()
                snap[path.name] = (hashlib.md5(path.read_bytes()).hexdigest(),
                                   st.st_mtime_ns)
            except OSError:
                snap[path.name] = ("", 0)
    return snap


_E2E_BAD_PREFIX = ("[diag] ", "VERDICT: FAIL")

_GUARD_NOISE = ("FAIL:", "ERROR:", "FAIL ")


def failure_lines(text, skip: tuple[str, ...] = ()):
    """从 unittest / E2E 的输出里挑出失败行，让汇总能直接看。

    护栏那一步里的 FAIL/ERROR 是注入出来的预期失败，正是要它们红才说明拦住了，
    跟着倒进汇总会把真正的 [漏过] 埋掉，所以调用方要显式 skip 掉。
    """
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(skip):
            continue
        if s.startswith(("FAIL:", "ERROR:", "FAIL ",
                         "[漏过]", "[失败]", "[锚点失效]")) \
                or s.startswith(_E2E_BAD_PREFIX) \
                or (s.startswith("[run] ")
                    and ("failed:" in s or "error:" in s)):
            out.append(s)
    return out


def main():
    argv = sys.argv[1:]
    want_e2e = "--full" in argv or "--all" in argv
    want_guard = "--guard" in argv or "--all" in argv
    update = "--update-baseline" in argv

    baseline = {} if update else load_baseline()

    new, known, detail = {}, [], []
    total = 4 + (1 if want_e2e else 0) + (1 if want_guard else 0)
    step = 0

    step += 1
    before = data_snapshot()
    code, out, secs = run([str(PY), "-m", "unittest", "discover",
                           "-t", ".", "-s", "tests", "-p", "test_*.py"])
    after = data_snapshot()
    touched = sorted(k for k in set(before) | set(after)
                     if before.get(k) != after.get(k))
    m = re.search(r"Ran (\d+) tests", out)
    label = f"{m.group(1)} 项" if m else ""
    if code != 0:
        new["单元测试"] = failure_lines(out) or [f"非零退出 {code}"]
    if touched:
        new["真实数据被测试改写"] = [
            f"{name} 被改动 —— 测试必须写在隔离目录里（tests/__init__.py）"
            for name in touched]
    print(f"[{step}/{total}] 单元测试 ......... {secs:6.1f}s  "
          f"{'通过 ' + label if code == 0 else '失败 ' + label}"
          f"{' · 数据目录未受影响' if not touched else ' · 数据目录被改动 ' + str(len(touched)) + ' 个'}")
    detail.append(("单元测试", secs, 0 if code == 0 else 1))

    step += 1
    found, scan_detail = run_scanners()
    scan_secs = sum(s for _, s, _ in scan_detail)
    for script, items in found.items():
        base = set(baseline.get(script, []))
        fresh = [i for i in items if i not in base]
        known += [i for i in items if i in base]
        if fresh:
            new[script] = fresh
    print(f"[{step}/{total}] 代码体检 {len(SCANNERS)} 项 .. {scan_secs:6.1f}s")
    for script, secs, count in scan_detail:
        print(f"        {script:<17} {secs:5.1f}s  "
              f"{'全绿' if count == 0 else str(count) + ' 项'}")
    detail.append(("代码体检", scan_secs, sum(1 for v in found.values() if v)))

    step += 1
    started = time.perf_counter()
    drift = dist_drift()
    secs = time.perf_counter() - started
    if drift:
        new["dist 同步"] = [f"{p} —— {why}" for p, why in drift]
    print(f"[{step}/{total}] dist 同步检查 ..... {secs:6.1f}s  "
          f"{'一致' if not drift else str(len(drift)) + ' 个文件待同步'}")
    detail.append(("dist 同步", secs, len(drift)))

    step += 1
    tstatus, tlines, secs = type_check()
    if tstatus == "fail":
        new["类型检查"] = tlines
    print(f"[{step}/{total}] 类型检查 (mypy) ... {secs:6.1f}s  "
          + {"ok": "通过", "fail": f"{len(tlines)} 处", "absent": "跳过（未安装 mypy）"}[tstatus])
    detail.append(("类型检查", secs, 0 if tstatus == "ok" else 1))

    if want_e2e:
        step += 1
        code, out, secs = run(["node", str(ROOT / "tests" / "e2e" /
                                           "hc-e2e-test.mjs")], timeout=600)
        if code != 0:
            new["E2E"] = failure_lines(out) or [f"非零退出 {code}"]
        print(f"[{step}/{total}] E2E ............... {secs:6.1f}s  "
              f"{'通过' if code == 0 else '失败'}")
        detail.append(("E2E", secs, 0 if code == 0 else 1))

    if want_guard:
        step += 1
        code, out, secs = run([str(PY), str(ROOT / "tools" /
                                            "guard-regression.py")], timeout=900)
        if code != 0:
            new["反向注入"] = failure_lines(out, skip=_GUARD_NOISE) \
                or [f"非零退出 {code}"]
        print(f"[{step}/{total}] 反向注入 {guard_case_count()} 项 ... {secs:6.1f}s  "
              f"{'全拦住' if code == 0 else '有问题'}")
        detail.append(("反向注入", secs, 0 if code == 0 else 1))

    if update:
        payload = {"_读我": BASELINE_NOTE, **found}
        BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        print(f"\n基线已重建（{sum(len(v) for v in found.values())} 项）→ {BASELINE}")
        return 0

    elapsed = sum(s for _, s, _ in detail)
    print("\n—— 汇总 ——")
    print(f"耗时 {elapsed:.1f}s · 新增问题 {sum(len(v) for v in new.values())} 项"
          f" · 已知基线 {len(known)} 项")
    if known:
        print(f"（基线在 {BASELINE.name}，重设跑 --update-baseline）")
    for name, items in new.items():
        print(f"\n  {name}：")
        for item in items[:12]:
            print("    " + (item if len(item) < 110 else item[:107] + "..."))
        if len(items) > 12:
            print(f"    ... 还有 {len(items) - 12} 项")
    if not new:
        print("没有新增问题。")
    return 1 if new else 0


def ensure_utf8_stdout():
    """控制台默认编码在中文 Windows 上是 GBK，扫描器里的中文条目会直接把它崩掉。

    护栏自己崩溃比报出问题更糟 —— 只会让人以为检查过了。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


ensure_utf8_stdout()

if __name__ == "__main__":
    sys.exit(main())
