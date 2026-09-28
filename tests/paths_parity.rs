use std::fs;
use std::path::{Path, PathBuf};

use happycrate::paths::{choose, Mode};
use serde_json::Value;

fn cases() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity/paths_cases.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

#[test]
fn parity_paths_resolve() {
    let data = cases();
    let inputs = &data["_inputs"];
    let portable = PathBuf::from(inputs["portable"].as_str().unwrap());
    let appdata = PathBuf::from(inputs["appdata"].as_str().unwrap());
    let env_dir = PathBuf::from(inputs["env_dir"].as_str().unwrap());
    let rows = data["resolve"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let name = row["name"].as_str().unwrap();
        let env = match row["env"].as_str() {
            Some(text) if !text.is_empty() => Some(env_dir.as_path()),
            _ => None,
        };
        let writable = row["portable_writable"].as_bool().unwrap();
        let has_appdata = row["has_appdata"].as_bool().unwrap();
        let (dir, mode) = choose(
            env,
            &portable,
            writable,
            if has_appdata { Some(appdata.as_path()) } else { None },
        );
        assert_eq!(dir.to_string_lossy(), row["dir"].as_str().unwrap(), "{name} 目录");
        assert_eq!(mode.as_str(), row["mode"].as_str().unwrap(), "{name} 模式");
    }
}

#[test]
fn parity_mode_labels() {
    let data = cases();
    for row in data["mode_labels"].as_array().unwrap() {
        let mode = match row["mode"].as_str().unwrap() {
            "env" => Mode::Env,
            "portable" => Mode::Portable,
            _ => Mode::Fallback,
        };
        assert_eq!(mode.label(), row["label"].as_str().unwrap(), "{:?}", mode);
        assert_eq!(mode.as_str(), row["mode"].as_str().unwrap(), "{:?}", mode);
    }
}
