use std::collections::{BTreeMap, HashSet};

use crate::model::{Item, SourceError, SourceResult};
use crate::sources::{
    base_of, collect_pages, default_base, first_failure, gather_pages, Fetch, Req,
};
use crate::util::{
    find_ci, find_tag_end, make_item, num_from_f64, parse_size_text, quote, to_int,
    ts_from_cn_dash, unescape,
};

pub const PAGES: i64 = 10;
pub const PAGE_SIZE: i64 = 20;
pub const MAX_HITS: usize = 400;
const RETRY_PAUSE_MS: u64 = 2000;

fn starts_ci(chars: &[char], needle: &str, at: usize) -> bool {
    let needle: Vec<char> = needle.chars().collect();
    chars.len() >= at + needle.len()
        && find_ci(&chars[at..at + needle.len()], &needle, 0) == Some(0)
}

fn label_value(block: &str, label: &str, attrs: bool) -> Option<String> {
    let chars: Vec<char> = block.chars().collect();
    let lab: Vec<char> = label.chars().collect();
    let mut pos = 0usize;
    while let Some(s) = find_ci(&chars, &lab, pos) {
        let mut i = s + lab.len();
        while i < chars.len() && chars[i] != '<' {
            i += 1;
        }
        if i >= chars.len() {
            return None;
        }
        let value = if attrs {
            if !starts_ci(&chars, "<b", i) {
                pos = s + 1;
                continue;
            }
            {
                let gt = find_tag_end(&chars, i + 2)?;
                gt + 1
            }
        } else {
            if !starts_ci(&chars, "<b>", i) {
                pos = s + 1;
                continue;
            }
            i + 3
        };
        let mut j = value;
        while j < chars.len() && chars[j] != '<' {
            j += 1;
        }
        if j > value && starts_ci(&chars, "</b>", j) {
            return Some(chars[value..j].iter().collect());
        }
        pos = s + 1;
    }
    None
}

fn title_value(block: &str) -> Option<String> {
    let chars: Vec<char> = block.chars().collect();
    let prefix: Vec<char> = "<a title=\"".chars().collect();
    let mut pos = 0usize;
    while let Some(s) = find_ci(&chars, &prefix, pos) {
        let start = s + prefix.len();
        let mut i = start;
        while i < chars.len() && chars[i] != '"' {
            i += 1;
        }
        if i < chars.len() {
            return Some(chars[start..i].iter().collect());
        }
        pos = s + 1;
    }
    None
}

fn hash_link(block: &str) -> Option<String> {
    let chars: Vec<char> = block.chars().collect();
    let prefix: Vec<char> = "href=\"/hash/".chars().collect();
    let mut pos = 0usize;
    while let Some(s) = find_ci(&chars, &prefix, pos) {
        let mut i = s + prefix.len();
        let mut hex = String::new();
        while i < chars.len() && chars[i].is_ascii_hexdigit() && hex.len() < 40 {
            hex.push(chars[i]);
            i += 1;
        }
        if hex.len() == 40 && starts_ci(&chars, ".html\"", i) {
            return Some(hex.to_lowercase());
        }
        pos = s + 1;
    }
    None
}

fn blocks(text: &str) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    let open: Vec<char> = "<div class=\"search-item".chars().collect();
    let body: Vec<char> = "</body>".chars().collect();
    let mut out = Vec::new();
    let mut pos = 0usize;
    while let Some(s) = find_ci(&chars, &open, pos) {
        let Some(gt) = find_tag_end(&chars, s + open.len()) else {
            break;
        };
        let cs = gt + 1;
        let end = match (find_ci(&chars, &open, cs), find_ci(&chars, &body, cs)) {
            (Some(a), Some(b)) => a.min(b),
            (Some(a), None) => a,
            (None, Some(b)) => b,
            (None, None) => break,
        };
        out.push(chars[cs..end].iter().collect());
        pos = end;
    }
    out
}

fn found_total(text: &str) -> Option<i64> {
    let chars: Vec<char> = text.chars().collect();
    let mark: Vec<char> = "找到".chars().collect();
    let mut from = 0usize;
    while let Some(at) = find_ci(&chars, &mark, from) {
        let mut i = at + mark.len();
        let mut digits = String::new();
        while i < chars.len() {
            let c = chars[i];
            if c.is_ascii_digit() {
                digits.push(c);
                i += 1;
            } else if c == ',' || c == '，' {
                i += 1;
            } else {
                break;
            }
        }
        if !digits.is_empty() && chars.get(i) == Some(&'条') {
            if let Ok(total) = digits.parse::<i64>() {
                return Some(total);
            }
        }
        from = at + mark.len();
    }
    None
}

fn wanted_pages(total: Option<i64>) -> i64 {
    match total {
        Some(0) => 1,
        Some(n) if n > 0 => {
            let mut need = (n + PAGE_SIZE - 1) / PAGE_SIZE;
            if n % PAGE_SIZE == 0 && need < PAGES {
                need += 1;
            }
            need.clamp(1, PAGES)
        }
        _ => PAGES,
    }
}

fn worth_retry(error: &SourceError) -> bool {
    match error {
        SourceError::Cancelled
        | SourceError::Blocked(_)
        | SourceError::TooLarge { .. }
        | SourceError::ProxyUnreachable(_) => false,
        SourceError::Http { code, .. } => *code == 429 || *code >= 500,
        _ => true,
    }
}

fn retry_keys(failed: &BTreeMap<i64, SourceError>) -> Vec<i64> {
    failed
        .iter()
        .filter(|(_, error)| worth_retry(error))
        .map(|(page, _)| *page)
        .collect()
}

fn refill<F: Fetch + Sync>(
    root: &str,
    query: &str,
    keys: &[i64],
    fetch: &F,
    pages: &mut BTreeMap<i64, Vec<Item>>,
) -> BTreeMap<i64, SourceError> {
    let (found, lost) = gather_pages(keys.iter().copied(), 2, |&p| {
        page(root, p, query, fetch).map(|(items, _)| items)
    });
    pages.extend(found);
    lost
}

pub fn parse_html(text: &str) -> Vec<Item> {
    let mut items = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for block in blocks(text) {
        let Some(hash) = hash_link(&block) else {
            continue;
        };
        if !seen.insert(hash.clone()) {
            continue;
        }
        let title = title_value(&block);
        let size = label_value(&block, "文件大小:", true);
        let date = label_value(&block, "创建时间:", false);
        let heat = label_value(&block, "下载热度:", false);
        items.push(make_item(
            &title.map(|t| unescape(&t)).unwrap_or_default(),
            &hash,
            size.map(|s| parse_size_text(&s)).unwrap_or(0),
            heat.and_then(|h| to_int(&serde_json::Value::String(h))),
            None,
            date.and_then(|d| ts_from_cn_dash(&d)).and_then(num_from_f64),
            "xccl263",
        ));
    }
    items
}

fn fetch_text<F: Fetch>(root: &str, page_no: i64, query: &str, fetch: &F) -> SourceResult<String> {
    let url = format!("{root}/search/kw-{}-{page_no}.html", quote(query));
    fetch.fetch(
        Req::get(&url)
            .referer(&format!("{root}/"))
            .header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
            .header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8"),
    )
}

fn page<F: Fetch>(
    root: &str,
    page_no: i64,
    query: &str,
    fetch: &F,
) -> SourceResult<(Vec<Item>, Option<i64>)> {
    let text = fetch_text(root, page_no, query, fetch)?;
    let total = found_total(&text);
    Ok((parse_html(&text), total))
}

fn search_words<F: Fetch + Sync>(
    root: &str,
    query: &str,
    page_no: i64,
    fetch: &F,
) -> SourceResult<Vec<Item>> {
    let first = page_no.max(1);
    let mut pages: BTreeMap<i64, Vec<Item>> = BTreeMap::new();
    let mut failed: BTreeMap<i64, SourceError> = BTreeMap::new();
    let mut total: Option<i64> = None;
    match page(root, first, query, fetch) {
        Ok((items, count)) => {
            if first == 1 {
                total = count;
            }
            pages.insert(first, items);
        }
        Err(exc) => {
            failed.insert(first, exc);
        }
    }
    let need = if first == 1 { wanted_pages(total) } else { PAGES };
    if need > 1 {
        let (found, lost) = gather_pages(first + 1..first + need, 2, |&p| {
            page(root, p, query, fetch).map(|(items, _)| items)
        });
        pages.extend(found);
        failed.extend(lost);
    }
    if !pages.is_empty() {
        let quick = retry_keys(&failed);
        if !quick.is_empty() {
            let lost = refill(root, query, &quick, fetch, &mut pages);
            failed.retain(|page, _| !quick.contains(page));
            failed.extend(lost);
        }
        let spaced = retry_keys(&failed);
        if !spaced.is_empty() {
            if !crate::sources::pause(fetch.batch(), RETRY_PAUSE_MS) {
                return Err(SourceError::Cancelled);
            }
            let lost = refill(root, query, &spaced, fetch, &mut pages);
            failed.extend(lost);
        }
    }
    if pages.is_empty() && !failed.is_empty() {
        return Err(first_failure(&failed));
    }
    let mut items = Vec::new();
    collect_pages(&pages, &mut HashSet::new(), &mut items, MAX_HITS);
    Ok(items)
}

fn alternate_code(word: &str) -> Option<String> {
    let chars: Vec<char> = word.chars().collect();
    let mut i = 0usize;
    while i < chars.len() && chars[i].is_ascii_alphabetic() {
        i += 1;
    }
    if !(2..=12).contains(&i) {
        return None;
    }
    let letters: String = chars[..i].iter().collect();
    let mut sep = false;
    if i < chars.len() && (chars[i] == '-' || chars[i] == '_') {
        sep = true;
        i += 1;
    }
    let start = i;
    while i < chars.len() && chars[i].is_ascii_digit() {
        i += 1;
    }
    let digits: String = chars[start..i].iter().collect();
    if i != chars.len() || !(2..=5).contains(&digits.len()) {
        return None;
    }
    if sep {
        Some(format!("{letters}{digits}"))
    } else {
        Some(format!("{letters}-{digits}"))
    }
}

fn merge_alternate<F: Fetch + Sync>(
    root: &str,
    page_no: i64,
    items: Vec<Item>,
    alternate: &str,
    fetch: &F,
) -> Vec<Item> {
    let mut merged: Vec<Item> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for item in items {
        if item.info_hash.is_empty() || !seen.insert(item.info_hash.clone()) {
            continue;
        }
        merged.push(item);
        if merged.len() >= MAX_HITS {
            return merged;
        }
    }
    if let Ok(found) = search_words(root, alternate, page_no, fetch) {
        for item in found {
            if item.info_hash.is_empty() || !seen.insert(item.info_hash.clone()) {
                continue;
            }
            merged.push(item);
            if merged.len() >= MAX_HITS {
                return merged;
            }
        }
    }
    merged
}

pub fn search<F: Fetch + Sync>(base: &str, query: &str, page_no: i64, fetch: &F) -> SourceResult<Vec<Item>> {
    let root = base_of(base, default_base("xccl263"));
    let words: Vec<String> = query
        .split_whitespace()
        .map(str::to_string)
        .collect();
    if words.is_empty() {
        return Ok(Vec::new());
    }

    let items = search_words(&root, query, page_no, fetch)?;
    if words.len() == 1 {
        if let Some(alternate) = alternate_code(&words[0]) {
            return Ok(merge_alternate(&root, page_no, items, &alternate, fetch));
        }
    }
    if !items.is_empty() || words.len() < 2 {
        return Ok(items);
    }

    let mut merged: Vec<Item> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    let mut first_error: Option<SourceError> = None;
    for word in &words {
        match search_words(&root, word, page_no, fetch) {
            Ok(found) => {
                for item in found {
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
