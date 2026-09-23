"""把 app/ 与 web/ 的源码同步进 dist/happycrate/_internal/。

改代码不用重新打包：app/ 与 web/ 是外置的。手工复制容易把路径写错
（历史上出现过 dist/happycrate/_internal/data 这种错位文件），所以统一走这里。
"""

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dist" / "happycrate" / "_internal"
PAIRS = (("app", "app"), ("web", "web"))
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIX = {".pyc", ".pyo"}


def source_files(src: Path):
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in SKIP_SUFFIX:
            continue
        yield path


def sync_one(name: str) -> tuple[list[str], list[str]]:
    src = ROOT / name
    dst = DIST / name
    if not src.is_dir():
        raise SystemExit(f"找不到源目录：{src}")
    if not DIST.is_dir():
        raise SystemExit(f"找不到 {DIST}，先打包一次：\n"
                         f"  .venv/Scripts/python.exe -m PyInstaller "
                         f"happycrate.spec --noconfirm")

    copied: list[str] = []
    removed: list[str] = []

    wanted = set()
    for path in source_files(src):
        rel = path.relative_to(src)
        wanted.add(rel)
        target = dst / rel
        if target.exists() and filecmp.cmp(path, target, shallow=False):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied.append(f"{name}/{rel}")

    for target in source_files(dst):
        rel = target.relative_to(dst)
        if rel not in wanted:
            target.unlink()
            removed.append(f"{name}/{rel}")

    return copied, removed


def main() -> int:
    total_copied: list[str] = []
    total_removed: list[str] = []
    for name, _ in PAIRS:
        copied, removed = sync_one(name)
        total_copied += copied
        total_removed += removed

    for item in total_copied:
        print("复制", item)
    for item in total_removed:
        print("删除僵尸文件", item)
    print(f"完成：复制 {len(total_copied)} 个 · 删除 {len(total_removed)} 个")
    if not total_copied and not total_removed:
        print("dist 与源码已经一致，无需改动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
