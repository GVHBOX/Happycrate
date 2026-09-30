"""生成 tests/parity/torrent_cases.json：体积格式化与种子清单解析的对照表。

种子数据是手工构造的 bencode 字节串，覆盖正常 / 畸形 / 越界 / 深度超限等情形。
每个用例记下 Python 的结果（或抛出的异常类型名）。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_torrent_parity.py
"""

from __future__ import annotations

import binascii
import json
import sys
from pathlib import Path

HAPPYCRATE = Path(r"D:\AI\happycrate")
OUT = Path(__file__).resolve().parent.parent / "tests" / "parity" / "torrent_cases.json"

sys.path.insert(0, str(HAPPYCRATE))

from app import core, sources  # noqa: E402


def bstr(value) -> bytes:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return str(len(raw)).encode() + b":" + raw


def bint(value: int) -> bytes:
    return b"i" + str(value).encode() + b"e"


def blist(items) -> bytes:
    return b"l" + b"".join(items) + b"e"


def bdict(pairs) -> bytes:
    return b"d" + b"".join(bstr(k) + v for k, v in pairs) + b"e"


SINGLE = bdict([
    ("announce", bstr("http://tracker.example/announce")),
    ("info", bdict([
        ("length", bint(1234567)),
        ("name", bstr("movie.mkv")),
        ("piece length", bint(262144)),
    ])),
])

MULTI = bdict([
    ("info", bdict([
        ("files", blist([
            bdict([("length", bint(100)), ("path", blist([bstr("a.txt")]))]),
            bdict([("length", bint(200)), ("path", blist([bstr("sub"), bstr("b.txt")]))]),
        ])),
        ("name", bstr("pack")),
    ])),
])

TORRENTS = [
    ("单文件", SINGLE),
    ("多文件", MULTI),
    ("顶层是整数", bint(5)),
    ("顶层是列表", blist([bint(1)])),
    ("没有 info", bdict([("announce", bstr("x"))])),
    ("info 不是字典", bdict([("info", bstr("x"))])),
    ("files 不是列表", bdict([("info", bdict([("files", bstr("x")), ("length", bint(7)), ("name", bstr("n"))]))])),
    ("缺 length", bdict([("info", bdict([("files", blist([bdict([("path", blist([bstr("a")]))])]))]))])),
    ("缺 path", bdict([("info", bdict([("files", blist([bdict([("length", bint(1))])]))]))])),
    ("条目不是字典", bdict([("info", bdict([("files", blist([bstr("x")]))]))])),
    ("路径里有非字节项", bdict([("info", bdict([("files", blist([
        bdict([("length", bint(5)), ("path", blist([bstr("a"), bint(9), bstr("b")]))]),
    ]))]))])),
    ("路径不是列表", bdict([("info", bdict([("files", blist([
        bdict([("length", bint(5)), ("path", bint(9))]),
    ]))]))])),
    ("长度是字节串", bdict([("info", bdict([("files", blist([
        bdict([("length", bstr("42")), ("path", blist([bstr("a")]))]),
    ]))]))])),
    ("空 files", bdict([("info", bdict([("files", blist([])), ("length", bint(1)), ("name", bstr("n"))]))])),
    ("单文件缺 name", bdict([("info", bdict([("length", bint(1))]))])),
    ("截断", SINGLE[:20]),
    ("空数据", b""),
    ("只有 d", b"d"),
    ("长度越界", bdict([("info", bdict([("name", b"999:abc"), ("length", bint(1))]))])),
    ("数字畸形", bdict([("info", bdict([("length", b"iXe"), ("name", bstr("n"))]))])),
    ("嵌套超限", bdict([("info", bdict([("files", blist([b"l" * 40 + b"e" * 40]))]))])),
    ("非 UTF8 名称", bdict([("info", bdict([("length", bint(3)), ("name", bstr(b"\xff\xfe\xfd"))]))])),
]

SIZES = [
    None, "", 0, -1, 1, 512, 1023, 1024, 1536, 1048576, 1073741824,
    1099511627776, 1125899906842624, 1152921504606846976, 0.5, 1.5,
    "1024", "abc", True, False, [], {}, 1e30, "inf", "nan", "-inf",
]


def main() -> int:
    rows = []
    for name, data in TORRENTS:
        row = {"name": name, "hex": binascii.hexlify(data).decode("ascii")}
        try:
            rows.append({**row, "out": sources.decode_torrent_files(data), "raises": None})
        except Exception as exc:
            rows.append({**row, "out": None, "raises": type(exc).__name__})

    cases = {
        "_scope": (
            "体积用例里用 inf / nan 的字符串形式而不是浮点无穷——"
            "json.dumps 会输出裸的 Infinity/NaN，那不是合法 JSON，Rust 侧解析不了。"
            "字符串走 float 路径得到同样的无穷，结果等价。"
            "种子数据是手工构造的 bencode。`decode_torrent_files` 里有两段语义："
            "解码失败被吞掉返回空表，但**遍历 files 时的异常会抛出去**——"
            "所以用例里带 `raises` 字段。"
            "**字典里的非字节键会被 Rust 侧忽略**（Python 会存下来），"
            "但被查看的键（info/files/length/path/name）都是字节串，不影响结果。"
        ),
        "torrents": rows,
        "sizes": [
            {"in": v, "out": core.format_size(v)} for v in SIZES
        ],
        "max_torrent_bytes": sources.MAX_TORRENT_BYTES,
        "files_cap": 200,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("种子 %d 条 · 体积 %d 条 → %s" % (len(rows), len(cases["sizes"]), OUT))
    for row in rows:
        summary = row["raises"] or (
            "%d 个文件" % len(row["out"]) if row["out"] is not None else "?"
        )
        print("  %-16s → %s" % (row["name"], summary))
    assert rows and cases["sizes"], "样本为空"
    return 0


if __name__ == "__main__":
    sys.exit(main())
