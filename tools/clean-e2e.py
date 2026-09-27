"""清理测试遗留的浏览器进程与 .scratch/tmp 下的 profile 目录。

按 profile 目录里的 DevToolsActivePort 找端口、再找监听该端口的进程，
只结束「自己起的那个浏览器」，绝不碰用户自己的浏览器。
覆盖 e2e（hc-e2e-*）与截图工具（prof）两处 profile，
两者都落在 .scratch/tmp 下。
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".scratch" / "tmp"


def profile_ports() -> list[int]:
    ports = []
    for f in sorted(TMP.glob("*/DevToolsActivePort")):
        try:
            ports.append(int(f.read_text(encoding="utf-8").split("\n")[0].strip()))
        except Exception:
            continue
    return ports


def listening_pids(ports: list[int]) -> list[str]:
    if not ports:
        return []
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            errors="replace", timeout=60,
        ).stdout
    except Exception as exc:
        print(f"查询端口失败：{exc}")
        return []
    pids = []
    for line in out.splitlines():
        if "LISTENING" not in line.upper():
            continue
        cols = line.split()
        if not cols or not cols[-1].isdigit():
            continue
        for port in ports:
            if re.search(r":" + str(port) + r"(?!\d)", line):
                pids.append(cols[-1])
                break
    return pids


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
    ports = profile_ports()
    if not ports:
        print("没有可用的调试端口记录，跳过进程清理")
        return 0
    print(f"profile 记录的调试端口：{ports}")
    for i in range(rounds):
        pids = listening_pids(ports)
        if not pids:
            print(f"第 {i + 1} 轮：端口已无人监听")
            break
        killed = sum(1 for pid in pids if kill(pid))
        total += killed
        print(f"第 {i + 1} 轮：发现 {len(pids)} 个监听进程，结束 {killed} 个")
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
