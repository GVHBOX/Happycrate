use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

use happycrate::model::{SourceError, SourceResult};
use happycrate::query::{builtin_roles, parse_with};
use happycrate::search::{self, Event, Hints, Job, Target};
use happycrate::sources::{self, Fetch, Req};
use serde_json::json;

struct DeadNet {
    calls: AtomicUsize,
}

impl Fetch for DeadNet {
    fn fetch(&self, _req: Req) -> SourceResult<String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Err(SourceError::Timeout)
    }
}

fn job(text: &str, token: i64) -> Job {
    Job {
        text: text.to_string(),
        page: 1,
        parsed: parse_with(text, &builtin_roles()),
        targets: vec![
            Target {
                key: "bitsearch".to_string(),
                base: String::new(),
                timeout: 5,
            },
            Target {
                key: "xccl263".to_string(),
                base: String::new(),
                timeout: 5,
            },
        ],
        min_len: 2,
        keep_dup: false,
        soft_deadline_ms: 0,
        hard_timeout_ms: 0,
        max_workers: 2,
        stamp: "guard".to_string(),
        now: happycrate::util::local_now(),
        token,
        hints: Hints {
            proxy: String::new(),
            has_proxy: false,
            tun: String::new(),
        },
    }
}

fn hook_of(event: &Event) -> String {
    let js = search::js_of(event);
    js.chars()
        .skip("window.".len())
        .take_while(|c| *c != ' ')
        .collect()
}

#[test]
fn relax_skipped_when_every_source_times_out() {
    search::cache_clear();
    let fetch = DeadNet {
        calls: AtomicUsize::new(0),
    };
    let token = sources::start_batch();
    let job = job("ubuntu 1080p", token);
    let seen: Mutex<Vec<Event>> = Mutex::new(Vec::new());
    search::execute(&job, &fetch, &|event| seen.lock().unwrap().push(event));

    let events = seen.into_inner().unwrap();
    let starts = events.iter().filter(|e| hook_of(e) == "__onSearchStart").count();
    let call_count = fetch.calls.load(Ordering::SeqCst);

    assert!(
        !job.parsed["mods"].as_array().unwrap().is_empty(),
        "用例本身要能放宽：解析结果里应有可去掉的修饰词"
    );
    assert_eq!(
        starts, 2,
        "全网超时时只该跑一轮，实际发出了 {starts} 个开始事件、{call_count} 次请求"
    );
    let one_round = 2 + 4;
    assert_eq!(
        call_count, one_round,
        "bitsearch 2 页 + xccl263 4 页，全网超时时只该有这一轮的量"
    );

    let done = events
        .iter()
        .find(|e| hook_of(e) == "__onSearchDone")
        .expect("没有收到收尾事件");
    let payload = match done {
        Event::Done(value) => value,
        _ => unreachable!(),
    };
    assert_eq!(payload["relaxed"], json!(""), "不应记录任何放宽词");
    assert_eq!(payload["kept"], json!(false));
}

#[test]
fn js_of_escapes_line_separators() {
    let event = Event::Source(json!({"key": "a\u{2028}b\u{2029}c"}));
    let js = search::js_of(&event);
    assert!(js.contains("\\u2028"), "U+2028 没被转义：{js}");
    assert!(js.contains("\\u2029"), "U+2029 没被转义：{js}");
    assert!(
        !js.contains('\u{2028}') && !js.contains('\u{2029}'),
        "JS 字面量里不能出现裸的分行符：{js}"
    );
}
