use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Map, Value};

use crate::config::{py_int, py_str, truthy, Config};
use crate::log;
use crate::paths;
use crate::settings::{coerce, spec_keys, Settings};

pub const MARK: &str = "migrated_from";
const LEGACY_ENV: &str = "CLB_DATA_DIR";
const LEGACY_NAMES: [&str; 2] = ["CLB", "clb"];

#[derive(Clone, Default)]
pub struct Report {
    pub done: bool,
    pub source: String,
    pub settings: usize,
    pub sources: usize,
    pub error: String,
}

fn candidates() -> Vec<PathBuf> {
    let mut out: Vec<PathBuf> = Vec::new();
    if let Some(from_env) = std::env::var_os(LEGACY_ENV) {
        out.push(PathBuf::from(from_env));
    }
    if let Some(appdata) = paths::appdata_dir() {
        for name in LEGACY_NAMES {
            out.push(appdata.join(name).join("data"));
            out.push(appdata.join(name));
        }
    }
    if let Some(parent) = paths::program_dir().parent().map(Path::to_path_buf) {
        for name in LEGACY_NAMES {
            out.push(parent.join(name).join("data"));
        }
    }
    out
}

pub fn find_legacy() -> Option<PathBuf> {
    candidates()
        .into_iter()
        .find(|path| path.join("sources.json").is_file())
}

fn merge_legacy_sources(legacy: &Path, cfg: &mut Config) -> usize {
    let Ok(text) = fs::read_to_string(legacy.join("sources.json")) else {
        return 0;
    };
    let Ok(raw) = serde_json::from_str::<Value>(&text) else {
        return 0;
    };
    let Some(entries) = raw.get("sources").and_then(Value::as_array) else {
        return 0;
    };

    let mut carried = 0usize;
    let Some(list) = cfg.data.get_mut("sources").and_then(Value::as_array_mut) else {
        return 0;
    };
    for entry in entries {
        let Some(fields) = entry.as_object() else {
            continue;
        };
        let key = py_str(fields.get("key").unwrap_or(&Value::Null))
            .trim()
            .to_string();
        let found = list
            .iter_mut()
            .find(|item| item.get("key").and_then(Value::as_str) == Some(key.as_str()));
        let Some(current) = found.and_then(Value::as_object_mut) else {
            continue;
        };

        if let Some(flag) = fields.get("enabled") {
            current.insert("enabled".to_string(), Value::Bool(truthy(flag)));
            carried += 1;
        }
        let base = py_str(fields.get("base").unwrap_or(&Value::Null))
            .trim()
            .to_string();
        if !base.is_empty() {
            current.insert("base".to_string(), Value::from(base));
        }
        let raw_order = fields.get("order").cloned().unwrap_or(Value::Null);
        let order = if truthy(&raw_order) {
            py_int(&raw_order)
        } else {
            Some(0)
        };
        if let Some(order) = order {
            current.insert("order".to_string(), Value::from(order));
        }
        let raw_timeout = fields.get("timeout").cloned().unwrap_or(Value::Null);
        let timeout = if truthy(&raw_timeout) {
            py_int(&raw_timeout).unwrap_or(0)
        } else {
            0
        };
        if (1..=120).contains(&timeout) {
            current.insert("timeout".to_string(), Value::from(timeout));
        }
    }

    if carried > 0 {
        cfg.normalize();
        log::info(
            log::MIGRATE,
            &format!("已从旧配置恢复 {carried} 个数据源的启停与设置"),
        );
    }
    carried
}

pub fn run(settings: &mut Settings, cfg: &mut Config) -> Report {
    let mut report = Report::default();

    if let Some(mark) = settings.data.get(MARK) {
        if truthy(mark) {
            report.done = true;
            report.source = match mark {
                Value::Object(fields) => py_str(fields.get("path").unwrap_or(&Value::Null)),
                other => py_str(other),
            };
            return report;
        }
    }

    let Some(legacy) = find_legacy() else {
        return report;
    };

    if let Ok(text) = fs::read_to_string(legacy.join("settings.json")) {
        if let Ok(Value::Object(fields)) = serde_json::from_str::<Value>(&text) {
            let known: Vec<&'static str> = spec_keys();
            let mut target: Map<String, Value> = match settings.data.as_object() {
                Some(map) => map.clone(),
                None => Map::new(),
            };
            for (key, value) in &fields {
                if !known.contains(&key.as_str()) {
                    continue;
                }
                if let Some(coerced) = coerce(key, value) {
                    target.insert(key.clone(), coerced);
                    report.settings += 1;
                }
            }
            settings.data = Value::Object(target);
        }
    }

    report.sources = merge_legacy_sources(&legacy, cfg);

    let now = crate::util::local_now();
    if let Some(map) = settings.data.as_object_mut() {
        map.insert(
            MARK.to_string(),
            json!({
                "path": legacy.to_string_lossy().to_string(),
                "at": crate::util::local_stamp(&now, 'T'),
            }),
        );
    }

    let reason = settings.save();
    if !reason.is_empty() {
        report.error = reason.clone();
        log::warning(log::MIGRATE, &format!("迁移后保存失败：{reason}"));
        return report;
    }

    report.done = true;
    report.source = legacy.to_string_lossy().to_string();
    log::info(
        log::MIGRATE,
        &format!(
            "已迁移旧配置：{} 项设置、{} 个数据源（来自 {}）",
            report.settings, report.sources, report.source
        ),
    );
    report
}
