import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import api as api_mod
from app import sources

BLOCKED = sources.BLOCKED_TEXT
LOGIN_TEXT = sources.JAVDB_LOGIN_TEXT
SLOW_MS = api_mod.SLOW_MS

OK_PIN = ("ok", 0, "ok", "")
SLOW_PIN = ("slow", 0, "ok", "")
EMPTY_PIN = ("empty", 0, "empty", "无结果")
CANCEL_PIN = ("cancel", 0, "na", "")
BLOCKED_PIN = ("blocked", 0, "err", BLOCKED)
LOGIN_PIN = ("login", 0, "warn", LOGIN_TEXT)
SHAPE_PIN = ("shape", 0, "warn", "结果页结构不符")
TIMEOUT_PIN = ("timeout", 0, "err", "超时")
NET_PIN = ("net", 0, "err", "无法连接")
PARSE_PIN = ("parse", 0, "warn", "解析失败")
UNKNOWN_PIN = ("unknown", 0, "warn", "请求失败")

HTTP451_PIN = ("http451", 451, "err", "451 地区受限")
HTTP429_PIN = ("http429", 429, "warn", "429 限流")
HTTP403_401_PIN = ("http403", 401, "err", "403 拒绝")
HTTP403_403_PIN = ("http403", 403, "err", "403 拒绝")
HTTP4XX_404_PIN = ("http4xx", 404, "warn", "请求被拒")
HTTP4XX_422_PIN = ("http4xx", 422, "warn", "请求被拒")
HTTP4XX_444_PIN = ("http4xx", 444, "warn", "请求被拒")
HTTP4XX_499_PIN = ("http4xx", 499, "warn", "请求被拒")
HTTP5XX_500_PIN = ("http5xx", 500, "err", "服务异常")
HTTP5XX_502_PIN = ("http5xx", 502, "err", "服务异常")
HTTP5XX_503_PIN = ("http5xx", 503, "err", "服务异常")
HTTP5XX_999_PIN = ("http5xx", 999, "err", "服务异常")


def pin(ok, count, err, ms):
    outcome, code = api_mod.classify(ok, count, err, ms)
    return (outcome, code, api_mod.OUTCOME_STATE[outcome], api_mod.OUTCOME_TEXT[outcome])


SUCCESS_PINS = (
    (True, 7, "", 120, OK_PIN),
    (True, 7, "", 0, OK_PIN),
    (True, 7, "", 999, OK_PIN),
    (True, 7, "", SLOW_MS - 1, OK_PIN),
    (True, 1, "", SLOW_MS, SLOW_PIN),
    (True, 7, "", SLOW_MS, SLOW_PIN),
    (True, 7, "", SLOW_MS + 1, SLOW_PIN),
    (True, 7, "", 9999999, SLOW_PIN),
    (True, 0, "", 120, EMPTY_PIN),
    (True, 0, "", 0, EMPTY_PIN),
    (True, 0, "", 9999999, EMPTY_PIN),
)

CANCEL_PINS = (
    (False, 0, "已停止", 10, CANCEL_PIN),
    (False, 0, "用户已停止搜索", 10, CANCEL_PIN),
    (False, 0, "SearchCancelled: 已停止", 10, CANCEL_PIN),
    (False, 0, "搜索已停止，代理还在排队", 10, CANCEL_PIN),
    (False, 0, "cancelled", 10, CANCEL_PIN),
    (False, 0, "CANCELLED", 10, CANCEL_PIN),
    (False, 0, "CancelledError: task was CancelLED", 10, CANCEL_PIN),
)

BLOCKED_PINS = (
    (False, 0, BLOCKED, 10, BLOCKED_PIN),
    (False, 0, f"Blocked: {BLOCKED}", 10, BLOCKED_PIN),
    (False, 0, f"Blocked: {BLOCKED}（Cloudflare 5 秒盾）", 10, BLOCKED_PIN),
    (False, 0, f"源站点返回 {BLOCKED}，稍后重试", 10, BLOCKED_PIN),
)

LOGIN_PINS = (
    (False, 0, LOGIN_TEXT, 10, LOGIN_PIN),
    (False, 0, f"Blocked: {LOGIN_TEXT}", 10, LOGIN_PIN),
    (False, 0, f"源站点返回 {LOGIN_TEXT}，先登录再试", 10, LOGIN_PIN),
)

SHAPE_PINS = (
    (False, 0, "ShapeError: knaben 返回的不是对象", 10, SHAPE_PIN),
    (False, 0, "shapeerror: 响应不是列表", 10, SHAPE_PIN),
    (False, 0, "SHAPEERROR: x", 10, SHAPE_PIN),
    (False, 0, "ShapeError: knaben 响应缺少 hits 列表", 10, SHAPE_PIN),
)

HTTP_CODE_PINS = (
    (False, 0, "HTTP 451", 10, HTTP451_PIN),
    (False, 0, "HTTP Error 451: Unavailable For Legal Reasons", 10, HTTP451_PIN),
    (False, 0, "状态码451", 10, HTTP451_PIN),
    (False, 0, "状态码 451 被地区封锁", 10, HTTP451_PIN),
    (False, 0, "HTTP 401", 10, HTTP403_401_PIN),
    (False, 0, "HTTP Error 401, unauthorized", 10, HTTP403_401_PIN),
    (False, 0, "HTTP 403", 10, HTTP403_403_PIN),
    (False, 0, "HTTP Error 403: Forbidden", 10, HTTP403_403_PIN),
    (False, 0, "状态码 403", 10, HTTP403_403_PIN),
    (False, 0, "HTTP 429", 10, HTTP429_PIN),
    (False, 0, "HTTP Error 429: Too Many Requests", 10, HTTP429_PIN),
    (False, 0, "HTTP 404", 10, HTTP4XX_404_PIN),
    (False, 0, "HTTP 422", 10, HTTP4XX_422_PIN),
    (False, 0, "HTTP 499", 10, HTTP4XX_499_PIN),
    (False, 0, "HTTP 500", 10, HTTP5XX_500_PIN),
    (False, 0, "HTTP 503", 10, HTTP5XX_503_PIN),
    (False, 0, "HTTP Error 503: Service Unavailable", 10, HTTP5XX_503_PIN),
    (False, 0, "HTTP 999", 10, HTTP5XX_999_PIN),
)

HTTP_CODE_EDGE_PINS = (
    (False, 0, "HTTP 4444", 10, HTTP4XX_444_PIN),
    (False, 0, "HTTP 40", 10, UNKNOWN_PIN),
    (False, 0, "HTTP Error 4: x", 10, UNKNOWN_PIN),
    (False, 0, "HTTP Error 302: Found", 10, UNKNOWN_PIN),
    (False, 0, "HTTP 200", 10, UNKNOWN_PIN),
    (False, 0, "HTTP 100", 10, UNKNOWN_PIN),
)

HTTP_PROSE_DIGIT_PINS = (
    (False, 0, "RuntimeError: 解析到第 451 行失败", 10, UNKNOWN_PIN),
    (False, 0, "ValueError: 重试了 500 次仍失败", 10, PARSE_PIN),
)

PROXY_PINS = (
    (False, 0, "系统代理 127.0.0.1:7890 连不上", 10, NET_PIN),
    (False, 0, "代理不可达", 10, NET_PIN),
    (False, 0, "proxy", 10, NET_PIN),
    (False, 0, "PROXY", 10, NET_PIN),
    (False, 0, "ProxyError: cannot connect to proxy", 10, NET_PIN),
    (False, 0, "tunnel", 10, NET_PIN),
    (False, 0, "Tunnel refused", 10, NET_PIN),
    (False, 0, "proxy 返回 451", 10, NET_PIN),
)

NET_PINS = (
    (False, 0, sources.NET_FAIL_TEXT, 10, NET_PIN,
     "自己造的网络请求失败已并入 _NET_SIGNS：红点不再降级成黄点"),
    (False, 0, "URLError: <urlopen error unknown>", 10, NET_PIN),
    (False, 0, "10061", 10, NET_PIN),
    (False, 0, "[Errno 10061]", 10, NET_PIN),
    (False, 0, "ConnectionRefusedError: [WinError 10061] 由于连接方在一段时间后没有正确答复"
               "或连接的主机没有反应，连接尝试失败。", 10, NET_PIN),
    (False, 0, "ConnectionRefusedError: 目标计算机积极拒绝，无法连接。", 10, NET_PIN),
    (False, 0, "ConnectionResetError: [WinError 10054] 远程主机强迫关闭了一个现有的连接。",
     10, NET_PIN),
    (False, 0, "远程主机强迫关闭了一个现有的连接", 10, NET_PIN),
    (False, 0, "[WinError 10054]", 10, NET_PIN),
    (False, 0, "[WinError 10051]", 10, NET_PIN),
    (False, 0, "连接被拒绝", 10, NET_PIN),
    (False, 0, "由于连接方在一段时间后没有正确答复", 10, NET_PIN),
    (False, 0, "远程计算机或网络连接主机会拒绝连接", 10, NET_PIN),
    (False, 0, "SSLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", 10,
     NET_PIN),
    (False, 0, "URLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", 10,
     NET_PIN),
    (False, 0, "SSLError: [SSL: TLSV1_ALERT_PROTOCOL_VERSION] tlsv1 alert", 10, NET_PIN),
    (False, 0, "URLError: [Errno 1] _ssl.c:1028: error:1409442E:SSL routines:ssl3_read_bytes:"
               "EOF occurred in violation of protocol", 10, NET_PIN),
    (False, 0, "URLError: <urlopen error [Errno 11001] getaddrinfo failed>", 10, NET_PIN),
    (False, 0, "gaierror: [Errno 11001] getaddrinfo failed", 10, NET_PIN),
    (False, 0, "URLError: <urlopen error [Errno -2] Name or service not known>", 10, NET_PIN),
    (False, 0, "gaierror: <urlopen error nodename nor servname provided", 10, NET_PIN),
    (False, 0, "ConnectionRefusedError: connection refused", 10, NET_PIN),
    (False, 0, "ConnectionResetError: connection reset by peer", 10, NET_PIN),
    (False, 0, "RemoteDisconnected: connection aborted", 10, NET_PIN),
    (False, 0, "OSError: Network is unreachable", 10, NET_PIN),
    (False, 0, "OSError: [Errno 113] No route to host", 10, NET_PIN),
)

TIMEOUT_PINS = (
    (False, 0, "URLError: timed out", 10, TIMEOUT_PIN),
    (False, 0, "socket.timeout: timed out", 10, TIMEOUT_PIN),
    (False, 0, "TimeoutError: The read operation timed out", 10, TIMEOUT_PIN),
    (False, 0, "<urlopen error timed out>", 10, TIMEOUT_PIN),
    (False, 0, "请求超时", 10, TIMEOUT_PIN),
    (False, 0, "TimeoutError", 10, TIMEOUT_PIN),
    (False, 0, "timeout", 10, TIMEOUT_PIN),
    (False, 0, "TIMEOUT", 10, TIMEOUT_PIN),
    (False, 0, "20s timeout", 10, TIMEOUT_PIN),
    (False, 0, sources.NET_TIMEOUT_TEXT, 10, TIMEOUT_PIN),
    (False, 0, "TUN 模式已接管网络，这些源仍超时：可能被墙或站点故障。", 10, TIMEOUT_PIN),
)

PARSE_PINS = (
    (False, 0, "JSONDecodeError: Expecting value: line 1 column 1 (char 0)", 10, PARSE_PIN),
    (False, 0, "Expecting value: line 1", 10, PARSE_PIN),
    (False, 0, "'NoneType' object is not subscriptable", 10, PARSE_PIN),
    (False, 0, "KeyError: 'x'", 10, PARSE_PIN),
    (False, 0, "'list' object has no attribute 'map'", 10, PARSE_PIN),
    (False, 0, "AttributeError: 'NoneType' object has no attribute 'get'", 10, PARSE_PIN),
    (False, 0, "TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'", 10,
     PARSE_PIN),
    (False, 0, "IndexError: list index out of range", 10, PARSE_PIN),
    (False, 0, "TypeError: cannot unpack non-iterable NoneType", 10, PARSE_PIN),
    (False, 0, "JSONDecodeError: Unexpected token < in JSON at position 0", 10, PARSE_PIN),
    (False, 0, "ValueError: 无法解析 RSS", 10, PARSE_PIN),
)

UNKNOWN_PINS = (
    (False, 0, " huh", 10, UNKNOWN_PIN),
    (False, 0, "", 10, UNKNOWN_PIN),
    (False, 0, None, 10, UNKNOWN_PIN),
    (False, 0, "RuntimeError: boom", 10, UNKNOWN_PIN),
    (False, 0, "OSError: 目录已满", 10, UNKNOWN_PIN),
)

ORDER_DEPENDENT_PINS = (
    (True, 3, "URLError: <urlopen error timed out>", 10, OK_PIN,
     "ok=True 时 err 全程不参与判断：源自己报了超时却仍返回条目，就只记 ok"),
    (True, 3, "HTTP 503", 10, OK_PIN,
     "ok=True 时状态码也不看：判序是 count → ms → err"),
    (True, 0, "HTTP 503", 10, EMPTY_PIN,
     "count 检查排在 err 检查之前：0 条时错误文本被吞成无结果"),
    (True, 0, "已停止", 10, EMPTY_PIN,
     "取消也救不回来：ok=True + 0 条仍是 empty，不是 cancel"),
    (False, 0, f"{BLOCKED} 已停止", 10, CANCEL_PIN,
     "取消排在封锁之前：两条都命中时记灰点而不是红点"),
    (False, 0, f"ShapeError: {BLOCKED}", 10, BLOCKED_PIN,
     "封锁排在形状之前：形状串里带拦截文案就改判 blocked"),
    (False, 0, f"HTTP 403 {BLOCKED}", 10, BLOCKED_PIN,
     "封锁排在 HTTP 码之前：403 被吞，只剩人机验证文案"),
    (False, 0, f"HTTP Error 451: {BLOCKED}", 10, BLOCKED_PIN,
     "封锁排在 451 之前：地区受限的红点被人机验证的红点顶掉"),
    (False, 0, "ShapeError: 状态码 500", 10, SHAPE_PIN,
     "形状排在 HTTP 码之前：镜像把 5xx 页判成结构不符时不走 http5xx"),
    (False, 0, "ShapeError: 页面超时后结构变了", 10, SHAPE_PIN,
     "形状排在超时之前：warn 而非 err，不参与降级"),
    (False, 0, "Tunnel 502 Bad Gateway", 10, NET_PIN,
     "502 前面没有 HTTP 或状态码前缀，_HTTP_CODE_RE 抓不到，代理分支接住"),
    (False, 0, "URLError: <urlopen error Tunnel connection failed: 502 Bad Gateway>", 10,
     NET_PIN,
     "代理层 502 仍是 net：降级解决不了代理故障"),
    (False, 0, "HTTP 502 Tunnel connection failed", 10, HTTP5XX_502_PIN,
     "同样的代理故障，文本一带 HTTP 前缀就改判 5xx：状态码检查排在代理符号之前"),
    (False, 0, "ProxyError: The read operation timed out", 10, TIMEOUT_PIN,
     "超时检查排在代理符号之前：代理超时算 timeout，不再叫无法连接"),
    (False, 0, "URLError: timed out", 10, TIMEOUT_PIN,
     "超时排在网络符号之前：类名是 URLError 也判 timeout"),
    (False, 0, "TimeoutError: [WinError 10060] 尝试的操作超时", 10, TIMEOUT_PIN,
     "10060 在 _NET_SIGNS 里，但中文「超时」先命中 timeout 分支"),
    (False, 0, "HTTP 403 SSLError: handshake", 10, HTTP403_403_PIN,
     "状态码排在网络符号之前：同行里的 SSLError 不参与判断"),
    (False, 0, "HTTP 500 JSONDecodeError", 10, HTTP5XX_500_PIN,
     "状态码排在解析符号之前：源站 5xx 吐出坏 JSON 仍记服务异常"),
    (False, 0, "AttributeError: 'NoneType' object has no attribute 'proxy'", 10, NET_PIN,
     "代理符号排在解析符号之前：属性名里的 proxy 把解析错判成无法连接"),
    (False, 0, "JSONDecodeError: 页面超时后返回了 HTML", 10, TIMEOUT_PIN,
     "超时排在解析符号之前：改版文案里的「超时」二字先命中"),
    (False, 0, "URLError: 远程主机强迫关闭，随后 JSONDecodeError", 10, NET_PIN,
     "网络符号排在解析符号之前：两种原因同时出现时只留 net"),
)

SEMANTIC_LEAK_PINS = (
    (False, 0, "返回 0 条", 10, UNKNOWN_PIN,
     "有语义的文案认不出来，与真故障同为 unknown"),
    (False, 0, "HTTP451", 10, UNKNOWN_PIN,
     "_HTTP_CODE_RE 的 HTTP 前缀要求一个空白，少个空格就丢码"),
    (False, 0, "Http 451", 10, UNKNOWN_PIN,
     "_HTTP_CODE_RE 没有 IGNORECASE，大小写一变就丢码"),
    (False, 0, "status 451", 10, UNKNOWN_PIN,
     "状态码前缀只认 HTTP 两种写法，英文别的说法不认"),
    (False, 0, "状态码：451", 10, UNKNOWN_PIN,
     "状态码后跟的是全角冒号，正则里的空白字符吃不下"),
    (False, 0, "ProxyError", 10, UNKNOWN_PIN,
     "代理符号要整词边界：ProxyError 里嵌的 proxy 命中不了 _PROXY_SIGN_RE"),
    (False, 0, "Blocked", 10, UNKNOWN_PIN,
     "封锁只认 BLOCKED_TEXT 中文原文，异常类名本身不是信号"),
    (False, 0, "BlockedError: 站点弹出验证页", 10, UNKNOWN_PIN,
     "换了说法的验证拦截认不出，红点降级成黄点"),
    (False, 0, "人机验证", 10, UNKNOWN_PIN,
     "封锁判定是整串子串匹配，缺后两个字就不算"),
    (False, 0, "Shape Error", 10, UNKNOWN_PIN,
     "形状信号是连写的 shapeerror，中间加空格即失效"),
    (False, 0, "用户取消了搜索", 10, UNKNOWN_PIN,
     "取消信号只有已停止与 cancelled，换近义词即失效"),
    (False, 0, "TooManyRequests", 10, UNKNOWN_PIN,
     "限流只靠状态码 429，文案里的名字不顶用"),
    (False, 0, "piratebayproxy 页面解析不了", 10, UNKNOWN_PIN,
     "代理符号要整词边界：TPB 镜像域名里嵌的 proxy 不算代理信号"),
    (False, 0, "无法解析", 10, UNKNOWN_PIN,
     "中文解析文案不在符号表里，只有异常类名算解析"),
)

DISPLAY_PINS = (
    ("ok", 0, ""),
    ("slow", 0, ""),
    ("empty", 0, "无结果"),
    ("cancel", 0, ""),
    ("timeout", 0, "超时"),
    ("net", 0, "无法连接"),
    ("parse", 0, "解析失败"),
    ("shape", 0, "结果页结构不符"),
    ("unknown", 0, "请求失败"),
    ("blocked", 0, BLOCKED),
    ("http451", 451, "451 地区受限"),
    ("http429", 429, "429 限流"),
    ("http403", 0, "403 拒绝"),
    ("http403", 401, "HTTP 401 拒绝"),
    ("http403", 403, "HTTP 403 拒绝"),
    ("http4xx", 0, "请求被拒"),
    ("http4xx", 404, "HTTP 404"),
    ("http5xx", 0, "服务异常"),
    ("http5xx", 503, "HTTP 503"),
)

ALL_PINS = (SUCCESS_PINS + CANCEL_PINS + BLOCKED_PINS + LOGIN_PINS + SHAPE_PINS
            + HTTP_CODE_PINS
            + HTTP_CODE_EDGE_PINS + HTTP_PROSE_DIGIT_PINS + PROXY_PINS + NET_PINS
            + TIMEOUT_PINS + PARSE_PINS + UNKNOWN_PINS + ORDER_DEPENDENT_PINS
            + SEMANTIC_LEAK_PINS)

PINNED_CODES = (401, 403, 404, 422, 429, 444, 451, 499, 500, 502, 503, 999)


class PinCase(unittest.TestCase):

    def verify(self, rows):
        for row in rows:
            ok, count, err, ms, expected = row[:5]
            note = row[5] if len(row) > 5 else ""
            with self.subTest(ok=ok, count=count, err=err, ms=ms):
                self.assertEqual(pin(ok, count, err, ms), expected, note)


class OutcomeContractTableTest(unittest.TestCase):

    def test_slow_threshold_is_five_seconds(self):
        self.assertEqual(SLOW_MS, 5000)

    def test_outcome_identifiers_are_stable(self):
        self.assertEqual(
            (api_mod.OUTCOME_OK, api_mod.OUTCOME_EMPTY, api_mod.OUTCOME_SLOW,
             api_mod.OUTCOME_TIMEOUT, api_mod.OUTCOME_NET, api_mod.OUTCOME_403,
             api_mod.OUTCOME_429, api_mod.OUTCOME_5XX, api_mod.OUTCOME_4XX,
             api_mod.OUTCOME_CANCEL, api_mod.OUTCOME_PARSE, api_mod.OUTCOME_451,
             api_mod.OUTCOME_BLOCKED, api_mod.OUTCOME_SHAPE,
             api_mod.OUTCOME_LOGIN, api_mod.OUTCOME_UNKNOWN),
            ("ok", "empty", "slow", "timeout", "net", "http403", "http429", "http5xx",
             "http4xx", "cancel", "parse", "http451", "blocked", "shape", "login",
             "unknown"))

    def test_outcome_state_table(self):
        self.assertEqual(dict(api_mod.OUTCOME_STATE), {
            "ok": "ok", "empty": "empty", "slow": "ok", "timeout": "err", "net": "err",
            "http403": "err", "http429": "warn", "http5xx": "err", "http4xx": "warn",
            "cancel": "na", "parse": "warn", "http451": "err", "blocked": "err",
            "shape": "warn", "login": "warn", "unknown": "warn"})

    def test_outcome_text_table(self):
        self.assertEqual(dict(api_mod.OUTCOME_TEXT), {
            "ok": "", "empty": "无结果", "slow": "", "timeout": "超时", "net": "无法连接",
            "http403": "403 拒绝", "http429": "429 限流", "http5xx": "服务异常",
            "http4xx": "请求被拒", "cancel": "", "parse": "解析失败",
            "http451": "451 地区受限", "blocked": BLOCKED,
            "shape": "结果页结构不符", "login": LOGIN_TEXT,
            "unknown": "请求失败"})

    def test_blocked_text_reuses_sources_constant(self):
        self.assertEqual(api_mod.OUTCOME_TEXT[api_mod.OUTCOME_BLOCKED], sources.BLOCKED_TEXT)

    def test_fatal_outcomes_drive_demotion(self):
        self.assertEqual(set(api_mod.FATAL_OUTCOMES),
                         {"timeout", "net", "http403", "http5xx", "blocked"})

    def test_sign_table_sizes(self):
        self.assertEqual(len(api_mod._NET_SIGNS), 24)
        self.assertEqual(len(api_mod._PARSE_SIGNS), 12)

    def test_sign_tables_are_lowercase_because_matching_is_lowercase(self):
        self.assertEqual([s for s in api_mod._NET_SIGNS if s != s.lower()], [],
                         "classify 拿 lower 之后的文本比对，大写符号永远命中不了")
        self.assertEqual([s for s in api_mod._PARSE_SIGNS if s != s.lower()], [],
                         "classify 拿 lower 之后的文本比对，大写符号永远命中不了")


class SuccessfulSearchBranchTest(PinCase):

    def test_result_count_and_latency_split_ok_slow_empty(self):
        self.verify(SUCCESS_PINS)


class CancelledBranchTest(PinCase):

    def test_cancelled_texts_pin_cancel(self):
        self.verify(CANCEL_PINS)


class BlockedBranchTest(PinCase):

    def test_blocked_text_pins_blocked(self):
        self.verify(BLOCKED_PINS)


class LoginBranchTest(PinCase):

    def test_login_wall_pins_login_and_not_blocked(self):
        self.verify(LOGIN_PINS)
        for row in LOGIN_PINS:
            outcome = pin(*row[:4])[0]
            self.assertNotEqual(
                outcome, api_mod.OUTCOME_BLOCKED,
                "登入墙不是人机验证：报成「人机验证拦截」会让用户去刷新重试，"
                "而正确的做法是知道该站要登录才给磁力")


class ShapeBranchTest(PinCase):

    def test_shape_error_text_is_case_insensitive(self):
        self.verify(SHAPE_PINS)


class HttpStatusCodeBranchTest(PinCase):

    def test_every_http_prefix_form_is_read(self):
        self.verify(HTTP_CODE_PINS)

    def test_status_numbers_outside_4xx_and_5xx_fall_through(self):
        self.verify(HTTP_CODE_EDGE_PINS)

    def test_bare_three_digit_numbers_are_not_status_codes(self):
        self.verify(HTTP_PROSE_DIGIT_PINS)


class ProxySignalBranchTest(PinCase):

    def test_proxy_and_tunnel_tokens_pin_net(self):
        self.verify(PROXY_PINS)


class NetworkSignalBranchTest(PinCase):

    def test_os_socket_and_ssl_texts_pin_net(self):
        self.verify(NET_PINS)

    def test_every_network_sign_in_the_table_pins_net(self):
        self.verify(tuple((False, 0, sign, 10, NET_PIN) for sign in api_mod._NET_SIGNS))


class TimeoutBranchTest(PinCase):

    def test_timeout_texts_pin_timeout(self):
        self.verify(TIMEOUT_PINS)


class ParseSignalBranchTest(PinCase):

    def test_python_exception_texts_pin_parse(self):
        self.verify(PARSE_PINS)

    def test_every_parse_sign_in_the_table_pins_parse(self):
        self.verify(tuple((False, 0, sign, 10, PARSE_PIN) for sign in api_mod._PARSE_SIGNS))


class UnknownBranchTest(PinCase):

    def test_unrecognized_texts_pin_unknown(self):
        self.verify(UNKNOWN_PINS)


class OrderDependentPrecedenceTest(PinCase):

    def test_branch_order_decides_conflicting_texts(self):
        self.verify(ORDER_DEPENDENT_PINS)


class SurprisingSemanticLeakTest(PinCase):

    def test_meaningful_texts_that_currently_land_in_unknown(self):
        self.verify(SEMANTIC_LEAK_PINS)

    def test_semantic_leaks_are_all_unrecognized_today(self):
        for row in SEMANTIC_LEAK_PINS:
            with self.subTest(err=row[2]):
                self.assertEqual(row[4], UNKNOWN_PIN,
                                 "这一组记的是文本匹配的漏洞面，认得出来就该挪走")


class OutcomeDisplayTextTest(unittest.TestCase):

    def test_outcome_text_assembly(self):
        for outcome, code, expected in DISPLAY_PINS:
            with self.subTest(outcome=outcome, code=code):
                self.assertEqual(api_mod.outcome_text(outcome, code), expected)


class PinCoverageTest(unittest.TestCase):

    def test_every_outcome_id_is_pinned(self):
        self.assertEqual({row[4][0] for row in ALL_PINS}, set(api_mod.OUTCOME_STATE),
                         "有 outcome 分支没被定着，重构时它就没人看守")

    def test_every_pinned_outcome_is_a_known_id(self):
        self.assertTrue({row[4][0] for row in ALL_PINS} <= set(api_mod.OUTCOME_STATE))

    def test_every_status_code_dim_is_pinned(self):
        pinned = {row[4][1] for row in ALL_PINS if row[4][1]}
        self.assertEqual(pinned, set(PINNED_CODES),
                         "状态码这一维漏了就是分类结果被悄悄改掉")


if __name__ == "__main__":
    unittest.main()
