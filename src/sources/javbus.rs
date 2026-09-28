use std::collections::HashSet;

use crate::model::{Item, SourceError, SourceResult};
use crate::sources::{base_of, default_base, merge_details, Fetch, Req};
use crate::util::{
    cell_text, find_ci, find_hash40, find_tag_end, findall_bounded, make_item, num_from_f64,
    parse_size_text, quote, quote_plus, ts_from_cn_ymd,
};

pub const DETAILS: usize = 12;
pub const MAX_HITS: usize = 300;

const EMPTY_SIGNS: [&str; 3] = ["沒有您要的結果", "沒有找到", "沒有相關"];

fn starts_ci(chars: &[char], needle: &str, at: usize) -> bool {
    let needle: Vec<char> = needle.chars().collect();
    chars.len() >= at + needle.len()
        && find_ci(&chars[at..at + needle.len()], &needle, 0) == Some(0)
}

fn tag_has_btn_class(tag: &[char]) -> bool {
    let marker: Vec<char> = "class=\"".chars().collect();
    let btn: Vec<char> = "btn".chars().collect();
    let mut from = 0usize;
    while let Some(p) = find_ci(tag, &marker, from) {
        let start = p + marker.len();
        let mut i = start;
        while i < tag.len() && tag[i] != '"' {
            i += 1;
        }
        if find_ci(&tag[start..i], &btn, 0).is_some() {
            return true;
        }
        from = start;
    }
    false
}

fn match_badge(chars: &[char], at: usize) -> Option<usize> {
    if starts_ci(chars, "<a", at) {
        if let Some(gt) = find_tag_end(chars, at + 2) {
            if tag_has_btn_class(&chars[at..=gt]) {
                let close: Vec<char> = "</a>".chars().collect();
                if let Some(e) = find_ci(chars, &close, gt + 1) {
                    return Some(e + close.len());
                }
            }
        }
    }
    if starts_ci(chars, "<button", at) {
        let after = at + 7;
        let boundary = after >= chars.len() || !(chars[after].is_alphanumeric() || chars[after] == '_');
        if boundary {
            if let Some(gt) = find_tag_end(chars, after) {
                let close: Vec<char> = "</button>".chars().collect();
                if let Some(e) = find_ci(chars, &close, gt + 1) {
                    return Some(e + close.len());
                }
            }
        }
    }
    None
}

fn strip_badges(cell: &str, gap: &str) -> String {
    let chars: Vec<char> = cell.chars().collect();
    let mut out = String::new();
    let mut i = 0usize;
    while i < chars.len() {
        if chars[i] == '<' {
            if let Some(end) = match_badge(&chars, i) {
                out.push_str(gap);
                i = end;
                continue;
            }
        }
        out.push(chars[i]);
        i += 1;
    }
    out
}

fn javbus_text(cell: &str) -> String {
    cell_text(&strip_badges(cell, " "), "", false)
}

fn digits_after(text: &str, prefix: &str, then: char) -> Option<String> {
    let mut from = 0usize;
    while let Some(p) = text[from..].find(prefix) {
        let start = from + p + prefix.len();
        let digits: String = text[start..]
            .chars()
            .take_while(|c| c.is_ascii_digit())
            .collect();
        let after = start + digits.len();
        if !digits.is_empty() && text[after..].starts_with(then) {
            return Some(digits);
        }
        from = start;
    }
    None
}

fn quoted_after(text: &str, prefix: &str, closer: char) -> Option<String> {
    let start = text.find(prefix)? + prefix.len();
    let end = text[start..].find(closer)? + start;
    Some(text[start..end].to_string())
}

fn seen_hash(block: &str, seen: &mut HashSet<String>) -> Option<String> {
    let hash = find_hash40(block)?;
    if seen.insert(hash.clone()) {
        Some(hash)
    } else {
        None
    }
}

pub fn parse_magnets(text: &str) -> Vec<Item> {
    let mut items = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for row in findall_bounded(text, "<tr", "</tr>") {
        let Some(hash) = seen_hash(&row, &mut seen) else {
            continue;
        };
        let cells = findall_bounded(&row, "<td", "</td>");
        let size = if cells.len() > 1 {
            cell_text(&cells[1], "", false)
        } else {
            String::new()
        };
        let date = if cells.len() > 2 {
            cells[2].clone()
        } else {
            String::new()
        };
        let title = if cells.is_empty() {
            String::new()
        } else {
            javbus_text(&cells[0])
        };
        items.push(make_item(
            &title,
            &hash,
            if size.is_empty() {
                0
            } else {
                parse_size_text(&size)
            },
            None,
            None,
            if date.is_empty() {
                None
            } else {
                ts_from_cn_ymd(&cell_text(&date, "", false)).and_then(num_from_f64)
            },
            "javbus",
        ));
    }
    items
}

fn detail<F: Fetch>(root: &str, url: &str, fetch: &F) -> SourceResult<Vec<Item>> {
    let page = fetch.fetch(
        Req::get(url)
            .referer(&format!("{root}/"))
            .header("Accept", "text/html,application/xhtml+xml,*/*;q=0.9")
            .header("Accept-Language", "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7"),
    )?;
    let Some(gid) = digits_after(&page, "var gid = ", ';') else {
        return Ok(Vec::new());
    };
    let uc = digits_after(&page, "var uc = ", ';').unwrap_or_else(|| "0".to_string());
    let img = quoted_after(&page, "var img = '", '\'').unwrap_or_default();
    let query = format!(
        "gid={}&lang=zh&img={}&uc={}",
        quote_plus(&gid),
        quote_plus(&img),
        quote_plus(&uc)
    );
    let body = fetch.fetch(
        Req::get(&format!("{root}/ajax/uncledatoolsbyajax.php?{query}"))
            .referer(url)
            .header("Accept", "*/*")
            .header("Accept-Language", "zh-CN,zh;q=0.9,ja;q=0.8")
            .header("X-Requested-With", "XMLHttpRequest"),
    )?;
    Ok(parse_magnets(&body))
}

fn search_page<F: Fetch>(root: &str, word: &str, page_no: i64, fetch: &F) -> SourceResult<Vec<String>> {
    let url = if page_no <= 1 {
        format!("{root}/search/{word}")
    } else {
        format!("{root}/search/{word}/{page_no}")
    };
    let referer = format!("{root}/");
    let text = match fetch.fetch(
        Req::get(&url)
            .referer(&referer)
            .header("Accept", "text/html,application/xhtml+xml,*/*;q=0.9")
            .header("Accept-Language", "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7"),
    ) {
        Ok(text) => text,
        Err(SourceError::Http { code: 404, body }) => {
            if EMPTY_SIGNS.iter().any(|s| body.contains(s)) {
                return Ok(Vec::new());
            }
            return Err(SourceError::Http { code: 404, body });
        }
        Err(exc) => return Err(exc),
    };
    let chars: Vec<char> = text.chars().collect();
    let prefix: Vec<char> = "<a class=\"movie-box\" href=\"".chars().collect();
    let mut out: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    let mut pos = 0usize;
    while let Some(s) = find_ci(&chars, &prefix, pos) {
        let start = s + prefix.len();
        let mut i = start;
        while i < chars.len() && chars[i] != '"' {
            i += 1;
        }
        let path: String = chars[start..i].iter().collect();
        if seen.insert(path.clone()) {
            out.push(path);
        }
        pos = start;
    }
    Ok(out)
}

fn fanout<F: Fetch>(
    root: &str,
    links: &[String],
    fetch: &F,
) -> SourceResult<Vec<Item>> {
    let mut found: Vec<Vec<Item>> = Vec::new();
    let mut first_error: Option<SourceError> = None;
    for link in links.iter().take(DETAILS) {
        match detail(root, link, fetch) {
            Ok(items) => found.push(items),
            Err(exc) => {
                if first_error.is_none() {
                    first_error = Some(exc);
                }
            }
        }
    }
    if found.is_empty() {
        if let Some(exc) = first_error {
            return Err(exc);
        }
    }
    Ok(merge_details(&found, MAX_HITS))
}

fn words_for<F: Fetch>(
    root: &str,
    word: &str,
    page_no: i64,
    fetch: &F,
) -> SourceResult<Vec<Item>> {
    let links = search_page(root, &quote(word), page_no, fetch)?;
    if links.is_empty() {
        return Ok(Vec::new());
    }
    fanout(root, &links, fetch)
}

pub fn search<F: Fetch>(base: &str, query: &str, page_no: i64, fetch: &F) -> SourceResult<Vec<Item>> {
    let root = base_of(base, default_base("javbus"));
    let first = page_no.max(1);
    let words: Vec<String> = query.split_whitespace().map(str::to_string).collect();
    if words.is_empty() {
        return Ok(Vec::new());
    }

    match words_for(&root, query, first, fetch) {
        Ok(items) => return Ok(items),
        Err(SourceError::Http { code, .. }) if words.len() >= 2 && (code == 403 || code == 404) => {}
        Err(SourceError::Shape(_)) if words.len() >= 2 => {}
        Err(exc) => return Err(exc),
    }

    let mut merged: Vec<Item> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    let mut first_error: Option<SourceError> = None;
    for word in &words {
        match words_for(&root, word, first, fetch) {
            Ok(items) => {
                for item in items {
                    if item.info_hash.is_empty() || !seen.insert(item.info_hash.clone()) {
                        continue;
                    }
                    merged.push(item);
                    if merged.len() >= MAX_HITS {
                        return Ok(merged);
                    }
                }
            }
            Err(exc) => {
                if first_error.is_none() {
                    first_error = Some(exc);
                }
            }
        }
    }
    if merged.is_empty() {
        if let Some(exc) = first_error {
            return Err(exc);
        }
    }
    Ok(merged)
}
