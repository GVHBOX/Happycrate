use std::fs;
use std::path::{Path, PathBuf};

use happycrate::api::{is_query_too_long, redact, Api};
use happycrate::settings::spec_keys;
use serde_json::Value;

fn cases() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity/api_cases.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn scratch(name: &str) -> PathBuf {
    let base = std::env::temp_dir().join(format!("hc-api-{}", std::process::id()));
    let directory = base.join(name);
    let _ = fs::remove_dir_all(&directory);
    fs::create_dir_all(&directory).unwrap();
    directory
}

#[test]
fn parity_api_commands() {
    let data = cases();
    let rows = data["commands"].as_array().unwrap();
    assert!(!rows.is_empty());
    for (index, row) in rows.iter().enumerate() {
        let name = row["name"].as_str().unwrap();
        let directory = scratch(&format!("api{index:02}"));
        let sources = directory.join("sources.json");
        let settings = directory.join("settings.json");
        fs::write(&sources, row["raw_sources"].as_str().unwrap()).unwrap();
        fs::write(&settings, row["raw_settings"].as_str().unwrap()).unwrap();

        let mut api = Api::new(Some(sources.clone()), Some(settings.clone()));
        api.config.load();
        api.settings.load();

        let mut results: Vec<Value> = Vec::new();
        for op in row["ops"].as_array().unwrap() {
            match op["op"].as_str().unwrap() {
                "toggle_source" => results.push(Value::Bool(api.toggle_source(
                    op["key"].as_str().unwrap(),
                    op["value"].as_bool().unwrap(),
                ))),
                "reorder_sources" => {
                    let keys: Vec<String> = op["keys"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .map(|v| v.as_str().unwrap().to_string())
                        .collect();
                    results.push(Value::Bool(api.reorder_sources(&keys)));
                }
                "set_auto_order" => results.push(Value::Bool(
                    api.set_auto_order(op["value"].as_bool().unwrap()),
                )),
                "save_settings" => {
                    results.push(api.save_settings(&op["fields"]));
                }
                "reload_query_roles" => results.push(Value::Bool(api.reload_query_roles())),
                other => panic!("未知操作 {other}"),
            }
        }

        assert_eq!(
            Value::Array(results),
            row["results"],
            "{name}: 命令返回值不一致"
        );
        assert_eq!(
            Value::Array(api.list_sources()),
            row["sources_view"],
            "{name}: list_sources 输出不一致"
        );
        assert_eq!(api.get_settings(), row["get_settings"], "{name}: get_settings");
        assert_eq!(
            api.default_settings(),
            row["default_settings"],
            "{name}: default_settings"
        );
        assert_eq!(
            api.config.data, row["config_data"],
            "{name}: 配置数据不一致"
        );
        assert_eq!(
            api.settings.data, row["settings_data"],
            "{name}: 设置数据不一致"
        );
        assert_eq!(
            api.config.order_locked(),
            row["order_locked"].as_bool().unwrap(),
            "{name}: orderLocked"
        );
        assert_eq!(
            api.last_write_error,
            row["last_write_error"].as_str().unwrap(),
            "{name}: 写入错误"
        );
        let written: Value =
            serde_json::from_str(&fs::read_to_string(&sources).unwrap()).unwrap();
        assert_eq!(written, row["saved_sources"], "{name}: 写回的 sources.json");
    }
}

#[test]
fn parity_redact() {
    let data = cases();
    for row in data["redact"].as_array().unwrap() {
        let input = row["in"].as_str().unwrap();
        assert_eq!(redact(input), row["out"].as_str().unwrap(), "redact({input:?})");
    }
}

#[test]
fn parity_query_length() {
    let data = cases();
    for row in data["too_long"].as_array().unwrap() {
        let input = row["in"].as_str().unwrap();
        assert_eq!(
            is_query_too_long(input),
            row["out"].as_bool().unwrap(),
            "is_query_too_long(长度 {})",
            input.chars().count()
        );
    }
}

#[test]
fn parity_spec_keys() {
    let data = cases();
    let want: Vec<String> = data["spec_keys"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect();
    let got: Vec<String> = spec_keys().into_iter().map(str::to_string).collect();
    assert_eq!(got.len(), want.len(), "设置项数量不一致");
    for key in &want {
        assert!(got.contains(key), "缺少设置项 {key}");
    }
}

#[test]
fn parity_app_info() {
    let data = cases();
    let rows = data["info"].as_array().unwrap();
    assert!(!rows.is_empty());
    let data_dir = scratch("info-data");
    std::env::set_var(happycrate::paths::ENV_DATA_DIR, &data_dir);
    for (index, row) in rows.iter().enumerate() {
        let name = row["name"].as_str().unwrap();
        let directory = scratch(&format!("info{index:02}"));
        let sources = directory.join("sources.json");
        let settings = directory.join("settings.json");
        fs::write(&sources, row["raw_sources"].as_str().unwrap()).unwrap();
        fs::write(&settings, row["raw_settings"].as_str().unwrap()).unwrap();

        let mut api = Api::new(Some(sources), Some(settings));
        api.config.load();
        api.settings.load();
        let info = api.app_info();

        assert_eq!(
            info["version"],
            happycrate::api::APP_VERSION,
            "{name}: version"
        );
        assert_eq!(info["mode"], row["mode"], "{name}: mode");
        assert_eq!(info["migratedFrom"], row["migratedFrom"], "{name}: migratedFrom");
        assert_eq!(info["autoOrder"], row["autoOrder"], "{name}: autoOrder");
        assert_eq!(
            info["dataDir"].as_str().unwrap(),
            happycrate::paths::data_dir().to_string_lossy(),
            "{name}: dataDir 应当就是数据目录函数的返回值"
        );
        let log_file = info["logFile"].as_str().unwrap();
        assert!(
            log_file.starts_with(&data_dir.to_string_lossy().to_string())
                && log_file.ends_with("happycrate.log"),
            "{name}: logFile 应当落在数据目录下，实际 {log_file}"
        );

        let want_proxy = row["proxy"].as_str().unwrap();
        let got_proxy = info["proxy"].as_str().unwrap();
        if want_proxy.starts_with("手动设置") {
            assert_eq!(got_proxy, want_proxy, "{name}: 手动代理描述");
        } else {
            assert!(
                got_proxy.starts_with("跟随系统 ") || got_proxy == "未检测到代理",
                "{name}: 系统代理描述只可能是这两种，实际 {got_proxy:?}"
            );
        }

        let recovered = info["recovered"].as_array().unwrap();
        assert_eq!(
            recovered.len(),
            row["recovered_count"].as_u64().unwrap() as usize,
            "{name}: 备份文件数量"
        );
        for path in recovered {
            assert!(
                path.as_str().unwrap().ends_with(".broken.json"),
                "{name}: 备份路径应当以 .broken.json 结尾"
            );
        }

        let self_test = api.selftest();
        assert_eq!(self_test["ok"], row["self_ok"], "{name}: selftest.ok");
        assert_eq!(self_test["missing"], row["self_missing"], "{name}: selftest.missing");
    }
    std::env::remove_var(happycrate::paths::ENV_DATA_DIR);
}

#[test]
fn parity_hex_color() {
    let data = cases();
    for row in data["hex_color"].as_array().unwrap() {
        let input = row["in"].as_str().unwrap();
        assert_eq!(
            happycrate::api::hex_color_ok(input.trim()),
            row["out"].as_bool().unwrap(),
            "hex_color_ok({input:?})"
        );
    }
}

#[test]
fn parity_proxy_status() {
    use std::collections::BTreeMap;
    let data = cases();
    let rows = data["proxy"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let name = row["name"].as_str().unwrap();
        let to_map = |key: &str| -> BTreeMap<String, String> {
            row[key]
                .as_object()
                .map(|map| {
                    map.iter()
                        .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string()))
                        .collect()
                })
                .unwrap_or_default()
        };
        let manual = to_map("manual");
        let system = to_map("system");
        let (mode, addr) = happycrate::net::pick(&manual, &system);
        let raw_port_ok = row["probe_port"].as_bool().unwrap_or(false);
        let raw_works = row["proxy_works"].as_bool().unwrap_or(false);
        let raw_tun = row["tun_stub"].as_str().unwrap();

        let mut got = happycrate::net::status_from(
            mode,
            &addr,
            !system.is_empty(),
            raw_port_ok,
            raw_works,
            raw_tun,
            0.0,
        );
        got.as_object_mut().unwrap().remove("checkedAt");
        assert_eq!(got, row["out"], "{name}: 代理状态不一致");
    }
}

#[test]
fn test_save_settings_reloads_http_client() {
    let dir = scratch("reload_http");
    let sources = dir.join("sources.json");
    let settings = dir.join("settings.json");
    let mut api = Api::new(Some(sources), Some(settings));
    api.config.load();
    api.settings.load();

    let client1 = api.http();
    assert!(client1.is_some());

    let new_proxy = "http://127.0.0.1:9876";
    let res = api.save_settings(&serde_json::json!({
        "proxy": new_proxy,
    }));
    assert!(res["ok"].as_bool().unwrap());

    let client2 = api.http();
    assert!(client2.is_some());
    let status2 = api.proxy_status(false);
    assert_eq!(status2["addr"].as_str().unwrap(), new_proxy);
}
