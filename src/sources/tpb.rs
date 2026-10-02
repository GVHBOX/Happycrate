use std::collections::HashSet;
use std::time::{Duration, Instant};

use crate::model::{Item, SourceResult};
use crate::model::SourceError;
use crate::sources::{collect_pages, gather_pages, Fetch, Req};
use crate::util::{
    cell_text, civil_stamp, find_ci, find_hex_after, findall_bounded,
    make_item, num_from_f64, parse_size_text, quote, strip_tags, to_int, unescape, LocalNow,
};

pub const MIRRORS: [&str; 4] = [
    "https://thepiratebay10.org",
    "https://thepiratebay10.xyz",
    "https://tpb.party",
    "https://piratebayproxy.live",
];
pub const PAGES: i64 = 20;
pub const MAX_HITS: usize = 600;
pub const PAGE_SIZE: usize = 30;

const RESULT_MARK: &str = "id=\"searchResult\"";

fn added(raw: &str, now: &LocalNow) -> Option<f64> {
    let text = raw.trim();
    if text.is_empty() {
        return None;
    }
    let now_ts = now.naive - now.offset;

    let tokens: Vec<&str> = text.split_whitespace().collect();
    if tokens.len() != 2 {
        return None;
    }
    let clock: Vec<&str> = tokens[1].split(':').collect();
    if clock.len() != 2 || clock[1].len() != 2 {
        return None;
    }
    if clock[0].is_empty() || clock[0].len() > 2 {
        return None;
    }
    if !clock[0].bytes().all(|b| b.is_ascii_digit()) || !clock[1].bytes().all(|b| b.is_ascii_digit())
    {
        return None;
    }
    let hour: i64 = clock[0].parse().ok()?;
    let minute: i64 = clock[1].parse().ok()?;
    if hour > 23 || minute > 59 {
        return None;
    }

    let lower = tokens[0].to_lowercase();
    if lower == "today" || lower == "y-day" || lower == "yday" {
        let base = if lower == "today" {
            now.naive
        } else {
            now.naive - 86400
        };
        let day_start = base - base.rem_euclid(86400);
        return Some((day_start + hour * 3600 + minute * 60 - now.offset) as f64);
    }

    let parts: Vec<&str> = tokens[0].split('-').collect();
    if parts.len() != 2 || parts[0].len() != 2 || parts[1].len() != 2 {
        return None;
    }
    let month: i64 = parts[0].parse().ok()?;
    let day: i64 = parts[1].parse().ok()?;
    let clock_secs = hour * 3600 + minute * 60;
    let base = civil_stamp(now.year, month, day)? * 86400 + clock_secs - now.offset;
    if base > now_ts + 86400 {
        let rolled = civil_stamp(now.year - 1, month, day)? * 86400 + clock_secs - now.offset;
        return Some(rolled as f64);
    }
    Some(base as f64)
}

fn title_link(row: &str) -> Option<String> {
    let chars: Vec<char> = row.chars().collect();
    let prefix: Vec<char> = "href=\"".chars().collect();
    let needle: Vec<char> = "/torrent/".chars().collect();
    let close_a: Vec<char> = "</a>".chars().collect();
    let mut pos = 0usize;
    while let Some(s) = find_ci(&chars, &prefix, pos) {
        let vs = s + prefix.len();
        let mut ve = vs;
        while ve < chars.len() && chars[ve] != '"' {
            ve += 1;
        }
        if ve >= chars.len() {
            return None;
        }
        let mut last = None;
        let mut q = 0usize;
        while let Some(p) = find_ci(&chars[vs..ve], &needle, q) {
            last = Some(vs + p);
            q = p + 1;
        }
        if let Some(t) = last {
            let mut i = t + needle.len();
            let ds = i;
            while i < ve && chars[i].is_ascii_digit() {
                i += 1;
            }
            if i > ds && i < ve && chars[i] == '/' && i + 1 < ve {
                let mut gt = ve + 1;
                while gt < chars.len() && chars[gt] != '>' {
                    gt += 1;
                }
                if gt < chars.len() {
                    if let Some(e) = find_ci(&chars, &close_a, gt + 1) {
                        let label: String = chars[gt + 1..e].iter().collect();
                        return Some(strip_tags(&label, ""));
                    }
                }
            }
        }
        pos = ve;
    }
    None
}

pub fn parse(text: &str, now_iso: &LocalNow) -> Vec<Item> {
    let mut items = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for row in findall_bounded(text, "<tr", "</tr>") {
        let Some(hash) = find_hex_after(&row, "href=\"magnet:?xt=urn:btih:", 40) else {
            continue;
        };
        if !seen.insert(hash.clone()) {
            continue;
        }
        let title = title_link(&row)
            .map(|label| unescape(&label))
            .unwrap_or_default();
        let cells: Vec<String> = findall_bounded(&row, "<td", "</td>")
            .iter()
            .map(|c| cell_text(c, "", true))
            .collect();
        items.push(make_item(
            &title,
            &hash,
            if cells.len() > 4 {
                parse_size_text(&cells[4])
            } else {
                0
            },
            if cells.len() > 5 {
                to_int(&serde_json::Value::String(cells[5].clone()))
            } else {
                None
            },
            if cells.len() > 6 {
                to_int(&serde_json::Value::String(cells[6].clone()))
            } else {
                None
            },
            if cells.len() > 2 {
                added(&cells[2], now_iso).and_then(num_from_f64)
            } else {
                None
            },
            "tpb",
        ));
    }
    items
}

fn fetch_page<F: Fetch>(
    root: &str,
    query: &str,
    page_no: i64,
    fetch: &F,
    timeout: u64,
) -> SourceResult<String> {
    let url = format!("{root}/search/{}/{page_no}/99/0", quote(query));
    fetch.fetch(Req::get(&url).retries(0).timeout(timeout))
}

fn more_pages<F: Fetch + Sync>(
    root: &str,
    query: &str,
    page_no: i64,
    fetch: &F,
    first: Vec<Item>,
    now_iso: &LocalNow,
    timeout: u64,
) -> Vec<Item> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut items: Vec<Item> = Vec::new();
    for item in first {
        seen.insert(item.info_hash.clone());
        items.push(item);
    }
    if items.len() < PAGE_SIZE {
        return items;
    }

    let first_page = page_no.max(1);
    let (pages, _) = gather_pages(first_page + 1..first_page + PAGES, 6, |&p| {
        let text = fetch_page(root, query, p, fetch, timeout)?;
        if text.contains(RESULT_MARK) {
            Ok(parse(&text, now_iso))
        } else {
            Ok(Vec::new())
        }
    });
    collect_pages(&pages, &mut seen, &mut items, MAX_HITS);
    items
}

pub fn search<F: Fetch + Sync>(
    base: &str,
    query: &str,
    page_no: i64,
    fetch: &F,
    now_iso: &LocalNow,
    timeout: u64,
) -> SourceResult<Vec<Item>> {
    let roots: Vec<String> = if base.is_empty() {
        MIRRORS.iter().map(|m| m.to_string()).collect()
    } else {
        vec![base.trim_end_matches('/').to_string()]
    };
    let budget = timeout.max(1);
    let per_try = (budget / 2).max(3);
    let deadline = Instant::now() + Duration::from_secs(budget);
    let mut net_exc = None;
    let mut shape_exc = None;
    for root in &roots {
        let left = deadline.saturating_duration_since(Instant::now()).as_secs();
        if left < 1 {
            break;
        }
        let text = match fetch_page(root, query, page_no, fetch, left.min(per_try)) {
            Ok(text) => text,
            Err(exc) => {
                net_exc = Some(exc);
                continue;
            }
        };
        if !text.contains(RESULT_MARK) {
            shape_exc = Some(SourceError::Shape(format!(
                "TPB 镜像 {root} 返回的不是搜索结果页"
            )));
            continue;
        }
        let items = parse(&text, now_iso);
        if !items.is_empty() {
            return Ok(more_pages(root, query, page_no, fetch, items, now_iso, timeout));
        }
        let lower = text.to_lowercase();
        if lower.contains("no hits") || lower.contains("nothing found") {
            return Ok(Vec::new());
        }
    }
    if let Some(exc) = net_exc {
        return Err(exc);
    }
    if let Some(exc) = shape_exc {
        return Err(exc);
    }
    Ok(Vec::new())
}
