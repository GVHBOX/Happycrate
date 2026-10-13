use std::collections::HashSet;
use std::time::{Duration, Instant};

use crate::model::{Item, SourceError, SourceResult};
use crate::sources::{base_of, default_base, Fetch, Req};
use crate::util::{
    find_hash40, make_item, num_from_f64, parse_size_text, quote, to_int, ts_from_cn_dash, unescape,
};

pub const LIST_PAGES: i64 = 4;
pub const PAGE_FULL: usize = 15;
pub const DETAILS: usize = 60;
pub const MAX_HITS: usize = 300;

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

fn list_url(root: &str, query: &str, page: i64) -> String {
    format!("{root}/search?q={}&orderby=seeders&p={page}", quote(query))
}

pub fn search<F: Fetch + Sync>(
    base: &str,
    query: &str,
    page_no: i64,
    fetch: &F,
    timeout: u64,
) -> SourceResult<Vec<Item>> {
    let started = Instant::now();
    let deadline = started + Duration::from_secs(timeout.max(1));
    let root = base_of(base, default_base("bt4g"));
    let referer = format!("{root}/");
    let first = page_no.max(1);

    let mut rows: Vec<Row> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    let mut list_error: Option<SourceError> = None;
    for offset in 0..LIST_PAGES {
        let url = list_url(&root, query, first + offset);
        let text = if offset == 0 {
            fetch.fetch(
                Req::get(&url)
                    .referer(&referer)
                    .header("Accept", "text/html,application/xhtml+xml,*/*;q=0.9")
                    .header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
                    .deadline(deadline),
            )?
        } else {
            let outcome = fetch
                .fetch_many(vec![
                    Req::get(&url)
                        .referer(&referer)
                        .header("Accept", "text/html,application/xhtml+xml,*/*;q=0.9")
                        .header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
                        .deadline(deadline),
                ])
                .into_iter()
                .next()
                .unwrap_or(Err(SourceError::Transport("取数通道无返回".to_string())));
            match outcome {
                Ok(text) => text,
                Err(exc) => {
                    if matches!(exc, SourceError::Cancelled) {
                        return Err(exc);
                    }
                    list_error = Some(exc);
                    break;
                }
            }
        };
        let page_rows: Vec<Row> = blocks(&text)
            .iter()
            .filter_map(|block| row_of(block))
            .collect();
        let full = page_rows.len() >= PAGE_FULL;
        for row in page_rows {
            if seen.insert(row.path.clone()) {
                rows.push(row);
            }
        }
        if !full {
            break;
        }
    }

    if rows.is_empty() {
        if let Some(exc) = list_error {
            return Err(exc);
        }
        return Ok(Vec::new());
    }

    let limit = rows.len().min(DETAILS);
    let urls: Vec<String> = rows[..limit]
        .iter()
        .map(|row| format!("{root}{}", row.path))
        .collect();
    let requests: Vec<Req> = urls
        .iter()
        .map(|url| {
            Req::get(url)
                .referer(&referer)
                .header("Accept", "text/html,application/xhtml+xml,*/*;q=0.9")
                .header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
                .deadline(deadline)
        })
        .collect();
    let results = fetch.fetch_many(requests);

    let mut items: Vec<Item> = Vec::new();
    let mut first_error: Option<SourceError> = None;
    for (row, outcome) in rows[..limit].iter().zip(results.into_iter()) {
        match outcome {
            Ok(page) => match find_hash40(&page) {
                Some(hash) => items.push(make_item(
                    &row.title,
                    &hash,
                    row.size,
                    row.seeders,
                    row.leechers,
                    row.added.clone(),
                    "bt4g",
                )),
                None => {
                    if first_error.is_none() {
                        first_error =
                            Some(SourceError::Shape("bt4g 磁力页缺少 info hash".to_string()));
                    }
                }
            },
            Err(exc) => {
                if matches!(exc, SourceError::Cancelled) {
                    return Err(exc);
                }
                if first_error.is_none() {
                    first_error = Some(exc);
                }
            }
        }
    }
    if items.is_empty() {
        if let Some(exc) = first_error {
            return Err(exc);
        }
        return Ok(Vec::new());
    }
    items.truncate(MAX_HITS);
    Ok(items)
}
