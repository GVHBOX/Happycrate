use std::collections::{BTreeMap, VecDeque};
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::model::{Item, SourceError, SourceResult};
use crate::outcome::{classify, outcome_text, state_of, CANCEL_TEXT};
use crate::search::{Event, Sink, Target};
use crate::sources::{self, Fetch, Scoped};
use crate::util::LocalNow;

pub const WORD: &str = "test";
pub const FALLBACK_WORD: &str = "1080p";
pub const WORKERS: usize = 8;
pub const TIMEOUT_CAP: u64 = 8;
pub const BUDGET_MS: u64 = 30000;

static TOKEN: AtomicI64 = AtomicI64::new(0);

fn start_token() -> i64 {
    TOKEN.fetch_add(1, Ordering::SeqCst) + 1
}

fn alive(token: i64) -> bool {
    TOKEN.load(Ordering::SeqCst) == token
}

fn probe_word<F: Fetch + Sync>(
    target: &Target,
    fetch: &F,
    now: &LocalNow,
    budget: u64,
    word: &str,
) -> SourceResult<Vec<Item>> {
    let bound = Scoped {
        inner: fetch,
        timeout: budget,
        batch: None,
        deadline: None,
    };
    sources::search(&target.key, &target.base, word, 1, now, budget, &bound)
}

fn run<F: Fetch + Sync>(target: &Target, fetch: &F, now: &LocalNow) -> (bool, i64, i64, String) {
    let started = Instant::now();
    let budget = target.timeout.min(TIMEOUT_CAP);
    let webview = if sources::WEBVIEW_KEYS.contains(&target.key.as_str()) {
        crate::web_fetch::shared()
    } else {
        None
    };
    let mut found = match webview.as_ref() {
        Some(web) => probe_word(target, &**web, now, budget, WORD),
        None => probe_word(target, fetch, now, budget, WORD),
    };
    if matches!(&found, Ok(items) if items.is_empty()) {
        found = match webview.as_ref() {
            Some(web) => probe_word(target, &**web, now, budget, FALLBACK_WORD),
            None => probe_word(target, fetch, now, budget, FALLBACK_WORD),
        };
    }
    let ms = started.elapsed().as_millis() as i64;
    match found {
        Ok(items) => (true, ms, items.len() as i64, String::new()),
        Err(SourceError::Cancelled) => (false, ms, 0, CANCEL_TEXT.to_string()),
        Err(exc) => (false, ms, 0, exc.search_text()),
    }
}

pub type Seen = Arc<Mutex<BTreeMap<String, Value>>>;

pub fn execute<F: Fetch + Sync>(
    targets: &[Target],
    fetch: &F,
    now: &LocalNow,
    sink: &(dyn Fn(Event) + Sync),
    token: i64,
    seen: &Seen,
) {
    if targets.is_empty() {
        sink(Event::ProbeDone);
        return;
    }
    let workers = targets.len().clamp(1, WORKERS);
    let queue = Mutex::new(targets.iter().collect::<VecDeque<&Target>>());
    let deadline = Instant::now() + Duration::from_millis(BUDGET_MS);
    std::thread::scope(|scope| {
        for _ in 0..workers {
            let queue = &queue;
            scope.spawn(move || loop {
                if !alive(token) || Instant::now() >= deadline {
                    return;
                }
                let target = match queue.lock().unwrap_or_else(|e| e.into_inner()).pop_front() {
                    Some(target) => target,
                    None => return,
                };
                let row = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    run(target, fetch, now)
                }));
                let (ok, ms, count, err) = match row {
                    Ok(res) => res,
                    Err(_) => (false, 0, 0, "内部异常".to_string()),
                };
                if !alive(token) {
                    return;
                }
                let (outcome, code) = classify(ok, count, &err, ms);
                let text = outcome_text(outcome, code);
                let state = state_of(&[outcome.to_string()]);
                crate::log::info(
                    crate::log::SOURCES,
                    &format!("测速 {}：{} 条 {}ms（{}）", target.key, count, ms, outcome),
                );
                let payload = json!({
                    "key": target.key,
                    "state": state,
                    "ms": ms,
                    "err": text,
                    "outcome": outcome,
                });
                if let Ok(mut guard) = seen.lock() {
                    guard.insert(target.key.clone(), payload.clone());
                }
                sink(Event::Probe(payload));
            });
        }
    });
    if alive(token) {
        sink(Event::ProbeDone);
    }
}

pub fn spawn(
    targets: Vec<Target>,
    http: Arc<crate::net::HttpClient>,
    sink: Option<Arc<Sink>>,
    now: LocalNow,
    seen: Seen,
) {
    let token = start_token();
    std::thread::spawn(move || {
        let push = move |event: Event| {
            if let Some(sink) = sink.as_ref() {
                sink(event);
            }
        };
        execute(&targets, http.as_ref(), &now, &push, token, &seen);
    });
}
