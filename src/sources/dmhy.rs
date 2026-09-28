use std::collections::{BTreeMap, HashSet};

use crate::model::{FetchTarget, Item, SourceError, SourceResult};
use crate::sources::{base_of, default_base, first_failure, Fetch};
use crate::util::{
    b32_to_hex, cell_text, find_b32_after, find_ci, find_hex_after, find_tag_end,
    findall_bounded, findall_marked, hash_from_magnet, hash_from_text, is_py_space, make_item,
    num_from_f64, parse_size_text, quote, size_from_title, split_items, strip_tags, tag,
    ts_from_cn_slash, ts_from_rfc, unescape,
};

pub const PAGES: i64 = 6;
pub const MAX_HITS: usize = 500;

struct Page {
    items: Vec<Item>,
    ok: bool,
}

fn date_head(content: &str) -> Option<String> {
    let chars: Vec<char> = content.chars().collect();
    let mut i = 0usize;
    while i < chars.len() && is_py_space(chars[i]) {
        i += 1;
    }
    if chars.len() < i + 16 {
        return None;
    }
    let head: Vec<char> = chars[i..i + 16].to_vec();
    let digit = |k: usize| head[k].is_ascii_digit();
    let ok = digit(0)
        && digit(1)
        && digit(2)
        && digit(3)
        && head[4] == '/'
        && digit(5)
        && digit(6)
        && head[7] == '/'
        && digit(8)
        && digit(9)
        && head[10] == ' '
        && digit(11)
        && digit(12)
        && head[13] == ':'
        && digit(14)
        && digit(15);
    if !ok {
        return None;
    }
    Some(head.iter().collect())
}

fn hidden_date(row: &str) -> Option<f64> {
    for content in findall_marked(row, "<span", "style=\"display:", "</span>") {
        if let Some(head) = date_head(&content) {
            return ts_from_cn_slash(&head);
        }
    }
    None
}

fn size_of(cell: &str) -> i64 {
    let text = cell_text(cell, "", false);
    if text.is_empty() || text == "-" || text == "&nbsp;" {
        return 0;
    }
    parse_size_text(&text)
}

fn count_of(cell: &str) -> Option<i64> {
    let text = cell_text(cell, "", false);
    if text.is_empty() || !text.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    text.parse::<i64>().ok()
}

fn view_link(cell: &str) -> Option<(String, String)> {
    let chars: Vec<char> = cell.chars().collect();
    let prefix: Vec<char> = "href=\"/topics/view/".chars().collect();
    let close_a: Vec<char> = "</a>".chars().collect();
    let mut pos = 0usize;
    while let Some(s) = find_ci(&chars, &prefix, pos) {
        let mut i = s + prefix.len();
        let mut path = String::from("/topics/view/");
        let mut taken = 0usize;
        while i < chars.len() && chars[i] != '"' {
            path.push(chars[i]);
            i += 1;
            taken += 1;
        }
        if taken >= 1 && i < chars.len() {
            if let Some(gt) = find_tag_end(&chars, i + 1) {
                let cs = gt + 1;
                if let Some(e) = find_ci(&chars, &close_a, cs) {
                    let label: String = chars[cs..e].iter().collect();
                    return Some((path, strip_tags(&label, "")));
                }
            }
        }
        pos = s + 1;
    }
    None
}

fn enclosure_url(chunk: &str) -> Option<String> {
    let chars: Vec<char> = chunk.chars().collect();
    let open: Vec<char> = "<enclosure".chars().collect();
    let marker: Vec<char> = "url=\"".chars().collect();
    let mut pos = 0usize;
    while let Some(s) = find_ci(&chars, &open, pos) {
        let Some(gt) = find_tag_end(&chars, s + open.len()) else {
            return None;
        };
        if let Some(p) = find_ci(&chars[s..gt], &marker, 0) {
            let mut i = s + p + marker.len();
            let mut url = String::new();
            while i < gt && chars[i] != '"' {
                url.push(chars[i]);
                i += 1;
            }
            if !url.is_empty() {
                return Some(url);
            }
        }
        pos = s + 1;
    }
    None
}

pub fn parse_list(page_text: &str, root: &str) -> (Vec<Item>, bool) {
    let Some(start) = page_text.find("id=\"topic_list\"") else {
        return (Vec::new(), false);
    };
    let body = &page_text[start..];
    let Some(tbody) = body.find("<tbody") else {
        return (Vec::new(), false);
    };

    let mut items = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for row in findall_bounded(&body[tbody..], "<tr", "</tr>") {
        let hash = match find_hex_after(&row, "btih:", 40) {
            Some(h) => h,
            None => match find_b32_after(&row, "btih:", 32).and_then(|c| b32_to_hex(&c)) {
                Some(h) => h,
                None => continue,
            },
        };
        if seen.contains(&hash) {
            continue;
        }
        let cells = findall_bounded(&row, "<td", "</td>");
        if cells.len() < 6 {
            continue;
        }
        seen.insert(hash.clone());

        let link = view_link(&cells[2]);
        let title = match &link {
            Some((_, label)) => unescape(label),
            None => String::new(),
        };
        let mut item = make_item(
            &title,
            &hash,
            size_of(&cells[4]),
            count_of(&cells[5]),
            None,
            hidden_date(&row).and_then(num_from_f64),
            "dmhy",
        );
        if let Some((path, _)) = link {
            item.fetch = Some(FetchTarget {
                url: format!("{root}{path}"),
            });
        }
        items.push(item);
    }
    (items, true)
}

pub fn parse_rss(text: &str) -> Vec<Item> {
    let mut items = Vec::new();
    for chunk in split_items(text) {
        let title = unescape(&tag(&chunk, "title"));
        let mut hash = String::new();
        if let Some(url) = enclosure_url(&chunk) {
            hash = hash_from_text(&url);
            if hash.is_empty() {
                hash = hash_from_magnet(&url);
            }
        }
        if hash.is_empty() {
            hash = hash_from_text(&tag(&chunk, "guid"));
        }
        if hash.is_empty() {
            hash = hash_from_text(&chunk);
        }
        if hash.is_empty() {
            continue;
        }
        let mut size = parse_size_text(&tag(&chunk, "contentLength"));
        if size == 0 {
            size = size_from_title(&title);
        }
        let guid = tag(&chunk, "guid");
        let mut item = make_item(
            &title,
            &hash,
            size,
            None,
            None,
            ts_from_rfc(&tag(&chunk, "pubDate")).and_then(num_from_f64),
            "dmhy",
        );
        if guid.starts_with("http") {
            item.fetch = Some(FetchTarget { url: guid });
        }
        items.push(item);
    }
    items
}

pub fn search<F: Fetch>(base: &str, query: &str, fetch: &F) -> SourceResult<Vec<Item>> {
    let root = base_of(base, default_base("dmhy"));
    let needle = quote(query);
    let mut pages: BTreeMap<i64, Page> = BTreeMap::new();
    let mut failed: BTreeMap<i64, SourceError> = BTreeMap::new();

    for p in 1..=PAGES {
        let url = format!("{root}/topics/list/page/{p}?keyword={needle}");
        match fetch.get(&url, None) {
            Ok(text) => {
                let (items, ok) = parse_list(&text, &root);
                pages.insert(p, Page { items, ok });
            }
            Err(exc) => {
                failed.insert(p, exc);
            }
        }
    }

    let mut seen: HashSet<String> = HashSet::new();
    let mut items: Vec<Item> = Vec::new();
    for page in pages.values() {
        for item in &page.items {
            if seen.insert(item.info_hash.clone()) {
                items.push(item.clone());
            }
        }
        if items.len() >= MAX_HITS {
            break;
        }
    }

    if !items.is_empty() {
        items.truncate(MAX_HITS);
        return Ok(items);
    }
    if pages.values().any(|p| p.ok) {
        return Ok(Vec::new());
    }
    if !failed.is_empty() {
        return Err(first_failure(&failed));
    }
    let url = format!("{root}/topics/rss/rss.xml?keyword={}", quote(query));
    Ok(parse_rss(&fetch.get(&url, None)?))
}
