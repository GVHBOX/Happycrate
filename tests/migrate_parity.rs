use std::fs;
use std::path::{Path, PathBuf};

use happycrate::config::Config;
use happycrate::migrate;
use happycrate::settings::Settings;
use serde_json::Value;

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).to_path_buf()
}

fn cases() -> Value {
    serde_json::from_str(
        &fs::read_to_string(root().join("tests/parity/migrate_cases.json")).unwrap(),
    )
    .unwrap()
}

fn stamp_ok(text: &str) -> bool {
    let bytes = text.as_bytes();
    if bytes.len() != 19 {
        return false;
    }
    for (index, byte) in bytes.iter().enumerate() {
        let expected = match index {
            4 | 7 => b'-',
            10 => b'T',
            13 | 16 => b':',
            _ => continue,
        };
        if *byte != expected {
            return false;
        }
    }
    bytes
        .iter()
        .enumerate()
        .all(|(index, byte)| matches!(index, 4 | 7 | 10 | 13 | 16) || byte.is_ascii_digit())
}

#[test]
fn migrate_matches_python() {
    let data = cases();
    let legacy = root().join("tests/legacy");
    assert!(legacy.join("sources.json").is_file(), "缺少老配置样本");
    std::env::set_var("CLB_DATA_DIR", &legacy);

    let sandbox = std::env::temp_dir().join(format!(
        "happycrate-migrate-test-{}",
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&sandbox);
    fs::create_dir_all(&sandbox).unwrap();

    let mut settings = Settings::new(Some(sandbox.join("settings.json")));
    let mut config = Config::new(Some(sandbox.join("sources.json")));
    let before = settings.data.clone();

    let report = migrate::run(&mut settings, &mut config);

    assert_eq!(report.done, data["report"]["done"].as_bool().unwrap());
    assert_eq!(
        report.settings as i64,
        data["report"]["settings"].as_i64().unwrap(),
        "迁移的设置项数与 Python 不一致"
    );
    assert_eq!(
        report.sources as i64,
        data["report"]["sources"].as_i64().unwrap(),
        "迁移的数据源个数与 Python 不一致"
    );
    assert!(report.error.is_empty(), "迁移报了错：{}", report.error);

    let mut after = settings.data.clone();
    let mark = after
        .as_object_mut()
        .and_then(|map| map.remove(migrate::MARK))
        .expect("没有写 migrated_from");
    assert_eq!(
        mark["path"].as_str().unwrap(),
        legacy.to_string_lossy(),
        "migrated_from.path 与老目录不一致"
    );
    let at = mark["at"].as_str().unwrap();
    assert!(stamp_ok(at), "migrated_from.at 形状不对：{at}");

    assert_eq!(after, data["settings"], "迁移后的设置与 Python 不一致");

    let mut changed: Vec<String> = after
        .as_object()
        .unwrap()
        .iter()
        .filter(|(key, value)| before.get(key.as_str()) != Some(*value))
        .map(|(key, _)| key.clone())
        .collect();
    changed.sort();
    let expected: Vec<String> = data["changed_settings"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| value.as_str().unwrap().to_string())
        .collect();
    assert_eq!(changed, expected, "被改动的设置键与 Python 不一致");

    assert_eq!(
        config.data["sources"], data["sources"],
        "迁移后的数据源列表与 Python 不一致"
    );

    let _ = fs::remove_dir_all(&sandbox);
}
