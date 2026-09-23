"""核对「源自报总数」与「实际取回条数」的缺口，并测量整链召回。

用法：
  ./.venv/Scripts/python.exe tools/hc-recall-audit.py 1080p matrix
  ./.venv/Scripts/python.exe tools/hc-recall-audit.py --fresh 1080p

--fresh 额外打印每个源的结果到达时间，用于确认首屏没有变慢。
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import core, sources


def per_source(query: str) -> tuple[dict, dict, float]:
    t0 = time.monotonic()
    res = sources.search_many(query)
    wall = (time.monotonic() - t0) * 1000
    counts = {k: len(v[0]) for k, v in res.items()}
    errors = {k: v[1] for k, v in res.items() if v[1]}
    return counts, errors, wall


def arrival(query: str) -> list[tuple[str, int, float]]:
    t0 = time.monotonic()
    marks: list[tuple[str, int, float]] = []

    def on_source(key, items, _err, _ms):
        marks.append((key, len(items), (time.monotonic() - t0) * 1000))

    sources.search_many(query, on_source=on_source)
    return sorted(marks, key=lambda m: m[2])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="*", default=["1080p"])
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    sources.reload_from_config()
    print("启用源:", ", ".join(sources.enabled_keys()))
    print()

    for q in args.queries:
        counts, errors, wall = per_source(q)
        total = sum(counts.values())
        print(f"=== {q} ===")
        print(f"  各源相加 {total} 条 · 墙钟 {wall:.0f}ms")
        for key in sorted(counts, key=lambda k: -counts[k]):
            flag = f"  失败: {errors[key]}" if key in errors else ""
            print(f"    {key:10s} {counts[key]:5d}{flag}")

        deduped, err = core.search(q, 1, None, None)
        print(f"  合并去重后 {len(deduped.items)} 条"
              f" · 重复 {total - len(deduped.items)} 条")
        if err:
            print(f"  整体错误: {err}")

        if args.fresh:
            print("  到达顺序:")
            for key, n, ms in arrival(q):
                print(f"    {ms:7.0f}ms  {key:10s} {n}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
