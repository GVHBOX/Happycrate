use std::collections::HashSet;

use crate::model::{Item, SourceResult};
use crate::sources::{base_of, default_base, Fetch, Req};
use crate::util::{cell_text, find_hex_after, make_item, parse_size_text, quote, unescape};

pub const MAX_HITS: usize = 200;

fn blocks(text: &str) -> Vec<String> {
    let open = "class=\"one_result\"";
    let body = "</body>";
    let mut starts: Vec<usize> = Vec::new();
    let mut pos = 0usize;
    while let Some(found) = text[pos..].find(open) {
        let at = pos + found;
        starts.push(at);
        pos = at + open.len();
    }
    let close = text.find(body).unwrap_or(text.len());
    let mut out = Vec::new();
    for (index, start) in starts.iter().enumerate() {
        let end = starts.get(index + 1).copied().unwrap_or(close).min(close);
        if end > *start {
            out.push(text[*start..end].to_string());
        }
    }
    out
}

fn class_text(block: &str, class: &str) -> Option<String> {
    let marker = format!("class=\"{class}\"");
    let at = block.find(&marker)? + marker.len();
    let rest = &block[at..];
    let gt = rest.find('>')? + 1;
    let tail = &rest[gt..];
    let lt = tail.find('<')?;
    Some(tail[..lt].trim().to_string())
}

fn title_of(block: &str) -> Option<String> {
    let at = block.find("class=\"torrent_name\"")? + "class=\"torrent_name\"".len();
    let rest = &block[at..];
    let after_div = rest.find('>')? + 1;
    let after_anchor = rest[after_div..].find('>')? + after_div + 1;
    let close = rest[after_anchor..].find("</a>")? + after_anchor;
    Some(cell_text(&rest[after_anchor..close], "", true))
}

pub fn search<F: Fetch + Sync>(
    base: &str,
    query: &str,
    page_no: i64,
    fetch: &F,
) -> SourceResult<Vec<Item>> {
    let root = base_of(base, default_base("btdig"));
    let page = page_no.max(1);
    let url = if page <= 1 {
        format!("{root}/search?q={}", quote(query))
    } else {
        format!("{root}/search?q={}&p={}", quote(query), page - 1)
    };
    let text = fetch.fetch(
        Req::get(&url)
            .referer(&format!("{root}/"))
            .header("Accept", "text/html,application/xhtml+xml,*/*;q=0.9")
            .header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8"),
    )?;
    let mut items = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for block in blocks(&text) {
        let Some(hash) = find_hex_after(&block, "xt=urn:btih:", 40) else {
            continue;
        };
        if !seen.insert(hash.clone()) {
            continue;
        }
        let Some(title) = title_of(&block).filter(|text| !text.trim().is_empty()) else {
            continue;
        };
        let size = class_text(&block, "torrent_size")
            .map(|raw| parse_size_text(&unescape(&raw)))
            .unwrap_or(0);
        items.push(make_item(&title, &hash, size, None, None, None, "btdig"));
        if items.len() >= MAX_HITS {
            break;
        }
    }
    Ok(items)
}
