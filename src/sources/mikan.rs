use std::collections::HashSet;

use crate::model::{FetchTarget, Item, SourceResult};
use crate::sources::{base_of, default_base, Fetch};
use crate::util::{
    cell_text, cn_date, find_hex_after, findall_bounded, findall_marked,
    hash_from_text, make_item, num_from_f64, parse_size_text, quote, split_items, tag, unescape,
    ts_cn_or_iso,
};

pub const MAX_HITS: usize = 1000;
const MAGNET_PREFIX: &str = "data-magnet=\"magnet:?xt=urn:btih:";

pub fn parse_html(page_text: &str, root: &str) -> Vec<Item> {
    let mut items = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for row in findall_marked(page_text, "<tr", "js-search-results-row", "</tr>") {
        let Some(hash) = find_hex_after(&row, MAGNET_PREFIX, 40) else {
            continue;
        };
        if seen.contains(&hash) {
            continue;
        }
        let cells = findall_bounded(&row, "<td", "</td>");
        if cells.len() < 4 {
            continue;
        }
        seen.insert(hash.clone());
        let mut item = make_item(
            &cell_text(&cells[1], " ", true),
            &hash,
            parse_size_text(&cell_text(&cells[2], " ", true)),
            None,
            None,
            cn_date(&cell_text(&cells[3], " ", true)).and_then(num_from_f64),
            "mikan",
        );
        item.fetch = Some(FetchTarget {
            url: format!("{root}/Home/Episode/{hash}"),
        });
        items.push(item);
        if items.len() >= MAX_HITS {
            break;
        }
    }
    items
}

pub fn parse_rss(text: &str) -> Vec<Item> {
    let mut items = Vec::new();
    for chunk in split_items(text) {
        let title = unescape(&tag(&chunk, "title"));
        let mut hash = find_hex_after(&chunk, "Home/Episode/", 40).unwrap_or_default();
        if hash.is_empty() {
            hash = hash_from_text(&chunk);
        }
        if hash.is_empty() {
            continue;
        }
        let pubdate = tag(&chunk, "pubDate");
        items.push(make_item(
            &title,
            &hash,
            parse_size_text(&tag(&chunk, "contentLength")),
            None,
            None,
            ts_cn_or_iso(&pubdate).and_then(num_from_f64),
            "mikan",
        ));
    }
    items
}

pub fn search<F: Fetch>(base: &str, query: &str, fetch: &F) -> SourceResult<Vec<Item>> {
    let root = base_of(base, default_base("mikan"));
    let url = format!("{root}/Home/Search?searchstr={}", quote(query));
    let items = match fetch.get(&url, None) {
        Ok(text) => parse_html(&text, &root),
        Err(_) => Vec::new(),
    };
    if !items.is_empty() {
        return Ok(items);
    }
    let rss_url = format!("{root}/RSS/Search?searchstr={}", quote(query));
    Ok(parse_rss(&fetch.get(&rss_url, None)?))
}
