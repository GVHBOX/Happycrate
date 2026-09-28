"""生成 tests/parity/net_cases.json：代理地址解析与绕过列表的对照表。

绕过的期望值来自 CPython 的 `_proxy_bypass_winreg_override(host, override)`
——它把 override 作为参数收，所以可以离线生成；不用现场的注册表值。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_net_parity.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

HAPPYCRATE = Path(r"D:\AI\happycrate")
OUT = Path(__file__).resolve().parent.parent / "tests" / "parity" / "net_cases.json"

sys.path.insert(0, str(HAPPYCRATE))

from app import sources  # noqa: E402

PARSE_PROXY = [
    "",
    "   ",
    ";",
    " ; ; ",
    "http://127.0.0.1:7890",
    "127.0.0.1:7890",
    "https://proxy.local:8080",
    "  http://p:1  ",
    "http://user:pass@h:1080",
    "socks5://127.0.0.1:1080",
    "socks://127.0.0.1:1080",
    "http=127.0.0.1:7890;https=127.0.0.1:7891",
    "http://a:1;https://b:2",
    "http://a:1;http://b:2",
    "ftp://a:1",
    "garbage",
    "://x",
    "http://",
    "http://:8080",
    "http://a:1;",
    ";http://a:1",
    "http://a:1;ftp",
    "a;b",
    "http://[::1]:8080",
    "HTTP://A:1",
]

OVERRIDES = [
    "",
    "<local>",
    "localhost;127.*;192.168.*;10.*;172.16.*;172.31.*;<local>",
    "*.example.com;10.*;172.16.*;<local>",
    "www.example.com;*.example.net; 192.168.0.1",
    "*.org",
    "10.0.0.?",
    "*",
    "127.0.0.1:8080",
]

HOSTS = [
    "",
    "apibay.org",
    "nyaa.si",
    "www.example.com",
    "example.com",
    "sub.example.net",
    "example.net",
    "127.0.0.1",
    "127.0.0.1:8080",
    "127.1.2.3",
    "192.168.1.5",
    "10.0.0.1",
    "10.0.0.10",
    "172.16.5.5",
    "172.31.255.1",
    "172.32.5.5",
    "localhost",
    "mybox",
    "intranet",
    "WWW.EXAMPLE.COM",
    "a.b.c",
    "[::1]",
    "thepiratebay10.org",
]


def main() -> int:
    live = urllib.request.getproxies()
    cases = {
        "_scope": (
            "绕过的期望值用固定 override 字符串离线生成，不读现场注册表；"
            "fnmatch 的 `[seq]` 字符集**未实现**（Python 支持），本项目路径上不会出现。"
        ),
        "_live": {"system": live, "env": urllib.request.getproxies_environment()},
        "parse_proxy": [
            {
                "in": raw,
                "mapping": sources.parse_proxy(raw)[0],
                "err": sources.parse_proxy(raw)[1],
            }
            for raw in PARSE_PROXY
        ],
        "bypass": [
            {
                "host": host,
                "override": override,
                "hit": urllib.request._proxy_bypass_winreg_override(host, override),
            }
            for override in OVERRIDES
            for host in HOSTS
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("parse_proxy %d 条 · bypass %d 条 → %s" % (
        len(cases["parse_proxy"]), len(cases["bypass"]), OUT))
    print("现场系统代理（供 smoke 比对）：", live)
    assert cases["parse_proxy"] and cases["bypass"], "样本为空"
    return 0


if __name__ == "__main__":
    sys.exit(main())
