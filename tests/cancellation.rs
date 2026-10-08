use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::{channel, Receiver};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use happycrate::api::Api;
use happycrate::model::SourceError;
use happycrate::net::HttpClient;
use happycrate::search::{execute, Event, Hints, Job, Target};
use happycrate::sources::{self, gather_pages, Req, Scoped};
use happycrate::util::LocalNow;
use serde_json::{json, Value};

enum ServerMode {
    SlowHeaders,
    SlowBody,
    TrickleBody,
    Retry502,
}

struct MockServer {
    port: u16,
    stop: Arc<AtomicBool>,
    req_count: Arc<AtomicUsize>,
    hit_rx: Receiver<()>,
    handle: Option<thread::JoinHandle<()>>,
}

impl MockServer {
    fn new(mode: ServerMode) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        listener.set_nonblocking(true).unwrap();

        let stop = Arc::new(AtomicBool::new(false));
        let req_count = Arc::new(AtomicUsize::new(0));
        let (hit_tx, hit_rx) = channel();

        let stop_clone = stop.clone();
        let count_clone = req_count.clone();

        let handle = thread::spawn(move || {
            let mode = mode;
            let mut streams: Vec<TcpStream> = Vec::new();
            while !stop_clone.load(Ordering::SeqCst) {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        count_clone.fetch_add(1, Ordering::SeqCst);
                        let _ = hit_tx.send(());
                        stream.set_nonblocking(false).unwrap();
                        let mut buf = [0u8; 1024];
                        let _ = stream.read(&mut buf);
                        match mode {
                            ServerMode::SlowHeaders => {
                                streams.push(stream);
                            }
                            ServerMode::SlowBody => {
                                let header = "HTTP/1.1 200 OK\r\nContent-Length: 1000000\r\nContent-Type: text/plain\r\n\r\n";
                                let _ = stream.write_all(header.as_bytes());
                                let _ = stream.write_all(b"partial-payload-bytes");
                                let _ = stream.flush();
                                streams.push(stream);
                            }
                            ServerMode::TrickleBody => {
                                let header = "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Type: text/plain\r\n\r\n";
                                let _ = stream.write_all(header.as_bytes());
                                let _ = stream.flush();
                                let stop_inner = stop_clone.clone();
                                thread::spawn(move || {
                                    while !stop_inner.load(Ordering::SeqCst) {
                                        let chunk = "5\r\n12345\r\n";
                                        if stream.write_all(chunk.as_bytes()).is_err() {
                                            break;
                                        }
                                        let _ = stream.flush();
                                        thread::sleep(Duration::from_millis(50));
                                    }
                                });
                            }
                            ServerMode::Retry502 => {
                                let resp = "HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n";
                                let _ = stream.write_all(resp.as_bytes());
                                let _ = stream.flush();
                            }
                        }
                    }
                    Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(10));
                    }
                    Err(_) => break,
                }
            }
        });

        MockServer {
            port,
            stop,
            req_count,
            hit_rx,
            handle: Some(handle),
        }
    }

    fn url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port)
    }

    fn wait_request(&self) {
        let _ = self.hit_rx.recv_timeout(Duration::from_secs(3));
    }

    fn count(&self) -> usize {
        self.req_count.load(Ordering::SeqCst)
    }
}

impl Drop for MockServer {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        let _ = TcpStream::connect(format!("127.0.0.1:{}", self.port));
        if let Some(h) = self.handle.take() {
            let _ = h.join();
        }
    }
}

fn client() -> HttpClient {
    HttpClient::new(
        "test-agent".to_string(),
        1,
        15,
        "",
    )
    .unwrap()
}

static TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

fn test_job(text: &str, token: i64, hard_ms: i64, soft_ms: i64) -> Job {
    Job {
        text: text.to_string(),
        page: 1,
        parsed: json!({"tokens": [text]}),
        targets: vec![Target {
            key: "apibay".to_string(),
            base: String::new(),
            timeout: 10,
        }],
        min_len: 2,
        keep_dup: false,
        soft_deadline_ms: soft_ms,
        hard_timeout_ms: hard_ms,
        max_workers: 2,
        stamp: "stamp".to_string(),
        now: LocalNow {
            naive: 0,
            offset: 0,
            year: 2026,
        },
        token,
        hints: Hints {
            proxy: String::new(),
            has_proxy: false,
            tun: String::new(),
        },
        seen: None,
        deadline: None,
    }
}

#[test]
fn c01_cancel_waiting_headers_exits_promptly() {
    let _lock = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let server = MockServer::new(ServerMode::SlowHeaders);
    let http = client();
    let token = sources::start_batch();

    let url = format!("{}/slow", server.url());
    let handle = thread::spawn(move || {
        let req = Req::get(&url).retries(2).timeout(15);
        let bound = Scoped {
            inner: &http,
            timeout: 15,
            batch: Some(token),
            deadline: None,
        };
        sources::Fetch::fetch(&bound, req)
    });

    server.wait_request();
    let t0 = Instant::now();
    sources::cancel_batch(token);

    let res = handle.join().unwrap();
    let elapsed = t0.elapsed();

    assert!(matches!(res, Err(SourceError::Cancelled)));
    assert!(
        elapsed < Duration::from_secs(2),
        "等待响应头取消延迟过大：{:?}",
        elapsed
    );
    assert_eq!(server.count(), 1);
}

#[test]
fn c02_cancel_reading_body_exits_promptly() {
    let _lock = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let server = MockServer::new(ServerMode::SlowBody);
    let http = client();
    let token = sources::start_batch();

    let url = format!("{}/body", server.url());
    let handle = thread::spawn(move || {
        let req = Req::get(&url).timeout(15);
        let bound = Scoped {
            inner: &http,
            timeout: 15,
            batch: Some(token),
            deadline: None,
        };
        sources::Fetch::fetch(&bound, req)
    });

    server.wait_request();
    thread::sleep(Duration::from_millis(50));
    let t0 = Instant::now();
    sources::cancel_batch(token);

    let res = handle.join().unwrap();
    let elapsed = t0.elapsed();

    assert!(matches!(res, Err(SourceError::Cancelled)));
    assert!(
        elapsed < Duration::from_secs(2),
        "读取 body 取消延迟过大：{:?}",
        elapsed
    );
}

#[test]
fn c03_cancel_during_backoff_aborts_retries() {
    let _lock = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let server = MockServer::new(ServerMode::Retry502);
    let http = client();
    let token = sources::start_batch();

    let url = format!("{}/retry", server.url());
    let handle = thread::spawn(move || {
        let req = Req::get(&url).retries(3).timeout(5);
        let bound = Scoped {
            inner: &http,
            timeout: 5,
            batch: Some(token),
            deadline: None,
        };
        sources::Fetch::fetch(&bound, req)
    });

    server.wait_request();
    thread::sleep(Duration::from_millis(50));
    let t0 = Instant::now();
    sources::cancel_batch(token);

    let res = handle.join().unwrap();
    let elapsed = t0.elapsed();

    assert!(matches!(res, Err(SourceError::Cancelled)));
    assert!(
        elapsed < Duration::from_secs(2),
        "退避取消延迟过大：{:?}",
        elapsed
    );
    assert_eq!(server.count(), 1);
}

#[test]
fn c04_gather_pages_stops_on_cancellation() {
    let _lock = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let server = MockServer::new(ServerMode::SlowHeaders);
    let http = client();
    let token = sources::start_batch();
    let url = server.url();

    let handle = thread::spawn(move || {
        gather_pages(0..10, 2, |idx| {
            let page_url = format!("{url}/page/{idx}");
            let req = Req::get(&page_url).timeout(10);
            let bound = Scoped {
                inner: &http,
                timeout: 10,
                batch: Some(token),
                deadline: None,
            };
            sources::Fetch::fetch(&bound, req)
        })
    });

    server.wait_request();
    sources::cancel_batch(token);

    let (ok, err) = handle.join().unwrap();
    assert!(ok.is_empty());
    assert!(err.values().any(|e| matches!(e, SourceError::Cancelled)));
    assert!(server.count() < 10);
}

#[test]
fn c05_consecutive_searches_token_isolation() {
    let _lock = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let token_a = sources::start_batch();
    assert!(sources::batch_alive(token_a));

    let token_b = sources::start_batch();
    assert!(!sources::batch_alive(token_a));
    assert!(sources::batch_alive(token_b));

    sources::cancel_batch(token_a);
    assert!(sources::batch_alive(token_b));

    sources::cancel_batch(token_b);
    assert!(!sources::batch_alive(token_b));
}

#[test]
fn c06_cancel_search_api_token_semantics() {
    let _lock = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let mut api = Api::new(None, None);
    let res1 = api.start_search("ubuntu linux", 1);
    let token1 = res1["token"].as_i64().unwrap();
    assert_ne!(token1, 0);

    let res2 = api.start_search("debian linux", 1);
    let token2 = res2["token"].as_i64().unwrap();
    assert_ne!(token2, 0);
    assert_ne!(token1, token2);

    api.cancel_search(token1);
    assert!(sources::batch_alive(token2));

    api.cancel_search(0);
    assert!(!sources::batch_alive(token2));
}

#[test]
fn c07_hard_timeout_smaller_than_soft_deadline() {
    let _lock = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    struct HangingFetch;
    impl sources::Fetch for HangingFetch {
        fn fetch(&self, req: Req) -> happycrate::model::SourceResult<String> {
            let t0 = Instant::now();
            while req.batch.map(sources::batch_alive).unwrap_or(true) {
                thread::sleep(Duration::from_millis(20));
                if t0.elapsed() > Duration::from_secs(5) {
                    break;
                }
            }
            Err(SourceError::Cancelled)
        }
    }

    let token = sources::start_batch();
    let job = test_job("c07-hard-timeout", token, 200, 5000);
    let events = Arc::new(std::sync::Mutex::new(Vec::new()));
    let events_clone = events.clone();

    let t0 = Instant::now();
    execute(&job, &HangingFetch, &move |ev| {
        events_clone.lock().unwrap().push(ev);
    });
    let elapsed = t0.elapsed();

    assert!(
        elapsed < Duration::from_millis(1500),
        "硬期限小于软期限时未按硬期限收尾：{:?}",
        elapsed
    );

    let recorded = events.lock().unwrap().clone();
    let done_event = recorded.iter().find(|e| matches!(e, Event::Done(_)));
    assert!(done_event.is_some());
    if let Some(Event::Done(payload)) = done_event {
        assert_eq!(payload.get("hardStopped"), Some(&Value::Bool(true)));
    }
}

#[test]
fn c08_hard_timeout_zero_allows_manual_cancel() {
    let _lock = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    struct HangThenCancel;
    impl sources::Fetch for HangThenCancel {
        fn fetch(&self, req: Req) -> happycrate::model::SourceResult<String> {
            while req.batch.map(sources::batch_alive).unwrap_or(true) {
                thread::sleep(Duration::from_millis(20));
            }
            Err(SourceError::Cancelled)
        }
    }

    let token = sources::start_batch();
    let job = test_job("c08-manual-cancel", token, 0, 0);

    let handle = thread::spawn(move || {
        let events = Arc::new(std::sync::Mutex::new(Vec::new()));
        let events_clone = events.clone();
        execute(&job, &HangThenCancel, &move |ev| {
            events_clone.lock().unwrap().push(ev);
        });
        let out = events.lock().unwrap().clone();
        out
    });

    thread::sleep(Duration::from_millis(100));
    assert!(sources::batch_alive(token));
    sources::cancel_batch(token);

    let events = handle.join().unwrap();
    assert!(!events.iter().any(|e| matches!(e, Event::Done(_))));
}

#[test]
fn c09_trickle_body_hits_hard_deadline() {
    let _lock = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let server = MockServer::new(ServerMode::TrickleBody);
    let http = client();
    let token = sources::start_batch();
    let deadline = Instant::now() + Duration::from_millis(300);

    let url = format!("{}/trickle", server.url());
    let req = Req::get(&url).timeout(10);
    let bound = Scoped {
        inner: &http,
        timeout: 10,
        batch: Some(token),
        deadline: Some(deadline),
    };

    let t0 = Instant::now();
    let res = sources::Fetch::fetch(&bound, req);
    let elapsed = t0.elapsed();

    assert!(matches!(res, Err(SourceError::Timeout)));
    assert!(
        elapsed < Duration::from_millis(1500),
        "持续小块未受硬期限约束：{:?}",
        elapsed
    );
}

#[test]
fn c10_no_results_or_duplicate_done_after_terminal() {
    let _lock = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    struct QuickMock;
    impl sources::Fetch for QuickMock {
        fn fetch(&self, _: Req) -> happycrate::model::SourceResult<String> {
            Ok("[]".to_string())
        }
    }

    let token = sources::start_batch();
    let job = test_job("c10-terminal", token, 1000, 500);
    let events = Arc::new(std::sync::Mutex::new(Vec::new()));
    let events_clone = events.clone();

    execute(&job, &QuickMock, &move |ev| {
        events_clone.lock().unwrap().push(ev);
    });

    let recorded = events.lock().unwrap().clone();
    let done_count = recorded.iter().filter(|e| matches!(e, Event::Done(_))).count();
    assert_eq!(done_count, 1);
}

#[test]
fn c12_rapid_start_and_cancel_no_task_leak() {
    let _lock = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let server = MockServer::new(ServerMode::SlowHeaders);
    let http = Arc::new(client());
    let url = server.url();

    for _ in 0..20 {
        let token = sources::start_batch();
        let url_clone = format!("{url}/rapid");
        let http_clone = http.clone();
        let h = thread::spawn(move || {
            let req = Req::get(&url_clone).timeout(5);
            let bound = Scoped {
                inner: &*http_clone,
                timeout: 5,
                batch: Some(token),
                deadline: None,
            };
            sources::Fetch::fetch(&bound, req)
        });
        sources::cancel_batch(token);
        let _ = h.join().unwrap();
    }
}
