use crate::model::{Item, SourceError, SourceResult};
use crate::sources::{base_of, default_base, gather_pages, merge_details, Fetch, Req};
use crate::util::{
    find_hash40, make_item, num_from_f64, parse_size_text, quote, to_int, ts_from_cn_dash, unescape,
};

use std::time::Instant;

pub const DETAILS: usize = 12;
pub const MAX_HITS: usize = 300;
pub const DETAIL_MS: u64 = 2000;
pub const RESERVE_MS: u64 = 2000;

struct Row {
    title: String,
    path: String,
    size: i64,
    seeders: Option<i64>,
    leechers: Option<i64>,
    added: Option<serde_json::Number>,
}

fn blocks(text: &str) -> Vec<String> {
    let open = "<div class=\"notion-list-item\">";
    let body = "</body>";
    let mut out = Vec::new();
    let mut pos = 0usize;
    while let Some(found) = text[pos..].find(open) {
        let start = pos + found + open.len();
        let end = match (text[start..].find(open), text[start..].find(body)) {
            (Some(next), Some(stop)) => start + next.min(stop),
            (Some(next), None) => start + next,
            (None, Some(stop)) => start + stop,
            (None, None) => text.len(),
        };
        out.push(text[start..end].to_string());
        pos = end;
    }
    out
}

fn title_of(block: &str) -> Option<String> {
    let anchor = block.find("<a title=\"")? + "<a title=\"".len();
    let rest = &block[anchor..];
    let end = rest.find('"')?;
    Some(unescape(&rest[..end]))
}

fn path_of(block: &str) -> Option<String> {
    let anchor = block.find("href=\"/magnet/")? + "href=\"".len();
    let rest = &block[anchor..];
    let end = rest.find('"')?;
    Some(rest[..end].to_string())
}

fn value_after(block: &str, label: &str) -> Option<String> {
    let at = block.find(label)? + label.len();
    let rest = &block[at..];
    let lt = rest.find('<')?;
    let plain = rest[..lt].replace("&nbsp;", " ").trim().to_string();
    if !plain.is_empty() {
        return Some(unescape(&plain));
    }
    let gt = rest[lt..].find('>')? + lt;
    let tail = &rest[gt + 1..];
    let end = tail.find('<')?;
    Some(unescape(tail[..end].trim()))
}

fn row_of(block: &str) -> Option<Row> {
    let path = path_of(block)?;
    let title = title_of(block)?;
    let size = value_after(block, "Total Size:")
        .map(|raw| parse_size_text(&raw))
        .unwrap_or(0);
    let seeders = value_after(block, "Seeders:")
        .and_then(|raw| to_int(&serde_json::Value::String(raw)));
    let leechers = value_after(block, "Leechers:")
        .and_then(|raw| to_int(&serde_json::Value::String(raw)));
    let added = value_after(block, "Creation Time:")
        .and_then(|raw| ts_from_cn_dash(&raw))
        .and_then(num_from_f64);
    Some(Row {
        title,
        path,
        size,
        seeders,
        leechers,
        added,
    })
}

fn detail<F: Fetch>(root: &str, row: &Row, fetch: &F) -> SourceResult<Item> {
    let page = fetch.fetch(
        Req::get(&format!("{root}{}", row.path))
            .referer(&format!("{root}/"))
            .header("Accept", "text/html,application/xhtml+xml,*/*;q=0.9")
            .header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8"),
    )?;
    let hash = find_hash40(&page)
        .ok_or_else(|| SourceError::Shape("bt4g 磁力页缺少 info hash".to_string()))?;
    Ok(make_item(
        &row.title,
        &hash,
        row.size,
        row.seeders,
        row.leechers,
        row.added.clone(),
        "bt4g",
    ))
}

fn detail_budget(ms: u64) -> usize {
    let usable = ms.saturating_sub(RESERVE_MS);
    ((usable / DETAIL_MS) as usize).max(1)
}

fn fanout<F: Fetch + Sync>(
    root: &str,
    rows: &[Row],
    fetch: &F,
    budget_ms: u64,
) -> SourceResult<Vec<Item>> {
    let limit = rows.len().min(DETAILS).min(detail_budget(budget_ms));
    let (details, failed) = gather_pages(0..limit, 4, |&i| detail(root, &rows[i], fetch));
    if let Some(err) = failed.values().find(|e| matches!(e, SourceError::Cancelled)) {
        return Err(err.clone());
    }
    let found: Vec<Vec<Item>> = details.into_values().map(|item| vec![item]).collect();
    if found.is_empty() {
        if let Some(exc) = failed.values().next() {
            return Err(exc.clone());
        }
    }
    Ok(merge_details(&found, MAX_HITS))
}

pub fn search<F: Fetch + Sync>(
    base: &str,
    query: &str,
    page_no: i64,
    fetch: &F,
    timeout: u64,
) -> SourceResult<Vec<Item>> {
    let started = Instant::now();
    let root = base_of(base, default_base("bt4g"));
    let url = format!(
        "{root}/search?q={}&orderby=seeders&p={}",
        quote(query),
        page_no.max(1)
    );
    let text = fetch.fetch(
        Req::get(&url)
            .referer(&format!("{root}/"))
            .header("Accept", "text/html,application/xhtml+xml,*/*;q=0.9")
            .header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8"),
    )?;
    let rows: Vec<Row> = blocks(&text)
        .iter()
        .filter_map(|block| row_of(block))
        .collect();
    if rows.is_empty() {
        return Ok(Vec::new());
    }
    let spent = started.elapsed().as_millis() as u64;
    let budget = timeout.saturating_mul(1000).saturating_sub(spent);
    fanout(&root, &rows, fetch, budget)
}
