use std::fs;
use std::path::{Path, PathBuf};

use happycrate::config::{broken_path, clamp_timeout, clamp_timeout_with, Config};
use serde_json::Value;

fn cases() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity/config_cases.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn scratch(name: &str) -> PathBuf {
    let base = std::env::temp_dir().join(format!("hc-config-{}", std::process::id()));
    let directory = base.join(name);
    let _ = fs::remove_dir_all(&directory);
    fs::create_dir_all(&directory).unwrap();
    directory
}

#[test]
fn parity_config_load() {
    let data = cases();
    let rows = data["load"].as_array().unwrap();
    assert!(!rows.is_empty());
    for (index, row) in rows.iter().enumerate() {
        let name = row["name"].as_str().unwrap();
        let directory = scratch(&format!("case{index:02}"));
        let target = directory.join("sources.json");
        if let Some(raw) = row["raw"].as_str() {
            fs::write(&target, raw).unwrap();
        }

        let mut config = Config::new(Some(target.clone()));
        config.load();

        assert_eq!(
            config.data, row["data"],
            "{name}: 规范化后的 data 不一致\nRust:   {}\nPython: {}",
            config.data, row["data"]
        );

        let want_broken = row["broken"].as_bool().unwrap();
        assert_eq!(
            config.broken.is_some(),
            want_broken,
            "{name}: 是否产生损坏备份不一致"
        );
        if let Some(backup) = &config.broken {
            assert!(backup.is_file(), "{name}: 备份文件不存在 {backup:?}");
        }

        let save_err = config.save();
        assert_eq!(save_err, row["save_err"].as_str().unwrap(), "{name}: 保存返回值");
        if save_err.is_empty() {
            let written: Value =
                serde_json::from_str(&fs::read_to_string(&target).unwrap()).unwrap();
            assert_eq!(written, row["saved"], "{name}: 写回文件内容不一致");
        }
    }
}

#[test]
fn parity_clamp_timeout() {
    let data = cases();
    for row in data["clamp_timeout"].as_array().unwrap() {
        assert_eq!(
            clamp_timeout(&row["in"]),
            row["out"].as_i64().unwrap(),
            "clamp_timeout({})",
            row["in"]
        );
    }
    for row in data["clamp_timeout_custom_default"].as_array().unwrap() {
        let default = row["default"].as_i64().unwrap();
        assert_eq!(
            clamp_timeout_with(&row["in"], default),
            row["out"].as_i64().unwrap(),
            "clamp_timeout({}, {default})",
            row["in"]
        );
    }
}

#[test]
fn parity_broken_path() {
    let data = cases();
    for row in data["broken_path"].as_array().unwrap() {
        let input = row["in"].as_str().unwrap();
        assert_eq!(
            broken_path(Path::new(input)).to_string_lossy(),
            row["out"].as_str().unwrap(),
            "broken_path({input:?})"
        );
    }
}

#[test]
fn parity_config_accessors() {
    let data = cases();
    let rows = data["accessors"].as_array().unwrap();
    assert!(!rows.is_empty());
    for (index, row) in rows.iter().enumerate() {
        let name = row["name"].as_str().unwrap();
        let directory = scratch(&format!("acc{index:02}"));
        let target = directory.join("sources.json");
        fs::write(&target, row["raw"].as_str().unwrap()).unwrap();
        let mut config = Config::new(Some(target));
        config.load();

        let mut results: Vec<Option<bool>> = Vec::new();
        for op in row["ops"].as_array().unwrap() {
            match op["op"].as_str().unwrap() {
                "set_enabled" => results.push(Some(config.set_enabled(
                    op["key"].as_str().unwrap(),
                    op["value"].as_bool().unwrap(),
                ))),
                "set_order_locked" => {
                    config.set_order_locked(op["value"].as_bool().unwrap());
                    results.push(None);
                }
                "strip_health" => results.push(Some(config.strip_health())),
                other => panic!("未知操作 {other}"),
            }
        }

        let want: Vec<Option<bool>> = row["results"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_bool())
            .collect();
        assert_eq!(results, want, "{name}: 操作返回值不一致");
        assert_eq!(
            config.enabled_keys(),
            row["enabled_keys"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v.as_str().unwrap().to_string())
                .collect::<Vec<_>>(),
            "{name}: enabled_keys"
        );
        assert_eq!(
            config.all_keys().len(),
            row["all_keys"].as_array().unwrap().len(),
            "{name}: all_keys 数量"
        );
        assert_eq!(
            config.order_locked(),
            row["order_locked"].as_bool().unwrap(),
            "{name}: order_locked"
        );
        assert_eq!(
            config.get("a").is_some(),
            row["has_a"].as_bool().unwrap(),
            "{name}: get(\"a\")"
        );
        assert!(row["missing_key"].is_null(), "{name}: 未知键应当取不到");
        assert_eq!(config.data, row["data"], "{name}: data 不一致");
    }
}

#[test]
fn parity_paths_files() {
    let data = cases();
    let files = &data["files"];
    let env = files["env"].as_str().unwrap();
    let base = std::env::temp_dir().join(format!("hc-paths-{}", std::process::id()));
    std::env::set_var(happycrate::paths::ENV_DATA_DIR, &base);
    std::env::remove_var(happycrate::paths::ENV_LOG_DIR);

    assert_eq!(happycrate::paths::data_dir(), base, "data_dir 应当就是环境变量值");
    assert_eq!(
        happycrate::paths::data_mode().as_str(),
        files["mode"].as_str().unwrap()
    );
    let (_, _, label) = happycrate::paths::describe();
    assert_eq!(label, files["label"].as_str().unwrap());

    for (key, got) in [
        ("sources", happycrate::paths::sources_path()),
        ("settings", happycrate::paths::settings_path()),
        ("health", happycrate::paths::health_path()),
        ("logs_dir", happycrate::paths::logs_dir()),
        ("log_path", happycrate::paths::log_path()),
    ] {
        let python = files[key].as_str().unwrap();
        let suffix = python.strip_prefix(env).unwrap_or(python);
        let want = base.join(suffix.trim_start_matches(std::path::MAIN_SEPARATOR));
        assert_eq!(got, want, "{key}: 路径组成不一致");
    }

    let created = happycrate::paths::ensure_dirs().expect("建目录失败");
    assert_eq!(created, base);
    assert!(base.join("logs").is_dir(), "logs 目录未创建");
    let _ = fs::remove_dir_all(&base);
}

#[test]
fn sweep_temp_files_removes_only_its_own() {
    let directory = scratch("sweep");
    fs::write(directory.join(".happycrate-tmp-1.json"), "{}").unwrap();
    fs::write(directory.join(".happycrate-tmp-2.json"), "{}").unwrap();
    fs::write(directory.join("sources.json"), "{}").unwrap();
    fs::write(directory.join("notes.txt"), "keep").unwrap();

    let removed = happycrate::config::sweep_temp_files(&directory);
    assert_eq!(removed, 2, "应当只清掉两个临时文件");
    assert!(directory.join("sources.json").is_file(), "正常文件被误删");
    assert!(directory.join("notes.txt").is_file(), "正常文件被误删");
    assert_eq!(happycrate::config::sweep_temp_files(&directory), 0);
}
