use serde_json::Value;

use crate::model::{FetchTarget, Item, SourceResult};
use crate::sources::{nyaa, Fetch};
use crate::util::{
    cell_text, find_hex_after, find_title_attr, find_torrent_path, findall_bounded, make_item,
    num_from_f64, parse_size_text, to_int, ts_cn_or_iso, unescape,
};

pub fn parse_html(page_text: &str, root: &str, source_key: &str) -> Vec<Item> {
    let mut items = Vec::new();
    for row in findall_bounded(page_text, "<tr", "</tr>") {
        let Some(hash) = find_hex_after(&row, "btih:", 40) else {
            continue;
        };
        let cells = findall_bounded(&row, "<td", "</td>");
        if cells.len() < 8 {
            continue;
        }
        let title = match find_title_attr(&row) {
            Some(raw) => unescape(&raw),
            None => cell_text(&cells[1], " ", false),
        };
        let added_text = cell_text(&cells[4], " ", false);
        let mut item = make_item(
            &title,
            &hash,
            parse_size_text(&cell_text(&cells[3], " ", false)),
            to_int(&Value::String(cell_text(&cells[5], " ", false))),
            to_int(&Value::String(cell_text(&cells[6], " ", false))),
            ts_cn_or_iso(&added_text).and_then(num_from_f64),
            source_key,
        );
        if let Some(path) = find_torrent_path(&row) {
            if !root.is_empty() {
                item.fetch = Some(FetchTarget {
                    url: format!("{root}{path}"),
                });
            }
        }
        items.push(item);
    }
    items
}

pub const PAGES: i64 = 14;
pub const MAX_HITS: usize = 1100;

pub fn search<F: Fetch>(base: &str, query: &str, page: i64, fetch: &F) -> SourceResult<Vec<Item>> {
    nyaa::family(base, query, page, fetch, "sukebei", PAGES, MAX_HITS)
}
