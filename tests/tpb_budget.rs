use std::sync::Mutex;
use std::time::{Duration, Instant};

use happycrate::model::{SourceError, SourceResult};
use happycrate::sources::{tpb, Fetch, Req};

const MIRRORS: usize = tpb::MIRRORS.len();

struct Slow {
    calls: Mutex<Vec<(String, u64)>>,
}

impl Fetch for Slow {
    fn fetch(&self, req: Req) -> SourceResult<String> {
        let timeout = req.timeout.unwrap_or(0);
        self.calls.lock().unwrap().push((req.url.to_string(), timeout));
        std::thread::sleep(Duration::from_secs(timeout.min(3)));
        Err(SourceError::Transport("镜像不可达".to_string()))
    }
}

#[test]
fn tpb_mirror_budget_stops_early() {
    let fetch = Slow {
        calls: Mutex::new(Vec::new()),
    };
    let started = Instant::now();
    let now = happycrate::util::local_now_from_iso("2026-09-28T18:00:00+08:00").unwrap();
    let result = tpb::search("", "ubuntu", 1, &fetch, &now, 2);
    let elapsed = started.elapsed();

    assert!(result.is_err(), "全部镜像都失败时应当报错");
    let calls = fetch.calls.lock().unwrap();
    assert!(
        !calls.is_empty(),
        "预算 2 秒时至少该试 1 个镜像，实际一个都没试"
    );
    assert!(
        calls.len() < MIRRORS,
        "预算 2 秒时不该把 {MIRRORS} 个镜像全试一遍，实际试了 {} 个",
        calls.len()
    );
    assert!(
        (1..=2).contains(&calls[0].1),
        "首个请求的超时应当由「剩余预算」决定（1~2 秒），而不是源配置的 15 秒，实际 {}",
        calls[0].1
    );
    assert!(
        elapsed < Duration::from_secs(5),
        "总耗时 {elapsed:?} 超出预算太多"
    );
}
