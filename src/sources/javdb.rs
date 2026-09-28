use std::collections::HashSet;

use crate::model::{Item, SourceError, SourceResult};
use crate::sources::{base_of, default_base, merge_details, Fetch, Req};
use crate::util::{
    cell_text, find_ci, find_hash40, parse_size_text, quote_plus, strip_tags, ts_from_cn_ymd,
    unescape,
};

pub const DETAILS: usize = 12;
pub const MAX_HITS: usize = 300;
pub const LOGIN_TEXT: &str = "部分影片需登入 JavDB 查看";

fn starts_ci(chars: &[char], needle: &str, at: usize) -> bool {
    let needle: Vec<char> = needle.chars().collect();
    chars.len() >= at + needle.len()
        && find_ci(&chars[at..at + needle.len()], &needle, 0) == Some(0)
}

fn item_match(chars: &[char], at: usize) -> Option<usize> {
    if !starts_ci(chars, "<div class=\"item", at) {
        return None;
    }
    let mut i = at + "<div class=\"item".len();
    let tail = chars.get(i).copied()?;
    if tail.is_whitespace() {
        i += 1;
        while i < chars.len() && chars[i] != '"' {
            i += 1;
        }
    }
    if i >= chars.len() || chars[i] != '"' {
        return None;
    }
    i += 1;
    while i < chars.len() && chars[i] != '>' {
        if starts_ci(chars, "data-rank=\"", i) {
            let mut j = i + "data-rank=\"".len();
            let ds = j;
            while j < chars.len() && chars[j].is_ascii_digit() {
                j += 1;
            }
            if j > ds && j < chars.len() && chars[j] == '"' {
                return Some(j + 1);
            }
            return None;
        }
        i += 1;
    }
    None
}

pub fn items_of(text: &str) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    let mut starts: Vec<usize> = Vec::new();
    let mut i = 0usize;
    while i < chars.len() {
        if chars[i] == '<' {
            if let Some(end) = item_match(&chars, i) {
                starts.push(i);
                i = end;
                continue;
            }
        }
        i += 1;
    }
    let mut blocks = Vec::new();
    for (k, start) in starts.iter().enumerate() {
        let end = starts.get(k + 1).copied().unwrap_or(chars.len());
        blocks.push(chars[*start..end].iter().collect());
    }
    blocks
}

fn span(block: &str, class: &str) -> Option<String> {
    let chars: Vec<char> = block.chars().collect();
    let open = format!("<span class=\"{class}\">");
    let prefix: Vec<char> = open.chars().collect();
    let close: Vec<char> = "</span>".chars().collect();
    let s = find_ci(&chars, &prefix, 0)?;
    let start = s + prefix.len();
    let e = find_ci(&chars, &close, start)?;
    Some(chars[start..e].iter().collect())
}

fn attr8(block: &str, prefix: &str) -> Option<String> {
    let mut from = 0usize;
    while let Some(p) = block[from..].find(prefix) {
        let start = from + p + prefix.len();
        let digits: String = block[start..]
            .chars()
            .take_while(|c| c.is_ascii_digit())
            .collect();
        let after = start + digits.len();
        if digits.len() == 8 && block[after..].starts_with('"') {
            return Some(digits);
        }
        from = start;
    }
    None
}

fn attr_digits(block: &str, prefix: &str) -> Option<i64> {
    let mut from = 0usize;
    while let Some(p) = block[from..].find(prefix) {
        let start = from + p + prefix.len();
        let digits: String = block[start..]
            .chars()
            .take_while(|c| c.is_ascii_digit())
            .collect();
        let after = start + digits.len();
        if !digits.is_empty() && block[after..].starts_with('"') {
            return digits.parse().ok();
        }
        from = start;
    }
    None
}

fn added(block: &str) -> Option<f64> {
    let raw = match attr8(block, "data-date=\"") {
        Some(value) => value,
        None => {
            let shown = span(block, "time").unwrap_or_default();
            cell_text(&shown, "", false).replace('-', "")
        }
    };
    if raw.len() != 8 || !raw.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    ts_from_cn_ymd(&format!("{}-{}-{}", &raw[0..4], &raw[4..6], &raw[6..8]))
}

pub fn parse_magnets(text: &str) -> Vec<Item> {
    let mut items = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for block in items_of(text) {
        let Some(hash) = find_hash40(&block) else {
            continue;
        };
        if !seen.insert(hash.clone()) {
            continue;
        }
        let name = span(&block, "name");
        let meta = span(&block, "meta");
        let mut size = match &meta {
            Some(raw) => parse_size_text(&unescape(&strip_tags(raw, " "))),
            None => 0,
        };
        if size == 0 {
            size = attr_digits(&block, "data-size=\"").unwrap_or(0) * 1024 * 1024;
        }
        let title = match &name {
            Some(raw) => unescape(&strip_tags(raw, " ")),
            None => String::new(),
        };
        items.push(crate::util::make_item(
            &title,
            &hash,
            size,
            None,
            None,
            added(&block).and_then(crate::util::num_from_f64),
            "javdb",
        ));
    }
    items
}

pub fn login_wall(text: &str) -> bool {
    let chars: Vec<char> = text.chars().collect();
    let prefix: Vec<char> = "<title".chars().collect();
    let mut pos = 0usize;
    while let Some(s) = find_ci(&chars, &prefix, pos) {
        let mut i = s + prefix.len();
        while i < chars.len() && chars[i] != '>' {
            i += 1;
        }
        if i < chars.len() {
            let mut j = i + 1;
            while j < chars.len() && chars[j].is_whitespace() {
                j += 1;
            }
            if starts_ci(&chars, "登", j) {
                let mut k = j + 1;
                if k < chars.len() && (chars[k] == '入' || chars[k] == '錄') {
                    k += 1;
                    while k < chars.len() && chars[k].is_whitespace() {
                        k += 1;
                    }
                    if k < chars.len() && chars[k] == '|' {
                        return true;
                    }
                }
            }
        }
        pos = s + 1;
    }
    false
}

fn search_page<F: Fetch>(root: &str, query: &str, page_no: i64, fetch: &F) -> SourceResult<Vec<String>> {
    let qs = format!(
        "f=all&q={}&locale=zh&page={}",
        quote_plus(query),
        page_no.max(1)
    );
    let text = fetch.fetch(
        Req::get(&format!("{root}/search?{qs}"))
            .referer(&format!("{root}/"))
            .header("Accept", "text/html,application/xhtml+xml,*/*;q=0.9")
            .header("Accept-Language", "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7"),
    )?;
    let chars: Vec<char> = text.chars().collect();
    let prefix: Vec<char> = "<a href=\"".chars().collect();
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
        let tail: String = chars[i..].iter().take(13).collect();
        if path.starts_with("/v/")
            && path.len() > 3
            && path[3..].chars().all(|c| c.is_ascii_alphanumeric())
            && tail.to_lowercase().starts_with("\" class=\"box")
            && seen.insert(path.clone())
        {
            out.push(path);
        }
        pos = start;
    }
    Ok(out)
}

fn detail<F: Fetch>(root: &str, path: &str, fetch: &F) -> SourceResult<Vec<Item>> {
    let text = fetch.fetch(
        Req::get(&format!("{root}{path}"))
            .referer(&format!("{root}/"))
            .header("Accept", "text/html,application/xhtml+xml,*/*;q=0.9")
            .header("Accept-Language", "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7"),
    )?;
    if login_wall(&text) {
        return Err(SourceError::Blocked(LOGIN_TEXT.to_string()));
    }
    Ok(parse_magnets(&text))
}

pub fn search<F: Fetch>(base: &str, query: &str, page_no: i64, fetch: &F) -> SourceResult<Vec<Item>> {
    let root = base_of(base, default_base("javdb"));
    let links = search_page(&root, query, page_no, fetch)?;
    if links.is_empty() {
        return Ok(Vec::new());
    }

    let mut found: Vec<Vec<Item>> = Vec::new();
    let mut first_error: Option<SourceError> = None;
    let mut walled = 0usize;
    for path in links.iter().take(DETAILS) {
        match detail(&root, path, fetch) {
            Ok(items) => found.push(items),
            Err(exc) => {
                if matches!(exc, SourceError::Blocked(_)) {
                    walled += 1;
                }
                if first_error.is_none() {
                    first_error = Some(exc);
                }
            }
        }
    }

    let got_magnets = found.iter().any(|group| !group.is_empty());
    if walled > 0 && !got_magnets {
        return Err(SourceError::Blocked(LOGIN_TEXT.to_string()));
    }
    if found.is_empty() {
        if let Some(exc) = first_error {
            return Err(exc);
        }
    }
    Ok(merge_details(&found, MAX_HITS))
}
