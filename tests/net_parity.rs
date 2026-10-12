use std::fs;
use std::path::Path;

use happycrate::net::{bypass_with, parse_proxy, system_proxies};
use serde_json::Value;

fn cases() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity/net_cases.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

#[test]
fn parity_parse_proxy() {
    let data = cases();
    let rows = data["parse_proxy"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let input = row["in"].as_str().unwrap();
        let (mapping, err) = parse_proxy(input);
        let want: Vec<(String, String)> = row["mapping"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string()))
            .collect();
        let got: Vec<(String, String)> = mapping.into_iter().collect();
        assert_eq!(got, want, "parse_proxy({input:?}) 映射不一致");
        assert_eq!(err, row["err"].as_str().unwrap(), "parse_proxy({input:?}) 错误文本不一致");
    }
}

#[test]
fn parity_bypass() {
    let data = cases();
    let rows = data["bypass"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let host = row["host"].as_str().unwrap();
        let override_ = row["override"].as_str().unwrap();
        assert_eq!(
            bypass_with(host, override_),
            row["hit"].as_bool().unwrap(),
            "bypass_with({host:?}, {override_:?})"
        );
    }
}

#[test]
fn captcha_sign_survives_beyond_head_window() {
    let mut page = String::from("<!DOCTYPE html><html><head><title>btdig.com</title></head><body>");
    while page.len() < 6000 {
        page.push_str("<div style=\"margin:0;padding:0\">blocked</div>");
    }
    assert!(
        !happycrate::net::captcha_text(&page),
        "纯样式填充页不应判为验证码页"
    );
    page.push_str("<h1>One more step</h1><div id=\"g-recaptcha\"></div></body></html>");
    assert!(
        happycrate::net::captcha_text(&page),
        "标记落在 4096 字符之后的挑战页应被识别"
    );
}

#[test]
fn captcha_weak_sign_needs_two_hits() {
    let single = "<html><body><a href=\"/captcha\">x</a></body></html>";
    assert!(!happycrate::net::captcha_text(single));
    let double = "<html><body><a href=\"/captcha\">输入验证码</a></body></html>";
    assert!(happycrate::net::captcha_text(double));
}

#[test]
fn live_registry_matches_python() {
    let python = Path::new("D:/AI/happycrate/.venv/Scripts/python.exe");
    if !python.is_file() {
        println!("跳过：找不到 Python 环境 {}", python.display());
        return;
    }
    let output = std::process::Command::new(python)
        .args([
            "-c",
            "import json, urllib.request; print(json.dumps(urllib.request.getproxies()))",
        ])
        .output()
        .expect("跑不动 Python");
    assert!(
        output.status.success(),
        "Python 侧失败：{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let parsed: Value = serde_json::from_slice(&output.stdout).expect("Python 输出不是 JSON");
    let keep = |key: &str| key == "http" || key == "https" || key == "ftp";

    let mut expected: Vec<(String, String)> = parsed
        .as_object()
        .unwrap()
        .iter()
        .filter(|(key, _)| keep(key))
        .map(|(key, value)| (key.clone(), value.as_str().unwrap().to_string()))
        .collect();
    let mut actual: Vec<(String, String)> = system_proxies()
        .into_iter()
        .filter(|(key, _)| keep(key))
        .collect();
    expected.sort();
    actual.sort();
    assert_eq!(
        actual, expected,
        "现场注册表/环境变量解析出的代理与 Python 的 getproxies() 不一致"
    );
    println!("现场代理解析与 Python 一致：{actual:?}");
}
