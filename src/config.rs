use std::path::{Path, PathBuf};

use serde_json::{Map, Value};

use crate::paths;

pub const SOURCES_VERSION: i64 = 1;
pub const SETTINGS_VERSION: i64 = 1;
pub const SOURCE_TIMEOUT_MIN: i64 = 1;
pub const SOURCE_TIMEOUT_MAX: i64 = 120;
pub const TMP_PREFIX: &str = ".happycrate-tmp-";

pub const RETIRED_SOURCES: [&str; 2] = ["btdig", "apibay_adult"];

pub const DEFAULT_SOURCES: [(&str, &str, i64, i64, bool); 12] = [
    ("apibay", "海盗湾", 15, 0, true),
    ("nyaa", "Nyaa", 15, 1, true),
    ("mikan", "蜜柑计划", 15, 2, true),
    ("dmhy", "动漫花园", 15, 3, true),
    ("sukebei", "Sukebei", 15, 4, true),
    ("eztv", "EZTV", 15, 5, true),
    ("tpb", "TPB镜像", 15, 6, true),
    ("knaben", "Knaben", 15, 7, true),
    ("xccl263", "小草磁力", 20, 8, true),
    ("javbus", "JavBus", 20, 9, true),
    ("bitsearch", "BitSearch", 15, 10, false),
    ("javdb", "JavDB", 20, 11, false),
];

fn default_source(key: &str, label: &str, timeout: i64, order: i64, enabled: bool) -> Value {
    let mut map = Map::new();
    map.insert("key".to_string(), Value::from(key));
    map.insert("label".to_string(), Value::from(label));
    map.insert("type".to_string(), Value::from("builtin"));
    map.insert("enabled".to_string(), Value::from(enabled));
    map.insert("timeout".to_string(), Value::from(timeout));
    map.insert("base".to_string(), Value::from(""));
    map.insert("order".to_string(), Value::from(order));
    Value::Object(map)
}

pub fn defaults() -> Value {
    let mut map = Map::new();
    map.insert("version".to_string(), Value::from(SOURCES_VERSION));
    map.insert(
        "sources".to_string(),
        Value::Array(
            DEFAULT_SOURCES
                .iter()
                .map(|(key, label, timeout, order, enabled)| {
                    default_source(key, label, *timeout, *order, *enabled)
                })
                .collect(),
        ),
    );
    Value::Object(map)
}

pub fn py_int(value: &Value) -> Option<i64> {
    match value {
        Value::Null => None,
        Value::Bool(b) => Some(i64::from(*b)),
        Value::Number(n) => n
            .as_i64()
            .or_else(|| n.as_f64().filter(|f| f.is_finite()).map(|f| f as i64)),
        Value::String(s) => {
            let trimmed = s.trim();
            if trimmed.is_empty() {
                None
            } else {
                trimmed.parse::<i64>().ok()
            }
        }
        _ => None,
    }
}

pub fn clamp_timeout(value: &Value) -> i64 {
    clamp_timeout_with(value, 15)
}

pub fn clamp_timeout_with(value: &Value, default: i64) -> i64 {
    match py_int(value) {
        Some(num) => num.clamp(SOURCE_TIMEOUT_MIN, SOURCE_TIMEOUT_MAX),
        None => default,
    }
}

pub fn py_str(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        Value::Bool(b) => {
            if *b {
                "True".to_string()
            } else {
                "False".to_string()
            }
        }
        _ => String::new(),
    }
}

pub fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(false),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

pub fn broken_path(path: &Path) -> PathBuf {
    let text = path.to_string_lossy().to_string();
    if text.to_lowercase().ends_with(".json") {
        return PathBuf::from(format!("{}.broken.json", &text[..text.len() - 5]));
    }
    PathBuf::from(format!("{text}.broken"))
}

pub fn sweep_temp_files(directory: &Path) -> usize {
    let Ok(entries) = std::fs::read_dir(directory) else {
        return 0;
    };
    let mut removed = 0usize;
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().to_string();
        if !name.starts_with(TMP_PREFIX) {
            continue;
        }
        if std::fs::remove_file(entry.path()).is_ok() {
            removed += 1;
        }
    }
    if removed > 0 {
        crate::log::info(
            crate::log::CONFIG,
            &format!("清理了 {removed} 个残留临时文件"),
        );
    }
    removed
}

pub fn atomic_write_json(path: &Path, data: &Value) -> String {
    let directory = path
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));
    if let Err(error) = std::fs::create_dir_all(&directory) {
        crate::log::error(
            crate::log::CONFIG,
            &format!("写入 {} 失败：{error}", path.display()),
        );
        return format!("写入失败：{error}");
    }
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let temp = directory.join(format!("{TMP_PREFIX}{}-{stamp}.json", std::process::id()));
    let body = serde_json::to_string_pretty(data).unwrap_or_default();
    match std::fs::write(&temp, body) {
        Ok(()) => {}
        Err(error) => {
            let _ = std::fs::remove_file(&temp);
            crate::log::error(
                crate::log::CONFIG,
                &format!("写入 {} 失败：{error}", path.display()),
            );
            return format!("写入失败：{error}");
        }
    }
    if let Err(error) = std::fs::rename(&temp, path) {
        let _ = std::fs::remove_file(&temp);
        crate::log::error(
            crate::log::CONFIG,
            &format!("写入 {} 失败：{error}", path.display()),
        );
        return format!("写入失败：{error}");
    }
    String::new()
}

pub fn load_json(path: &Path) -> (Value, bool, Option<PathBuf>) {
    if !path.is_file() {
        return (Value::Null, true, None);
    }
    let failed = |reason: String| {
        let backup = broken_path(path);
        crate::log::error(
            crate::log::CONFIG,
            &format!(
                "配置 {} 解析失败（{reason}），已备份为 {} 并回退默认",
                path.display(),
                backup.display()
            ),
        );
        if let Err(copy_error) = std::fs::copy(path, &backup) {
            crate::log::warning(
                crate::log::CONFIG,
                &format!("备份损坏配置失败：{copy_error}"),
            );
        }
        (Value::Null, true, Some(backup))
    };
    match std::fs::read_to_string(path) {
        Ok(text) => match serde_json::from_str::<Value>(&text) {
            Ok(parsed) => (parsed, false, None),
            Err(error) => failed(error.to_string()),
        },
        Err(error) => failed(error.to_string()),
    }
}

pub struct Config {
    pub path: PathBuf,
    pub data: Value,
    pub broken: Option<PathBuf>,
}

impl Config {
    pub fn new(path: Option<PathBuf>) -> Self {
        Config {
            path: path.unwrap_or_else(paths::sources_path),
            data: defaults(),
            broken: None,
        }
    }

    pub fn load(&mut self) -> &mut Self {
        let (raw, is_default, broken) = load_json(&self.path);
        self.broken = broken;
        self.data = if is_default { defaults() } else { raw };
        self.normalize();
        self
    }

    pub fn normalize(&mut self) {
        let mut source_list: Vec<Value> = match self.data.get("sources") {
            Some(Value::Array(list)) => list.clone(),
            _ => Vec::new(),
        };

        let mut cleaned: Vec<Value> = Vec::new();
        let mut seen: Vec<String> = Vec::new();
        for item in source_list.drain(..) {
            let Some(entry) = item.as_object() else {
                continue;
            };
            let key = py_str(entry.get("key").unwrap_or(&Value::Null))
                .trim()
                .to_string();
            if key.is_empty() || seen.contains(&key) {
                continue;
            }
            if RETIRED_SOURCES.contains(&key.as_str()) {
                crate::log::info(
                    crate::log::CONFIG,
                    &format!("数据源 {key} 已下线，从配置中移除"),
                );
                continue;
            }
            seen.push(key.clone());
            let mut entry = entry.clone();
            entry.insert("key".to_string(), Value::from(key.clone()));
            entry
                .entry("label".to_string())
                .or_insert_with(|| Value::from(key.clone()));
            entry
                .entry("type".to_string())
                .or_insert_with(|| Value::from("builtin"));
            entry
                .entry("enabled".to_string())
                .or_insert(Value::Bool(true));
            let timeout = clamp_timeout(entry.get("timeout").unwrap_or(&Value::Null));
            entry.insert("timeout".to_string(), Value::from(timeout));
            entry
                .entry("base".to_string())
                .or_insert_with(|| Value::from(""));
            let order = entry
                .get("order")
                .filter(|v| truthy(v))
                .and_then(py_int)
                .unwrap_or(0);
            entry.insert("order".to_string(), Value::from(order));
            cleaned.push(Value::Object(entry));
        }

        for (key, label, timeout, order, enabled) in DEFAULT_SOURCES {
            if seen.contains(&key.to_string()) {
                continue;
            }
            seen.push(key.to_string());
            crate::log::info(
                crate::log::CONFIG,
                &format!("数据源 {key} 为新增内置源，已加入配置"),
            );
            let mut fresh = default_source(key, label, timeout, order, enabled);
            if let Some(map) = fresh.as_object_mut() {
                map.insert("order".to_string(), Value::from(cleaned.len() as i64));
            }
            cleaned.push(fresh);
        }

        cleaned.sort_by_key(|entry| {
            entry
                .get("order")
                .and_then(py_int)
                .unwrap_or(0)
        });
        for (index, entry) in cleaned.iter_mut().enumerate() {
            if let Some(map) = entry.as_object_mut() {
                map.insert("order".to_string(), Value::from(index as i64));
            }
        }

        if let Some(map) = self.data.as_object_mut() {
            map.insert("version".to_string(), Value::from(SOURCES_VERSION));
            map.insert("sources".to_string(), Value::Array(cleaned));
        } else {
            let mut map = Map::new();
            map.insert("version".to_string(), Value::from(SOURCES_VERSION));
            map.insert("sources".to_string(), Value::Array(cleaned));
            self.data = Value::Object(map);
        }
    }

    pub fn save(&mut self) -> String {
        self.normalize();
        let mut payload = self.data.clone();
        if let Some(map) = payload.as_object_mut() {
            let stripped: Vec<Value> = self
                .sources()
                .iter()
                .map(|entry| {
                    let mut copy = entry.clone();
                    if let Some(item) = copy.as_object_mut() {
                        item.remove("health");
                    }
                    copy
                })
                .collect();
            map.insert("sources".to_string(), Value::Array(stripped));
        }
        atomic_write_json(&self.path, &payload)
    }

    pub fn sources(&self) -> Vec<Value> {
        match self.data.get("sources") {
            Some(Value::Array(list)) => list.clone(),
            _ => Vec::new(),
        }
    }

    pub fn get(&self, key: &str) -> Option<Value> {
        self.sources()
            .into_iter()
            .find(|entry| entry.get("key").and_then(Value::as_str) == Some(key))
    }

    pub fn enabled_keys(&self) -> Vec<String> {
        self.sources()
            .iter()
            .filter(|entry| {
                entry
                    .get("enabled")
                    .map(truthy)
                    .unwrap_or(false)
            })
            .filter_map(|entry| entry.get("key").and_then(Value::as_str).map(str::to_string))
            .collect()
    }

    pub fn all_keys(&self) -> Vec<String> {
        self.sources()
            .iter()
            .filter_map(|entry| entry.get("key").and_then(Value::as_str).map(str::to_string))
            .collect()
    }

    pub fn set_enabled(&mut self, key: &str, on: bool) -> bool {
        let mut found = false;
        if let Some(Value::Array(list)) = self.data.get_mut("sources") {
            for entry in list.iter_mut() {
                if entry.get("key").and_then(Value::as_str) == Some(key) {
                    if let Some(map) = entry.as_object_mut() {
                        map.insert("enabled".to_string(), Value::Bool(on));
                    }
                    found = true;
                    break;
                }
            }
        }
        found
    }

    pub fn set_order_locked(&mut self, on: bool) {
        let Some(map) = self.data.as_object_mut() else {
            return;
        };
        if on {
            map.insert("orderLocked".to_string(), Value::Bool(true));
        } else {
            map.remove("orderLocked");
        }
        if let Some(Value::Array(list)) = self.data.get_mut("sources") {
            for entry in list.iter_mut() {
                if let Some(item) = entry.as_object_mut() {
                    item.remove("demoted");
                    item.remove("demoteFrom");
                }
            }
        }
    }

    pub fn order_locked(&self) -> bool {
        self.data
            .get("orderLocked")
            .map(truthy)
            .unwrap_or(false)
    }

    pub fn strip_health(&mut self) -> bool {
        let mut removed = false;
        if let Some(Value::Array(list)) = self.data.get_mut("sources") {
            for entry in list.iter_mut() {
                if let Some(map) = entry.as_object_mut() {
                    if map.remove("health").is_some() {
                        removed = true;
                    }
                }
            }
        }
        removed
    }

}
