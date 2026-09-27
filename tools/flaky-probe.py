"""抓偶发失败：把整套单测连跑 N 遍，统计每个失败点复现了几次。

什么时候用：`check-all.py` 红了一次、重跑又绿 —— 这种"时通时不通"要先确认
是真 flaky 还是当次环境抖动，最快的办法就是连跑若干遍看复现率。

用法：
  .venv/Scripts/python.exe tools/flaky-probe.py       # 默认 10 遍（约 9s × N）
  .venv/Scripts/python.exe tools/flaky-probe.py 3     # 只跑 3 遍

退出码：复现到失败 → 1；N 遍全绿 → 0。
命令自带 `-t .`（否则 tests/__init__.py 不执行、数据目录隔离失效）。
"""

import collections
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
CMD = [str(PY), "-m", "unittest", "discover", "-t", ".", "-s", "tests",
       "-p", "test_*.py"]
MAX_LINE = 140


def main() -> int:
    rounds = 10
    if len(sys.argv) > 1:
        try:
            rounds = max(1, int(sys.argv[1]))
        except ValueError:
            print("轮数得是整数，例如 tools/flaky-probe.py 5")
            return 2

    fails: collections.Counter = collections.Counter()
    for i in range(1, rounds + 1):
        r = subprocess.run(CMD, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        bad = [ln.strip()[:MAX_LINE] for ln in out.splitlines()
               if ln.startswith(("FAIL:", "ERROR:"))]
        for line in bad:
            fails[line] += 1
        status = "ok" if r.returncode == 0 else f"红 {len(bad)} 项"
        print(f"[{i}/{rounds}] {status}", flush=True)

    print()
    if not fails:
        print(f"0/{rounds} 未复现，N 遍全绿")
        return 0
    print("—— 复现统计 ——")
    for line, n in fails.most_common():
        print(f"  {n}/{rounds}  {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
