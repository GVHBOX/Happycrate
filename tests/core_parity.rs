use std::fs;
use std::path::Path;

use happycrate::core::{dedupe, structure_score};
use serde_json::Value;

fn cases() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity/core_cases.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

#[test]
fn parity_structure_score() {
    let data = cases();
    let rows = data["structure_score"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let title = row["title"].as_str().unwrap();
        assert_eq!(
            structure_score(title),
            row["score"].as_i64().unwrap(),
            "structure_score({title:?})"
        );
    }
}

#[test]
fn parity_dedupe() {
    let data = cases();
    let groups = data["dedupe"].as_array().unwrap();
    assert!(!groups.is_empty());
    for (i, group) in groups.iter().enumerate() {
        let input = group["items"].as_array().unwrap();
        let want = group["out"].clone();
        let got = Value::Array(dedupe(input));
        assert_eq!(got, want, "dedupe 第 {i} 组不一致\nRust:   {got}\nPython: {want}");
    }
}
