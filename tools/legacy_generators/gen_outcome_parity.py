"""生成 tests/parity/outcome_cases.json：classify / state_of / outcome_text 的对照表。

用法：

    cd /d D:\\AI\\happycrate
    .venv/Scripts/python.exe D:\\AI\\happycrate-rust\\tools\\gen_outcome_parity.py
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

HAPPYCRATE = Path(r"D:\AI\happycrate")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "parity" / "outcome_cases.json"

sys.path.insert(0, str(HAPPYCRATE))

from app import api  # noqa: E402

CLASSIFY = [
    (True, 5, "", 100),
    (True, 0, "", 100),
    (True, 5, "", 6000),
    (True, 5, "", 5000),
    (True, 5, "", 0),
    (True, 1, "ignored", 10),
    (False, 0, "", 0),
    (False, 5, "", 0),
    (False, 0, "timed out", 0),
    (False, 0, "连接超时", 0),
    (False, 0, "TimeoutError('x')", 0),
    (False, 0, "HTTP Error 403: Forbidden", 0),
    (False, 0, "HTTP Error 401: Unauthorized", 0),
    (False, 0, "HTTP Error 429: Too Many Requests", 0),
    (False, 0, "HTTP Error 451: Unavailable For Legal Reasons", 0),
    (False, 0, "HTTP Error 404: Not Found", 0),
    (False, 0, "HTTP Error 500: Internal Server Error", 0),
    (False, 0, "HTTP 503", 0),
    (False, 0, "状态码 429", 0),
    (False, 0, "状态码418", 0),
    (False, 0, "http error 404", 0),
    (False, 0, api.sources.CANCEL_TEXT, 0),
    (False, 0, "cancelled by user", 0),
    (False, 0, api.sources.BLOCKED_TEXT, 0),
    (False, 0, api.sources.JAVDB_LOGIN_TEXT, 0),
    (False, 0, "ShapeError: 结果页没有条目", 0),
    (False, 0, api.sources.PROXY_MARK + " http://127.0.0.1:7890 连不上", 0),
    (False, 0, api.sources.PROXY_UNREACHABLE_MARK, 0),
    (False, 0, "Tunnel connection failed: 502 Bad Gateway", 0),
    (False, 0, "ProxyError: cannot connect", 0),
    (False, 0, "myproxy issue", 0),
    (False, 0, "tunneling failed", 0),
    (False, 0, "<urlopen error [WinError 10061]>", 0),
    (False, 0, "connection reset by peer", 0),
    (False, 0, "gaierror: getaddrinfo failed", 0),
    (False, 0, api.sources.NET_FAIL_TEXT, 0),
    (False, 0, "SSLError: certificate verify failed", 0),
    (False, 0, "JSONDecodeError: Expecting value: line 1", 0),
    (False, 0, "KeyError: 'hits'", 0),
    (False, 0, "TypeError: unsupported operand type(s)", 0),
    (False, 0, "something else entirely", 0),
    (False, 0, "state code 500", 0),
    (False, 0, "10061 is not a signal here", 0),
]

OUTCOME_TEXT = [
    (api.OUTCOME_OK, 0),
    (api.OUTCOME_EMPTY, 0),
    (api.OUTCOME_SLOW, 0),
    (api.OUTCOME_TIMEOUT, 0),
    (api.OUTCOME_NET, 0),
    (api.OUTCOME_403, 0),
    (api.OUTCOME_403, 403),
    (api.OUTCOME_429, 0),
    (api.OUTCOME_5XX, 0),
    (api.OUTCOME_5XX, 503),
    (api.OUTCOME_4XX, 0),
    (api.OUTCOME_4XX, 418),
    (api.OUTCOME_CANCEL, 0),
    (api.OUTCOME_PARSE, 0),
    (api.OUTCOME_451, 0),
    (api.OUTCOME_BLOCKED, 0),
    (api.OUTCOME_SHAPE, 0),
    (api.OUTCOME_LOGIN, 0),
    (api.OUTCOME_UNKNOWN, 0),
    ("nonsense", 0),
]

STATE_INPUTS = [
    [],
    [""],
    [api.OUTCOME_OK],
    [api.OUTCOME_OK] * 5,
    [api.OUTCOME_SLOW],
    [api.OUTCOME_EMPTY],
    [api.OUTCOME_EMPTY] * 5,
    [api.OUTCOME_TIMEOUT],
    [api.OUTCOME_TIMEOUT] * 3,
    [api.OUTCOME_BLOCKED],
    [api.OUTCOME_BLOCKED] * 3,
    [api.OUTCOME_NET],
    [api.OUTCOME_403],
    [api.OUTCOME_429],
    [api.OUTCOME_4XX],
    [api.OUTCOME_5XX],
    [api.OUTCOME_451],
    [api.OUTCOME_PARSE],
    [api.OUTCOME_SHAPE],
    [api.OUTCOME_LOGIN],
    [api.OUTCOME_UNKNOWN],
    [api.OUTCOME_CANCEL],
    [api.OUTCOME_CANCEL] * 7,
    [api.OUTCOME_OK, api.OUTCOME_EMPTY],
    [api.OUTCOME_EMPTY, api.OUTCOME_OK],
    [api.OUTCOME_OK, api.OUTCOME_OK, api.OUTCOME_TIMEOUT],
    [api.OUTCOME_OK, api.OUTCOME_TIMEOUT, api.OUTCOME_TIMEOUT,
     api.OUTCOME_TIMEOUT],
    [api.OUTCOME_OK] * 2 + [api.OUTCOME_TIMEOUT] * 3,
    [api.OUTCOME_EMPTY, api.OUTCOME_EMPTY, api.OUTCOME_EMPTY,
     api.OUTCOME_TIMEOUT],
    [api.OUTCOME_EMPTY, api.OUTCOME_TIMEOUT, api.OUTCOME_TIMEOUT,
     api.OUTCOME_TIMEOUT],
    [api.OUTCOME_OK, api.OUTCOME_EMPTY, api.OUTCOME_EMPTY,
     api.OUTCOME_EMPTY, api.OUTCOME_EMPTY],
    [api.OUTCOME_CANCEL, api.OUTCOME_OK],
    [api.OUTCOME_OK, api.OUTCOME_CANCEL, api.OUTCOME_EMPTY],
    ["", api.OUTCOME_OK, ""],
    [api.OUTCOME_SLOW, api.OUTCOME_SLOW, api.OUTCOME_EMPTY,
     api.OUTCOME_EMPTY, api.OUTCOME_EMPTY],
]

ALL_OUTCOMES = [
    api.OUTCOME_OK, api.OUTCOME_EMPTY, api.OUTCOME_SLOW, api.OUTCOME_TIMEOUT,
    api.OUTCOME_NET, api.OUTCOME_403, api.OUTCOME_429, api.OUTCOME_5XX,
    api.OUTCOME_4XX, api.OUTCOME_CANCEL, api.OUTCOME_PARSE, api.OUTCOME_451,
    api.OUTCOME_BLOCKED, api.OUTCOME_SHAPE, api.OUTCOME_LOGIN,
    api.OUTCOME_UNKNOWN,
]

PAIRS = [list(p) for p in itertools.permutations(ALL_OUTCOMES[:6], 2)]


def main() -> int:
    cases = {
        "_scope": (
            "classify 的每个分支都会被 43 条错误文本覆盖到；"
            "state_of / window_empty 用 35 组窗口 + 前 6 种 outcome 的全排列两两组合。"
        ),
        "classify": [
            {"ok": ok, "count": count, "err": err, "ms": ms,
             "outcome": api.classify(ok, count, err, ms)[0],
             "code": api.classify(ok, count, err, ms)[1]}
            for ok, count, err, ms in CLASSIFY
        ],
        "outcome_text": [
            {"outcome": o, "code": c, "text": api.outcome_text(o, c)}
            for o, c in OUTCOME_TEXT
        ],
        "state_of": [
            {"in": seq, "state": api._state_of(list(seq)),
             "empty_window": api._window_empty(list(seq))}
            for seq in STATE_INPUTS
        ],
        "state_of_pairs": [
            {"in": pair, "state": api._state_of(list(pair)),
             "empty_window": api._window_empty(list(pair))}
            for pair in PAIRS
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    for name, rows in cases.items():
        if isinstance(rows, list):
            print("  %-16s %d 条" % (name, len(rows)))
    assert all(v for k, v in cases.items() if isinstance(v, list)), "有分组为空"
    return 0


if __name__ == "__main__":
    sys.exit(main())
