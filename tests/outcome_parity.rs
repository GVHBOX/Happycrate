use std::fs;
use std::path::Path;

use happycrate::outcome::{classify, outcome_text, state_of, window_empty};
use serde_json::Value;

fn cases() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity/outcome_cases.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect()
}

#[test]
fn parity_classify() {
    let data = cases();
    let rows = data["classify"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let ok = row["ok"].as_bool().unwrap();
        let count = row["count"].as_i64().unwrap();
        let err = row["err"].as_str().unwrap();
        let ms = row["ms"].as_i64().unwrap();
        let (got, code) = classify(ok, count, err, ms);
        assert_eq!(
            got,
            row["outcome"].as_str().unwrap(),
            "classify({ok}, {count}, {err:?}, {ms}) 分类不一致"
        );
        assert_eq!(
            code,
            row["code"].as_u64().unwrap() as u16,
            "classify({ok}, {count}, {err:?}, {ms}) 状态码不一致"
        );
    }
}

#[test]
fn parity_outcome_text() {
    let data = cases();
    for row in data["outcome_text"].as_array().unwrap() {
        let outcome = row["outcome"].as_str().unwrap();
        let code = row["code"].as_u64().unwrap() as u16;
        assert_eq!(
            outcome_text(outcome, code),
            row["text"].as_str().unwrap(),
            "outcome_text({outcome:?}, {code})"
        );
    }
}

fn check_states(group: &str) {
    let data = cases();
    let rows = data[group].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let seq = strings(&row["in"]);
        assert_eq!(
            state_of(&seq),
            row["state"].as_str().unwrap(),
            "{group}: state_of({seq:?})"
        );
        assert_eq!(
            window_empty(&seq),
            row["empty_window"].as_bool().unwrap(),
            "{group}: window_empty({seq:?})"
        );
    }
}

#[test]
fn parity_state_of() {
    check_states("state_of");
    check_states("state_of_pairs");
}
