"""提交前检查：挡住「改了源码忘了同步 dist」这类会骗人的提交。

dist/happycrate/_internal/ 里的 app/ 与 web/ 是程序真正跑的那份。
改了源码忘记 sync-dist，界面上跑的还是旧代码，然后你会对着旧代码排查新 bug ——
这个坑不会让任何测试变红，只有比对文件才看得见。

用法：
  .venv/Scripts/python.exe tools/pre-commit.py             # 快检 + 同步检查
  .venv/Scripts/python.exe tools/pre-commit.py --install    # 装进 .git/hooks/pre-commit
  .venv/Scripts/python.exe tools/pre-commit.py --no-tests   # 跳过单测

钩子装好之后每次 git commit 自动跑；想跳过某次提交用 git commit --no-verify。
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
HOOK = ROOT / ".git" / "hooks" / "pre-commit"

HOOK_BODY = (
    "#!/bin/sh\n"
    "# 由 tools/pre-commit.py --install 生成\n"
    ".venv/Scripts/python.exe tools/pre-commit.py\n"
)


def staged_files():
    r = subprocess.run(["git", "diff", "--cached", "--name-only"],
                       cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


def load_check_all():
    """复用 check-all.py 的体检与 dist 比对，不起子进程。

    文件名带连字符不能直接 import，所以用 spec_from_file_location 加载。
    """
    path = ROOT / "tools" / "check-all.py"
    spec = importlib.util.spec_from_file_location("hc_check_all", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install():
    if not HOOK.parent.is_dir():
        raise SystemExit(f"找不到 {HOOK.parent}，这不是一个 git 仓库？")
    if HOOK.is_file() and "pre-commit.py" in HOOK.read_text(encoding="utf-8"):
        print(f"钩子已经装过了：{HOOK}")
        return 0
    HOOK.write_text(HOOK_BODY, encoding="utf-8")
    print(f"已写入 {HOOK}")
    print("想临时跳过某次提交：git commit --no-verify")
    return 0


def main():
    if "--install" in sys.argv[1:]:
        return install()

    check_all = load_check_all()
    problems = []

    # 只报本次提交动过的部分，跟改动无关的历史漂移交给 check-all 去管
    touched = {n.split("/", 1)[0] for n in staged_files()}
    drift = [(p, why) for p, why in check_all.dist_drift()
             if p.split("/", 1)[0] in touched]
    if drift:
        problems.append(("dist 未同步", [f"{p} —— {why}" for p, why in drift]))

    if "--no-tests" not in sys.argv[1:]:
        r = subprocess.run([str(PY), "-m", "unittest", "discover",
                            "-s", "tests", "-p", "test_*.py"],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            out = (r.stdout or "") + (r.stderr or "")
            lines = [l.strip() for l in out.splitlines()
                     if l.startswith(("FAIL:", "ERROR:"))]
            problems.append(("单元测试", lines or [f"非零退出 {r.returncode}"]))

    baseline = check_all.load_baseline()
    fresh = []
    for script, items in check_all.run_scanners()[0].items():
        known = set(baseline.get(script, []))
        fresh += [f"{script}: {i}" for i in items if i not in known]
    if fresh:
        problems.append(("代码体检", fresh))

    if not problems:
        print("提交前检查通过。")
        return 0

    print("提交前检查没过：\n")
    for title, items in problems:
        print(f"  {title}：")
        for item in items[:12]:
            print("    " + (item if len(item) < 110 else item[:107] + "..."))
        if len(items) > 12:
            print(f"    ... 还有 {len(items) - 12} 项")
    if drift:
        print("\n  同步：.venv/Scripts/python.exe tools/sync-dist.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
