"""清理测试遗留的无头 Edge 进程与 .scratch/tmp 下的 profile 目录。

只结束「浏览器进程 且 命令行含 .scratch/tmp」，绝不碰用户自己的浏览器，
也不会误伤同时在跑的 bash / python。
覆盖 e2e（hc-e2e-*）与截图工具（prof）两处 profile，
两者都落在 .scratch/tmp 下，所以用同一个标记识别。
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".scratch" / "tmp"
MARK = str(TMP)
BROWSERS = ("msedge", "chrome", "chromium")

PS_QUERY = (
    "Get-CimInstance Win32_Process | "
    "Where-Object { "
    f"$_.CommandLine -like '*{MARK}*' -and ("
    + " -or ".join(f"$_.Name -like '*{b}*'" for b in BROWSERS)
    + ") } | Select-Object -ExpandProperty ProcessId"
)


def e2e_pids() -> list[str]:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", PS_QUERY],
            capture_output=True, text=True, errors="replace", timeout=120,
        ).stdout
    except Exception as exc:
        print(f"查询进程失败：{exc}")
        return []
    return [p.strip() for p in out.split() if p.strip().isdigit()]


def kill(pid: str) -> bool:
    try:
        return subprocess.run(
            ["taskkill", "/F", "/T", "/PID", pid],
            capture_output=True, timeout=30,
        ).returncode == 0
    except Exception:
        return False


def reap(rounds: int = 6) -> int:
    total = 0
    for i in range(rounds):
        pids = e2e_pids()
        if not pids:
            print(f"第 {i + 1} 轮：已无残留进程")
            break
        killed = sum(1 for pid in pids if kill(pid))
        total += killed
        print(f"第 {i + 1} 轮：发现 {len(pids)} 个，结束 {killed} 个")
    return total


def sweep_dirs() -> int:
    removed = 0
    for d in sorted(TMP.iterdir()):
        if not d.is_dir():
            continue
        try:
            shutil.rmtree(d)
            removed += 1
        except Exception as exc:
            print(f"  删除失败 {d.name}：{exc}")
    return removed


def main() -> int:
    if not TMP.is_dir():
        print(f"{TMP} 不存在")
        return 0
    before = sum(f.stat().st_size for f in TMP.rglob("*") if f.is_file())

    print(f"目标：{TMP}")
    print(f"清理前子目录 {len([d for d in TMP.iterdir() if d.is_dir()])} 个")
    reaped = reap()
    removed = sweep_dirs()

    after = sum(f.stat().st_size for f in TMP.rglob("*") if f.is_file())
    print(f"结束进程 {reaped} 个 · 删除目录 {removed} 个")
    print(f"回收 {before / 1024 ** 2:.0f} MB → 现 {after / 1024 ** 2:.1f} MB")
    left = [d for d in TMP.iterdir() if d.is_dir()]
    if left:
        names = ", ".join(d.name for d in left)
        print(f"仍有 {len(left)} 个目录未删掉（可能仍被占用）：{names}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
