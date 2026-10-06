use std::path::PathBuf;

use serde_json::{Map, Value};

use crate::config::{load_json, py_int, py_str, atomic_write_json, SETTINGS_VERSION};
use crate::paths;

pub const INTERNAL_SETTING_KEYS: [&str; 1] = ["migrated_from"];

const PROGRESS_LOOK_DEFAULT: &str = "{\"on\":\"#8B7FE0\",\"warn\":\"#6F5CB8\",\"line\":\"#4C3D8F\",\"err\":\"#D4676E\",\"slot\":\"#E3E1F2\",\"gap\":\"#C5C1DF\"}";

const TRUE_WORDS: [&str; 4] = ["1", "true", "yes", "on"];

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Int,
    Str,
    Bool,
}

pub struct Spec {
    pub kind: Kind,
    pub min: Option<i64>,
    pub max: Option<i64>,
    pub choices: Option<&'static [i64]>,
}

const FONT_CHOICES: [i64; 3] = [14, 18, 22];

fn spec_of(key: &str) -> Option<Spec> {
    let int = |min: i64, max: i64| {
        Some(Spec {
            kind: Kind::Int,
            min: Some(min),
            max: Some(max),
            choices: None,
        })
    };
    let text = || {
        Some(Spec {
            kind: Kind::Str,
            min: None,
            max: None,
            choices: None,
        })
    };
    let flag = || {
        Some(Spec {
            kind: Kind::Bool,
            min: None,
            max: None,
            choices: None,
        })
    };
    match key {
        "min_query_len" => int(1, 20),
        "max_workers" => int(1, 32),
        "timeout" => int(1, 120),
        "default_downloader" => text(),
        "retries" => int(0, 5),
        "user_agent" => text(),
        "proxy" => text(),
        "ui_font_size" => Some(Spec {
            kind: Kind::Int,
            min: Some(12),
            max: Some(24),
            choices: Some(&FONT_CHOICES),
        }),
        "selbar" | "sound" | "sound_start" | "sound_done" | "sound_select" | "sound_copy"
        | "sound_deliver" | "sound_fail" | "auto_files" | "keep_duplicates" | "progress_line" => {
            flag()
        }
        "sound_volume" => int(0, 100),
        "theme" => text(),
        "brand" => text(),
        "soft_deadline_ms" => int(0, 60000),
        "hard_timeout_ms" => int(0, 180000),
        "progress_style" => text(),
        "progress_look" => text(),
        _ => None,
    }
}

pub fn spec_keys() -> Vec<&'static str> {
    SPEC_KEYS.to_vec()
}

const SPEC_KEYS: [&str; 26] = [
    "min_query_len", "max_workers", "timeout", "default_downloader", "retries", "user_agent",
    "proxy", "ui_font_size", "selbar", "sound", "sound_start", "sound_done", "sound_select",
    "sound_copy", "sound_deliver", "sound_fail", "sound_volume", "theme", "brand", "auto_files",
    "soft_deadline_ms", "hard_timeout_ms", "keep_duplicates", "progress_style", "progress_line",
    "progress_look",
];

pub fn setting_label(key: &str) -> &'static str {
    match key {
        "min_query_len" => "最短关键词",
        "max_workers" => "并发数",
        "timeout" => "投递/清单超时",
        "default_downloader" => "投递工具",
        "retries" => "重试次数",
        "user_agent" => "User-Agent",
        "proxy" => "代理",
        "ui_font_size" => "界面字号",
        "selbar" => "浮动选择条",
        "sound" => "音效反馈",
        "sound_start" => "搜索开始提示音",
        "sound_done" => "搜索完成提示音",
        "sound_select" => "勾选提示音",
        "sound_copy" => "复制提示音",
        "sound_deliver" => "投递提示音",
        "sound_fail" => "失败提示音",
        "sound_volume" => "总音量",
        "theme" => "主题",
        "brand" => "主题色",
        "auto_files" => "文件命中时自动展开",
        "soft_deadline_ms" => "软截止",
        "hard_timeout_ms" => "搜索时限",
        "keep_duplicates" => "保留重复项",
        "progress_style" => "进度条样式",
        "progress_line" => "进度条警戒线",
        "progress_look" => "进度条外观",
        _ => "",
    }
}

fn label_or_key(key: &str) -> String {
    let label = setting_label(key);
    if label.is_empty() {
        key.to_string()
    } else {
        label.to_string()
    }
}

pub fn reason(key: &str) -> String {
    let label = label_or_key(key);
    match spec_of(key) {
        Some(spec) => match (spec.min, spec.max) {
            (Some(min), Some(max)) => format!("{label}需在 {min}-{max} 之间"),
            _ => format!("{label}取值不合法"),
        },
        None => format!("{label}取值不合法"),
    }
}

pub fn settings_defaults() -> Value {
    let mut map = Map::new();
    map.insert("version".to_string(), Value::from(SETTINGS_VERSION));
    map.insert("min_query_len".to_string(), Value::from(2));
    map.insert("max_workers".to_string(), Value::from(12));
    map.insert("timeout".to_string(), Value::from(15));
    map.insert("default_downloader".to_string(), Value::from(""));
    map.insert("retries".to_string(), Value::from(1));
    map.insert("user_agent".to_string(), Value::from(""));
    map.insert("proxy".to_string(), Value::from(""));
    map.insert("ui_font_size".to_string(), Value::from(18));
    map.insert("selbar".to_string(), Value::Bool(false));
    map.insert("sound".to_string(), Value::Bool(true));
    map.insert("sound_start".to_string(), Value::Bool(true));
    map.insert("sound_done".to_string(), Value::Bool(true));
    map.insert("sound_select".to_string(), Value::Bool(false));
    map.insert("sound_copy".to_string(), Value::Bool(true));
    map.insert("sound_deliver".to_string(), Value::Bool(true));
    map.insert("sound_fail".to_string(), Value::Bool(false));
    map.insert("sound_volume".to_string(), Value::from(80));
    map.insert("theme".to_string(), Value::from("light"));
    map.insert("brand".to_string(), Value::from("lilac"));
    map.insert("auto_files".to_string(), Value::Bool(true));
    map.insert("soft_deadline_ms".to_string(), Value::from(3000));
    map.insert("hard_timeout_ms".to_string(), Value::from(45000));
    map.insert("keep_duplicates".to_string(), Value::Bool(false));
    map.insert("progress_style".to_string(), Value::from("segment"));
    map.insert("progress_line".to_string(), Value::Bool(true));
    map.insert(
        "progress_look".to_string(),
        Value::from(PROGRESS_LOOK_DEFAULT),
    );
    Value::Object(map)
}

pub fn coerce(key: &str, value: &Value) -> Option<Value> {
    let Some(spec) = spec_of(key) else {
        return Some(value.clone());
    };
    match spec.kind {
        Kind::Int => {
            if value.is_null() {
                return None;
            }
            let num = py_int(value)?;
            if let Some(min) = spec.min {
                if num < min {
                    return None;
                }
            }
            if let Some(max) = spec.max {
                if num > max {
                    return None;
                }
            }
            if let Some(choices) = spec.choices {
                let best = choices
                    .iter()
                    .min_by_key(|choice| ((**choice - num).abs(), -**choice))?;
                return Some(Value::from(*best));
            }
            Some(Value::from(num))
        }
        Kind::Str => {
            if value.is_null() {
                return Some(Value::from(""));
            }
            Some(Value::from(py_str(value)))
        }
        Kind::Bool => {
            if value.is_null() {
                return Some(Value::from(""));
            }
            if let Value::Bool(flag) = value {
                return Some(Value::Bool(*flag));
            }
            let text = py_str(value).trim().to_lowercase();
            Some(Value::Bool(TRUE_WORDS.contains(&text.as_str())))
        }
    }
}

pub struct Settings {
    pub path: PathBuf,
    pub data: Value,
    pub broken: Option<PathBuf>,
}

impl Settings {
    pub fn new(path: Option<PathBuf>) -> Self {
        Settings {
            path: path.unwrap_or_else(paths::settings_path),
            data: settings_defaults(),
            broken: None,
        }
    }

    pub fn load(&mut self) -> &mut Self {
        let (raw, _is_default, broken) = load_json(&self.path);
        self.broken = broken;
        let mut data = match settings_defaults() {
            Value::Object(map) => map,
            _ => Map::new(),
        };
        if let Value::Object(map) = &raw {
            for (key, value) in map {
                if spec_of(key).is_some() {
                    if let Some(coerced) = coerce(key, value) {
                        data.insert(key.clone(), coerced);
                    }
                } else if INTERNAL_SETTING_KEYS.contains(&key.as_str()) {
                    data.insert(key.clone(), value.clone());
                }
            }
        }
        self.data = Value::Object(data);
        self
    }

    pub fn save(&mut self) -> String {
        if let Some(map) = self.data.as_object_mut() {
            map.insert("version".to_string(), Value::from(SETTINGS_VERSION));
        }
        atomic_write_json(&self.path, &self.data)
    }

    pub fn get(&self, key: &str) -> Value {
        if let Some(value) = self.data.get(key) {
            return value.clone();
        }
        settings_defaults()
            .get(key)
            .cloned()
            .unwrap_or(Value::Null)
    }

    pub fn get_or(&self, key: &str, fallback: Value) -> Value {
        if let Some(value) = self.data.get(key) {
            return value.clone();
        }
        fallback
    }

    pub fn update(&mut self, fields: &[(&str, Value)]) -> Vec<String> {
        let mut rejected: Vec<String> = Vec::new();
        let mut coerced: Vec<(String, Value)> = Vec::new();
        for (key, value) in fields {
            if spec_of(key).is_none() {
                rejected.push(reason(key));
                continue;
            }
            match coerce(key, value) {
                Some(fresh) => coerced.push((key.to_string(), fresh)),
                None => rejected.push(reason(key)),
            }
        }
        if rejected.is_empty() {
            if let Some(map) = self.data.as_object_mut() {
                for (key, value) in coerced {
                    map.insert(key, value);
                }
            }
        }
        rejected
    }

    pub fn as_int(&self, key: &str, fallback: i64) -> i64 {
        py_int(&self.get(key)).unwrap_or(fallback)
    }

    pub fn as_bool(&self, key: &str) -> bool {
        match self.get(key) {
            Value::Bool(flag) => flag,
            Value::Null => false,
            other => {
                let text = py_str(&other).trim().to_lowercase();
                TRUE_WORDS.contains(&text.as_str())
            }
        }
    }
}
