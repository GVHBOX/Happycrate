use crate::util::{find_ci, is_nd_digit, is_py_space};

pub const OK: &str = "ok";
pub const EMPTY: &str = "empty";
pub const SLOW: &str = "slow";
pub const TIMEOUT: &str = "timeout";
pub const NET: &str = "net";
pub const CODE_403: &str = "http403";
pub const CODE_429: &str = "http429";
pub const CODE_5XX: &str = "http5xx";
pub const CODE_4XX: &str = "http4xx";
pub const CANCEL: &str = "cancel";
pub const PARSE: &str = "parse";
pub const CODE_451: &str = "http451";
pub const BLOCKED: &str = "blocked";
pub const SHAPE: &str = "shape";
pub const LOGIN: &str = "login";
pub const UNKNOWN: &str = "unknown";

pub const HEALTH_WINDOW: usize = 5;
pub const BAD_MIN: usize = 3;
pub const SLOW_MS: i64 = 5000;

pub const BLOCKED_TEXT: &str = "人机验证拦截";
pub const CANCEL_TEXT: &str = "已停止";
pub const SHAPE_MARK: &str = "ShapeError";
pub const LOGIN_TEXT: &str = "部分影片需登入 JavDB 查看";
pub const NET_FAIL_TEXT: &str = "网络请求失败";
pub const NET_TIMEOUT_TEXT: &str = "网络请求超时";

const FATAL: [&str; 5] = [TIMEOUT, NET, CODE_403, CODE_5XX, BLOCKED];

const PARSE_SIGNS: [&str; 12] = [
    "jsondecodeerror",
    "expecting value",
    "unexpected token",
    "valueerror",
    "keyerror",
    "indexerror",
    "attributeerror",
    "typeerror",
    "not subscriptable",
    "has no attribute",
    "cannot unpack",
    "unsupported operand",
];

const NET_SIGNS: [&str; 24] = [
    "网络请求失败",
    "urlerror",
    "gaierror",
    "getaddrinfo",
    "name or service not known",
    "nodename nor servname",
    "connection refused",
    "connection reset",
    "connection aborted",
    "network is unreachable",
    "no route to host",
    "10061",
    "10060",
    "10054",
    "10051",
    "目标计算机积极拒绝",
    "由于连接方",
    "远程主机",
    "远程计算机",
    "连接被拒绝",
    "sslerror",
    "certificate verify",
    "tlsv1",
    "eof occurred",
];

pub fn outcome_state(outcome: &str) -> &'static str {
    match outcome {
        OK | SLOW => "ok",
        EMPTY => "empty",
        TIMEOUT | NET | CODE_403 | CODE_5XX | CODE_451 | BLOCKED => "err",
        CODE_429 | CODE_4XX | PARSE | SHAPE | LOGIN | UNKNOWN => "warn",
        CANCEL => "na",
        _ => "na",
    }
}

pub fn outcome_text(outcome: &str, code: u16) -> String {
    if outcome == CODE_403 && code != 0 {
        return format!("HTTP {code} 拒绝");
    }
    if (outcome == CODE_5XX || outcome == CODE_4XX) && code != 0 {
        return format!("HTTP {code}");
    }
    match outcome {
        EMPTY => "无结果".to_string(),
        TIMEOUT => "超时".to_string(),
        NET => "无法连接".to_string(),
        CODE_403 => "403 拒绝".to_string(),
        CODE_429 => "429 限流".to_string(),
        CODE_5XX => "服务异常".to_string(),
        CODE_4XX => "请求被拒".to_string(),
        PARSE => "解析失败".to_string(),
        CODE_451 => "451 地区受限".to_string(),
        BLOCKED => BLOCKED_TEXT.to_string(),
        SHAPE => "结果页结构不符".to_string(),
        LOGIN => LOGIN_TEXT.to_string(),
        UNKNOWN => "请求失败".to_string(),
        _ => String::new(),
    }
}

fn word_char(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

fn find_word(chars: &[char], word: &str) -> bool {
    let needle: Vec<char> = word.chars().collect();
    let mut from = 0usize;
    while let Some(i) = find_ci(chars, &needle, from) {
        let before = i == 0 || !word_char(chars[i - 1]);
        let after = i + needle.len() >= chars.len() || !word_char(chars[i + needle.len()]);
        if before && after {
            return true;
        }
        from = i + 1;
    }
    false
}

fn proxy_sign(text: &str) -> bool {
    if text.contains("系统代理") || text.contains("代理不可达") {
        return true;
    }
    let chars: Vec<char> = text.chars().collect();
    find_word(&chars, "proxy") || find_word(&chars, "tunnel")
}

fn digits_at(chars: &[char], from: usize, want: usize) -> bool {
    chars.len() >= from + want && chars[from..from + want].iter().all(|c| is_nd_digit(*c))
}

fn taken_digits(chars: &[char], from: usize, want: usize) -> Option<String> {
    if digits_at(chars, from, want) {
        Some(chars[from..from + want].iter().collect())
    } else {
        None
    }
}

fn http_code(err: &str) -> u16 {
    if err.is_empty() {
        return 0;
    }
    let chars: Vec<char> = err.chars().collect();
    for i in 0..chars.len() {
        if chars.len() >= i + 4 {
            let head: String = chars[i..i + 4].iter().collect();
            if head == "HTTP" {
                let mut j = i + 4;
                let ws = j;
                while j < chars.len() && is_py_space(chars[j]) {
                    j += 1;
                }
                if j == ws {
                    continue;
                }
                if chars.len() >= j + 5 && chars[j..j + 5].iter().collect::<String>() == "Error" {
                    let mut k = j + 5;
                    let ws2 = k;
                    while k < chars.len() && is_py_space(chars[k]) {
                        k += 1;
                    }
                    if k > ws2 {
                        if let Some(text) = taken_digits(&chars, k, 3) {
                            return text.parse().unwrap_or(0);
                        }
                    }
                }
                if let Some(text) = taken_digits(&chars, j, 3) {
                    return text.parse().unwrap_or(0);
                }
            }
        }
        if chars.len() >= i + 3 {
            let head: String = chars[i..i + 3].iter().collect();
            if head == "状态码" {
                let mut j = i + 3;
                while j < chars.len() && is_py_space(chars[j]) {
                    j += 1;
                }
                if let Some(text) = taken_digits(&chars, j, 3) {
                    return text.parse().unwrap_or(0);
                }
            }
        }
    }
    0
}

pub fn is_timeout_text(err: &str) -> bool {
    let low = err.to_lowercase();
    low.contains("timed out") || low.contains("timeout") || err.contains("超时")
}

pub fn classify(ok: bool, count: i64, err: &str, ms: i64) -> (&'static str, u16) {
    if ok {
        if count == 0 {
            return (EMPTY, 0);
        }
        if ms != 0 && ms >= SLOW_MS {
            return (SLOW, 0);
        }
        return (OK, 0);
    }

    let low = err.to_lowercase();
    if err.contains(CANCEL_TEXT) || low.contains("cancelled") {
        return (CANCEL, 0);
    }
    if err.contains(LOGIN_TEXT) {
        return (LOGIN, 0);
    }
    if err.contains(BLOCKED_TEXT) {
        return (BLOCKED, 0);
    }
    if low.contains(&SHAPE_MARK.to_lowercase()) {
        return (SHAPE, 0);
    }

    let code = http_code(err);
    if code == 451 {
        return (CODE_451, code);
    }
    if code == 401 || code == 403 {
        return (CODE_403, code);
    }
    if code == 429 {
        return (CODE_429, code);
    }
    if (400..500).contains(&code) {
        return (CODE_4XX, code);
    }
    if code >= 500 {
        return (CODE_5XX, code);
    }
    if is_timeout_text(err) {
        return (TIMEOUT, 0);
    }
    if proxy_sign(err) {
        return (NET, 0);
    }
    for sign in NET_SIGNS {
        if sign.is_empty() {
            continue;
        }
        if low.contains(sign) {
            return (NET, 0);
        }
    }
    for sign in PARSE_SIGNS {
        if low.contains(sign) {
            return (PARSE, 0);
        }
    }
    (UNKNOWN, 0)
}

fn recent_of(outcomes: &[String]) -> Vec<String> {
    let filtered: Vec<String> = outcomes
        .iter()
        .filter(|o| !o.is_empty() && o.as_str() != CANCEL)
        .cloned()
        .collect();
    let start = filtered.len().saturating_sub(HEALTH_WINDOW);
    filtered[start..].to_vec()
}

pub fn window_empty(outcomes: &[String]) -> bool {
    let recent = recent_of(outcomes);
    if recent.is_empty() {
        return false;
    }
    let hit = recent.iter().filter(|o| o.as_str() == EMPTY).count();
    let miss = recent
        .iter()
        .filter(|o| FATAL.contains(&o.as_str()))
        .count();
    if hit == 0 || hit < miss {
        return false;
    }
    hit > recent.len() - hit
}

pub fn state_of(outcomes: &[String]) -> &'static str {
    let recent = recent_of(outcomes);
    if recent.is_empty() {
        return "na";
    }
    if recent.iter().filter(|o| FATAL.contains(&o.as_str())).count() >= BAD_MIN {
        return "err";
    }
    let last = recent[recent.len() - 1].as_str();
    if FATAL.contains(&last) {
        return "err";
    }
    if last == EMPTY {
        return "empty";
    }
    if [CODE_429, CODE_4XX, PARSE, SHAPE, UNKNOWN].contains(&last) {
        return "warn";
    }
    if last == OK || last == SLOW {
        return if window_empty(&recent) { "warn" } else { "ok" };
    }
    outcome_state(last)
}
