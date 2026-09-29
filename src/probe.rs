use std::collections::BTreeMap;
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use serde_json::{json, Value};

use crate::model::SourceError;
use crate::outcome::{classify, outcome_text, state_of, CANCEL_TEXT};
use crate::search::{Event, Sink, Target};
use crate::sources::{self, Fetch, Scoped};
use crate::util::LocalNow;

pub const WORD: &str = "test";
pub const FALLBACK_WORD: &str = "1080p";
pub const WORKERS: usize = 8;

static TOKEN: AtomicI64 = AtomicI64::new(0);

fn start_token() -> i64 {
    TOKEN.fetch_add(1, Ordering::SeqCst) + 1
}

fn alive(token: i64) -> bool {
    TOKEN.load(Ordering::SeqCst) == token
}

fn run<F: Fetch>(target: &Target, fetch: &F, now: &LocalNow) -> (bool, i64, i64, String) {
    let started = Instant::now();
    let bound = Scoped {
        inner: fetch,
        timeout: target.timeout,
        batch: None,
    };
    let mut found = sources::search(
        &target.key,
        &target.base,
        WORD,
        1,
        now,
        target.timeout,
        &bound,
    );
    if matches!(&found, Ok(items) if items.is_empty()) {
        found = sources::search(
            &target.key,
            &target.base,
            FALLBACK_WORD,
            1,
            now,
            target.timeout,
            &bound,
        );
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
    let workers = targets.len().min(WORKERS).max(1);
    std::thread::scope(|scope| {
        for lane in 0..workers {
            scope.spawn(move || {
                for target in targets.iter().skip(lane).step_by(workers) {
                    if !alive(token) {
                        return;
                    }
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
                }
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
