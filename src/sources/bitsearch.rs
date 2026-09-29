use std::collections::{BTreeMap, HashSet};

use serde_json::Value;

use crate::model::{Item, SourceError, SourceResult};
use crate::sources::{base_of, collect_pages, default_base, first_failure, Fetch, Req};
use crate::util::{is_hash40, make_item, num_from_f64, quote, text_of, to_int, ts_from_iso};

pub const PAGE_SIZE: i64 = 100;
pub const PAGES: i64 = 2;
pub const MAX_HITS: usize = 200;

fn page<F: Fetch>(root: &str, page_no: i64, query: &str, fetch: &F) -> SourceResult<Vec<Item>> {
    let url = format!(
        "{root}/api/v1/search?q={}&sort=seeders&page={page_no}&limit={PAGE_SIZE}",
        quote(query)
    );
    let text = fetch.fetch(Req::get(&url).header("Accept", "application/json"))?;
    let payload: Value = serde_json::from_str(&text)
        .map_err(|_| SourceError::Shape("BitSearch 返回的不是 JSON".to_string()))?;
    let Some(rows) = payload.get("results").and_then(Value::as_array) else {
        return Ok(Vec::new());
    };

    let mut out = Vec::new();
    for row in rows {
        let Some(obj) = row.as_object() else {
            continue;
        };
        let h = text_of(obj.get("infohash").unwrap_or(&Value::Null))
            .trim()
            .to_lowercase();
        if !is_hash40(&h) {
            continue;
        }
        out.push(make_item(
            &text_of(obj.get("title").unwrap_or(&Value::Null)),
            &h,
            obj.get("size").and_then(to_int).unwrap_or(0),
            obj.get("seeders").and_then(to_int),
            obj.get("leechers").and_then(to_int),
            ts_from_iso(&text_of(obj.get("updatedAt").unwrap_or(&Value::Null)))
                .and_then(num_from_f64),
            "bitsearch",
        ));
    }
    Ok(out)
}

pub fn search<F: Fetch>(base: &str, query: &str, page_no: i64, fetch: &F) -> SourceResult<Vec<Item>> {
    let root = base_of(base, default_base("bitsearch"));
    let first = page_no.max(1);
    let mut pages: BTreeMap<i64, Vec<Item>> = BTreeMap::new();
    let mut failed: BTreeMap<i64, SourceError> = BTreeMap::new();

    for p in first..first + PAGES {
        match page(&root, p, query, fetch) {
            Ok(items) => {
                pages.insert(p, items);
            }
            Err(exc) => {
                failed.insert(p, exc);
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
