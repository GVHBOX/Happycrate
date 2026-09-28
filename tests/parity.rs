use std::fs;
use std::path::Path;

use happycrate::util::{
    collapse, parse_size, quote, split_items, tags, to_int, ts_from_iso, unescape,
};
use serde_json::Value;

fn cases() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity/util_cases.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn rows(group: &str) -> Vec<Value> {
    cases()[group].as_array().unwrap().clone()
}

#[test]
fn parity_unescape() {
    for row in rows("unescape") {
        let input = row["in"].as_str().unwrap();
        assert_eq!(
            unescape(input),
            row["out"].as_str().unwrap(),
            "unescape({input:?})"
        );
    }
}

#[test]
fn parity_collapse() {
    for row in rows("collapse") {
        let input = row["in"].as_str().unwrap();
        assert_eq!(
            collapse(input),
            row["out"].as_str().unwrap(),
            "collapse({input:?})"
        );
    }
}

#[test]
fn parity_quote() {
    for row in rows("quote") {
        let input = row["in"].as_str().unwrap();
        assert_eq!(quote(input), row["out"].as_str().unwrap(), "quote({input:?})");
    }
}

#[test]
fn parity_ts_from_iso() {
    for row in rows("ts_from_iso") {
        let input = row["in"].as_str().unwrap();
        let want = &row["out"];
        match want {
            Value::Null => assert!(
                ts_from_iso(input).is_none(),
                "ts_from_iso({input:?}) 应为 None，实际 {:?}",
                ts_from_iso(input)
            ),
            Value::Number(n) => {
                let expected = n.as_f64().unwrap();
                let got = ts_from_iso(input);
                assert!(
                    got.is_some(),
                    "ts_from_iso({input:?}) 应为 {expected}，实际 None"
                );
                assert!(
                    (got.unwrap() - expected).abs() < 1e-6,
                    "ts_from_iso({input:?}) = {:?}，应为 {expected}",
                    got
                );
            }
            _ => panic!("对照表格式错误：{input:?} -> {want:?}"),
        }
    }
}

#[test]
fn parity_to_int() {
    for row in rows("to_int") {
        let input = &row["in"];
        let want = &row["out"];
        let got = to_int(input);
        match want {
            Value::Null => assert_eq!(got, None, "to_int({input})"),
            Value::Number(n) => assert_eq!(
                got,
                n.as_i64(),
                "to_int({input}) = {got:?}，应为 {:?}",
                n.as_i64()
            ),
            _ => panic!("对照表格式错误：{input} -> {want}"),
        }
    }
}

fn as_strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect()
}

#[test]
fn parity_parse_size() {
    for row in rows("parse_size") {
        let input = &row["in"];
        assert_eq!(
            parse_size(input),
            row["out"].as_i64().unwrap(),
            "parse_size({input})"
        );
    }
}

#[test]
fn parity_tag() {
    for row in rows("tag") {
        let chunk = row["chunk"].as_str().unwrap();
        let names: Vec<String> = as_strings(&row["names"]);
        let refs: Vec<&str> = names.iter().map(String::as_str).collect();
        assert_eq!(
            tags(chunk, &refs),
            as_strings(&row["out"]),
            "tags({chunk:?}, {names:?})"
        );
    }
}

#[test]
fn parity_split_items() {
    for row in rows("split_items") {
        let input = row["in"].as_str().unwrap();
        assert_eq!(
            split_items(input),
            as_strings(&row["out"]),
            "split_items({input:?})"
        );
    }
}

fn assert_num(group: &str, check: impl Fn(&str) -> Option<f64>) {
    for row in rows(group) {
        let input = row["in"].as_str().unwrap();
        let want = &row["out"];
        let got = check(input);
        match want {
            Value::Null => assert!(got.is_none(), "{group}({input:?}) 应为 None，实际 {got:?}"),
            Value::Number(n) => {
                let expected = n.as_f64().unwrap();
                let got = got.unwrap_or_else(|| panic!("{group}({input:?}) 应为 {expected}"));
                assert!(
                    (got - expected).abs() < 1e-6,
                    "{group}({input:?}) = {got}，应为 {expected}"
                );
            }
            _ => panic!("对照表格式错误：{input:?} -> {want:?}"),
        }
    }
}

fn assert_text(group: &str, check: impl Fn(&str) -> Option<String>) {
    for row in rows(group) {
        let input = row["in"].as_str().unwrap();
        let want = match &row["out"] {
            Value::Null => None,
            Value::String(s) => Some(s.clone()),
            other => panic!("对照表格式错误：{input:?} -> {other:?}"),
        };
        assert_eq!(check(input), want, "{group}({input:?})");
    }
}

#[test]
fn parity_ts_from_rfc() {
    assert_num("ts_from_rfc", happycrate::util::ts_from_rfc);
}

#[test]
fn parity_ts_from_naive_cn() {
    assert_num("ts_from_naive_cn", happycrate::util::ts_from_naive_cn);
}

fn assert_cell(group: &str, gap: &str, unescape: bool) {
    for row in rows(group) {
        let input = row["in"].as_str().unwrap();
        assert_eq!(
            happycrate::util::cell_text(input, gap, unescape),
            row["out"].as_str().unwrap(),
            "{group}({input:?})"
        );
    }
}

#[test]
fn parity_cell_text() {
    assert_cell("cell_text_gap_empty", "", false);
    assert_cell("cell_text_gap_space", " ", false);
    assert_cell("cell_text_empty_unescaped", "", true);
    assert_cell("cell_text_space_unescaped", " ", true);
}

#[test]
fn parity_find_title_attr() {
    assert_text("find_title_attr", happycrate::util::find_title_attr);
}

#[test]
fn parity_find_torrent_path() {
    assert_text("find_torrent_path", happycrate::util::find_torrent_path);
}

#[test]
fn parity_find_hex_after() {
    assert_text("find_hex_after", |s| {
        happycrate::util::find_hex_after(s, "btih:", 40)
    });
}

#[test]
fn parity_ts_from_cn_slash() {
    assert_num("ts_from_cn_slash", happycrate::util::ts_from_cn_slash);
}

#[test]
fn parity_cn_date() {
    assert_num("cn_date", happycrate::util::cn_date);
}

#[test]
fn parity_b32_to_hex() {
    assert_text("b32_to_hex", happycrate::util::b32_to_hex);
}

#[test]
fn parity_hash_from_text() {
    assert_text("hash_from_text", |s| {
        let v = happycrate::util::hash_from_text(s);
        if v.is_empty() {
            None
        } else {
            Some(v)
        }
    });
}

#[test]
fn parity_hash_from_magnet() {
    assert_text("hash_from_magnet", |s| {
        let v = happycrate::util::hash_from_magnet(s);
        if v.is_empty() {
            None
        } else {
            Some(v)
        }
    });
}

#[test]
fn parity_size_from_title() {
    for row in rows("size_from_title") {
        let input = row["in"].as_str().unwrap();
        assert_eq!(
            happycrate::util::size_from_title(input),
            row["out"].as_i64().unwrap(),
            "size_from_title({input:?})"
        );
    }
}

#[test]
fn parity_find_b32_after() {
    assert_text("find_b32_after", |s| {
        happycrate::util::find_b32_after(s, "btih:", 32)
    });
}

#[test]
fn parity_ts_from_cn_dash() {
    assert_num("ts_from_cn_dash", happycrate::util::ts_from_cn_dash);
}

#[test]
fn parity_ts_from_cn_ymd() {
    assert_num("ts_from_cn_ymd", happycrate::util::ts_from_cn_ymd);
}

#[test]
fn parity_quote_plus() {
    for row in rows("quote_plus") {
        let input = row["in"].as_str().unwrap();
        assert_eq!(
            happycrate::util::quote_plus(input),
            row["out"].as_str().unwrap(),
            "quote_plus({input:?})"
        );
    }
}
