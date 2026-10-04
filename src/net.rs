use std::collections::BTreeMap;
use std::os::windows::process::CommandExt;
use std::process::Command;
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
        let address = address.trim();
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
        proxies.insert(protocol.to_string(), value);
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

pub fn captcha_text(text: &str) -> bool {
    let head: String = text.chars().take(4096).collect::<String>().to_lowercase();
    if !head.contains("<html") && !head.contains("<!doctype") {
        return false;
    }
    if CAPTCHA_STRONG.iter().any(|s| head.contains(s)) {
        return true;
    }
    CAPTCHA_WEAK.iter().filter(|s| head.contains(*s)).count() >= 2
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

enum Attempt {
    Ok(Vec<u8>),
    TooLarge,
    Http { code: u16, body: String },
    Timeout,
    Cert,
    ProxyDown,
    Cancelled,
    Other(String),
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
    pub fn new(
        ua: String,
        retries: u32,
        default_timeout: u64,
        manual_proxy: &str,
    ) -> SourceResult<Self> {
        let rt = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .map_err(|e| SourceError::Transport(e.to_string()))?;
        let resolved = resolve(manual_proxy);
        Ok(HttpClient {
            rt,
            ua,
            retries,
            default_timeout,
            resolved,
            clients: std::sync::Mutex::new(std::collections::HashMap::new()),
            lax: std::sync::Mutex::new(std::collections::HashMap::new()),
            probe: std::sync::Mutex::new(None),
            tun: std::sync::Mutex::new(None),
        })
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
            .timeout(Duration::from_millis(timeout_ms))
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
                } else {
                    reqwest::Proxy::http(url)
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
        if guard.len() > LAX_LIMIT {
            let mut entries: Vec<(String, Instant)> =
                guard.iter().map(|(k, v)| (k.clone(), *v)).collect();
            entries.sort_by_key(|(_, until)| *until);
            let drop_count = entries.len() - LAX_LIMIT;
            for (name, _) in entries.into_iter().take(drop_count) {
                guard.remove(&name);
            }
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

    fn attempt(&self, req: &Req, use_lax: bool, limit: usize) -> Attempt {
        if let Some(token) = req.batch {
            if !crate::sources::batch_alive(token) {
                return Attempt::Cancelled;
            }
        }
        let timeout_ms = req.timeout.unwrap_or(self.default_timeout) * 1000;
        let proxied = !bypass(&host_of(req.url), &self.resolved);
        let client = match self.client(timeout_ms, use_lax, proxied) {
            Ok(client) => client,
            Err(exc) => return Attempt::Other(exc.search_text()),
        };
        let proxy_in_play = proxied && self.resolved.mode != "none";
        let referer = req.referer.to_string();
        let headers: Vec<(String, String)> = req
            .headers
            .iter()
            .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
            .collect();
        let url = req.url.to_string();
        let data = req.data.map(|d| d.to_vec());

        self.rt.block_on(async move {
            let mut builder = match data {
                Some(body) => client.post(&url).body(body),
                None => client.get(&url),
            };
            if !referer.is_empty() {
                builder = builder.header(reqwest::header::REFERER, referer);
            }
            for (name, value) in headers {
                builder = builder.header(name, value);
            }
            let response = match builder.send().await {
                Ok(response) => response,
                Err(error) => return classify_error(&error, proxy_in_play),
            };
            let status = response.status();
            if !status.is_success() {
                let body = match read_body(response, CAPTCHA_SCAN_BYTES, false).await {
                    BodyRead::Ok(bytes) => bytes,
                    _ => Vec::new(),
                };
                return Attempt::Http {
                    code: status.as_u16(),
                    body: String::from_utf8_lossy(&body).to_string(),
                };
            }
            match read_body(response, limit, true).await {
                BodyRead::Ok(bytes) => Attempt::Ok(bytes),
                BodyRead::TooLarge => Attempt::TooLarge,
                BodyRead::Failed(message) => Attempt::Other(message),
            }
        })
    }

    pub fn run_raw(&self, req: &Req, limit: usize) -> SourceResult<Vec<u8>> {
        let retries = req.retries.unwrap_or(self.retries) as i64;
        let mut attempt: i64 = 0;
        let mut use_lax = self.known_lax(req.url);
        while attempt <= retries {
            attempt += 1;
            if let Some(token) = req.batch {
                if !crate::sources::batch_alive(token) {
                    return Err(SourceError::Cancelled);
                }
            }
            match self.attempt(req, use_lax, limit) {
                Attempt::Ok(raw) => return Ok(raw),
                Attempt::Cancelled => return Err(SourceError::Cancelled),
                Attempt::TooLarge => return Err(SourceError::TooLarge { limit }),
                Attempt::Http { code, body } => {
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
                        std::thread::sleep(Duration::from_secs_f64(1.0 * attempt as f64));
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
                    return Err(SourceError::ProxyUnreachable(self.proxy_hint()))
                }
                Attempt::Timeout => return Err(SourceError::Timeout),
                Attempt::Other(message) => {
                    if attempt <= retries {
                        std::thread::sleep(Duration::from_secs_f64(1.5 * attempt as f64));
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

async fn read_body(mut response: reqwest::Response, limit: usize, strict: bool) -> BodyRead {
    let mut out: Vec<u8> = Vec::new();
    let mut got = 0usize;
    loop {
        match response.chunk().await {
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
