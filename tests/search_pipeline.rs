use std::collections::{BTreeMap, HashMap, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use happycrate::model::{SourceError, SourceResult};
use happycrate::query::{builtin_roles, parse_with};
use happycrate::search::{self, Event, Hints, Job, Target};
use happycrate::sources::{self, Fetch, Req};
use happycrate::util::LocalNow;
use serde_json::{json, Value};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).to_path_buf()
}

fn cases() -> Value {
    serde_json::from_str(
        &fs::read_to_string(root().join("tests/parity/search_pipeline.json")).unwrap(),
    )
    .unwrap()
}

fn frozen_now(data: &Value) -> LocalNow {
    let now = &data["now"];
    LocalNow {
        naive: now["naive"].as_i64().unwrap(),
        offset: now["offset"].as_i64().unwrap(),
        year: now["year"].as_i64().unwrap(),
    }
}

fn canonical_body(data: Option<&[u8]>) -> String {
    let raw = match data {
        None => return String::new(),
        Some(bytes) => String::from_utf8_lossy(bytes).to_string(),
    };
    if raw.is_empty() {
        return String::new();
    }
    match serde_json::from_str::<Value>(&raw) {
        Ok(value) => value.to_string(),
        Err(_) => raw,
    }
}

struct Replay {
    state: Mutex<State>,
}

struct State {
    queues: HashMap<String, VecDeque<String>>,
    served: usize,
}

impl Replay {
    fn load(keys: &[String]) -> Replay {
        let mut queues: HashMap<String, VecDeque<String>> = HashMap::new();
        for key in keys {
            let dir = root().join("tests/fixtures").join(key);
            let meta: Value =
                serde_json::from_str(&fs::read_to_string(dir.join("meta.json")).unwrap()).unwrap();
            for entry in meta["captures"].as_array().unwrap() {
                let slot = format!(
                    "{}\u{1}{}",
                    entry["url"].as_str().unwrap(),
                    canonical_body(entry["request_body"].as_str().map(str::as_bytes))
                );
                let body = fs::read_to_string(dir.join(entry["file"].as_str().unwrap())).unwrap();
                queues.entry(slot).or_default().push_back(body);
            }
        }
        Replay {
            state: Mutex::new(State {
                queues,
                served: 0,
            }),
        }
    }

    fn served(&self) -> usize {
        self.state.lock().unwrap().served
    }
}

impl Fetch for Replay {
    fn fetch(&self, req: Req) -> SourceResult<String> {
        if let Some(token) = req.batch {
            if !sources::batch_alive(token) {
                return Err(SourceError::Cancelled);
            }
        }
        let slot = format!("{}\u{1}{}", req.url, canonical_body(req.data));
        let mut state = self.state.lock().unwrap();
        match state.queues.get_mut(&slot).and_then(|queue| queue.pop_front()) {
            Some(body) => {
                state.served += 1;
                Ok(body)
            }
            None => Err(SourceError::Http {
                code: 404,
                body: String::new(),
            }),
        }
    }
}

fn normalize(value: &Value) -> Value {
    match value {
        Value::Number(n) => match n.as_f64() {
            Some(number) => serde_json::Number::from_f64(number)
                .map(Value::Number)
                .unwrap_or(Value::Null),
            None => Value::Null,
        },
        Value::Array(items) => Value::Array(items.iter().map(normalize).collect()),
        Value::Object(map) => {
            Value::Object(map.iter().map(|(k, v)| (k.clone(), normalize(v))).collect())
        }
        other => other.clone(),
    }
}

fn split(event: Event) -> (String, Value) {
    let js = search::js_of(&event);
    let hook: String = js
        .chars()
        .skip("window.".len())
        .take_while(|c| *c != ' ')
        .collect();
    let payload = match event {
        Event::Start(value)
        | Event::Source(value)
        | Event::Batch(value)
        | Event::Settled(value)
        | Event::Done(value)
        | Event::Probe(value) => value,
        Event::ProbeDone => Value::Null,
    };
    (hook, payload)
}

fn job_of(scenario: &Value, now: &LocalNow) -> Job {
    let text = scenario["text"].as_str().unwrap().to_string();
    let parsed = parse_with(&text, &builtin_roles());
    let targets = scenario["targets"]
        .as_array()
        .unwrap()
        .iter()
        .map(|entry| Target {
            key: entry["key"].as_str().unwrap().to_string(),
            base: entry["base"].as_str().unwrap().to_string(),
            timeout: entry["timeout"].as_i64().unwrap() as u64,
        })
        .collect();
    let hints = &scenario["hints"];
    Job {
        text,
        page: scenario["page"].as_i64().unwrap(),
        parsed,
        targets,
        min_len: scenario["min_len"].as_i64().unwrap(),
        keep_dup: scenario["keep_dup"].as_bool().unwrap(),
        soft_deadline_ms: scenario["soft_deadline_ms"].as_i64().unwrap(),
        hard_timeout_ms: scenario
            .get("hard_timeout_ms")
            .and_then(Value::as_i64)
            .unwrap_or(0),
        max_workers: scenario["max_workers"].as_i64().unwrap() as usize,
        stamp: scenario["stamp"].as_str().unwrap().to_string(),
        now: now.clone(),
        token: scenario["token"].as_i64().unwrap(),
        hints: Hints {
            proxy: hints["proxy"].as_str().unwrap().to_string(),
            has_proxy: hints["has_proxy"].as_bool().unwrap(),
            tun: hints["tun"].as_str().unwrap().to_string(),
        },
        seen: None,
    }
}

fn key_order(value: &Value) -> String {
    value["payload"]["key"].as_str().unwrap_or("").to_string()
}

fn wanted(scenario: &Value) -> Vec<Value> {
    scenario["events"]
        .as_array()
        .unwrap()
        .iter()
        .map(|event| {
            json!({
                "hook": event["hook"].clone(),
                "payload": normalize(&event["payload"]),
            })
        })
        .collect()
}

#[test]
fn search_pipeline_matches_python() {
    let data = cases();
    let now = frozen_now(&data);
    let scenarios = data["scenarios"].as_array().unwrap();
    assert!(!scenarios.is_empty(), "没有场景");

    search::cache_clear();
    let mut replay: Option<Replay> = None;

    for scenario in scenarios {
        let name = scenario["name"].as_str().unwrap();
        let stamp = scenario["stamp"].as_str().unwrap();
        let entries = scenario["entries"].as_array().unwrap().clone();
        assert_eq!(
            search::source_stamp(&entries),
            stamp,
            "{name} 源指纹与 Python 的 _source_stamp 不一致"
        );

        let keys: Vec<String> = scenario["targets"]
            .as_array()
            .unwrap()
            .iter()
            .map(|entry| entry["key"].as_str().unwrap().to_string())
            .collect();
        if !scenario["reuse"].as_bool().unwrap() {
            search::cache_clear();
            replay = Some(Replay::load(&keys));
        }
        let replay = replay.as_ref().unwrap();
        let before = replay.served();

        let job = job_of(scenario, &now);
        let token = sources::start_batch();
        assert_eq!(
            token, job.token,
            "{name} 批次号对不上：Python 是 {}，Rust 是 {token}",
            job.token
        );
        if scenario["cancel"].as_bool().unwrap() {
            sources::cancel_batch(token);
        }

        let seen: Mutex<Vec<Event>> = Mutex::new(Vec::new());
        search::execute(&job, replay, &|event| seen.lock().unwrap().push(event));
        let mut got: Vec<Value> = seen
            .into_inner()
            .unwrap()
            .into_iter()
            .map(|event| {
                let (hook, payload) = split(event);
                json!({"hook": hook, "payload": normalize(&payload)})
            })
            .collect();
        got.sort_by_key(key_order);

        let want = wanted(scenario);
        assert_eq!(
            got.len(),
            want.len(),
            "{name} 推送条数：Rust {} / Python {}",
            got.len(),
            want.len()
        );
        for (index, (mine, theirs)) in got.iter().zip(want.iter()).enumerate() {
            assert_eq!(
                mine["hook"], theirs["hook"],
                "{name} 第 {index} 条推送的类型不一样"
            );
            assert_eq!(
                mine["payload"], theirs["payload"],
                "{name} 第 {index} 条 {} 载荷不一样\nRust   {}\nPython {}",
                mine["hook"],
                mine["payload"],
                theirs["payload"]
            );
        }
        assert_eq!(
            replay.served() - before,
            scenario["requests"].as_i64().unwrap() as usize,
            "{name} 请求次数不一致"
        );
    }
}

#[test]
fn search_fatal_hint_matches_python() {
    let data = cases();
    let rows = data["fatal"].as_array().unwrap();
    assert!(!rows.is_empty(), "没有失败提示用例");
    for row in rows {
        let errors: BTreeMap<String, String> =
            serde_json::from_value(row["errors"].clone()).unwrap();
        let hints = Hints {
            proxy: row["hints"]["proxy"].as_str().unwrap().to_string(),
            has_proxy: row["hints"]["has_proxy"].as_bool().unwrap(),
            tun: row["hints"]["tun"].as_str().unwrap().to_string(),
        };
        assert_eq!(
            search::proxy_hint_for(&hints, &errors),
            row["out"].as_str().unwrap(),
            "输入 {}",
            row["errors"]
        );
    }
}
