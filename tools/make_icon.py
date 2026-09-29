"""从用户自己设计的应用图标生成 assets/icon.ico。

**不重画、不缩放、不改色**：只是把 web/assets/app-256.png 装进 ICO 容器。
Vista 之后 ICO 允许直接内嵌 PNG，256×256 的条目宽高字段写 0（表示 256）。

用法：

    python tools/make_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "web" / "assets" / "app-256.png"
ICON_DIR = ROOT / "assets"
TARGET = ICON_DIR / "icon.ico"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != PNG_SIGNATURE:
        raise ValueError("不是 PNG 文件")
    if data[12:16] != b"IHDR":
        raise ValueError("PNG 结构异常：第一块不是 IHDR")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def build_ico(png: bytes, width: int, height: int) -> bytes:
    dim = lambda n: 0 if n >= 256 else n
    directory = struct.pack("<HHH", 0, 1, 1)
    offset = len(directory) + 16
    entry = struct.pack(
        "<BBBBHHII",
        dim(width),
        dim(height),
        0,
        0,
        1,
        32,
        len(png),
        offset,
    )
    return directory + entry + png


def read_back(data: bytes) -> tuple[int, int, int]:
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    width, height, _, _, planes, depth, size, offset = struct.unpack(
        "<BBBBHHII", data[6:22]
    )
    assert reserved == 0 and kind == 1, "ICO 头不合法"
    assert count == 1, "应当只有一个图像条目"
    assert planes == 1 and depth == 32, "应当声明 32 位单平面"
    assert offset + size == len(data), "图像偏移与长度对不上"
    assert data[offset : offset + 8] == PNG_SIGNATURE, "条目内应当是 PNG"
    return width or 256, height or 256, size


def main() -> int:
    png = SOURCE.read_bytes()
    width, height = png_size(png)
    if width != height:
        print("源图不是正方形，拒绝生成：%dx%d" % (width, height))
        return 1
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(build_ico(png, width, height))

    got_w, got_h, size = read_back(TARGET.read_bytes())
    assert (got_w, got_h) == (width, height), "写出去再读回来尺寸不一致"
    print("源图     : %s (%dx%d, %d 字节)" % (SOURCE.relative_to(ROOT), width, height, len(png)))
    print("产出     : %s (%d 字节)" % (TARGET.relative_to(ROOT), TARGET.stat().st_size))
    print("自检通过 : 读回 %dx%d，内嵌 PNG %d 字节" % (got_w, got_h, size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
