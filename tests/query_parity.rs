use std::fs;
use std::path::{Path, PathBuf};

use happycrate::query::{
    builtin_roles, contains, load_roles, needles, normalize, parse_with, season_forms, season_of,
};
use serde_json::Value;

fn cases() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity/query_cases.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn scratch(name: &str) -> PathBuf {
    let base = std::env::temp_dir().join(format!("hc-query-{}", std::process::id()));
    let directory = base.join(name);
    let _ = fs::remove_dir_all(&directory);
    fs::create_dir_all(&directory).unwrap();
    directory
}

#[test]
fn parity_query_normalize() {
    let data = cases();
    for row in data["normalize"].as_array().unwrap() {
        let input = row["in"].as_str().unwrap();
        assert_eq!(
            normalize(input),
            row["out"].as_str().unwrap(),
            "normalize({input:?})"
        );
    }
}

#[test]
fn parity_query_contains() {
    let data = cases();
    for row in data["contains"].as_array().unwrap() {
        let token = row["token"].as_str().unwrap();
        let word = row["word"].as_str().unwrap();
        assert_eq!(
            contains(token, word),
            row["out"].as_bool().unwrap(),
            "contains({token:?}, {word:?})"
        );
    }
}

#[test]
fn parity_query_season_of() {
    let data = cases();
    for row in data["season_of"].as_array().unwrap() {
        let token = row["token"].as_str().unwrap();
        let want = &row["out"];
        let got = season_of(token);
        if want.is_null() {
            assert!(got.is_none(), "season_of({token:?}) 应为 None，实际 {got:?}");
        } else {
            let s = want["s"].as_i64().unwrap();
            let e = want["e"].as_i64().unwrap();
            assert_eq!(got, Some((s, e)), "season_of({token:?})");
        }
    }
}

#[test]
fn parity_query_season_forms() {
    let data = cases();
    for row in data["season_forms"].as_array().unwrap() {
        let s = row["s"].as_i64().unwrap();
        let e = row["e"].as_i64().unwrap();
        let want: Vec<String> = row["out"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        assert_eq!(season_forms(s, e), want, "season_forms({s}, {e})");
    }
}

#[test]
fn parity_query_parse() {
    let data = cases();
    let table = builtin_roles();
    let rows = data["parse"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let input = row["in"].as_str().unwrap();
        let parsed = parse_with(input, &table);
        assert_eq!(
            parsed, row["out"],
            "parse({input:?}) 不一致\nRust:   {parsed}\nPython: {}",
            row["out"]
        );
        let want: Vec<String> = row["needles"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        assert_eq!(needles(&parsed), want, "needles(parse({input:?}))");
    }
}

#[test]
fn parity_query_load() {
    let data = cases();
    let rows = data["load"].as_array().unwrap();
    assert!(!rows.is_empty());
    for (index, row) in rows.iter().enumerate() {
        let name = row["name"].as_str().unwrap();
        let directory = scratch(&format!("roles{index:02}"));
        let target = directory.join("query_roles.json");
        if let Some(raw) = row["raw"].as_str() {
            fs::write(&target, raw).unwrap();
        }
        let table = load_roles(&target);
        let want_words = row["words"].as_object().unwrap();
        assert_eq!(
            table.words.len(),
            want_words.len(),
            "{name}: 角色数量不一致"
        );
        for (role, words) in want_words {
            let expect: Vec<String> = words
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v.as_str().unwrap().to_string())
                .collect();
            let got = table
                .words
                .iter()
                .find(|(name, _)| name == role)
                .map(|(_, list)| list.clone());
            assert_eq!(got, Some(expect), "{name}: 角色 {role} 词表不一致");
        }
        let want_variants = row["variants"].as_object().unwrap();
        assert_eq!(
            table.variants.len(),
            want_variants.len(),
            "{name}: 变体数量不一致"
        );
        for (key, forms) in want_variants {
            let expect: Vec<String> = forms
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v.as_str().unwrap().to_string())
                .collect();
            assert_eq!(
                table.variants.get(key),
                Some(&expect),
                "{name}: 变体 {key} 不一致"
            );
        }
    }
}

#[test]
fn cached_roles_can_be_reloaded() {
    let base = std::env::temp_dir().join(format!("hc-query-roles-{}", std::process::id()));
    let _ = fs::remove_dir_all(&base);
    fs::create_dir_all(&base).unwrap();
    std::env::set_var(happycrate::paths::ENV_DATA_DIR, &base);
    let target = base.join("query_roles.json");

    fs::write(&target, r#"{"words": {"EXTRA": ["aaa"]}}"#).unwrap();
    happycrate::query::reload();
    let first = happycrate::query::roles();
    assert!(
        first.words.iter().any(|(role, _)| role == "EXTRA"),
        "首次加载应当读到自定义角色"
    );

    fs::write(&target, r#"{"words": {"OTHER": ["bbb"]}}"#).unwrap();
    let cached = happycrate::query::roles();
    assert!(
        cached.words.iter().any(|(role, _)| role == "EXTRA"),
        "未 reload 时应当仍然是缓存里的旧表"
    );

    happycrate::query::reload();
    let fresh = happycrate::query::roles();
    assert!(
        !fresh.words.iter().any(|(role, _)| role == "EXTRA"),
        "reload 之后应当读到新表"
    );
    assert!(fresh.words.iter().any(|(role, _)| role == "OTHER"));
    let _ = fs::remove_dir_all(&base);
}
