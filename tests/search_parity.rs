use std::fs;
use std::path::Path;

use happycrate::api::{item_view, relaxed_query};
use happycrate::config::py_int;
use happycrate::core::{format_time_relative, magnet_of};
use happycrate::query::{builtin_roles, parse_with};
use happycrate::util::LocalNow;
use serde_json::Value;

fn cases() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity/search_cases.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn frozen_now(data: &Value) -> LocalNow {
    let now = &data["now"];
    LocalNow {
        naive: now["naive"].as_i64().unwrap(),
        offset: now["offset"].as_i64().unwrap(),
        year: now["year"].as_i64().unwrap(),
    }
}

#[test]
fn parity_format_time_relative() {
    let data = cases();
    let now = frozen_now(&data);
    let rows = data["relative"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let input = &row["in"];
        assert_eq!(
            format_time_relative(input, &now),
            row["out"].as_str().unwrap(),
            "format_time_relative({input})"
        );
    }
}

#[test]
fn parity_magnet_of() {
    let data = cases();
    for row in data["magnet"].as_array().unwrap() {
        let input = &row["in"];
        assert_eq!(
            magnet_of(input),
            row["out"].as_str().unwrap(),
            "magnet_of({input})"
        );
    }
}

#[test]
fn parity_as_int() {
    let data = cases();
    for row in data["as_int"].as_array().unwrap() {
        let input = &row["in"];
        let want = row["out"].as_i64();
        assert_eq!(py_int(input), want, "py_int({input})");
    }
}

#[test]
fn parity_relaxed_query() {
    let data = cases();
    let table = builtin_roles();
    let rows = data["relaxed"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let text = row["text"].as_str().unwrap();
        let dropped: Vec<String> = row["dropped"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        let parsed = parse_with(text, &table);
        let (next, word) = relaxed_query(&parsed, &dropped);
        assert_eq!(
            next,
            row["next"].as_str().unwrap(),
            "relaxed_query({text:?}, {dropped:?}) 剩下的词"
        );
        assert_eq!(
            word,
            row["word"].as_str().unwrap(),
            "relaxed_query({text:?}, {dropped:?}) 去掉的词"
        );
    }
}

#[test]
fn parity_item_view() {
    let data = cases();
    let now = frozen_now(&data);
    let rows = data["item_view"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let input = &row["in"];
        let got = item_view(input, &now);
        assert_eq!(
            got, row["out"],
            "item_view({}) 不一致\nRust:   {got}\nPython: {}",
            input, row["out"]
        );
    }
}
