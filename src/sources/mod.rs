pub mod apibay;
pub mod bitsearch;
pub mod dmhy;
pub mod eztv;
pub mod javbus;
pub mod javdb;
pub mod knaben;
pub mod mikan;
pub mod nyaa;
pub mod xccl263;
pub mod sukebei;
pub mod tpb;

use std::collections::{BTreeMap, HashSet};
use std::sync::atomic::{AtomicI64, Ordering};

use crate::model::{Item, SourceError, SourceResult};

pub const PAGELESS_KEYS: &[&str] = &["apibay", "mikan", "dmhy", "eztv"];
pub const KEYWORD_SAMPLE: usize = 12;
pub const FUZZY_RATE: f64 = 0.2;
pub const OVERSEAS_KEYS: [&str; 9] = [
    "nyaa", "sukebei", "mikan", "dmhy", "eztv", "bitsearch", "tpb", "javbus", "javdb",
];

static CANCEL_EPOCH: AtomicI64 = AtomicI64::new(0);

pub fn start_batch() -> i64 {
    CANCEL_EPOCH.fetch_add(1, Ordering::SeqCst) + 1
}

pub fn cancel_batch(token: i64) {
    let _ = CANCEL_EPOCH.fetch_update(Ordering::SeqCst, Ordering::SeqCst, |current| {
        if current <= token {
            Some(token + 1)
        } else {
            None
        }
    });
}

pub fn batch_alive(token: i64) -> bool {
    CANCEL_EPOCH.load(Ordering::SeqCst) == token
}

pub fn keyword_hit_rate(items: &[Item], needles: &[String]) -> f64 {
    let wanted: Vec<String> = needles
        .iter()
        .map(|n| n.trim().to_lowercase())
        .filter(|s| !s.is_empty())
        .collect();
    if wanted.is_empty() {
        return 1.0;
    }
    let pool: Vec<&Item> = items.iter().take(KEYWORD_SAMPLE).collect();
    if pool.is_empty() {
        return 1.0;
    }
    let hit = pool
        .iter()
        .filter(|it| {
            let title = it.title.to_lowercase();
            wanted.iter().any(|w| title.contains(w.as_str()))
        })
        .count();
    hit as f64 / pool.len() as f64
}

pub const DEFAULT_BASES: &[(&str, &str)] = &[
    ("apibay", "https://apibay.org"),
    ("nyaa", "https://nyaa.si"),
    ("mikan", "https://mikanani.me"),
    ("dmhy", "https://share.dmhy.org"),
    ("sukebei", "https://sukebei.nyaa.si"),
    ("eztv", "https://eztvx.to"),
    ("bitsearch", "https://bitsearch.to"),
    ("tpb", "https://thepiratebay10.org"),
    ("xccl263", "https://www.xccl263.xyz"),
    ("knaben", "https://api.knaben.org/v1"),
    ("javbus", "https://www.javbus.com"),
    ("javdb", "https://javdb.com"),
];

pub struct Req<'a> {
    pub url: &'a str,
    pub data: Option<&'a [u8]>,
    pub referer: &'a str,
    pub headers: Vec<(&'a str, &'a str)>,
    pub retries: Option<u32>,
    pub timeout: Option<u64>,
    pub batch: Option<i64>,
}

impl<'a> Req<'a> {
    pub fn get(url: &'a str) -> Self {
        Req {
            url,
            data: None,
            referer: "",
            headers: Vec::new(),
            retries: None,
            timeout: None,
            batch: None,
        }
    }

    pub fn post(url: &'a str, data: &'a [u8]) -> Self {
        Req {
            data: Some(data),
            ..Req::get(url)
        }
    }

    pub fn referer(mut self, referer: &'a str) -> Self {
        self.referer = referer;
        self
    }

    pub fn header(mut self, name: &'a str, value: &'a str) -> Self {
        self.headers.push((name, value));
        self
    }

    pub fn retries(mut self, retries: u32) -> Self {
        self.retries = Some(retries);
        self
    }

    pub fn timeout(mut self, seconds: u64) -> Self {
        self.timeout = Some(seconds);
        self
    }

    pub fn batch(mut self, token: i64) -> Self {
        self.batch = Some(token);
        self
    }
}

pub struct Scoped<'a, F: Fetch> {
    pub inner: &'a F,
    pub timeout: u64,
    pub batch: Option<i64>,
}

impl<F: Fetch> Fetch for Scoped<'_, F> {
    fn fetch(&self, mut req: Req) -> SourceResult<String> {
        if req.timeout.is_none() {
            req.timeout = Some(self.timeout);
        }
        if req.batch.is_none() {
            req.batch = self.batch;
        }
        self.inner.fetch(req)
    }
}

pub fn search<F: Fetch>(
    key: &str,
    base: &str,
    query: &str,
    page: i64,
    now: &crate::util::LocalNow,
    timeout: u64,
    fetch: &F,
) -> SourceResult<Vec<Item>> {
    let page = if PAGELESS_KEYS.contains(&key) {
        1
    } else {
        page.max(1)
    };
    match key {
        "apibay" => apibay::search(base, query, fetch),
        "nyaa" => nyaa::family(base, query, page, fetch, "nyaa", 14, 1100),
        "mikan" => mikan::search(base, query, fetch),
        "dmhy" => dmhy::search(base, query, fetch),
        "sukebei" => sukebei::search(base, query, page, fetch),
        "eztv" => eztv::search(base, query, fetch),
        "bitsearch" => bitsearch::search(base, query, page, fetch),
        "tpb" => tpb::search(base, query, page, fetch, now, timeout),
        "xccl263" => xccl263::search(base, query, page, fetch),
        "knaben" => knaben::search(base, query, page, fetch),
        "javbus" => javbus::search(base, query, page, fetch),
        "javdb" => javdb::search(base, query, page, fetch),
        other => Err(SourceError::Shape(format!("未知数据源 {other}"))),
    }
}

pub trait Fetch {
    fn fetch(&self, req: Req) -> SourceResult<String>;

    fn get(&self, url: &str, data: Option<&[u8]>) -> SourceResult<String> {
        let req = match data {
            Some(body) => Req::post(url, body),
            None => Req::get(url),
        };
        self.fetch(req)
    }
}

pub fn default_base(key: &str) -> &'static str {
    DEFAULT_BASES
        .iter()
        .find(|(k, _)| *k == key)
        .map(|(_, v)| *v)
        .unwrap_or("")
}

pub fn base_of(base: &str, default: &str) -> String {
    let chosen = if base.is_empty() { default } else { base };
    chosen.trim_end_matches('/').to_string()
}

pub fn collect_pages(
    pages: &BTreeMap<i64, Vec<Item>>,
    seen: &mut HashSet<String>,
    items: &mut Vec<Item>,
    max_hits: usize,
) {
    for page in pages.values() {
        for item in page {
            if !seen.insert(item.info_hash.clone()) {
                continue;
            }
            items.push(item.clone());
            if items.len() >= max_hits {
                return;
            }
        }
    }
}

pub fn first_failure(failed: &BTreeMap<i64, SourceError>) -> SourceError {
    failed
        .values()
        .next()
        .cloned()
        .unwrap_or(SourceError::Shape("全部页面失败".to_string()))
}

pub fn merge_details(found: &[Vec<Item>], max_hits: usize) -> Vec<Item> {
    let mut merged: Vec<Item> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for group in found {
        for item in group {
            if item.info_hash.is_empty() || !seen.insert(item.info_hash.clone()) {
                continue;
            }
            merged.push(item.clone());
            if merged.len() >= max_hits {
                return merged;
            }
        }
    }
    merged
}
