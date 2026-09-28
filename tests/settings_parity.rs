use std::fs;
use std::path::{Path, PathBuf};

use happycrate::settings::{coerce, reason, settings_defaults, Settings};
use serde_json::Value;

fn cases() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity/settings_cases.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn scratch(name: &str) -> PathBuf {
    let base = std::env::temp_dir().join(format!("hc-settings-{}", std::process::id()));
    let directory = base.join(name);
    let _ = fs::remove_dir_all(&directory);
    fs::create_dir_all(&directory).unwrap();
    directory
}

#[test]
fn parity_settings_defaults() {
    assert_eq!(settings_defaults(), cases()["defaults"]);
}

#[test]
fn parity_settings_load() {
    let data = cases();
    let rows = data["load"].as_array().unwrap();
    assert!(!rows.is_empty());
    for (index, row) in rows.iter().enumerate() {
        let name = row["name"].as_str().unwrap();
        let directory = scratch(&format!("case{index:02}"));
        let target = directory.join("settings.json");
        if let Some(raw) = row["raw"].as_str() {
            fs::write(&target, raw).unwrap();
        }
        let mut settings = Settings::new(Some(target.clone()));
        settings.load();
        assert_eq!(settings.data, row["data"], "{name}: data 不一致");
        assert_eq!(
            settings.broken.is_some(),
            row["broken"].as_bool().unwrap(),
            "{name}: 损坏备份"
        );
        let save_err = settings.save();
        assert_eq!(save_err, row["save_err"].as_str().unwrap(), "{name}: 保存返回值");
        if save_err.is_empty() {
            let written: Value =
                serde_json::from_str(&fs::read_to_string(&target).unwrap()).unwrap();
            assert_eq!(written, row["saved"], "{name}: 写回内容不一致");
        }
    }
}

#[test]
fn parity_settings_coerce() {
    let data = cases();
    let rows = data["coerce"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let key = row["key"].as_str().unwrap();
        let input = &row["in"];
        let want = &row["out"];
        let got = coerce(key, input);
        if want.is_null() {
            assert!(got.is_none(), "coerce({key}, {input}) 应为 None，实际 {got:?}");
        } else {
            assert_eq!(
                got.as_ref(),
                Some(want),
                "coerce({key}, {input}) 不一致"
            );
        }
    }
}

#[test]
fn parity_settings_update() {
    let data = cases();
    let rows = data["update"].as_array().unwrap();
    assert!(!rows.is_empty());
    for (index, row) in rows.iter().enumerate() {
        let directory = scratch(&format!("upd{index:02}"));
        let mut settings = Settings::new(Some(directory.join("settings.json")));
        settings.load();
        let fields: Vec<(&str, Value)> = row["fields"]
            .as_array()
            .unwrap()
            .iter()
            .map(|pair| {
                let list = pair.as_array().unwrap();
                (list[0].as_str().unwrap(), list[1].clone())
            })
            .collect();
        let rejected = settings.update(&fields);
        assert_eq!(
            rejected,
            row["rejected"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v.as_str().unwrap().to_string())
                .collect::<Vec<_>>(),
            "update({fields:?}) 拒绝清单"
        );
        assert_eq!(settings.data, row["data"], "update({fields:?}) 后的 data");
    }
}

#[test]
fn parity_settings_reason() {
    let data = cases();
    for row in data["reason"].as_array().unwrap() {
        let key = row["key"].as_str().unwrap();
        assert_eq!(reason(key), row["out"].as_str().unwrap(), "reason({key})");
    }
}

#[test]
fn parity_settings_get() {
    let data = cases();
    let directory = scratch("get");
    let mut settings = Settings::new(Some(directory.join("settings.json")));
    settings.load();
    for row in data["get"].as_array().unwrap() {
        let key = row["key"].as_str().unwrap();
        assert_eq!(settings.get(key), row["out"], "get({key})");
        assert_eq!(
            settings.get_or(key, Value::from("FB")),
            row["with_fallback"],
            "get({key}, \"FB\")"
        );
    }
}
