use std::fs;
use std::path::Path;

use happycrate::downloaders::{
    clean_magnets, plan_gaps, DeliveryResult, EXE_CANDIDATES, PROTOCOL_FLAG, PROTOCOL_KEYS,
};
use serde_json::Value;

fn cases() -> Value {
    let path =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity/downloaders_cases.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

#[test]
fn parity_plan_gaps() {
    let data = cases();
    let rows = data["gaps"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let count = row["count"].as_u64().unwrap() as usize;
        let timeout = row["timeout"].as_i64().unwrap();
        let want: Vec<f64> = row["out"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_f64().unwrap())
            .collect();
        let got = plan_gaps(count, timeout);
        assert_eq!(got.len(), want.len(), "plan_gaps({count}, {timeout}) 长度");
        for (index, (a, b)) in got.iter().zip(want.iter()).enumerate() {
            assert!(
                (a - b).abs() < 1e-9,
                "plan_gaps({count}, {timeout}) 第 {index} 项：{a} vs {b}"
            );
        }
    }
}

#[test]
fn parity_clean_magnets() {
    let data = cases();
    let rows = data["clean"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let input: Vec<String> = row["in"]
            .as_array()
            .unwrap()
            .iter()
            .map(|value| match value {
                Value::String(text) => text.clone(),
                Value::Null => String::new(),
                other => other.to_string(),
            })
            .collect();
        let want: Vec<String> = row["out"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        assert_eq!(clean_magnets(&input), want, "clean_magnets({input:?})");
    }
}

#[test]
fn parity_delivery_message() {
    let data = cases();
    let rows = data["message"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let added = row["added"].as_u64().unwrap() as usize;
        let total = row["total"].as_u64().unwrap() as usize;
        let errors: Vec<String> = row["errors"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        let ok = row["ok"].as_bool();
        let result = DeliveryResult::new(added, total, errors, "protocol", ok);
        assert_eq!(
            result.message(),
            row["out"].as_str().unwrap(),
            "message(added={added}, total={total}, ok={ok:?})"
        );
    }
}

#[test]
fn constants_match() {
    let data = cases();
    let candidates: Vec<String> = data["exe_candidates"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect();
    assert_eq!(
        EXE_CANDIDATES.iter().map(|s| s.to_string()).collect::<Vec<_>>(),
        candidates
    );
    let keys: Vec<String> = data["protocol_keys"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect();
    assert_eq!(
        PROTOCOL_KEYS.iter().map(|s| s.to_string()).collect::<Vec<_>>(),
        keys
    );
    assert_eq!(PROTOCOL_FLAG, data["protocol_flag"].as_str().unwrap());
}
