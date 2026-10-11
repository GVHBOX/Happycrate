use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use happycrate::model::{SourceError, SourceResult};
use happycrate::sources::{batch_alive, cancel_batch, start_batch, Fetch, Req};
use happycrate::web_fetch::{Driver, WebFetch};

#[derive(Clone, Default)]
struct MockStats {
    calls: Arc<AtomicUsize>,
    concurrent: Arc<AtomicUsize>,
    peak: Arc<AtomicUsize>,
    seen: Arc<Mutex<Vec<String>>>,
    fail_with: Arc<Mutex<Option<SourceError>>>,
}

struct MockDriver {
    delay: Duration,
    stats: MockStats,
}

impl MockDriver {
    fn new(delay: Duration) -> (MockDriver, MockStats) {
        let stats = MockStats::default();
        (
            MockDriver {
                delay,
                stats: stats.clone(),
            },
            stats,
        )
    }
}

impl Driver for MockDriver {
    fn load(&self, url: &str, deadline: Instant, batch: Option<i64>) -> SourceResult<String> {
        self.stats.calls.fetch_add(1, Ordering::SeqCst);
        self.stats.seen.lock().unwrap().push(url.to_string());
        let now = self.stats.concurrent.fetch_add(1, Ordering::SeqCst) + 1;
        self.stats.peak.fetch_max(now, Ordering::SeqCst);
        let mut slept = Duration::ZERO;
        while slept < self.delay {
            thread::sleep(Duration::from_millis(25));
            slept += Duration::from_millis(25);
            if let Some(token) = batch {
                if !batch_alive(token) {
                    break;
                }
            }
        }
        self.stats.concurrent.fetch_sub(1, Ordering::SeqCst);
        if let Some(token) = batch {
            if !batch_alive(token) {
                return Err(SourceError::Cancelled);
            }
        }
        if let Some(error) = self.stats.fail_with.lock().unwrap().clone() {
            return Err(error);
        }
        if Instant::now() >= deadline {
            return Err(SourceError::Timeout);
        }
        Ok(format!("<html>{url}</html>"))
    }
}

#[test]
fn returns_driver_body() {
    let (driver, stats) = MockDriver::new(Duration::ZERO);
    let fetch = WebFetch::start(driver);
    let html = fetch
        .fetch(Req::get("https://example.com/a"))
        .expect("取数失败");
    assert_eq!(html, "<html>https://example.com/a</html>");
    assert_eq!(stats.calls.load(Ordering::SeqCst), 1);
}

#[test]
fn requests_are_serialized() {
    let (driver, stats) = MockDriver::new(Duration::from_millis(120));
    let fetch = Arc::new(WebFetch::start(driver));
    let mut handles = Vec::new();
    for index in 0..2 {
        let fetch = fetch.clone();
        handles.push(thread::spawn(move || {
            fetch
                .fetch(Req::get(&format!("https://example.com/{index}")))
                .expect("取数失败")
        }));
    }
    for handle in handles {
        handle.join().expect("线程失败");
    }
    assert_eq!(stats.calls.load(Ordering::SeqCst), 2);
    assert_eq!(stats.peak.load(Ordering::SeqCst), 1);
}

#[test]
fn slow_driver_hits_timeout() {
    let (driver, _stats) = MockDriver::new(Duration::from_millis(2000));
    let fetch = WebFetch::start(driver);
    let started = Instant::now();
    let outcome = fetch.fetch(Req::get("https://example.com/slow").timeout(1));
    assert!(matches!(outcome, Err(SourceError::Timeout)));
    assert!(started.elapsed() < Duration::from_millis(2000));
}

#[test]
fn cancel_batch_interrupts_fetch() {
    let (driver, _stats) = MockDriver::new(Duration::from_millis(800));
    let fetch = Arc::new(WebFetch::start(driver));
    let token = start_batch();
    let worker = {
        let fetch = fetch.clone();
        thread::spawn(move || {
            let mut req = Req::get("https://example.com/cancel");
            req.batch = Some(token);
            fetch.fetch(req)
        })
    };
    thread::sleep(Duration::from_millis(150));
    cancel_batch(token);
    let outcome = worker.join().expect("线程失败");
    assert!(matches!(outcome, Err(SourceError::Cancelled)));
}

#[test]
fn driver_error_passes_through() {
    let (driver, stats) = MockDriver::new(Duration::ZERO);
    *stats.fail_with.lock().unwrap() = Some(SourceError::Blocked("验证码拦截".to_string()));
    let fetch = WebFetch::start(driver);
    let outcome = fetch.fetch(Req::get("https://example.com/blocked"));
    match outcome {
        Err(SourceError::Blocked(text)) => assert_eq!(text, "验证码拦截"),
        other => panic!("未按预期透传：{other:?}"),
    }
}
