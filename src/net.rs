use std::collections::BTreeMap;
use std::future::Future;
use std::os::windows::process::CommandExt;
use std::pin::Pin;
use std::process::Command;
use std::task::{Context, Poll};
use std::time::{Duration, Instant};

use crate::model::{SourceError, SourceResult};
use crate::sources::{Fetch, Req};

pub const DEFAULT_UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
pub const ACCEPT_LANGUAGE: &str = "zh-CN,zh;q=0.9,en;q=0.8";
pub const PROBE_URL: &str = "http://www.gstatic.com/generate_204";
pub const PROBE_TIMEOUT_MS: u64 = 1500;
pub const PROBE_CACHE_TTL_SECS: u64 = 15;
pub const TUN_ADAPTER_TTL_SECS: u64 = 30;

const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub const PROXY_MARK: &str = "系统代理";

fn scheme_of(raw: &str) -> &str {
    match raw.find("://") {
        Some(at) => &raw[..at],
        None => "",
    }
}

fn normalize(part: &str) -> String {
    if part.contains("://") {
        part.to_string()
    } else {
        format!("http://{part}")
    }
}

fn reject(part: &str) -> String {
    let scheme = scheme_of(part).to_lowercase();
    if scheme.starts_with("socks") {
        return format!("不支持 {scheme} 代理，只支持 HTTP 代理端口");
    }
    format!("代理地址格式无法识别：{part}")
}

pub fn has_host(url: &str) -> bool {
    let after = match url.find("://") {
        Some(at) => &url[at + 3..],
        None => url,
    };
    let authority = after
        .split(['/', '?', '#'])
        .next()
        .unwrap_or("");
    let host_port = match authority.rsplit_once('@') {
        Some((_, rest)) => rest,
        None => authority,
    };
    let host = if host_port.starts_with('[') {
        match host_port.find(']') {
            Some(at) => &host_port[..=at],
            None => host_port,
        }
    } else {
        host_port.split(':').next().unwrap_or("")
    };
    !host.is_empty()
}

pub fn parse_proxy(raw: &str) -> (BTreeMap<String, String>, String) {
    let text = raw.trim();
    if text.is_empty() {
        return (BTreeMap::new(), String::new());
    }
    let parts: Vec<String> = text
        .split(';')
        .map(|p| p.trim().to_string())
        .filter(|p| !p.is_empty())
        .collect();
    if parts.is_empty() {
        return (BTreeMap::new(), "代理地址为空".to_string());
    }

    if parts.len() == 1 {
        let part = normalize(&parts[0]);
        let low = part.to_lowercase();
        if !low.starts_with("http://") && !low.starts_with("https://") {
            return (BTreeMap::new(), reject(&parts[0]));
        }
        if !has_host(&part) {
            return (BTreeMap::new(), format!("代理地址缺少主机名：{}", parts[0]));
        }
        let mut out = BTreeMap::new();
        out.insert("http".to_string(), part.clone());
        out.insert("https".to_string(), part);
        return (out, String::new());
    }

    let mut out: BTreeMap<String, String> = BTreeMap::new();
    for raw_part in &parts {
        let part = normalize(raw_part);
        let low = part.to_lowercase();
        if !low.starts_with("http://") && !low.starts_with("https://") {
            return (BTreeMap::new(), reject(raw_part));
        }
        if !has_host(&part) {
            return (BTreeMap::new(), format!("代理地址缺少主机名：{raw_part}"));
        }
        let key = if low.starts_with("https://") {
            "https"
        } else {
            "http"
        };
        if out.contains_key(key) {
            return (BTreeMap::new(), format!("代理重复指定同一类型：{raw_part}"));
        }
        out.insert(key.to_string(), part);
    }
    (out, String::new())
}

pub fn env_proxies() -> BTreeMap<String, String> {
    let mut proxies: BTreeMap<String, String> = BTreeMap::new();
    let request_method = std::env::var_os("REQUEST_METHOD").is_some();

    for (name, value) in std::env::vars() {
        if name.len() > 5 && name.as_bytes()[name.len() - 6] == b'_' {
            let tail = name[name.len() - 5..].to_lowercase();
            if tail == "proxy" {
                let key = name[..name.len() - 6].to_lowercase();
                if !value.is_empty() {
                    proxies.insert(key, value);
                }
            }
        }
    }

    if request_method {
        proxies.remove("http");
    }

    for (name, value) in std::env::vars() {
        if name.len() > 5 && name.as_bytes()[name.len() - 6] == b'_' {
            let tail = name[name.len() - 5..].to_lowercase();
            if tail == "proxy" && name.ends_with("_proxy") {
                let key = name[..name.len() - 6].to_lowercase();
                if value.is_empty() {
                    proxies.remove(&key);
                } else {
                    proxies.insert(key, value);
                }
            }
        }
    }

    proxies
}

fn reg_query(value: &str) -> Option<String> {
    const KEY: &str =
        r"Software\Microsoft\Windows\CurrentVersion\Internet Settings";
    let candidates: Vec<String> = match std::env::var("SystemRoot") {
        Ok(root) => vec![
            format!(r"{root}\System32\reg.exe"),
            "reg.exe".to_string(),
        ],
        Err(_) => vec!["reg.exe".to_string()],
    };
    for exe in candidates {
        let Ok(output) = Command::new(&exe)
            .args(["query", &format!("HKCU\\{KEY}"), "/v", value])
            .creation_flags(CREATE_NO_WINDOW)
            .output()
        else {
            continue;
        };
        if !output.status.success() {
            continue;
        }
        let text = String::from_utf8_lossy(&output.stdout);
        for line in text.lines() {
            let fields: Vec<&str> = line.split_whitespace().collect();
            if fields.len() < 3 {
                continue;
            }
            if fields[0] != value {
                continue;
            }
            let at = line.find(fields[2]).unwrap_or(0);
            return Some(line[at..].trim().to_string());
        }
        return None;
    }
    None
}

fn reg_value(raw: &str) -> Option<String> {
    match raw {
        "" => None,
        other => Some(other.to_string()),
    }
}

pub fn registry_proxies() -> BTreeMap<String, String> {
    let mut proxies: BTreeMap<String, String> = BTreeMap::new();
    if std::env::consts::OS != "windows" {
        return proxies;
    }
    let Some(enable) = reg_query("ProxyEnable") else {
        return proxies;
    };
    if enable != "0x1" && enable != "0x01" && enable != "1" {
        return proxies;
    }
    let Some(server) = reg_value(&reg_query("ProxyServer").unwrap_or_default()) else {
        return proxies;
    };

    let mut text = server.as_str().to_string();
    if !text.contains('=') && !text.contains(';') {
        text = format!("http={0};https={0};ftp={0}", server.trim());
    }
    for piece in text.split(';') {
        let Some((protocol, address)) = piece.split_once('=') else {
            continue;
        };
        let protocol = protocol.trim().to_ascii_lowercase();
        let address = address.trim();
        if protocol.is_empty() || address.is_empty() {
            continue;
        }
        let prefixed = match address.find("://") {
            Some(at) => !address[..at].contains(['/', ':']),
            None => false,
        };
        let value = if prefixed {
            address.to_string()
        } else if protocol == "socks" {
            format!("socks://{address}")
        } else {
            format!("http://{address}")
        };
        proxies.insert(protocol, value);
    }
    if let Some(socks) = proxies.get("socks").cloned() {
        let socks = socks.strip_prefix("socks://").map_or(socks.clone(), |rest| {
            format!("socks4://{rest}")
        });
        for key in ["http", "https"] {
            if !proxies.contains_key(key) {
                proxies.insert(key.to_string(), socks.clone());
            }
        }
        proxies.insert("socks".to_string(), socks);
    }
    proxies
}

pub fn system_proxies() -> BTreeMap<String, String> {
    let from_env = env_proxies();
    if !from_env.is_empty() {
        return from_env;
    }
    registry_proxies()
}

fn split_port(host: &str) -> &str {
    match host.strip_prefix('[') {
        Some(rest) => match rest.find(']') {
            Some(at) => host[..at + 2].trim_end_matches(']'),
            None => host,
        },
        None => host.split(':').next().unwrap_or(""),
    }
}

fn glob_match(pattern: &str, text: &str) -> bool {
    let p: Vec<char> = pattern.chars().collect();
    let t: Vec<char> = text.chars().collect();
    let (mut pi, mut ti) = (0usize, 0usize);
    let mut star: Option<usize> = None;
    let mut mark = 0usize;
    while ti < t.len() {
        if pi < p.len() && (p[pi] == '?' || p[pi] == t[ti]) {
            pi += 1;
            ti += 1;
            continue;
        }
        if pi < p.len() && p[pi] == '*' {
            star = Some(pi);
            mark = ti;
            pi += 1;
            continue;
        }
        match star {
            Some(at) => {
                pi = at + 1;
                mark += 1;
                ti = mark;
            }
            None => return false,
        }
    }
    while pi < p.len() && p[pi] == '*' {
        pi += 1;
    }
    pi == p.len()
}

pub fn bypass_with(host: &str, overrides: &str) -> bool {
    let host = split_port(host).to_lowercase();
    for test in overrides.split(';') {
        let test = test.trim();
        if test == "<local>" {
            if !host.contains('.') {
                return true;
            }
            continue;
        }
        if glob_match(&test.to_lowercase(), &host) {
            return true;
        }
    }
    false
}

pub fn proxy_overrides() -> String {
    if std::env::consts::OS != "windows" {
        return String::new();
    }
    reg_query("ProxyOverride").unwrap_or_default()
}

pub struct Resolved {
    pub mode: &'static str,
    pub addr: String,
    pub mapping: BTreeMap<String, String>,
    pub overrides: String,
}

pub fn pick(
    manual: &BTreeMap<String, String>,
    system: &BTreeMap<String, String>,
) -> (&'static str, String) {
    let chosen = if !manual.is_empty() {
        ("manual", manual)
    } else if !system.is_empty() {
        ("system", system)
    } else {
        return ("none", String::new());
    };
    let addr = chosen
        .1
        .get("https")
        .or_else(|| chosen.1.get("http"))
        .cloned()
        .unwrap_or_default();
    (chosen.0, addr)
}

pub fn resolve(manual_raw: &str) -> Resolved {
    let (manual, _err) = parse_proxy(manual_raw);
    let system = system_proxies();
    let (mode, addr) = pick(&manual, &system);
    let mapping = if mode == "manual" { manual } else { system };
    Resolved {
        mode,
        addr,
        mapping,
        overrides: if mode == "none" {
            String::new()
        } else {
            proxy_overrides()
        },
    }
}

pub fn status_from(
    mode: &'static str,
    addr: &str,
    system_on: bool,
    raw_port_ok: bool,
    raw_works: bool,
    raw_tun: &str,
    checked_at: f64,
) -> serde_json::Value {
    let port_ok = mode != "none" && raw_port_ok;
    let works = port_ok && raw_works;
    let tun = if mode == "none" { raw_tun } else { "" };
    serde_json::json!({
        "mode": mode,
        "addr": crate::api::redact(addr),
        "portOk": port_ok,
        "works": works,
        "systemOn": system_on,
        "tun": tun,
        "checkedAt": checked_at,
    })
}

pub fn probe_port(addr: &str) -> bool {
    let text = addr.trim();
    let after = match text.find("://") {
        Some(at) => &text[at + 3..],
        None => text,
    };
    let authority = after.split(['/', '?', '#']).next().unwrap_or("");
    let host_port = match authority.rsplit_once('@') {
        Some((_, rest)) => rest,
        None => authority,
    };
    if host_port.is_empty() {
        return false;
    }
    let (host, port) = match host_port.rsplit_once(':') {
        Some((name, digits)) => match digits.parse::<u16>() {
            Ok(port) => (name.to_string(), port),
            Err(_) => (host_port.to_string(), default_port(text)),
        },
        None => (host_port.to_string(), default_port(text)),
    };
    if host.is_empty() {
        return false;
    }
    let target = format!("{host}:{port}");
    let Ok(addresses) = std::net::ToSocketAddrs::to_socket_addrs(&target) else {
        return false;
    };
    for address in addresses {
        if std::net::TcpStream::connect_timeout(&address, Duration::from_millis(500)).is_ok() {
            return true;
        }
    }
    false
}

fn default_port(addr: &str) -> u16 {
    if addr.to_lowercase().starts_with("https://") {
        443
    } else {
        80
    }
}

pub fn bypass(host: &str, resolved: &Resolved) -> bool {
    if resolved.mode == "none" || resolved.overrides.is_empty() {
        return false;
    }
    bypass_with(host, &resolved.overrides)
}

const TUN_WORDS: [&str; 9] = [
    "clash",
    "mihomo",
    "wintun",
    "sing-box",
    "singbox",
    "v2ray",
    "tap-windows",
    "utun",
    "tunnel",
];

fn adapter_name(head: &str) -> String {
    if let Some(at) = head.find("适配器") {
        return head[at + "适配器".len()..].trim().to_string();
    }
    if let Some((at, _)) = head.char_indices().find(|&(i, _)| {
        head.get(i..i + 7).map(|sub| sub.eq_ignore_ascii_case("adapter")).unwrap_or(false)
    }) {
        return head[at + 7..].trim().to_string();
    }
    head.trim().to_string()
}

fn carries_ipv4(block: &str) -> bool {
    block.to_lowercase().contains("ipv4")
}

pub fn scan_tun_adapter() -> String {
    if std::env::consts::OS != "windows" {
        return String::new();
    }
    let Ok(output) = Command::new("ipconfig")
        .creation_flags(CREATE_NO_WINDOW)
        .output() else {
        return String::new();
    };
    let text = decode(&output.stdout);
    let lines: Vec<&str> = text.lines().collect();
    let mut index = 0;
    while index < lines.len() {
        let line = lines[index].trim_end();
        index += 1;
        let low = line.to_lowercase();
        if !(line.contains("适配器") || low.contains("adapter")) {
            continue;
        }
        if !TUN_WORDS.iter().any(|w| low.contains(w)) {
            continue;
        }
        let head = line.split(':').next().unwrap_or("");
        let name = adapter_name(head).trim_matches(|c| c == ' ' || c == '.' || c == ':').to_string();
        if name.is_empty() {
            continue;
        }
        let start = index;
        while index < lines.len() {
            let next = lines[index];
            if next.contains("适配器") || next.to_lowercase().contains("adapter") {
                break;
            }
            index += 1;
        }
        if carries_ipv4(&lines[start..index].join(" ")) {
            return name;
        }
    }
    String::new()
}

const RETRY_STATUS: [u16; 5] = [429, 500, 502, 503, 504];
pub const HTTP_BODY_LIMIT: usize = 20 * 1024 * 1024;
const CAPTCHA_SCAN_BYTES: usize = 8192;
const LAX_TTL_SECS: u64 = 600;
const LAX_LIMIT: usize = 32;
const VT_LIMIT: usize = 32;
const VT_DEFAULT_TTL_SECS: u64 = 1800;
const VT_DELAY_MS: u64 = 320;

const CAPTCHA_SIGNS: [&str; 7] = [
    "one more step",
    "please complete the security check",
    "captcha",
    "cf-browser-verification",
    "just a moment",
    "enable javascript and cookies",
    "验证码",
];
const CAPTCHA_STRONG: [&str; 10] = [
    "one more step",
    "please complete the security check",
    "cf-browser-verification",
    "just a moment",
    "cf-chl",
    "challenge-platform",
    "checking your browser",
    "g-recaptcha",
    "hcaptcha",
    "turnstile",
];
const CAPTCHA_WEAK: [&str; 3] = ["captcha", "enable javascript and cookies", "验证码"];
const CAPTCHA_DEEP: [&str; 5] = [
    "one more step",
    "please complete the security check",
    "just a moment",
    "checking your browser",
    "cf-browser-verification",
];

pub fn captcha_text(text: &str) -> bool {
    let head: String = text.chars().take(4096).collect();
    let head_low = head.to_lowercase();
    if !head_low.contains("<html") && !head_low.contains("<!doctype") {
        return false;
    }
    if captcha_signs(&head_low) {
        return true;
    }
    if head.len() == text.len() {
        return false;
    }
    let low = text.to_lowercase();
    CAPTCHA_DEEP.iter().any(|s| low.contains(s))
}

fn captcha_signs(low: &str) -> bool {
    if CAPTCHA_STRONG.iter().any(|s| low.contains(s)) {
        return true;
    }
    CAPTCHA_WEAK.iter().filter(|s| low.contains(*s)).count() >= 2
}

pub fn captcha_wall(body: &[u8]) -> bool {
    let low = String::from_utf8_lossy(body).to_lowercase();
    CAPTCHA_SIGNS.iter().any(|s| low.contains(s))
}

pub fn decode(raw: &[u8]) -> String {
    if let Ok(text) = std::str::from_utf8(raw) {
        return text.to_string();
    }
    for enc in [encoding_rs::GB18030, encoding_rs::BIG5] {
        let (text, _, had_errors) = enc.decode(raw);
        if !had_errors {
            return text.to_string();
        }
    }
    raw.iter().map(|b| *b as char).collect()
}

pub struct VtGate {
    pub nonce: String,
    pub ch: String,
}

pub fn fnv1a32_utf16(text: &str) -> u32 {
    let mut hash: u32 = 0x811c_9dc5;
    for unit in text.encode_utf16() {
        hash ^= unit as u32;
        hash = hash.wrapping_mul(0x0100_0193);
    }
    hash
}

fn is_ident_byte(b: u8) -> bool {
    b.is_ascii_alphanumeric() || b == b'_' || b == b'$'
}

fn js_string_var(text: &str, name: &str) -> Option<String> {
    let bytes = text.as_bytes();
    let target = name.as_bytes();
    let mut from = 0usize;
    while let Some(rel) = text[from..].find(name) {
        let at = from + rel;
        from = at + name.len();
        if at > 0 && is_ident_byte(bytes[at - 1]) {
            continue;
        }
        let mut cursor = at + target.len();
        if cursor < bytes.len() && is_ident_byte(bytes[cursor]) {
            continue;
        }
        while cursor < bytes.len() && bytes[cursor].is_ascii_whitespace() {
            cursor += 1;
        }
        if cursor >= bytes.len() || bytes[cursor] != b'=' {
            continue;
        }
        cursor += 1;
        while cursor < bytes.len() && bytes[cursor].is_ascii_whitespace() {
            cursor += 1;
        }
        let Some(&quote) = bytes.get(cursor) else {
            break;
        };
        if quote != b'"' && quote != b'\'' {
            continue;
        }
        cursor += 1;
        let start = cursor;
        while cursor < bytes.len() {
            let b = bytes[cursor];
            if b == b'\\' || b == b'\n' || b == b'\r' {
                break;
            }
            if b == quote {
                if cursor > start {
                    return Some(text[start..cursor].to_string());
                }
                break;
            }
            cursor += 1;
        }
    }
    None
}

pub fn parse_vt_gate(body: &str) -> Option<VtGate> {
    if !body.contains("/__vt")
        || !body.contains("0x811c9dc5")
        || !body.contains("0x01000193")
    {
        return None;
    }
    Some(VtGate {
        nonce: js_string_var(body, "nonce")?,
        ch: js_string_var(body, "ch")?,
    })
}

pub fn vt_form_body(gate: &VtGate) -> String {
    let ans = fnv1a32_utf16(&gate.nonce);
    format!("c={}&a={ans}&w=0", crate::util::quote(&gate.ch))
}

pub fn origin_of(url: &str) -> Option<String> {
    let scheme_end = url.find("://")?;
    let scheme = &url[..scheme_end];
    let after = &url[scheme_end + 3..];
    let authority = after.split(['/', '?', '#']).next().unwrap_or("");
    let host_port = match authority.rsplit_once('@') {
        Some((_, rest)) => rest,
        None => authority,
    };
    if scheme.is_empty() || host_port.is_empty() {
        None
    } else {
        Some(format!("{}://{}", scheme.to_lowercase(), host_port))
    }
}

pub fn parse_set_cookies(values: &[&str]) -> Option<(String, u64)> {
    let mut pairs: Vec<String> = Vec::new();
    let mut min_age: Option<u64> = None;
    for raw in values {
        let mut parts = raw.split(';');
        let Some(first) = parts.next() else {
            continue;
        };
        let Some((name, val)) = first.trim().split_once('=') else {
            continue;
        };
        let name = name.trim();
        let val = val.trim();
        if name.is_empty() || val.is_empty() {
            continue;
        }
        let mut expired = false;
        for attr in parts {
            let trimmed = attr.trim();
            let Some((k, v)) = trimmed.split_once('=') else {
                continue;
            };
            if k.trim().eq_ignore_ascii_case("max-age") {
                if let Ok(secs) = v.trim().parse::<i64>() {
                    if secs <= 0 {
                        expired = true;
                    } else {
                        let secs = secs as u64;
                        min_age = Some(min_age.map_or(secs, |cur| cur.min(secs)));
                    }
                }
            }
        }
        if !expired {
            pairs.push(format!("{name}={val}"));
        }
    }
    if pairs.is_empty() {
        return None;
    }
    let raw_ttl = min_age.unwrap_or(VT_DEFAULT_TTL_SECS);
    let ttl = if raw_ttl > 60 {
        (raw_ttl - 60).clamp(60, 86400)
    } else {
        raw_ttl.clamp(1, 60)
    };
    Some((pairs.join("; "), ttl))
}

fn cap_oldest<V>(
    map: &mut std::collections::HashMap<String, V>,
    limit: usize,
    until_of: impl Fn(&V) -> Instant,
) {
    if map.len() <= limit {
        return;
    }
    let mut entries: Vec<(String, Instant)> = map
        .iter()
        .map(|(k, v)| (k.clone(), until_of(v)))
        .collect();
    entries.sort_by_key(|(_, until)| *until);
    let drop_count = entries.len() - limit;
    for (name, _) in entries.into_iter().take(drop_count) {
        map.remove(&name);
    }
}

enum Attempt {
    Ok(Vec<u8>),
    TooLarge,
    Http {
        code: u16,
        url: String,
        body: String,
    },
    Timeout,
    Cert,
    ProxyDown,
    Cancelled,
    Other(String),
}

enum Either<A, B> {
    Left(A),
    Right(B),
}

struct Race<A, B> {
    a: A,
    b: B,
}

fn race<A, B>(a: A, b: B) -> Race<A, B> {
    Race { a, b }
}

impl<A: Future + Unpin, B: Future + Unpin> Future for Race<A, B> {
    type Output = Either<A::Output, B::Output>;

    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        if let Poll::Ready(res) = Pin::new(&mut self.b).poll(cx) {
            return Poll::Ready(Either::Right(res));
        }
        if let Poll::Ready(res) = Pin::new(&mut self.a).poll(cx) {
            return Poll::Ready(Either::Left(res));
        }
        Poll::Pending
    }
}

async fn await_with_cancel<F, T>(
    fut: F,
    batch: Option<i64>,
    deadline: Option<Instant>,
) -> Result<T, Attempt>
where
    F: Future<Output = T>,
{
    if let Some(token) = batch {
        if !crate::sources::batch_alive(token) {
            return Err(Attempt::Cancelled);
        }
    }
    if let Some(dl) = deadline {
        if Instant::now() >= dl {
            return Err(Attempt::Timeout);
        }
    }

    tokio::pin!(fut);
    loop {
        if let Some(token) = batch {
            if !crate::sources::batch_alive(token) {
                return Err(Attempt::Cancelled);
            }
        }
        if let Some(dl) = deadline {
            if Instant::now() >= dl {
                return Err(Attempt::Timeout);
            }
        }

        let notify = crate::sources::cancel_notified();
        tokio::pin!(notify);

        let race_fut = race(&mut fut, &mut notify);

        let outcome = match deadline {
            Some(dl) => {
                let left = dl.saturating_duration_since(Instant::now());
                if left.is_zero() {
                    return Err(Attempt::Timeout);
                }
                match tokio::time::timeout(left, race_fut).await {
                    Ok(either) => either,
                    Err(_) => return Err(Attempt::Timeout),
                }
            }
            None => race_fut.await,
        };

        match outcome {
            Either::Left(res) => return Ok(res),
            Either::Right(()) => {
                if let Some(token) = batch {
                    if !crate::sources::batch_alive(token) {
                        return Err(Attempt::Cancelled);
                    }
                }
            }
        }
    }
}

pub struct HttpClient {
    rt: tokio::runtime::Runtime,
    ua: String,
    retries: u32,
    default_timeout: u64,
    resolved: Resolved,
    clients: std::sync::Mutex<std::collections::HashMap<(u64, bool, bool), reqwest::Client>>,
    probe: std::sync::Mutex<Option<(String, Instant, serde_json::Value)>>,
    tun: std::sync::Mutex<Option<(Instant, String)>>,
    lax: std::sync::Mutex<std::collections::HashMap<String, Instant>>,
    vt_cookies: std::sync::Mutex<std::collections::HashMap<String, (String, Instant)>>,
    vt_solve: std::sync::Mutex<()>,
}

fn host_of(url: &str) -> String {
    let after = match url.find("://") {
        Some(at) => &url[at + 3..],
        None => url,
    };
    let authority = after.split(['/', '?', '#']).next().unwrap_or("");
    let host_port = match authority.rsplit_once('@') {
        Some((_, rest)) => rest,
        None => authority,
    };
    host_port
        .split(':')
        .next()
        .unwrap_or("")
        .to_lowercase()
}

fn chain_text(error: &(dyn std::error::Error + 'static)) -> String {
    let mut out = error.to_string();
    let mut cursor = error.source();
    while let Some(inner) = cursor {
        out.push_str(" | ");
        out.push_str(&inner.to_string());
        cursor = inner.source();
    }
    out
}

impl HttpClient {
    fn with_resolved(
        ua: String,
        retries: u32,
        default_timeout: u64,
        resolved: Resolved,
    ) -> SourceResult<Self> {
        let rt = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .map_err(|e| SourceError::Transport(e.to_string()))?;
        Ok(HttpClient {
            rt,
            ua,
            retries,
            default_timeout,
            resolved,
            clients: std::sync::Mutex::new(std::collections::HashMap::new()),
            lax: std::sync::Mutex::new(std::collections::HashMap::new()),
            vt_cookies: std::sync::Mutex::new(std::collections::HashMap::new()),
            vt_solve: std::sync::Mutex::new(()),
            probe: std::sync::Mutex::new(None),
            tun: std::sync::Mutex::new(None),
        })
    }

    pub fn new(
        ua: String,
        retries: u32,
        default_timeout: u64,
        manual_proxy: &str,
    ) -> SourceResult<Self> {
        Self::with_resolved(ua, retries, default_timeout, resolve(manual_proxy))
    }

    pub fn new_direct(
        ua: String,
        retries: u32,
        default_timeout: u64,
    ) -> SourceResult<Self> {
        let resolved = Resolved {
            mode: "none",
            addr: String::new(),
            mapping: BTreeMap::new(),
            overrides: String::new(),
        };
        Self::with_resolved(ua, retries, default_timeout, resolved)
    }

    pub fn resolved(&self) -> &Resolved {
        &self.resolved
    }

    fn client(&self, timeout_ms: u64, lax: bool, proxied: bool) -> SourceResult<reqwest::Client> {
        let key = (timeout_ms, lax, proxied);
        if let Some(found) = self.clients.lock().unwrap_or_else(|e| e.into_inner()).get(&key) {
            return Ok(found.clone());
        }
        let mut base = reqwest::header::HeaderMap::new();
        base.insert(
            reqwest::header::ACCEPT,
            reqwest::header::HeaderValue::from_static("*/*"),
        );
        base.insert(
            reqwest::header::ACCEPT_LANGUAGE,
            reqwest::header::HeaderValue::from_static(ACCEPT_LANGUAGE),
        );
        let mut builder = reqwest::Client::builder()
            .user_agent(&self.ua)
            .default_headers(base)
            .connect_timeout(Duration::from_millis(timeout_ms))
            .read_timeout(Duration::from_millis(timeout_ms))
            .tcp_keepalive(Some(Duration::from_secs(60)))
            .gzip(true)
            .brotli(true)
            .no_proxy();
        if lax {
            builder = builder.danger_accept_invalid_certs(true);
        }
        if proxied {
            for (scheme, url) in &self.resolved.mapping {
                let proxy = if scheme == "https" {
                    reqwest::Proxy::https(url)
                } else if scheme == "http" {
                    reqwest::Proxy::http(url)
                } else {
                    continue;
                };
                builder = builder
                    .proxy(proxy.map_err(|e| SourceError::Transport(e.to_string()))?);
            }
        }
        let client = builder
            .build()
            .map_err(|e| SourceError::Transport(e.to_string()))?;
        self.clients.lock().unwrap_or_else(|e| e.into_inner()).insert(key, client.clone());
        Ok(client)
    }

    fn known_lax(&self, url: &str) -> bool {
        let host = host_of(url);
        let mut guard = self.lax.lock().unwrap_or_else(|e| e.into_inner());
        let now = Instant::now();
        guard.retain(|_, until| *until > now);
        guard.contains_key(&host)
    }

    fn mark_lax(&self, url: &str) {
        let host = host_of(url);
        let mut guard = self.lax.lock().unwrap_or_else(|e| e.into_inner());
        guard.insert(host, Instant::now() + Duration::from_secs(LAX_TTL_SECS));
        cap_oldest(&mut guard, LAX_LIMIT, |until| *until);
    }

    fn vt_cookie(&self, host: &str) -> Option<String> {
        let mut guard = self.vt_cookies.lock().unwrap_or_else(|e| e.into_inner());
        let now = Instant::now();
        guard.retain(|_, (_, until)| *until > now);
        guard.get(host).map(|(cookie, _)| cookie.clone())
    }

    fn store_vt_cookie(&self, host: &str, cookie: String, ttl_secs: u64) {
        let mut guard = self.vt_cookies.lock().unwrap_or_else(|e| e.into_inner());
        let now = Instant::now();
        guard.retain(|_, (_, until)| *until > now);
        guard.insert(
            host.to_string(),
            (cookie, now + Duration::from_secs(ttl_secs)),
        );
        cap_oldest(&mut guard, VT_LIMIT, |(_, until)| *until);
    }

    fn invalidate_vt_cookie(&self, host: &str, expected: &str) {
        let mut guard = self.vt_cookies.lock().unwrap_or_else(|e| e.into_inner());
        if guard.get(host).is_some_and(|(cur, _)| cur == expected) {
            guard.remove(host);
        }
    }

    pub fn tun_adapter(&self, force: bool) -> String {
        let mut guard = self.tun.lock().unwrap_or_else(|e| e.into_inner());
        if !force {
            if let Some((at, name)) = guard.as_ref() {
                if at.elapsed() < Duration::from_secs(TUN_ADAPTER_TTL_SECS) {
                    return name.clone();
                }
            }
        }
        let name = scan_tun_adapter();
        *guard = Some((Instant::now(), name.clone()));
        name
    }

    pub fn probe_works(&self) -> bool {
        if self.resolved.mapping.is_empty() {
            return false;
        }
        let Ok(client) = self.client(PROBE_TIMEOUT_MS, false, true) else {
            return false;
        };
        self.rt.block_on(async {
            match client.get(PROBE_URL).send().await {
                Ok(response) => response.status().as_u16() < 400,
                Err(_) => false,
            }
        })
    }

    pub fn probe_direct(&self) -> bool {
        let Ok(client) = self.client(PROBE_TIMEOUT_MS, false, false) else {
            return false;
        };
        self.rt.block_on(async {
            match client.get(PROBE_URL).send().await {
                Ok(response) => response.status().as_u16() < 400,
                Err(_) => false,
            }
        })
    }

    pub fn proxy_status(&self, force: bool) -> serde_json::Value {
        let key = format!("{}|{}", self.resolved.mode, self.resolved.addr);
        if !force {
            let guard = self.probe.lock().unwrap_or_else(|e| e.into_inner());
            if let Some((cached_key, at, data)) = guard.as_ref() {
                if *cached_key == key
                    && at.elapsed() < Duration::from_secs(PROBE_CACHE_TTL_SECS)
                {
                    return data.clone();
                }
            }
        }
        let system_on = !system_proxies().is_empty();
        let port_ok = if self.resolved.mode != "none" {
            probe_port(&self.resolved.addr)
        } else {
            false
        };
        let works = if port_ok { self.probe_works() } else { false };
        let direct_works = if self.resolved.mode == "none" {
            self.probe_direct()
        } else {
            false
        };
        let tun = self.tun_adapter(force);
        let checked_at = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        let mut data = status_from(
            self.resolved.mode,
            &self.resolved.addr,
            system_on,
            port_ok,
            works,
            &tun,
            checked_at,
        );
        if let Some(obj) = data.as_object_mut() {
            obj.insert("directWorks".to_string(), serde_json::Value::Bool(direct_works));
            obj.insert("tunActive".to_string(), serde_json::Value::String(tun));
        }
        *self.probe.lock().unwrap_or_else(|e| e.into_inner()) = Some((key, Instant::now(), data.clone()));
        data
    }

    pub fn has_proxy(&self) -> bool {
        !self.resolved.addr.is_empty()
    }

    pub fn proxy_hint(&self) -> String {
        if self.resolved.addr.is_empty() {
            return crate::outcome::NET_FAIL_TEXT.to_string();
        }
        format!("{PROXY_MARK} {} 连不上", crate::api::redact(&self.resolved.addr))
    }

    fn backoff_sleep(
        &self,
        duration: Duration,
        batch: Option<i64>,
        deadline: Option<Instant>,
    ) -> Result<(), SourceError> {
        self.rt.block_on(async {
            match await_with_cancel(tokio::time::sleep(duration), batch, deadline).await {
                Ok(()) => Ok(()),
                Err(Attempt::Cancelled) => Err(SourceError::Cancelled),
                Err(Attempt::Timeout) => Err(SourceError::Timeout),
                Err(_) => Err(SourceError::Cancelled),
            }
        })
    }

    fn send_once(
        &self,
        req: &Req,
        use_lax: bool,
        limit: usize,
        cookie: Option<&str>,
        want_cookies: bool,
    ) -> (Attempt, Vec<String>) {
        if let Some(token) = req.batch {
            if !crate::sources::batch_alive(token) {
                return (Attempt::Cancelled, Vec::new());
            }
        }
        if let Some(deadline) = req.deadline {
            if Instant::now() >= deadline {
                return (Attempt::Timeout, Vec::new());
            }
        }
        let timeout_ms = req.timeout.unwrap_or(self.default_timeout) * 1000;
        let proxied = !bypass(&host_of(req.url), &self.resolved);
        let client = match self.client(timeout_ms, use_lax, proxied) {
            Ok(client) => client,
            Err(exc) => return (Attempt::Other(exc.search_text()), Vec::new()),
        };
        let proxy_in_play = proxied && self.resolved.mode != "none";
        let referer = req.referer.to_string();
        let has_cookie = req
            .headers
            .iter()
            .any(|(k, _)| k.eq_ignore_ascii_case("cookie"));
        let extra_cookie = if has_cookie {
            None
        } else {
            cookie.map(str::to_string)
        };
        let headers: Vec<(String, String)> = req
            .headers
            .iter()
            .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
            .collect();
        let url = req.url.to_string();
        let data = req.data.map(|d| d.to_vec());
        let batch = req.batch;
        let deadline = req.deadline;

        self.rt.block_on(async move {
            let mut builder = match data {
                Some(body) => client.post(&url).body(body),
                None => client.get(&url),
            };
            if !referer.is_empty() {
                builder = builder.header(reqwest::header::REFERER, referer);
            }
            if let Some(value) = extra_cookie {
                builder = builder.header(reqwest::header::COOKIE, value);
            }
            for (name, value) in headers {
                builder = builder.header(name, value);
            }
            let response = match await_with_cancel(builder.send(), batch, deadline).await {
                Ok(Ok(response)) => response,
                Ok(Err(error)) => return (classify_error(&error, proxy_in_play), Vec::new()),
                Err(Attempt::Cancelled) => return (Attempt::Cancelled, Vec::new()),
                Err(Attempt::Timeout) => return (Attempt::Timeout, Vec::new()),
                Err(other) => return (other, Vec::new()),
            };
            let set_cookies = if want_cookies {
                response
                    .headers()
                    .get_all(reqwest::header::SET_COOKIE)
                    .iter()
                    .filter_map(|v| v.to_str().ok().map(str::to_string))
                    .collect()
            } else {
                Vec::new()
            };
            let status = response.status();
            let final_url = response.url().to_string();
            if !status.is_success() {
                let body = match read_body(response, CAPTCHA_SCAN_BYTES, false, batch, deadline).await {
                    BodyRead::Ok(bytes) => bytes,
                    BodyRead::Cancelled => return (Attempt::Cancelled, set_cookies),
                    BodyRead::Timeout => return (Attempt::Timeout, set_cookies),
                    _ => Vec::new(),
                };
                return (
                    Attempt::Http {
                        code: status.as_u16(),
                        url: final_url,
                        body: String::from_utf8_lossy(&body).to_string(),
                    },
                    set_cookies,
                );
            }
            let attempt = match read_body(response, limit, true, batch, deadline).await {
                BodyRead::Ok(bytes) => Attempt::Ok(bytes),
                BodyRead::TooLarge => Attempt::TooLarge,
                BodyRead::Cancelled => Attempt::Cancelled,
                BodyRead::Timeout => Attempt::Timeout,
                BodyRead::Failed(message) => Attempt::Other(message),
            };
            (attempt, set_cookies)
        })
    }

    fn ensure_vt_cookie(
        &self,
        req: &Req,
        fail_url: &str,
        gate: &VtGate,
        sent_cookie: Option<&str>,
        use_lax: bool,
    ) -> Result<(), SourceError> {
        let req_host = host_of(req.url);
        let post_url = if fail_url.is_empty() {
            req.url
        } else {
            fail_url
        };
        let post_host = host_of(post_url);
        let Some(origin) = origin_of(post_url) else {
            return Err(SourceError::Shape("invalid origin".to_string()));
        };
        let _guard = self.vt_solve.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(current) = self.vt_cookie(&req_host) {
            if sent_cookie != Some(current.as_str()) {
                return Ok(());
            }
        }
        if let Some(stale) = sent_cookie {
            self.invalidate_vt_cookie(&req_host, stale);
        }
        self.backoff_sleep(
            Duration::from_millis(VT_DELAY_MS),
            req.batch,
            req.deadline,
        )?;
        let vt_url = format!("{origin}/__vt");
        let form = vt_form_body(gate);
        let vt_req = Req {
            url: &vt_url,
            data: Some(form.as_bytes()),
            referer: post_url,
            headers: vec![
                ("Content-Type", "application/x-www-form-urlencoded"),
                ("Origin", &origin),
                ("Accept", "*/*"),
                ("Accept-Language", ACCEPT_LANGUAGE),
            ],
            retries: Some(0),
            timeout: req.timeout,
            batch: req.batch,
            deadline: req.deadline,
        };
        let mut vt_lax = use_lax || self.known_lax(&vt_url);
        for round in 0..2 {
            let (outcome, raw_cookies) =
                self.send_once(&vt_req, vt_lax, CAPTCHA_SCAN_BYTES, None, true);
            match outcome {
                Attempt::Ok(_) => {
                    let refs: Vec<&str> = raw_cookies.iter().map(String::as_str).collect();
                    let Some((cookie, ttl)) = parse_set_cookies(&refs) else {
                        crate::log::warning(
                            crate::log::SOURCES,
                            &format!("站点校验未返回 Cookie：{req_host}"),
                        );
                        return Err(SourceError::Shape("missing vt cookie".to_string()));
                    };
                    self.store_vt_cookie(&req_host, cookie.clone(), ttl);
                    if !post_host.is_empty() && post_host != req_host {
                        self.store_vt_cookie(&post_host, cookie, ttl);
                    }
                    crate::log::info(
                        crate::log::SOURCES,
                        &format!("完成站点浏览器校验：{req_host}（{ttl}s）"),
                    );
                    return Ok(());
                }
                Attempt::Cert if round == 0 && !vt_lax => {
                    self.mark_lax(&vt_url);
                    vt_lax = true;
                }
                Attempt::Cancelled => return Err(SourceError::Cancelled),
                Attempt::Timeout => return Err(SourceError::Timeout),
                Attempt::ProxyDown => {
                    return Err(SourceError::ProxyUnreachable(self.proxy_hint()));
                }
                Attempt::Http { code, body, .. } => {
                    crate::log::warning(
                        crate::log::SOURCES,
                        &format!("站点校验失败（HTTP {code}）：{req_host}"),
                    );
                    return Err(SourceError::Http { code, body });
                }
                Attempt::Cert => {
                    return Err(SourceError::Transport("证书校验失败".to_string()));
                }
                Attempt::TooLarge => {
                    return Err(SourceError::TooLarge {
                        limit: CAPTCHA_SCAN_BYTES,
                    });
                }
                Attempt::Other(message) => {
                    crate::log::warning(
                        crate::log::SOURCES,
                        &format!("站点校验异常（{req_host}）：{message}"),
                    );
                    return Err(SourceError::Transport(message));
                }
            }
        }
        Err(SourceError::Transport("站点校验未完成".to_string()))
    }

    pub fn run_raw(&self, req: &Req, limit: usize) -> SourceResult<Vec<u8>> {
        let retries = req.retries.unwrap_or(self.retries) as i64;
        let mut attempt: i64 = 0;
        let mut use_lax = self.known_lax(req.url);
        let mut vt_solved = false;
        while attempt <= retries {
            attempt += 1;
            if let Some(token) = req.batch {
                if !crate::sources::batch_alive(token) {
                    return Err(SourceError::Cancelled);
                }
            }
            if let Some(deadline) = req.deadline {
                if Instant::now() >= deadline {
                    return Err(SourceError::Timeout);
                }
            }
            let sent_cookie = self.vt_cookie(&host_of(req.url));
            match self
                .send_once(req, use_lax, limit, sent_cookie.as_deref(), false)
                .0
            {
                Attempt::Ok(raw) => return Ok(raw),
                Attempt::Cancelled => return Err(SourceError::Cancelled),
                Attempt::TooLarge => return Err(SourceError::TooLarge { limit }),
                Attempt::Http { code, url, body } => {
                    if code == 403 && !vt_solved {
                        if let Some(gate) = parse_vt_gate(&body) {
                            vt_solved = true;
                            match self.ensure_vt_cookie(
                                req,
                                &url,
                                &gate,
                                sent_cookie.as_deref(),
                                use_lax,
                            ) {
                                Ok(()) => {
                                    use_lax = self.known_lax(req.url);
                                    attempt -= 1;
                                    continue;
                                }
                                Err(err)
                                    if matches!(
                                        err,
                                        SourceError::Cancelled
                                            | SourceError::Timeout
                                            | SourceError::ProxyUnreachable(_)
                                    ) =>
                                {
                                    return Err(err);
                                }
                                Err(_) => {}
                            }
                        }
                    }
                    if (code == 403 || code == 429) && captcha_wall(body.as_bytes()) {
                        crate::log::warning(
                            crate::log::SOURCES,
                            &format!("被验证码拦截：{}", crate::api::redact(req.url)),
                        );
                        return Err(SourceError::Blocked(
                            crate::outcome::BLOCKED_TEXT.to_string(),
                        ));
                    }
                    if RETRY_STATUS.contains(&code) && attempt <= retries {
                        self.backoff_sleep(
                            Duration::from_secs_f64(1.0 * attempt as f64),
                            req.batch,
                            req.deadline,
                        )?;
                        continue;
                    }
                    return Err(SourceError::Http { code, body });
                }
                Attempt::Cert => {
                    if !use_lax {
                        self.mark_lax(req.url);
                        crate::log::warning(
                            crate::log::SOURCES,
                            &format!(
                                "SSL 严格校验失败，临时降级 {LAX_TTL_SECS}s：{}",
                                host_of(req.url)
                            ),
                        );
                        use_lax = true;
                        attempt -= 1;
                        continue;
                    }
                    return Err(SourceError::Transport("证书校验失败".to_string()));
                }
                Attempt::ProxyDown => {
                    crate::log::warning(
                        crate::log::SOURCES,
                        &format!("代理不可达（{}）", host_of(req.url)),
                    );
                    return Err(SourceError::ProxyUnreachable(self.proxy_hint()));
                }
                Attempt::Timeout => return Err(SourceError::Timeout),
                Attempt::Other(message) => {
                    if attempt <= retries {
                        self.backoff_sleep(
                            Duration::from_secs_f64(1.5 * attempt as f64),
                            req.batch,
                            req.deadline,
                        )?;
                        continue;
                    }
                    return Err(SourceError::Transport(message));
                }
            }
        }
        Err(SourceError::Transport(format!(
            "重试 {retries} 次后仍未拿到响应"
        )))
    }
}

impl HttpClient {
    pub fn run(&self, req: &Req, limit: usize) -> SourceResult<String> {
        let raw = self.run_raw(req, limit)?;
        let text = decode(&raw);
        if captcha_text(&text) {
            crate::log::warning(
                crate::log::SOURCES,
                &format!("返回验证码页：{}", crate::api::redact(req.url)),
            );
            return Err(SourceError::Blocked(
                crate::outcome::BLOCKED_TEXT.to_string(),
            ));
        }
        Ok(text)
    }

    pub fn fetch_bytes(&self, req: &Req, limit: usize) -> SourceResult<Vec<u8>> {
        self.run_raw(req, limit)
    }
}

impl Fetch for HttpClient {
    fn fetch(&self, req: Req) -> SourceResult<String> {
        self.run(&req, HTTP_BODY_LIMIT)
    }
}

fn classify_error(error: &reqwest::Error, proxy_in_play: bool) -> Attempt {
    let text = chain_text(error);
    let low = text.to_lowercase();
    if error.is_timeout() || low.contains("timed out") || low.contains("timeout") {
        return Attempt::Timeout;
    }
    if low.contains("certificate") {
        return Attempt::Cert;
    }
    let refused = low.contains("10061") || low.contains("10060");
    let reset = low.contains("connection refused") || low.contains("connection reset");
    if refused || (proxy_in_play && reset) {
        return Attempt::ProxyDown;
    }
    Attempt::Other(text)
}

enum BodyRead {
    Ok(Vec<u8>),
    TooLarge,
    Cancelled,
    Timeout,
    Failed(String),
}

static RX_TOTAL: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
static RX_SAMPLE: std::sync::Mutex<Option<(u64, Instant, f64)>> = std::sync::Mutex::new(None);

pub fn down_rate() -> f64 {
    let now = Instant::now();
    let total = RX_TOTAL.load(std::sync::atomic::Ordering::Relaxed);
    let mut guard = RX_SAMPLE.lock().unwrap_or_else(|e| e.into_inner());
    let rate = match *guard {
        Some((prev_total, prev_at, last)) => {
            let secs = now.duration_since(prev_at).as_secs_f64();
            if secs < 0.2 {
                last
            } else {
                total.saturating_sub(prev_total) as f64 / secs
            }
        }
        None => 0.0,
    };
    *guard = Some((total, now, rate));
    rate
}

async fn read_body(
    mut response: reqwest::Response,
    limit: usize,
    strict: bool,
    batch: Option<i64>,
    deadline: Option<Instant>,
) -> BodyRead {
    let mut out: Vec<u8> = Vec::with_capacity(limit.min(16 * 1024));
    let mut got = 0usize;
    loop {
        let chunk_res = match await_with_cancel(response.chunk(), batch, deadline).await {
            Ok(res) => res,
            Err(Attempt::Cancelled) => return BodyRead::Cancelled,
            Err(Attempt::Timeout) => return BodyRead::Timeout,
            Err(_) => return BodyRead::Failed("中断".to_string()),
        };
        match chunk_res {
            Ok(Some(chunk)) => {
                got += chunk.len();
                RX_TOTAL.fetch_add(chunk.len() as u64, std::sync::atomic::Ordering::Relaxed);
                if got > limit {
                    if strict {
                        return BodyRead::TooLarge;
                    }
                    let before = got - chunk.len();
                    let keep = limit - before;
                    out.extend_from_slice(&chunk[..keep.min(chunk.len())]);
                    break;
                }
                out.extend_from_slice(&chunk);
            }
            Ok(None) => break,
            Err(error) => return BodyRead::Failed(chain_text(&error)),
        }
    }
    BodyRead::Ok(out)
}
