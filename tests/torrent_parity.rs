use std::fs;
use std::path::Path;

use happycrate::bencode::{decode_torrent_files, MAX_DEPTH};
use happycrate::core::format_size;
use serde_json::Value;

fn cases() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity/torrent_cases.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn unhex(text: &str) -> Vec<u8> {
    (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).unwrap())
        .collect()
}

#[test]
fn parity_format_size() {
    let data = cases();
    let rows = data["sizes"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let input = &row["in"];
        assert_eq!(
            format_size(input),
            row["out"].as_str().unwrap(),
            "format_size({input})"
        );
    }
}

#[test]
fn parity_decode_torrent_files() {
    let data = cases();
    let rows = data["torrents"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let name = row["name"].as_str().unwrap();
        let raw = unhex(row["hex"].as_str().unwrap());
        let got = decode_torrent_files(&raw);
        match &row["raises"] {
            Value::String(kind) => {
                let error = got.err().unwrap_or_else(|| {
                    panic!("{name}: Python 抛了 {kind}，Rust 却没有报错")
                });
                assert!(
                    error.starts_with(kind.as_str()),
                    "{name}: 错误文本应当以 {kind} 开头，实际 {error:?}"
                );
            }
            _ => {
                let entries = got.unwrap_or_else(|e| panic!("{name}: 不该报错，实际 {e}"));
                let want: Vec<(String, i64)> = row["out"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|item| {
                        (
                            item["n"].as_str().unwrap().to_string(),
                            item["b"].as_i64().unwrap(),
                        )
                    })
                    .collect();
                let actual: Vec<(String, i64)> = entries
                    .iter()
                    .map(|entry| (entry.name.clone(), entry.bytes))
                    .collect();
                assert_eq!(actual, want, "{name}: 文件清单不一致");
            }
        }
    }
}

#[test]
fn constants_match() {
    let data = cases();
    assert_eq!(
        happycrate::api::MAX_TORRENT_BYTES as u64,
        data["max_torrent_bytes"].as_u64().unwrap()
    );
    assert_eq!(
        happycrate::api::FILES_CAP as u64,
        data["files_cap"].as_u64().unwrap()
    );
    assert_eq!(MAX_DEPTH, 32);
}
