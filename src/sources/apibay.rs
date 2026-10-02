use std::collections::HashSet;

use serde_json::Value;

use crate::model::{Item, SourceError, SourceResult};
use crate::sources::{base_of, default_base, gather_pages, keyword_hit_rate, Fetch};
use crate::util::{
    is_hash40, is_py_space, make_item, num_from_i64, parse_size, quote, text_of, to_int,
};

pub const CATS: [i64; 6] = [100, 200, 300, 400, 500, 600];
pub const MAX_HITS: usize = 600;

fn split_tokens(needle: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    for c in needle.chars() {
        if is_py_space(c) || matches!(c, '-' | '_' | '.' | ':' | '+' | '/' | '|' | ',') {
            if !cur.is_empty() {
                out.push(std::mem::take(&mut cur));
            }
        } else {
            cur.push(c);
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

fn relevant(items: &[Item], query: &str) -> bool {
    let needle = query.trim().to_lowercase();
    if needle.is_empty() {
        return false;
    }
    if !needle.chars().any(|c| c.is_alphanumeric()) {
        return false;
    }
    let tokens: Vec<String> = split_tokens(&needle)
        .into_iter()
        .filter(|t| t.chars().count() >= 2)
        .collect();
    if keyword_hit_rate(items, std::slice::from_ref(&needle)) > 0.0 {
        return true;
    }
    keyword_hit_rate(items, &tokens) > 0.0
}

fn url_for(root: &str, query: &str, cat: Option<i64>) -> String {
    let mut url = format!("{root}/q.php?q={}", quote(query));
    if let Some(c) = cat {
        url.push_str(&format!("&cat={c}"));
    }
    url
}

fn rows(text: &str, source_key: &str) -> SourceResult<Vec<Item>> {
    let parsed: Value = serde_json::from_str(text)
        .map_err(|_| SourceError::Shape("apibay 返回的不是 JSON".to_string()))?;
    let Some(arr) = parsed.as_array() else {
        return Ok(Vec::new());
    };
    let zero_hash = "0".repeat(40);
    let mut items = Vec::new();
    for row in arr {
        let Some(obj) = row.as_object() else {
            continue;
        };
        let h = text_of(obj.get("info_hash").unwrap_or(&Value::Null))
            .trim()
            .to_lowercase();
        let name = text_of(obj.get("name").unwrap_or(&Value::Null))
            .trim()
            .to_string();
        if h.is_empty() || !is_hash40(&h) || h == zero_hash {
            continue;
        }
        if name.to_lowercase() == "no results" {
            continue;
        }
        items.push(make_item(
            &name,
            &h,
            parse_size(obj.get("size").unwrap_or(&Value::Null)),
            obj.get("seeders").and_then(to_int),
            obj.get("leechers").and_then(to_int),
            obj.get("added").and_then(to_int).and_then(num_from_i64),
            source_key,
        ));
    }
    Ok(items)
}

pub fn search<F: Fetch + Sync>(base: &str, query: &str, fetch: &F) -> SourceResult<Vec<Item>> {
    let root = base_of(base, default_base("apibay"));
    let head = rows(&fetch.get(&url_for(&root, query, None), None)?, "apibay")?;
    if head.is_empty() {
        return Ok(Vec::new());
    }
    if !relevant(&head, query) {
        return Ok(head);
    }

    let mut all = head;
    let (cats_data, _) = gather_pages(CATS, 6, |&cat| {
        let more = fetch.get(&url_for(&root, query, Some(cat)), None)?;
        rows(&more, "apibay")
    });
    for items in cats_data.into_values() {
        all.extend(items);
    }

    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for item in all {
        if !seen.insert(item.info_hash.clone()) {
            continue;
        }
        out.push(item);
        if out.len() >= MAX_HITS {
            break;
        }
    }
    Ok(out)
}
