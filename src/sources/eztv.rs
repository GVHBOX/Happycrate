use std::collections::{BTreeMap, HashSet};

use serde_json::Value;

use crate::model::{Item, SourceError, SourceResult};
use crate::sources::{base_of, default_base, first_failure, Fetch};
use crate::util::{is_hash40, make_item, num_from_i64, parse_size, text_of, to_int};

pub const PAGE_SIZE: usize = 100;
pub const PAGES: i64 = 15;
pub const MAX_HITS: usize = 400;

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(false),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

fn first_truthy<'a>(a: &'a Value, b: &'a Value) -> &'a Value {
    if truthy(a) {
        a
    } else {
        b
    }
}

fn page<F: Fetch>(root: &str, page_no: i64, fetch: &F) -> SourceResult<Vec<Item>> {
    let url = format!("{root}/api/get-torrents?limit={PAGE_SIZE}&page={page_no}");
    let text = fetch.get(&url, None)?;
    let payload: Value = serde_json::from_str(&text)
        .map_err(|_| SourceError::Shape("EZTV 接口返回的不是 JSON".to_string()))?;
    let Some(rows) = payload.get("torrents").and_then(Value::as_array) else {
        return Ok(Vec::new());
    };

    let mut out = Vec::new();
    for row in rows {
        let Some(obj) = row.as_object() else {
            continue;
        };
        let title = text_of(obj.get("title").unwrap_or(&Value::Null))
            .trim()
            .to_string();
        let h = text_of(obj.get("hash").unwrap_or(&Value::Null))
            .trim()
            .to_lowercase();
        if h.is_empty() || !is_hash40(&h) {
            continue;
        }
        let null = Value::Null;
        let size = first_truthy(
            obj.get("size_bytes").unwrap_or(&null),
            obj.get("size").unwrap_or(&null),
        );
        out.push(make_item(
            &title,
            &h,
            parse_size(size),
            obj.get("seeds").and_then(to_int),
            obj.get("peers").and_then(to_int),
            obj.get("date_released_unix").and_then(to_int).and_then(num_from_i64),
            "eztv",
        ));
    }
    Ok(out)
}

pub fn search<F: Fetch>(base: &str, query: &str, fetch: &F) -> SourceResult<Vec<Item>> {
    let root = base_of(base, default_base("eztv"));
    let needle = query.trim().to_lowercase();
    if needle.is_empty() {
        return Ok(Vec::new());
    }

    let first = page(&root, 1, fetch)?;
    let mut pages: BTreeMap<i64, Vec<Item>> = BTreeMap::new();
    let mut failed: BTreeMap<i64, SourceError> = BTreeMap::new();
    let gated = first.len() >= PAGE_SIZE;
    pages.insert(1, first);

    if gated {
        for p in 2..=PAGES {
            match page(&root, p, fetch) {
                Ok(items) => {
                    pages.insert(p, items);
                }
                Err(exc) => {
                    failed.insert(p, exc);
                }
            }
        }
        if !failed.is_empty() && failed.len() >= (PAGES - 1) as usize {
            return Err(first_failure(&failed));
        }
    }

    let mut seen = HashSet::new();
    let mut items = Vec::new();
    for page_items in pages.values() {
        for item in page_items {
            if !item.title.to_lowercase().contains(&needle) {
                continue;
            }
            if !seen.insert(item.info_hash.clone()) {
                continue;
            }
            items.push(item.clone());
            if items.len() >= MAX_HITS {
                return Ok(items);
            }
        }
    }
    Ok(items)
}
