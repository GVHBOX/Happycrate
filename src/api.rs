use std::collections::BTreeMap;
use std::path::PathBuf;

use serde_json::{Map, Value};

use crate::config::Config;
use crate::net::parse_proxy;
use crate::sources::Req;
use crate::outcome::{state_of, HEALTH_WINDOW};
use crate::query;
use crate::settings::{settings_defaults, Settings};

pub const MAX_QUERY_LEN: usize = 100;
pub const FILES_CAP: usize = 200;
pub const MAX_TORRENT_BYTES: usize = 8 * 1024 * 1024;

pub enum TorrentError {
    TooLarge,
    Other(String),
}

fn find_ci_bytes(hay: &[u8], needle: &[u8], from: usize) -> Option<usize> {
    if needle.is_empty() || hay.len() < needle.len() {
        return None;
    }
    for start in from..=hay.len() - needle.len() {
        if hay[start..start + needle.len()].eq_ignore_ascii_case(needle) {
            return Some(start);
        }
    }
    None
}

fn ends_ci(hay: &[u8], suffix: &[u8]) -> bool {
    hay.len() >= suffix.len() && hay[hay.len() - suffix.len()..].eq_ignore_ascii_case(suffix)
}

fn is_absolute_href(rest: &[u8]) -> bool {
    if rest.starts_with(b"//") {
        return true;
    }
    let scheme: &[u8] = if rest.len() >= 7 { &rest[..7] } else { rest };
    scheme.eq_ignore_ascii_case(b"http://") || scheme.eq_ignore_ascii_case(b"https://")
}

fn href_value(page: &[u8], from: usize) -> Option<(usize, Vec<u8>)> {
    let marker = b"href=\"";
    let at = find_ci_bytes(page, marker, from)?;
    let start = at + marker.len();
    let rest = &page[start..];
    let end = rest.iter().position(|b| *b == b'"')?;
    Some((start, rest[..end].to_vec()))
}

fn abs_link(page: &[u8]) -> Option<String> {
    let mut from = 0usize;
    while let Some((start, content)) = href_value(page, from) {
        if is_absolute_href(&content) && ends_ci(&content, b".torrent") {
            return Some(content.iter().map(|b| *b as char).collect());
        }
        from = start;
    }
    let mut from = 0usize;
    while let Some((start, content)) = href_value(page, from) {
        if content.starts_with(b"/") && content.len() > 1 && ends_ci(&content, b".torrent") {
            return Some(content.iter().map(|b| *b as char).collect());
        }
        from = start;
    }
    None
}

fn scheme_and_host(url: &str) -> (String, String) {
    let split = match url.find("://") {
        Some(at) => (&url[..at], &url[at + 3..]),
        None => ("", url),
    };
    let authority = split.1.split(['/', '?', '#']).next().unwrap_or("");
    (split.0.to_string(), authority.to_string())
}
pub const APP_TITLE: &str = "happycrate";
pub const APP_VERSION: &str = "1.0.2";

pub fn hex_color_ok(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() == 7
        && bytes[0] == b'#'
        && bytes[1..].iter().all(|b| b.is_ascii_hexdigit())
}

pub fn log_file_string() -> String {
    let path = crate::paths::log_path();
    std::path::absolute(&path)
        .unwrap_or(path)
        .to_string_lossy()
        .to_string()
}

pub fn proxy_desc(settings: &Settings) -> String {
    let manual = settings.get("proxy");
    let manual = if crate::config::truthy(&manual) {
        crate::config::py_str(&manual).trim().to_string()
    } else {
        String::new()
    };
    if !manual.is_empty() {
        return format!("手动设置 {}", redact(&manual));
    }
    let info = crate::net::system_proxies();
    let addr = info
        .get("https")
        .or_else(|| info.get("http"))
        .cloned()
        .unwrap_or_default();
    if addr.is_empty() {
        return "未检测到代理".to_string();
    }
    format!("跟随系统 {}", redact(&addr))
}

pub fn py_len(text: &str) -> usize {
    text.chars().count()
}

pub const RELAX_RANK: [(&str, i64); 8] = [
    ("QUALITY", 0),
    ("CODEC", 1),
    ("YEAR", 2),
    ("MISC", 3),
    ("AUDIO", 4),
    ("LANG", 5),
    ("TYPE", 6),
    ("GENRE", 7),
];

fn relax_rank(role: &str) -> i64 {
    RELAX_RANK
        .iter()
        .find(|(name, _)| *name == role)
        .map(|(_, rank)| *rank)
        .unwrap_or(99)
}

pub fn relaxed_query(parsed: &Value, dropped: &[String]) -> (String, String) {
    let tokens: Vec<String> = match parsed.get("tokens") {
        Some(Value::Array(list)) => list.iter().map(crate::config::py_str).collect(),
        _ => Vec::new(),
    };
    let subject: Vec<String> = match parsed.get("subject") {
        Some(Value::Array(list)) => list.iter().map(crate::config::py_str).collect(),
        _ => Vec::new(),
    };
    if tokens.len() <= 1 {
        return (String::new(), String::new());
    }

    let mut droppable: Vec<(i64, String)> = Vec::new();
    if let Some(Value::Array(list)) = parsed.get("mods") {
        for item in list {
            let role = item.get("role").map(crate::config::py_str).unwrap_or_default();
            let text = item.get("text").map(crate::config::py_str).unwrap_or_default();
            droppable.push((relax_rank(&role), text));
        }
    }
    if let Some(Value::Array(list)) = parsed.get("soft") {
        for item in list {
            let kind = item.get("kind").map(crate::config::py_str).unwrap_or_default();
            let text = item.get("text").map(crate::config::py_str).unwrap_or_default();
            droppable.push((relax_rank(&kind), text));
        }
    }
    droppable.sort_by_key(|(rank, _)| *rank);

    for (_, text) in droppable {
        if !tokens.contains(&text) || subject.contains(&text) || dropped.contains(&text) {
            continue;
        }
        let rest: Vec<String> = tokens
            .iter()
            .filter(|token| **token != text && !dropped.contains(token))
            .cloned()
            .collect();
        if !rest.is_empty() {
            return (rest.join(" "), text);
        }
    }
    (String::new(), String::new())
}

pub fn item_view(item: &Value, now: &crate::util::LocalNow) -> Value {
    let size = item.get("size").cloned().unwrap_or(Value::Null);
    let added = item.get("added").cloned().unwrap_or(Value::Null);

    let names: Vec<String> = match item.get("sources") {
        Some(Value::Array(list)) if !list.is_empty() => {
            list.iter().map(crate::config::py_str).collect()
        }
        _ => match item.get("source") {
            Some(value) if crate::config::truthy(value) => {
                vec![crate::config::py_str(value)]
            }
            _ => Vec::new(),
        },
    };

    let files: Vec<Value> = match item.get("files") {
        Some(Value::Array(list)) => list
            .iter()
            .filter(|entry| entry.is_object())
            .filter(|entry| {
                entry
                    .get("n")
                    .map(crate::config::truthy)
                    .unwrap_or(false)
            })
            .take(FILES_CAP)
            .map(|entry| {
                let name = entry.get("n").map(crate::config::py_str).unwrap_or_default();
                let shown = entry.get("s").map(crate::config::py_str).unwrap_or_default();
                let text = if !shown.is_empty() {
                    shown
                } else {
                    match entry.get("b") {
                        Some(value) if crate::config::truthy(value) => {
                            crate::core::format_size(value)
                        }
                        _ => String::new(),
                    }
                };
                let mut row = Map::new();
                row.insert("n".to_string(), Value::from(name));
                row.insert("s".to_string(), Value::from(text));
                Value::Object(row)
            })
            .collect(),
        _ => Vec::new(),
    };

    let fetch = match item.get("fetch") {
        Some(Value::Object(map)) => {
            let url = map
                .get("url")
                .map(crate::config::py_str)
                .unwrap_or_default();
            if url.starts_with("http://") || url.starts_with("https://") {
                let mut out = Map::new();
                out.insert("url".to_string(), Value::from(url));
                Value::Object(out)
            } else {
                Value::Object(Map::new())
            }
        }
        _ => Value::Object(Map::new()),
    };

    let hash = item
        .get("info_hash")
        .map(crate::config::py_str)
        .unwrap_or_default()
        .to_lowercase();
    let title = item
        .get("title")
        .map(crate::config::py_str)
        .unwrap_or_default();

    let mut out = Map::new();
    out.insert("hash".to_string(), Value::from(hash));
    out.insert("title".to_string(), Value::from(title));
    out.insert(
        "size".to_string(),
        Value::from(crate::config::py_int(&size).unwrap_or(0)),
    );
    out.insert("sizeText".to_string(), Value::from(crate::core::format_size(&size)));
    out.insert(
        "seeders".to_string(),
        crate::config::py_int(item.get("seeders").unwrap_or(&Value::Null))
            .map(Value::from)
            .unwrap_or(Value::Null),
    );
    out.insert(
        "leechers".to_string(),
        crate::config::py_int(item.get("leechers").unwrap_or(&Value::Null))
            .map(Value::from)
            .unwrap_or(Value::Null),
    );
    out.insert(
        "added".to_string(),
        Value::from(crate::config::py_int(&added).unwrap_or(0)),
    );
    out.insert(
        "addedText".to_string(),
        Value::from(crate::core::format_time_relative(&added, now)),
    );
    out.insert("magnet".to_string(), Value::from(crate::core::magnet_of(item)));
    out.insert(
        "sources".to_string(),
        Value::Array(
            names
                .into_iter()
                .filter(|name| !name.is_empty())
                .map(Value::from)
                .collect(),
        ),
    );
    out.insert("files".to_string(), Value::Array(files));
    out.insert("fetch".to_string(), fetch);
    Value::Object(out)
}

pub fn is_query_too_long(text: &str) -> bool {
    py_len(text) > MAX_QUERY_LEN
}

pub fn redact(text: &str) -> String {
    let chars: Vec<char> = text.chars().collect();
    let n = chars.len();
    let mut out = String::with_capacity(text.len());
    let mut cursor = 0usize;
    let mut search = 0usize;
    while search + 2 <= n {
        if chars[search] != '/' || chars[search + 1] != '/' {
            search += 1;
            continue;
        }
        let begin = search + 2;
        let mut end = begin;
        while end < n
            && chars[end] != '/'
            && chars[end] != '@'
            && !crate::util::is_py_space(chars[end])
        {
            end += 1;
        }
        if end >= n || chars[end] != '@' {
            search += 1;
            continue;
        }
        let segment: Vec<char> = chars[begin..end].to_vec();
        let Some(at) = segment.iter().rposition(|c| *c == ':') else {
            search += 1;
            continue;
        };
        if at == 0 || at + 1 >= segment.len() {
            search += 1;
            continue;
        }
        out.extend(chars[cursor..begin].iter());
        out.push_str("***");
        cursor = end;
        search = end;
    }
    out.extend(chars[cursor..].iter());
    out
}

pub fn base_of(key: &str, base: &str) -> String {
    let chosen = if base.is_empty() {
        crate::sources::default_base(key)
    } else {
        base
    };
    chosen.trim_end_matches('/').to_string()
}

pub fn addr_of(entry: &Value) -> String {
    let key = entry.get("key").and_then(Value::as_str).unwrap_or("");
    let base = entry.get("base").and_then(Value::as_str).unwrap_or("");
    redact(&base_of(key, base))
}

pub fn source_view(entry: &Value) -> Value {
    let key = entry.get("key").and_then(Value::as_str).unwrap_or("");
    let label = match entry.get("label") {
        Some(value) => value.clone(),
        None => Value::from(key),
    };
    let enabled = match entry.get("enabled") {
        Some(value) => crate::config::truthy(value),
        None => true,
    };
    let health = entry.get("health").cloned().unwrap_or(Value::Null);
    let outcomes: Vec<String> = match health.get("outcomes") {
        Some(Value::Array(list)) => list
            .iter()
            .filter_map(|v| v.as_str().map(str::to_string))
            .filter(|s| !s.is_empty())
            .collect(),
        _ => Vec::new(),
    };
    let start = outcomes.len().saturating_sub(HEALTH_WINDOW);

    let mut health_view = Map::new();
    health_view.insert(
        "ms".to_string(),
        Value::from(crate::config::py_int(health.get("ms").unwrap_or(&Value::Null)).unwrap_or(0)),
    );
    health_view.insert(
        "err".to_string(),
        Value::from(match health.get("err") {
            Some(Value::String(text)) => text.clone(),
            _ => String::new(),
        }),
    );
    health_view.insert("state".to_string(), Value::from(state_of(&outcomes)));
    health_view.insert(
        "outcomes".to_string(),
        Value::Array(
            outcomes[start..]
                .iter()
                .cloned()
                .map(Value::from)
                .collect(),
        ),
    );

    let mut view = Map::new();
    view.insert("key".to_string(), Value::from(key));
    view.insert("label".to_string(), label);
    view.insert("enabled".to_string(), Value::Bool(enabled));
    view.insert("addr".to_string(), Value::from(addr_of(entry)));
    view.insert("health".to_string(), Value::Object(health_view));
    Value::Object(view)
}

pub struct Api {
    pub config: Config,
    pub settings: Settings,
    pub last_write_error: String,
    pub search_token: i64,
    pub migration: crate::migrate::Report,
    probe_seen: crate::probe::Seen,
    http: std::sync::Mutex<Option<std::sync::Arc<crate::net::HttpClient>>>,
    push: Option<std::sync::Arc<crate::search::Sink>>,
}

impl Api {
    pub fn new(config_path: Option<PathBuf>, settings_path: Option<PathBuf>) -> Self {
        Api {
            config: Config::new(config_path),
            settings: Settings::new(settings_path),
            last_write_error: String::new(),
            search_token: 0,
            migration: crate::migrate::Report::default(),
            probe_seen: std::sync::Arc::new(std::sync::Mutex::new(BTreeMap::new())),
            http: std::sync::Mutex::new(None),
            push: None,
        }
    }

    pub fn set_push(&mut self, sink: std::sync::Arc<crate::search::Sink>) {
        self.push = Some(sink);
    }

    pub fn reset_http(&self) {
        let mut guard = self.http.lock().unwrap_or_else(|e| e.into_inner());
        *guard = None;
    }

    pub fn http(&self) -> Option<std::sync::Arc<crate::net::HttpClient>> {
        let mut guard = self.http.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(client) = guard.as_ref() {
            return Some(client.clone());
        }
        let ua = match std::env::var("HAPPYCRATE_UA") {
            Ok(value) if !value.is_empty() => value,
            _ => {
                let configured = crate::config::py_str(&self.settings.get("user_agent"));
                if configured.is_empty() {
                    crate::net::DEFAULT_UA.to_string()
                } else {
                    configured
                }
            }
        };
        let retries = self.settings.as_int("retries", 1).max(0) as u32;
        let timeout = self.settings.as_int("timeout", 15).max(1) as u64;
        let proxy = crate::config::py_str(&self.settings.get("proxy"));
        match crate::net::HttpClient::new(ua, retries, timeout, &proxy) {
            Ok(client) => {
                let arc = std::sync::Arc::new(client);
                *guard = Some(arc.clone());
                Some(arc)
            }
            Err(err) => {
                crate::log::error(crate::log::API, &format!("创建网络客户端失败：{err:?}"));
                None
            }
        }
    }

    pub fn torrent_meta(
        &self,
        url: &str,
        timeout: i64,
        referer: &str,
    ) -> Result<Vec<crate::bencode::FileEntry>, TorrentError> {
        torrent_meta_fetch(self.http().as_deref(), url, timeout, referer)
    }

    pub fn torrent_files(&self, payload: &Value) -> Value {
        torrent_files_fetch(
            self.http().as_deref(),
            self.settings.as_int("timeout", 15),
            payload,
        )
    }

    pub fn downloaders(&self) -> Vec<Value> {
        let found: Vec<&'static str> = crate::downloaders::available_downloaders(false)
            .iter()
            .map(|info| info.key)
            .collect();
        crate::downloaders::all_downloaders()
            .iter()
            .map(|info| {
                let mut map = Map::new();
                map.insert("key".to_string(), Value::from(info.key));
                map.insert("label".to_string(), Value::from(info.label));
                map.insert(
                    "available".to_string(),
                    Value::Bool(found.contains(&info.key)),
                );
                Value::Object(map)
            })
            .collect()
    }

    pub fn deliver(&mut self, magnets: &[Value], key: &str) -> Value {
        let configured = self.settings.get("default_downloader");
        let timeout = self.settings.as_int("timeout", 15);
        deliver_prepared(magnets, key, &configured, timeout)
    }

    pub fn proxy_status(&self, force: bool) -> Value {
        match self.http() {
            Some(client) => client.proxy_status(force),
            None => serde_json::json!({
                "mode": "none", "addr": "", "portOk": false, "works": false,
                "systemOn": false, "tun": "", "checkedAt": 0.0,
            }),
        }
    }

    fn target_of(&self, entry: &Value) -> crate::search::Target {
        let key = entry
            .get("key")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let base = entry
            .get("base")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let timeout = crate::config::py_int(entry.get("timeout").unwrap_or(&Value::Null))
            .filter(|value| *value != 0)
            .unwrap_or(15)
            .max(1) as u64;
        crate::search::Target {
            key,
            base,
            timeout,
        }
    }

    fn enabled_targets(&self, keys: Option<&[String]>) -> Vec<crate::search::Target> {
        self.config
            .sources()
            .iter()
            .filter(|entry| {
                entry
                    .get("enabled")
                    .map(crate::config::truthy)
                    .unwrap_or(false)
            })
            .filter(|entry| match keys {
                Some(wanted) if !wanted.is_empty() => entry
                    .get("key")
                    .and_then(Value::as_str)
                    .map(|key| wanted.iter().any(|item| item == key))
                    .unwrap_or(false),
                _ => true,
            })
            .map(|entry| self.target_of(entry))
            .collect()
    }

    pub fn probe_sources(&mut self, keys: Option<&[String]>) -> i64 {
        let targets = self.enabled_targets(keys);
        if targets.is_empty() {
            if let Some(sink) = self.push.as_ref() {
                sink(crate::search::Event::ProbeDone);
            }
            return 0;
        }
        let Some(http) = self.http() else {
            if let Some(sink) = self.push.as_ref() {
                sink(crate::search::Event::ProbeDone);
            }
            return 0;
        };
        let count = targets.len() as i64;
        crate::probe::spawn(
            targets,
            http,
            self.push.clone(),
            crate::util::local_now(),
            self.probe_seen.clone(),
        );
        count
    }

    pub fn start_search(&mut self, text: &str, page: i64) -> Value {
        let text = crate::util::py_trim(text).to_string();
        let configured = self.settings.as_int("min_query_len", 2);
        let min_len = if configured == 0 { 2 } else { configured };
        if (py_len(&text) as i64) < min_len {
            return serde_json::json!({
                "ok": false, "token": 0, "total": 0,
                "error": crate::core::min_len_message(min_len),
            });
        }
        if is_query_too_long(&text) {
            return serde_json::json!({
                "ok": false, "token": 0, "total": 0,
                "error": format!("关键字最长 {MAX_QUERY_LEN} 个字符"),
            });
        }

        let targets = self.enabled_targets(None);
        if targets.is_empty() {
            return serde_json::json!({
                "ok": false, "token": 0, "total": 0, "error": "没有启用的数据源",
            });
        }

        let Some(http) = self.http() else {
            return serde_json::json!({
                "ok": false, "token": 0, "total": 0, "error": "网络层不可用",
            });
        };

        let parsed = query::parse(&text);
        if self.search_token != 0 {
            crate::sources::cancel_batch(self.search_token);
        }
        let token = crate::sources::start_batch();
        self.search_token = token;

        let hints = crate::search::Hints {
            proxy: http.proxy_hint(),
            has_proxy: http.has_proxy(),
            tun: http.tun_adapter(false),
        };
        let job = crate::search::Job {
            text,
            page: page.max(1),
            parsed: parsed.clone(),
            targets,
            min_len,
            keep_dup: self.settings.get("keep_duplicates") == Value::Bool(true),
            soft_deadline_ms: self.settings.as_int("soft_deadline_ms", 3000),
            max_workers: self.settings.as_int("max_workers", 12).max(1) as usize,
            stamp: crate::search::source_stamp(&self.config.sources()),
            now: crate::util::local_now(),
            token,
            hints,
        };
        let total = job.targets.len();
        crate::search::spawn(job, http, self.push.clone());

        serde_json::json!({
            "ok": true, "token": token, "total": total, "error": "", "query": parsed,
        })
    }

    pub fn cancel_search(&mut self, token: i64) -> bool {
        let target = if token == 0 { self.search_token } else { token };
        self.search_token = 0;
        crate::sources::cancel_batch(target);
        true
    }

    pub fn boot(mut self) -> Self {
        self.config.load();
        self.settings.load();
        self.migration = crate::migrate::run(&mut self.settings, &mut self.config);
        if !self.migration.error.is_empty() {
            let reason = self.migration.error.clone();
            self.note_write(reason);
        }
        if self.migration.sources > 0 {
            let reason = self.config.save();
            self.note_write(reason);
        }
        crate::log::info(
            crate::log::API,
            &format!(
                "{} v{} 启动 · 数据目录 {}",
                APP_TITLE,
                APP_VERSION,
                crate::paths::data_dir().to_string_lossy()
            ),
        );
        self
    }

    fn note_write(&mut self, reason: String) {
        if !reason.is_empty() {
            crate::log::error(crate::log::API, &format!("配置没有写入成功：{reason}"));
        }
        self.last_write_error = reason;
    }

    pub fn list_sources(&self) -> Vec<Value> {
        let seen = self.probe_seen.lock().unwrap().clone();
        self.config
            .sources()
            .iter()
            .map(|entry| {
                let mut view = source_view(entry);
                let key = entry.get("key").and_then(Value::as_str).unwrap_or("");
                if let Some(row) = seen.get(key) {
                    if let Some(fields) = view.as_object_mut() {
                        fields.insert(
                            "health".to_string(),
                            serde_json::json!({
                                "ms": row["ms"],
                                "err": row["err"],
                                "state": row["state"],
                                "outcomes": [row["outcome"]],
                            }),
                        );
                    }
                }
                view
            })
            .collect()
    }

    pub fn source_issues(&self) -> Vec<Value> {
        let seen = self.probe_seen.lock().unwrap().clone();
        let mut out = Vec::new();
        for entry in self.config.sources() {
            let key = match entry.get("key").and_then(Value::as_str) {
                Some(value) => value,
                None => continue,
            };
            let row = match seen.get(key) {
                Some(row) => row,
                None => continue,
            };
            if row.get("state").and_then(Value::as_str).unwrap_or("") != "err" {
                continue;
            }
            let err = row.get("err").and_then(Value::as_str).unwrap_or("");
            let label = match entry.get("label").and_then(Value::as_str) {
                Some(value) => value.to_string(),
                None => key.to_string(),
            };
            out.push(serde_json::json!({
                "key": key,
                "label": label,
                "addr": addr_of(&entry),
                "kind": "fail",
                "detail": if err.is_empty() { "请求失败" } else { err },
            }));
        }
        out
    }

    pub fn toggle_source(&mut self, key: &str, on: bool) -> bool {
        if !self.config.set_enabled(key, on) {
            return false;
        }
        crate::search::cache_clear();
        let reason = self.config.save();
        self.note_write(reason);
        true
    }

    pub fn reorder_sources(&mut self, keys: &[String]) -> bool {
        let order: BTreeMap<&str, usize> = keys
            .iter()
            .enumerate()
            .map(|(index, key)| (key.as_str(), index))
            .collect();
        let fallback = order.len();
        let mut entries = self.config.sources();
        entries.sort_by_key(|entry| {
            let key = entry.get("key").and_then(Value::as_str).unwrap_or("");
            *order.get(key).unwrap_or(&fallback)
        });
        for (index, entry) in entries.iter_mut().enumerate() {
            if let Some(map) = entry.as_object_mut() {
                map.insert("order".to_string(), Value::from(index as i64));
            }
        }
        if let Some(map) = self.config.data.as_object_mut() {
            map.insert("sources".to_string(), Value::Array(entries));
        }
        self.config.set_order_locked(true);
        let reason = self.config.save();
        self.note_write(reason);
        true
    }

    pub fn set_auto_order(&mut self, on: bool) -> bool {
        self.config.set_order_locked(!on);
        let reason = self.config.save();
        self.note_write(reason);
        true
    }

    pub fn get_settings(&self) -> Value {
        let mut out = Map::new();
        for key in crate::settings::spec_keys() {
            if let Some(value) = self.settings.data.get(key) {
                out.insert(key.to_string(), value.clone());
            }
        }
        Value::Object(out)
    }

    pub fn default_settings(&self) -> Value {
        let defaults = settings_defaults();
        let mut out = Map::new();
        for key in crate::settings::spec_keys() {
            let value = defaults.get(key).cloned().unwrap_or(Value::Null);
            out.insert(key.to_string(), value);
        }
        Value::Object(out)
    }

    pub fn save_settings(&mut self, fields: &Value) -> Value {
        let proxy = match fields.get("proxy") {
            Some(value) if crate::config::truthy(value) => crate::config::py_str(value),
            _ => String::new(),
        };
        let proxy = proxy.trim().to_string();
        let (_mapping, proxy_err) = parse_proxy(&proxy);
        if !proxy_err.is_empty() {
            return settings_result(false, vec![proxy_err]);
        }

        let pairs: Vec<(String, Value)> = match fields.as_object() {
            Some(map) => map
                .iter()
                .map(|(key, value)| (key.clone(), value.clone()))
                .collect(),
            None => Vec::new(),
        };
        let refs: Vec<(&str, Value)> = pairs
            .iter()
            .map(|(key, value)| (key.as_str(), value.clone()))
            .collect();
        let bad = self.settings.update(&refs);
        if !bad.is_empty() {
            return settings_result(false, bad);
        }

        let reason = self.settings.save();
        self.reset_http();
        crate::search::cache_clear();
        self.note_write(reason.clone());
        if !reason.is_empty() {
            return settings_result(
                false,
                vec![format!("改动未能保存到磁盘：{reason}")],
            );
        }
        settings_result(true, Vec::new())
    }

    pub fn reload_query_roles(&mut self) -> bool {
        query::reload();
        crate::search::cache_clear();
        true
    }

    pub fn selftest(&self) -> Value {
        let mut missing: Vec<String> = Vec::new();
        let view = self.list_sources();
        if view.is_empty() {
            missing.push("sources 为空".to_string());
        } else {
            for field in ["key", "label", "enabled", "addr", "health"] {
                if view[0].get(field).is_none() {
                    missing.push(field.to_string());
                }
            }
        }
        let mut out = Map::new();
        out.insert("ok".to_string(), Value::Bool(missing.is_empty()));
        out.insert(
            "missing".to_string(),
            Value::Array(missing.into_iter().map(Value::from).collect()),
        );
        Value::Object(out)
    }

    pub fn app_info(&self) -> Value {
        let (directory, _mode, label) = crate::paths::describe();
        let mut recovered: Vec<Value> = Vec::new();
        for backup in [&self.config.broken, &self.settings.broken] {
            if let Some(path) = backup {
                recovered.push(Value::from(path.to_string_lossy().to_string()));
            }
        }
        let mut out = Map::new();
        out.insert("version".to_string(), Value::from(APP_VERSION));
        out.insert(
            "dataDir".to_string(),
            Value::from(directory.to_string_lossy().to_string()),
        );
        out.insert("mode".to_string(), Value::from(label));
        out.insert("logFile".to_string(), Value::from(log_file_string()));
        out.insert(
            "migratedFrom".to_string(),
            Value::from(if self.migration.done {
                self.migration.source.clone()
            } else {
                String::new()
            }),
        );
        out.insert("proxy".to_string(), Value::from(proxy_desc(&self.settings)));
        out.insert(
            "autoOrder".to_string(),
            Value::Bool(!self.config.order_locked()),
        );
        out.insert("recovered".to_string(), Value::Array(recovered));
        Value::Object(out)
    }

    pub fn open_logs(&self) -> bool {
        let directory = crate::paths::logs_dir();
        if std::fs::create_dir_all(&directory).is_err() {
            return false;
        }
        std::process::Command::new("explorer")
            .arg(directory.as_os_str())
            .spawn()
            .is_ok()
    }

}

fn map_torrent_error(error: crate::model::SourceError) -> TorrentError {
    match error {
        crate::model::SourceError::TooLarge { .. } => TorrentError::TooLarge,
        other => TorrentError::Other(other.search_text()),
    }
}

pub fn torrent_meta_fetch(
    client: Option<&crate::net::HttpClient>,
    url: &str,
    timeout: i64,
    referer: &str,
) -> Result<Vec<crate::bencode::FileEntry>, TorrentError> {
    let Some(client) = client else {
        return Err(TorrentError::Other("URLError: 网络层不可用".to_string()));
    };
    let mut target = url.to_string();
    if !url.to_lowercase().ends_with(".torrent") {
        let page = client
            .fetch_bytes(
                &Req::get(url).referer(referer).timeout(timeout.max(1) as u64),
                MAX_TORRENT_BYTES,
            )
            .map_err(map_torrent_error)?;
        let Some(link) = abs_link(&page) else {
            return Ok(Vec::new());
        };
        if let Some(rest) = link.strip_prefix("//") {
            target = format!("https://{rest}");
        } else if link.starts_with('/') {
            let (scheme, host) = scheme_and_host(url);
            target = format!("{scheme}://{host}{link}");
        } else {
            target = link;
        }
    }
    let data = client
        .fetch_bytes(
            &Req::get(&target)
                .referer(referer)
                .retries(0)
                .timeout(timeout.max(1) as u64),
            MAX_TORRENT_BYTES,
        )
        .map_err(map_torrent_error)?;
    crate::bencode::decode_torrent_files(&data).map_err(TorrentError::Other)
}

pub fn torrent_files_fetch(
    client: Option<&crate::net::HttpClient>,
    timeout: i64,
    payload: &Value,
) -> Value {
    let url = match payload.get("url") {
        Some(value) if crate::config::truthy(value) => crate::config::py_str(value),
        _ => String::new(),
    };
    if !url.starts_with("http://") && !url.starts_with("https://") {
        return torrent_result(false, Vec::new(), "缺少有效的种子地址");
    }
    let (scheme, host) = scheme_and_host(&url);
    let referer = format!("{scheme}://{host}/");
    match torrent_meta_fetch(client, &url, timeout, &referer) {
        Err(TorrentError::TooLarge) => {
            torrent_result(false, Vec::new(), "种子文件过大，已拒绝读取")
        }
        Err(TorrentError::Other(text)) => {
            let clipped: String = text.chars().take(180).collect();
            torrent_result(false, Vec::new(), &clipped)
        }
        Ok(rows) => {
            let files: Vec<Value> = rows
                .iter()
                .filter(|row| !row.name.is_empty())
                .take(FILES_CAP)
                .map(|row| {
                    let mut entry = Map::new();
                    entry.insert("n".to_string(), Value::from(row.name.clone()));
                    entry.insert(
                        "s".to_string(),
                        Value::from(crate::core::format_size(&Value::from(row.bytes))),
                    );
                    Value::Object(entry)
                })
                .collect();
            if files.is_empty() {
                return torrent_result(false, Vec::new(), "种子内没有文件清单");
            }
            torrent_result(true, files, "")
        }
    }
}

fn torrent_result(ok: bool, files: Vec<Value>, error: &str) -> Value {
    let mut map = Map::new();
    map.insert("ok".to_string(), Value::Bool(ok));
    map.insert("files".to_string(), Value::Array(files));
    map.insert("error".to_string(), Value::from(error));
    Value::Object(map)
}

pub fn deliver_prepared(
    magnets: &[Value],
    key: &str,
    configured: &Value,
    timeout: i64,
) -> Value {
    let items: Vec<String> = magnets
        .iter()
        .filter(|value| crate::config::truthy(value))
        .map(crate::config::py_str)
        .collect();
    if items.is_empty() {
        return deliver_result(false, "没有可提交的磁力链接");
    }
    let cap = crate::downloaders::MAGNET_CAP;
    if items.len() > cap {
        return deliver_result(
            false,
            &format!("一次最多提交 {cap} 条，本次 {} 条", items.len()),
        );
    }

    let prefer = if !key.is_empty() {
        key.to_string()
    } else if crate::config::truthy(configured) {
        crate::config::py_str(configured)
    } else {
        String::new()
    };
    if crate::downloaders::pick_default(&prefer, true).is_none() {
        return deliver_result(false, "没找到可用的下载工具");
    }

    let outcome = crate::downloaders::add(&items, timeout, &[]);
    if !outcome.ok {
        crate::log::warning(
            crate::log::API,
            &format!("投递失败：{}", outcome.message()),
        );
    }
    deliver_result(outcome.ok, &outcome.message())
}

fn deliver_result(ok: bool, message: &str) -> Value {
    let mut map = Map::new();
    map.insert("ok".to_string(), Value::Bool(ok));
    map.insert("message".to_string(), Value::from(message));
    Value::Object(map)
}

fn settings_result(ok: bool, errors: Vec<String>) -> Value {
    let mut map = Map::new();
    map.insert("ok".to_string(), Value::Bool(ok));
    map.insert(
        "errors".to_string(),
        Value::Array(errors.into_iter().map(Value::from).collect()),
    );
    Value::Object(map)
}
