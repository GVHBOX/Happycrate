use std::cell::RefCell;
use std::collections::{HashMap, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};

use happycrate::model::SourceError;
use happycrate::sources::{knaben, Fetch, Req};
use serde_json::Value;

fn fixtures_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures")
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
    bodies: RefCell<HashMap<String, VecDeque<String>>>,
    served: RefCell<Vec<String>>,
}

impl Replay {
    fn load(source: &str) -> Replay {
        let meta: Value = serde_json::from_str(
            &fs::read_to_string(fixtures_root().join(source).join("meta.json")).unwrap(),
        )
        .unwrap();
        let dir = fixtures_root().join(source);
        let mut bodies: HashMap<String, VecDeque<String>> = HashMap::new();
        for entry in meta["captures"].as_array().unwrap() {
            let url = entry["url"].as_str().unwrap().to_string();
            let body = entry["request_body"].as_str().map(|s| s.to_string());
            let key = format!("{url}\u{1}{}", canonical_body(body.as_deref().map(str::as_bytes)));
            let content = fs::read_to_string(dir.join(entry["file"].as_str().unwrap())).unwrap();
            bodies.entry(key).or_default().push_back(content);
        }
        Replay {
            bodies: RefCell::new(bodies),
            served: RefCell::new(Vec::new()),
        }
    }
}

impl Fetch for Replay {
    fn fetch(&self, req: Req) -> Result<String, SourceError> {
        let url = req.url;
        let data = req.data;
        let key = format!("{url}\u{1}{}", canonical_body(data));
        self.served.borrow_mut().push(key.clone());
        let served = self.bodies.borrow_mut().get_mut(&key).and_then(|q| q.pop_front());
        match served {
            Some(body) => Ok(body),
            None => Err(SourceError::MissingFixture {
                url: url.to_string(),
                body: data.map(|b| String::from_utf8_lossy(b).to_string()),
            }),
        }
    }
}

fn normalize(value: &Value) -> Value {
    match value {
        Value::Number(n) => match n.as_f64() {
            Some(f) => serde_json::Number::from_f64(f)
                .map(Value::Number)
                .unwrap_or(Value::Null),
            None => Value::Null,
        },
        Value::Array(items) => Value::Array(items.iter().map(normalize).collect()),
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(k, v)| (k.clone(), normalize(v)))
                .collect(),
        ),
        other => other.clone(),
    }
}

fn meta_value(source: &str, key: &str) -> Value {
    let path = fixtures_root().join(source).join("meta.json");
    serde_json::from_str::<Value>(&fs::read_to_string(path).unwrap()).unwrap()[key].clone()
}

fn golden(source: &str) -> Value {
    serde_json::from_str(
        &fs::read_to_string(fixtures_root().join(source).join("golden.json")).unwrap(),
    )
    .unwrap()
}

fn compare(source: &str, actual: Vec<happycrate::model::Item>) {
    let expected = golden(source);
    let want: Vec<Value> = expected["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(normalize)
        .collect();
    let got: Vec<Value> = actual
        .into_iter()
        .map(|i| normalize(&i.into_value()))
        .collect();

    assert_eq!(
        got.len(),
        want.len(),
        "{source} 条数不一致：Rust {} / Python {}",
        got.len(),
        want.len()
    );
    for (i, (g, w)) in got.iter().zip(want.iter()).enumerate() {
        assert_eq!(
            g,
            w,
            "{source} 第 {i} 条字段不一致\nRust:   {g}\nPython: {w}"
        );
    }
}

#[test]
fn fixtures_complete() {
    let root = fixtures_root();
    let mut found = Vec::new();
    for entry in fs::read_dir(&root).unwrap() {
        let dir = entry.unwrap().path();
        if !dir.is_dir() {
            continue;
        }
        let name = dir.file_name().unwrap().to_string_lossy().to_string();
        assert!(dir.join("meta.json").exists(), "{name} 缺 meta.json");
        assert!(dir.join("golden.json").exists(), "{name} 缺 golden.json");
        found.push(name);
    }
    found.sort();
    assert_eq!(found.len(), 12, "fixture 源数量应为 12，实际 {found:?}");
}

#[test]
fn golden_knaben() {
    let replay = Replay::load("knaben");
    let g = golden("knaben");
    let query = g["query"].as_str().unwrap();
    let items = knaben::search("", query, 1, &replay).expect("knaben 解析失败");
    compare("knaben", items);
}

fn run_golden<F>(source: &str, call: F)
where
    F: FnOnce(&Replay, &str) -> Vec<happycrate::model::Item>,
{
    let replay = Replay::load(source);
    let g = golden(source);
    let query = g["query"].as_str().unwrap().to_string();
    compare(source, call(&replay, &query));
}

#[test]
fn golden_apibay() {
    run_golden("apibay", |r, q| {
        happycrate::sources::apibay::search("", q, r).expect("apibay 解析失败")
    });
}

#[test]
fn golden_bitsearch() {
    run_golden("bitsearch", |r, q| {
        happycrate::sources::bitsearch::search("", q, 1, r).expect("bitsearch 解析失败")
    });
}

#[test]
fn golden_nyaa() {
    run_golden("nyaa", |r, q| {
        happycrate::sources::nyaa::family("", q, 1, r, "nyaa", 14, 1100)
            .expect("nyaa 解析失败")
    });
}

#[test]
fn golden_sukebei() {
    run_golden("sukebei", |r, q| {
        happycrate::sources::sukebei::search("", q, 1, r).expect("sukebei 解析失败")
    });
}

#[test]
fn golden_eztv() {
    run_golden("eztv", |r, q| {
        happycrate::sources::eztv::search("", q, r).expect("eztv 解析失败")
    });
}

#[test]
fn golden_mikan() {
    run_golden("mikan", |r, q| {
        happycrate::sources::mikan::search("", q, r).expect("mikan 解析失败")
    });
}

#[test]
fn golden_dmhy() {
    run_golden("dmhy", |r, q| {
        happycrate::sources::dmhy::search("", q, r).expect("dmhy 解析失败")
    });
}

#[test]
fn golden_xccl263() {
    run_golden("xccl263", |r, q| {
        happycrate::sources::xccl263::search("", q, 1, r).expect("xccl263 解析失败")
    });
}

#[test]
fn golden_tpb() {
    let replay = Replay::load("tpb");
    let g = golden("tpb");
    let query = g["query"].as_str().unwrap();
    let now = meta_value("tpb", "captured_local")
        .as_str()
        .unwrap()
        .to_string();
    let now = happycrate::util::local_now_from_iso(&now).unwrap();
    compare(
        "tpb",
        happycrate::sources::tpb::search("", query, 1, &replay, &now, 15)
            .expect("tpb 解析失败"),
    );
}

#[test]
fn golden_javbus() {
    run_golden("javbus", |r, q| {
        happycrate::sources::javbus::search("", q, 1, r).expect("javbus 解析失败")
    });
}

#[test]
fn golden_javdb() {
    run_golden("javdb", |r, q| {
        happycrate::sources::javdb::search("", q, 1, r).expect("javdb 解析失败")
    });
}
