use std::collections::{BTreeMap, HashSet};

use serde_json::Value;

use crate::model::{Item, SourceError, SourceResult};
use crate::sources::{base_of, collect_pages, default_base, first_failure, Fetch, Req};
use crate::util::{is_hash40, make_item, num_from_f64, text_of, to_int, ts_from_iso};

pub const PAGE_SIZE: i64 = 300;
pub const PAGES: i64 = 7;
pub const MAX_HITS: usize = 2100;
pub const ORDER: &str = "seeders";

fn hits(payload: &Value) -> SourceResult<&Vec<Value>> {
    let hits = payload
        .get("hits")
        .ok_or_else(|| SourceError::Shape("knaben 响应缺少 hits 列表".to_string()))?;
    hits.as_array()
        .ok_or_else(|| SourceError::Shape("knaben 响应缺少 hits 列表".to_string()))
}

fn page<F: Fetch>(
    root: &str,
    query: &str,
    start: i64,
    fetch: &F,
) -> SourceResult<Vec<Item>> {
    let body = serde_json::json!({
        "query": query,
        "order_by": ORDER,
        "size": PAGE_SIZE,
        "from": start,
    });
    let encoded = serde_json::to_vec(&body).map_err(|e| SourceError::Shape(e.to_string()))?;
    let text = fetch.fetch(
        Req::post(root, &encoded)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json"),
    )?;
    let payload: Value = serde_json::from_str(&text)
        .map_err(|_| SourceError::Shape("knaben 返回的不是对象".to_string()))?;
    if !payload.is_object() {
        return Err(SourceError::Shape("knaben 返回的不是对象".to_string()));
    }

    let mut out = Vec::new();
    for hit in hits(&payload)? {
        if !hit.is_object() {
            continue;
        }
        let hash = text_of(hit.get("hash").unwrap_or(&Value::Null))
            .trim()
            .to_lowercase();
        if !is_hash40(&hash) {
            continue;
        }
        let bytes = hit
            .get("bytes")
            .and_then(to_int)
            .unwrap_or(0);
        out.push(make_item(
            &text_of(hit.get("title").unwrap_or(&Value::Null)),
            &hash,
            bytes,
            hit.get("seeders").and_then(to_int),
            hit.get("peers").and_then(to_int),
            ts_from_iso(&text_of(hit.get("date").unwrap_or(&Value::Null))).and_then(num_from_f64),
            "knaben",
        ));
    }
    Ok(out)
}

pub fn search<F: Fetch>(
    base: &str,
    query: &str,
    page_no: i64,
    fetch: &F,
) -> SourceResult<Vec<Item>> {
    let root = base_of(base, default_base("knaben"));
    let first = (page_no.max(1) - 1) * PAGE_SIZE * PAGES;
    let starts: Vec<i64> = (0..PAGES).map(|i| first + i * PAGE_SIZE).collect();

    let mut pages: BTreeMap<i64, Vec<Item>> = BTreeMap::new();
    let mut failed: BTreeMap<i64, SourceError> = BTreeMap::new();
    for start in starts {
        match page(&root, query, start, fetch) {
            Ok(items) => {
                pages.insert(start, items);
            }
            Err(exc) => {
                failed.insert(start, exc);
            }
        }
    }

    let mut seen = HashSet::new();
    let mut items = Vec::new();
    collect_pages(&pages, &mut seen, &mut items, MAX_HITS);

    if pages.is_empty() && !failed.is_empty() {
        return Err(first_failure(&failed));
    }
    Ok(items)
}
