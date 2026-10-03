use std::collections::{BTreeMap, BTreeSet, HashMap, VecDeque};
use std::sync::{mpsc, Condvar, LazyLock, Mutex};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::api::{item_view, relaxed_query};
use crate::core::dedupe;
use crate::model::{Item, SourceError};
use crate::outcome::{classify, outcome_text, is_timeout_text, state_of, CANCEL_TEXT};
use crate::query;
use crate::sources::{self, Fetch, Scoped};
use crate::util::LocalNow;

pub const CACHE_TTL: f64 = 60.0;
pub const CACHE_MAX: usize = 8;
pub const MAX_RELAX_ROUNDS: usize = 2;

pub struct Target {
    pub key: String,
    pub base: String,
    pub timeout: u64,
}

pub struct Hints {
    pub proxy: String,
    pub has_proxy: bool,
    pub tun: String,
}

pub struct Job {
    pub text: String,
    pub page: i64,
    pub parsed: Value,
    pub targets: Vec<Target>,
    pub min_len: i64,
    pub keep_dup: bool,
    pub soft_deadline_ms: i64,
    pub max_workers: usize,
    pub stamp: String,
    pub now: LocalNow,
    pub token: i64,
    pub hints: Hints,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Event {
    Start(Value),
    Source(Value),
    Batch(Value),
    Settled(Value),
    Done(Value),
    Probe(Value),
    ProbeDone,
}

pub fn js_of(event: &Event) -> String {
    let (hook, payload) = match event {
        Event::Start(value) => ("__onSearchStart", value),
        Event::Source(value) => ("__onSearchSource", value),
        Event::Batch(value) => ("__onSearchBatch", value),
        Event::Settled(value) => ("__onSearchSettled", value),
        Event::Done(value) => ("__onSearchDone", value),
        Event::Probe(value) => ("__onProbe", value),
        Event::ProbeDone => return "window.__onProbeDone && window.__onProbeDone()".to_string(),
    };
    let text = serde_json::to_string(payload).unwrap_or_else(|_| "null".to_string());
    format!("window.{hook} && window.{hook}({text})")
}

pub type Sink = dyn Fn(Event) + Send + Sync;

#[derive(Default)]
struct Acc {
    needs: Vec<String>,
    rows: Vec<Value>,
    index_of: HashMap<String, usize>,
    raw: i64,
    dup: i64,
    errors: BTreeMap<String, String>,
    ok_keys: BTreeSet<String>,
    fuzzy_keys: BTreeSet<String>,
    source_counts: BTreeMap<String, i64>,
    relaxed_used: Vec<String>,
    relax_round: i64,
}

#[derive(Clone)]
struct Cached {
    ts: f64,
    rows: Vec<Value>,
    raw: i64,
    dup: i64,
    ok: Vec<String>,
    fuzzy: Vec<String>,
    errors: BTreeMap<String, String>,
    source_counts: BTreeMap<String, i64>,
}

static CACHE: LazyLock<Mutex<HashMap<String, Cached>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

pub fn cache_clear() {
    CACHE.lock().unwrap_or_else(|e| e.into_inner()).clear();
}

fn now_secs() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

fn cache_take(ckey: &str) -> Option<Cached> {
    let mut cache = CACHE.lock().unwrap_or_else(|e| e.into_inner());
    let hit = cache.get(ckey)?.clone();
    if now_secs() - hit.ts > CACHE_TTL {
        cache.remove(ckey);
        return None;
    }
    Some(hit)
}

fn cache_put(ckey: &str, entry: Cached) {
    let mut cache = CACHE.lock().unwrap_or_else(|e| e.into_inner());
    cache.insert(ckey.to_string(), entry);
    while cache.len() > CACHE_MAX {
        let oldest = cache
            .iter()
            .min_by(|a, b| a.1.ts.total_cmp(&b.1.ts))
            .map(|(key, _)| key.clone());
        match oldest {
            Some(key) => {
                cache.remove(&key);
            }
            None => break,
        }
    }
}

pub fn cache_key(job: &Job) -> String {
    let mut keys: Vec<&str> = job.targets.iter().map(|t| t.key.as_str()).collect();
    keys.sort();
    let text = match job.parsed.get("text").and_then(Value::as_str) {
        Some(value) if !value.is_empty() => value.to_string(),
        _ => job.text.clone(),
    };
    format!(
        "{text}|{}|{}|p{}|{}",
        keys.join(","),
        if job.keep_dup { "k" } else { "" },
        job.page,
        job.stamp
    )
}

pub fn source_stamp(entries: &[Value]) -> String {
    let mut parts: Vec<String> = Vec::new();
    for entry in entries {
        let enabled = entry
            .get("enabled")
            .map(crate::config::truthy)
            .unwrap_or(false);
        if !enabled {
            continue;
        }
        let key = entry.get("key").and_then(Value::as_str).unwrap_or("");
        let base = entry.get("base").and_then(Value::as_str).unwrap_or("");
        let timeout = match entry.get("timeout") {
            Some(Value::Number(number)) => number.to_string(),
            Some(Value::String(text)) => text.clone(),
            _ => String::new(),
        };
        parts.push(format!("{key}:{}:{timeout}", crate::api::base_of(key, base)));
    }
    parts.sort();
    parts.join(",")
}

pub fn proxy_hint_for(hints: &Hints, errors: &BTreeMap<String, String>) -> String {
    if hints.has_proxy {
        return hints.proxy.clone();
    }
    let keys: Vec<&String> = errors.keys().filter(|key| !key.is_empty()).collect();
    if keys.is_empty() {
        return crate::outcome::NET_FAIL_TEXT.to_string();
    }
    let timed: Vec<&&String> = keys
        .iter()
        .filter(|key| is_timeout_text(errors.get(**key).map(String::as_str).unwrap_or("")))
        .collect();
    let overseas = timed
        .iter()
        .filter(|key| sources::OVERSEAS_KEYS.contains(&key.as_str()))
        .count();
    if overseas >= 2 && overseas * 2 >= keys.len() {
        if !hints.tun.is_empty() {
            return "TUN 模式已接管网络，这些源仍超时：可能被墙或站点故障。".to_string();
        }
        return "未检测到代理，这些源需要代理才能访问。".to_string();
    }
    if !timed.is_empty() {
        return crate::outcome::NET_TIMEOUT_TEXT.to_string();
    }
    crate::outcome::NET_FAIL_TEXT.to_string()
}

fn search_one<F: Fetch + Sync>(
    job: &Job,
    target: &Target,
    query_text: &str,
    fetch: &F,
) -> (Vec<Item>, String, i64) {
    let started = Instant::now();
    let bound = Scoped {
        inner: fetch,
        timeout: target.timeout,
        batch: Some(job.token),
    };
    let outcome = sources::search(
        &target.key,
        &target.base,
        query_text,
        job.page,
        &job.now,
        target.timeout,
        &bound,
    );
    let ms = started.elapsed().as_millis() as i64;
    match outcome {
        Ok(items) => {
            crate::log::info(
                crate::log::SOURCES,
                &format!("源 {} 返回 {} 条", target.key, items.len()),
            );
            (items, String::new(), ms)
        }
        Err(SourceError::Cancelled) => {
            crate::log::info(
                crate::log::SOURCES,
                &format!("源 {}：搜索已停止", target.key),
            );
            (Vec::new(), CANCEL_TEXT.to_string(), ms)
        }
        Err(exc) => {
            let text = exc.search_text();
            crate::log::warning(
                crate::log::SOURCES,
                &format!("源 {} 失败：{text}", target.key),
            );
            (Vec::new(), text, ms)
        }
    }
}

fn on_start(job: &Job, key: &str, sink: &(dyn Fn(Event) + Sync)) {
    if !sources::batch_alive(job.token) {
        return;
    }
    sink(Event::Start(json!({
        "token": job.token,
        "key": key,
        "typical_ms": 0,
    })));
}

fn on_source(
    job: &Job,
    key: &str,
    items: &[Item],
    err: &str,
    ms: i64,
    sink: &(dyn Fn(Event) + Sync),
    acc: &Mutex<Acc>,
) {
    if !sources::batch_alive(job.token) {
        return;
    }
    let count = items.len() as i64;
    let mut state = acc.lock().unwrap_or_else(|e| e.into_inner());
    if state.relax_round > 0 && err.is_empty() && count == 0 {
        crate::log::info(
            crate::log::SOURCES,
            &format!("源 {key}：放宽轮 0 条不计健康度（放宽词搜不到不算源失败）"),
        );
        return;
    }
    let (outcome, code) = classify(err.is_empty(), count, err, ms);
    let text_err = outcome_text(outcome, code);
    let fuzzy = !items.is_empty()
        && !state.needs.is_empty()
        && sources::keyword_hit_rate(items, &state.needs) < sources::FUZZY_RATE;
    if fuzzy {
        state.fuzzy_keys.insert(key.to_string());
    } else if !items.is_empty() && err.is_empty() {
        state.ok_keys.insert(key.to_string());
    }
    if err.is_empty() {
        state.errors.remove(key);
    }
    state.source_counts.insert(key.to_string(), count);
    let state_text = state_of(&[outcome.to_string()]);
    drop(state);

    sink(Event::Source(json!({
        "token": job.token,
        "key": key,
        "count": count,
        "err": text_err,
        "outcome": outcome,
        "state": state_text,
        "fuzzy": fuzzy,
    })));

    let values: Vec<Value> = items.iter().map(|it| it.clone().into_value()).collect();
    let merged = if job.keep_dup {
        values
    } else {
        dedupe(&values)
    };

    let mut state = acc.lock().unwrap_or_else(|e| e.into_inner());
    state.raw += count;
    state.dup += count - merged.len() as i64;
    let mut batch: Vec<Value> = Vec::with_capacity(merged.len());
    for it in &merged {
        let hash = it
            .get("info_hash")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_lowercase();
        let ikey = if job.keep_dup && !hash.is_empty() {
            format!("{hash}|{key}")
        } else {
            hash
        };
        if !ikey.is_empty() {
            match state.index_of.get(&ikey).copied() {
                None => {
                    let next = state.rows.len();
                    state.index_of.insert(ikey.clone(), next);
                    state.rows.push(it.clone());
                }
                Some(pos) => {
                    state.dup += 1;
                    let merged_row = dedupe(&[state.rows[pos].clone(), it.clone()]);
                    state.rows[pos] = merged_row[0].clone();
                }
            }
        }
        let row = match state.index_of.get(&ikey) {
            Some(pos) if !ikey.is_empty() => state.rows[*pos].clone(),
            _ => it.clone(),
        };
        batch.push(item_view(&row, &job.now));
    }
    drop(state);

    if !batch.is_empty() {
        sink(Event::Batch(json!({
            "token": job.token,
            "key": key,
            "items": batch,
        })));
    }
}

fn fan_out<F: Fetch + Sync>(
    job: &Job,
    indices: &[usize],
    query_text: &str,
    fetch: &F,
    sink: &(dyn Fn(Event) + Sync),
    acc: &Mutex<Acc>,
) -> BTreeMap<String, (Vec<Item>, String, i64)> {
    let mut results: BTreeMap<String, (Vec<Item>, String, i64)> = BTreeMap::new();
    if indices.is_empty() {
        return results;
    }
    let workers = job.max_workers.clamp(1, indices.len());
    let queue = Mutex::new(VecDeque::from(indices.to_vec()));
    let (tx, rx) = mpsc::channel::<(usize, (Vec<Item>, String, i64))>();

    std::thread::scope(|scope| {
        for _ in 0..workers {
            let tx = tx.clone();
            let queue = &queue;
            scope.spawn(move || loop {
                if !sources::batch_alive(job.token) {
                    break;
                }
                let index = match queue.lock().unwrap_or_else(|e| e.into_inner()).pop_front() {
                    Some(index) => index,
                    None => break,
                };
                let target = &job.targets[index];
                on_start(job, &target.key, sink);
                let row = match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    search_one(job, target, query_text, fetch)
                })) {
                    Ok(row) => row,
                    Err(_) => {
                        crate::log::warning(
                            crate::log::SOURCES,
                            &format!("源 {} 异常退出", target.key),
                        );
                        (Vec::new(), "内部异常".to_string(), 0)
                    }
                };
                if tx.send((index, row)).is_err() {
                    break;
                }
            });
        }
        drop(tx);
        for (index, row) in rx {
            let key = job.targets[index].key.clone();
            on_source(job, &key, &row.0, &row.1, row.2, sink, acc);
            results.insert(key, row);
        }
    });

    results
}

fn run_round<F: Fetch + Sync>(
    job: &Job,
    query_text: &str,
    subset: Option<&[String]>,
    fetch: &F,
    sink: &(dyn Fn(Event) + Sync),
    acc: &Mutex<Acc>,
) {
    if crate::api::py_len(query_text.trim()) < job.min_len as usize {
        let mut state = acc.lock().unwrap_or_else(|e| e.into_inner());
        if state.rows.is_empty() && state.ok_keys.is_empty() {
            state
                .errors
                .insert(String::new(), crate::core::min_len_message(job.min_len));
        }
        return;
    }

    let indices: Vec<usize> = match subset {
        Some(keys) => {
            let wanted: BTreeSet<&str> = keys.iter().map(String::as_str).collect();
            job.targets
                .iter()
                .enumerate()
                .filter(|(_, target)| wanted.contains(target.key.as_str()))
                .map(|(index, _)| index)
                .collect()
        }
        None => (0..job.targets.len()).collect(),
    };

    let results = fan_out(job, &indices, query_text, fetch, sink, acc);

    let mut reached = 0i64;
    let mut errors: BTreeMap<String, String> = BTreeMap::new();
    for (key, (_, err, _)) in &results {
        if err.is_empty() {
            reached += 1;
        } else {
            errors.insert(key.clone(), err.clone());
        }
    }

    let mut state = acc.lock().unwrap_or_else(|e| e.into_inner());
    if reached == 0 && !errors.is_empty() {
        let fatal = if errors.values().all(|msg| msg.contains(&job.hints.proxy)) {
            job.hints.proxy.clone()
        } else {
            proxy_hint_for(&job.hints, &errors)
        };
        if state.rows.is_empty() && state.ok_keys.is_empty() {
            state.errors.insert(String::new(), fatal);
        }
    }
    for (key, msg) in errors {
        if !msg.is_empty() && msg != CANCEL_TEXT {
            let (outcome, code) = classify(false, 0, &msg, 0);
            state.errors.insert(key, outcome_text(outcome, code));
        }
    }
}

fn runner<F: Fetch + Sync>(
    job: &Job,
    fetch: &F,
    sink: &(dyn Fn(Event) + Sync),
    acc: &Mutex<Acc>,
    retry: Option<&[String]>,
) {
    run_round(job, &job.text, retry, fetch, sink, acc);
    let mut rounds = 0usize;
    while rounds < MAX_RELAX_ROUNDS {
        if !sources::batch_alive(job.token) {
            return;
        }
        let (exhausted, has_rows, relaxed_used) = {
            let state = acc.lock().unwrap_or_else(|e| e.into_inner());
            (
                !state.ok_keys.is_empty() && state.ok_keys.is_subset(&state.fuzzy_keys),
                !state.rows.is_empty(),
                state.relaxed_used.clone(),
            )
        };
        if has_rows && !exhausted {
            return;
        }
        let (next, dropped) = relaxed_query(&job.parsed, &relaxed_used);
        if next.is_empty() {
            return;
        }
        rounds += 1;
        crate::log::info(
            crate::log::API,
            &format!("放宽关键词重搜：去掉 {dropped}"),
        );
        {
            let mut state = acc.lock().unwrap_or_else(|e| e.into_inner());
            state.relaxed_used.push(dropped);
            state.relax_round = rounds as i64;
        }
        run_round(job, &next, None, fetch, sink, acc);
    }
}

fn seed(job: &Job, cached: &Cached, acc: &Mutex<Acc>, sink: &(dyn Fn(Event) + Sync)) {
    {
        let mut state = acc.lock().unwrap_or_else(|e| e.into_inner());
        state.rows = cached.rows.clone();
        let hashes: Vec<String> = state
            .rows
            .iter()
            .map(|row| {
                row.get("info_hash")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_lowercase()
            })
            .collect();
        for (index, hash) in hashes.into_iter().enumerate() {
            if !hash.is_empty() {
                state.index_of.entry(hash).or_insert(index);
            }
        }
        state.raw = cached.raw;
        state.dup = cached.dup;
        state.ok_keys = cached.ok.iter().cloned().collect();
        state.fuzzy_keys = cached.fuzzy.iter().cloned().collect();
        state.errors = cached.errors.clone();
        state.source_counts = cached.source_counts.clone();
    }

    let batch: Vec<Value> = cached
        .rows
        .iter()
        .map(|row| item_view(row, &job.now))
        .collect();
    if !batch.is_empty() {
        sink(Event::Batch(json!({
            "token": job.token,
            "key": "",
            "items": batch,
        })));
    }
    for target in &job.targets {
        if cached.errors.contains_key(&target.key) {
            continue;
        }
        let count = cached.source_counts.get(&target.key).copied().unwrap_or(0);
        let state_text = if count > 0 { "ok" } else { "empty" };
        sink(Event::Source(json!({
            "token": job.token,
            "key": target.key,
            "count": count,
            "err": "",
            "outcome": state_text,
            "state": state_text,
            "fuzzy": cached.fuzzy.contains(&target.key),
            "cached": true,
        })));
    }
}

struct DoneFlag<'a>(&'a (Mutex<bool>, Condvar));

impl Drop for DoneFlag<'_> {
    fn drop(&mut self) {
        let (lock, alarm) = &self.0;
        *lock.lock().unwrap_or_else(|e| e.into_inner()) = true;
        alarm.notify_all();
    }
}

pub fn execute<F: Fetch + Sync>(job: &Job, fetch: &F, sink: &(dyn Fn(Event) + Sync)) {
    let acc = Mutex::new(Acc {
        needs: query::needles(&job.parsed),
        ..Acc::default()
    });
    let ckey = cache_key(job);
    let cached = cache_take(&ckey);
    let retry: Option<Vec<String>> = cached
        .as_ref()
        .map(|hit| hit.errors.keys().cloned().collect());

    if let Some(hit) = cached.as_ref() {
        seed(job, hit, &acc, sink);
        crate::log::info(
            crate::log::API,
            &format!(
                "命中搜索缓存：{} 行复用，重打 {} 个源",
                hit.rows.len(),
                retry.as_ref().map(Vec::len).unwrap_or(0)
            ),
        );
    }

    let gate = (Mutex::new(false), Condvar::new());
    std::thread::scope(|scope| {
        scope.spawn(|| {
            let _done = DoneFlag(&gate);
            if std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                runner(job, fetch, sink, &acc, retry.as_deref());
            }))
            .is_err()
            {
                crate::log::warning(crate::log::API, "搜索主流程异常退出");
            }
        });

        if job.soft_deadline_ms > 0 {
            let (lock, alarm) = &gate;
            let guard = lock.lock().unwrap_or_else(|e| e.into_inner());
            let (guard, _) = alarm
                .wait_timeout(guard, Duration::from_millis(job.soft_deadline_ms as u64))
                .unwrap_or_else(|e| e.into_inner());
            if !*guard && sources::batch_alive(job.token) && !acc.lock().unwrap_or_else(|e| e.into_inner()).rows.is_empty() {
                drop(guard);
                sink(Event::Settled(json!({"token": job.token})));
            }
        }

        let (lock, alarm) = &gate;
        let mut guard = lock.lock().unwrap_or_else(|e| e.into_inner());
        while !*guard {
            guard = alarm.wait(guard).unwrap_or_else(|e| e.into_inner());
        }
    });

    if !sources::batch_alive(job.token) {
        return;
    }

    let state = acc.into_inner().unwrap_or_else(|e| e.into_inner());
    cache_put(
        &ckey,
        Cached {
            ts: now_secs(),
            rows: state.rows.clone(),
            raw: state.raw,
            dup: state.dup,
            ok: state.ok_keys.iter().cloned().collect(),
            fuzzy: state.fuzzy_keys.iter().cloned().collect(),
            errors: state.errors.clone(),
            source_counts: state.source_counts.clone(),
        },
    );

    sink(Event::Done(json!({
        "token": job.token,
        "total": state.rows.len(),
        "errors": state.errors,
        "raw": state.raw,
        "dup": state.dup,
        "relaxed": state.relaxed_used.join("、"),
        "kept": job.keep_dup,
    })));
}

pub fn spawn(
    job: Job,
    http: std::sync::Arc<crate::net::HttpClient>,
    sink: Option<std::sync::Arc<Sink>>,
) {
    std::thread::spawn(move || {
        let push = move |event: Event| {
            if let Some(sink) = sink.as_ref() {
                sink(event);
            }
        };
        execute(&job, http.as_ref(), &push);
    });
}
