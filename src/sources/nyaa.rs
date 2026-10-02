use std::collections::HashSet;

use serde_json::Value;

use crate::model::{FetchTarget, Item, SourceError, SourceResult};
use crate::sources::{base_of, default_base, gather_pages, sukebei, Fetch};
use crate::util::{
    find_after, find_hex40, make_item, num_from_f64, parse_size_text, quote, split_items, tag,
    to_int, ts_from_rfc, unescape,
};

pub const PAGES: i64 = 14;
pub const MAX_HITS: usize = 1100;
pub const RSS_PAGE: usize = 75;

pub fn parse_rss(text: &str, source_key: &str, root: &str) -> Vec<Item> {
    let mut items = Vec::new();
    for chunk in split_items(text) {
        let title = unescape(&tag(&chunk, "title"));
        let mut hash = unescape(&tag(&chunk, "nyaa:infoHash")).to_lowercase();
        if hash.is_empty() {
            hash = find_hex40(&chunk).unwrap_or_default();
        }
        if hash.is_empty() {
            continue;
        }
        let mut item = make_item(
            &title,
            &hash,
            parse_size_text(&tag(&chunk, "nyaa:size")),
            to_int(&Value::String(tag(&chunk, "nyaa:seeders"))),
            to_int(&Value::String(tag(&chunk, "nyaa:leechers"))),
            ts_from_rfc(&tag(&chunk, "pubDate")).and_then(num_from_f64),
            source_key,
        );
        if let Some(gid) = find_after(&tag(&chunk, "guid"), "/view/") {
            if !root.is_empty() {
                item.fetch = Some(FetchTarget {
                    url: format!("{root}/download/{gid}.torrent"),
                });
            }
        }
        items.push(item);
    }
    items
}

pub fn family<F: Fetch + Sync>(
    base: &str,
    query: &str,
    page: i64,
    fetch: &F,
    source_key: &str,
    pages: i64,
    max_hits: usize,
) -> SourceResult<Vec<Item>> {
    let root = base_of(base, default_base(source_key));
    let rss_url = format!("{root}/?page=rss&q={}&p={page}", quote(query));
    let mut rss_failed: Option<SourceError> = None;
    let rss = match fetch.get(&rss_url, None) {
        Ok(text) => parse_rss(&text, source_key, &root),
        Err(exc) => {
            rss_failed = Some(exc);
            Vec::new()
        }
    };

    let mut seen: HashSet<String> = HashSet::new();
    let mut items: Vec<Item> = Vec::new();
    for item in rss {
        seen.insert(item.info_hash.clone());
        items.push(item);
    }

    if !items.is_empty() && items.len() < RSS_PAGE {
        return Ok(items);
    }

    let needle = quote(query);
    let (collected, _) = gather_pages(page..page + pages, 6, |&p| {
        let url = format!("{root}/?q={needle}&c=0_0&f=0&s=seeders&o=desc&p={p}");
        let text = fetch.get(&url, None)?;
        Ok(sukebei::parse_html(&text, &root, source_key))
    });

    if collected.is_empty() && items.is_empty() {
        if let Some(exc) = rss_failed {
            return Err(exc);
        }
    }

    for page_items in collected.values() {
        for item in page_items {
            if !seen.insert(item.info_hash.clone()) {
                continue;
            }
            items.push(item.clone());
            if items.len() >= max_hits {
                return Ok(items);
            }
        }
    }
    Ok(items)
}
