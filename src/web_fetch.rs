use std::path::PathBuf;
use std::sync::mpsc::{channel, Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant};

use serde::Deserialize;
use tauri::{AppHandle, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

use crate::model::{SourceError, SourceResult};
use crate::sources::{batch_alive, Fetch, Req};

pub const LABEL: &str = "fetch";

const POLL_INTERVAL: Duration = Duration::from_millis(1200);
const POLL_SLICE: Duration = Duration::from_millis(200);
const WAIT_GRACE: Duration = Duration::from_millis(600);
const EVAL_TIMEOUT: Duration = Duration::from_secs(10);
const WINDOW_CREATE_TIMEOUT: Duration = Duration::from_secs(12);
const CHALLENGE_SURFACE_AFTER: Duration = Duration::from_secs(8);
const DEFAULT_TIMEOUT_SECS: u64 = 30;
const PROBE_ENV: &str = "HAPPYCRATE_WEBFETCH_PROBE";
const PROBE_URL_ENV: &str = "HAPPYCRATE_WEBFETCH_PROBE_URL";

const STATUS_SCRIPT: &str = r##"
(function () {
  try {
    var title = document.title || "";
    var challenge = /just a moment|请稍候|正在验证|安全验证|checking your browser|attention required/i.test(title)
      || !!document.querySelector("#challenge-running, #challenge-stage, .cf-browser-verification, #cf-challenge-running");
    return {
      ready: document.readyState === "complete",
      challenge: challenge
    };
  } catch (error) {
    return { ready: false, challenge: false };
  }
})();
"##;

const CONTENT_SCRIPT: &str = r##"
(function () {
  try {
    return { html: document.documentElement ? document.documentElement.outerHTML : "" };
  } catch (error) {
    return { html: "", error: String(error) };
  }
})();
"##;

pub trait Driver: Send + Sync {
    fn load(&self, url: &str, deadline: Instant, batch: Option<i64>) -> SourceResult<String>;
}

struct Job {
    url: String,
    deadline: Instant,
    batch: Option<i64>,
    reply: Sender<SourceResult<String>>,
}

pub struct WebFetch {
    tx: Sender<Job>,
}

impl WebFetch {
    pub fn start<D: Driver + 'static>(driver: D) -> WebFetch {
        let (tx, rx) = channel();
        thread::spawn(move || worker_loop(driver, rx));
        WebFetch { tx }
    }
}

impl Fetch for WebFetch {
    fn fetch(&self, req: Req) -> SourceResult<String> {
        if req.url.is_empty() {
            return Err(SourceError::Transport("取数地址为空".to_string()));
        }
        let by_timeout = Instant::now()
            + Duration::from_secs(req.timeout.unwrap_or(DEFAULT_TIMEOUT_SECS).max(1));
        let deadline = match req.deadline {
            Some(given) => given.min(by_timeout),
            None => by_timeout,
        };
        let (reply, rx) = channel();
        let job = Job {
            url: req.url.to_string(),
            deadline,
            batch: req.batch,
            reply,
        };
        if self.tx.send(job).is_err() {
            return Err(SourceError::Transport("取数通道不可用".to_string()));
        }
        let give_up = deadline + WAIT_GRACE;
        loop {
            if let Some(token) = req.batch {
                if !batch_alive(token) {
                    return Err(SourceError::Cancelled);
                }
            }
            match rx.recv_timeout(POLL_SLICE) {
                Ok(result) => return result,
                Err(RecvTimeoutError::Timeout) => {
                    if Instant::now() >= give_up {
                        return Err(SourceError::Timeout);
                    }
                }
                Err(RecvTimeoutError::Disconnected) => {
                    return Err(SourceError::Transport("取数通道已断开".to_string()));
                }
            }
        }
    }
}

fn worker_loop<D: Driver>(driver: D, rx: Receiver<Job>) {
    while let Ok(job) = rx.recv() {
        let result = if Instant::now() >= job.deadline {
            Err(SourceError::Timeout)
        } else if let Some(token) = job.batch {
            if batch_alive(token) {
                driver.load(&job.url, job.deadline, Some(token))
            } else {
                Err(SourceError::Cancelled)
            }
        } else {
            driver.load(&job.url, job.deadline, None)
        };
        let _ = job.reply.send(result);
    }
}

pub struct WindowDriver {
    app: AppHandle,
    window: Mutex<Option<WebviewWindow>>,
}

impl WindowDriver {
    pub fn new(app: AppHandle) -> WindowDriver {
        WindowDriver {
            app,
            window: Mutex::new(None),
        }
    }

    fn window(&self) -> SourceResult<WebviewWindow> {
        if let Some(found) = self
            .window
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .as_ref()
        {
            return Ok(found.clone());
        }
        let created = self.create()?;
        *self.window.lock().unwrap_or_else(|e| e.into_inner()) = Some(created.clone());
        Ok(created)
    }

    fn create(&self) -> SourceResult<WebviewWindow> {
        let profile: PathBuf = crate::paths::data_dir().join("webview");
        let start = blank_url();
        let (tx, rx) = channel();
        let app = self.app.clone();
        self.app
            .run_on_main_thread(move || {
                let outcome = WebviewWindowBuilder::new(&app, LABEL, WebviewUrl::External(start))
                    .title("fetch")
                    .visible(false)
                    .skip_taskbar(true)
                    .inner_size(1100.0, 760.0)
                    .data_directory(profile)
                    .build()
                    .map_err(|error| error.to_string());
                let _ = tx.send(outcome);
            })
            .map_err(|error| SourceError::Transport(error.to_string()))?;
        match rx.recv_timeout(WINDOW_CREATE_TIMEOUT) {
            Ok(Ok(window)) => Ok(window),
            Ok(Err(message)) => Err(SourceError::Transport(message)),
            Err(_) => Err(SourceError::Transport("取数窗口创建超时".to_string())),
        }
    }
}

impl Driver for WindowDriver {
    fn load(&self, url: &str, deadline: Instant, batch: Option<i64>) -> SourceResult<String> {
        let target = url
            .parse::<tauri::Url>()
            .map_err(|_| SourceError::Transport(format!("取数地址无法解析：{url}")))?;
        let window = self.window()?;
        window
            .navigate(target)
            .map_err(|error| SourceError::Transport(error.to_string()))?;
        let started = Instant::now();
        let mut surfaced = false;
        loop {
            if let Some(token) = batch {
                if !batch_alive(token) {
                    reset(&window);
                    return Err(SourceError::Cancelled);
                }
            }
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                reset(&window);
                return Err(SourceError::Timeout);
            }
            thread::sleep(left.min(POLL_INTERVAL));
            if Instant::now() >= deadline {
                reset(&window);
                return Err(SourceError::Timeout);
            }
            let status: PageStatus = match eval_json(&window, STATUS_SCRIPT) {
                Ok(status) => status,
                Err(SourceError::Shape(_)) | Err(SourceError::Timeout) => continue,
                Err(other) => return Err(other),
            };
            if status.ready && !status.challenge {
                if surfaced {
                    let _ = window.hide();
                }
                let content: PageContent = eval_json(&window, CONTENT_SCRIPT)?;
                if content.html.is_empty() {
                    return Err(SourceError::Shape("取数窗口返回空页面".to_string()));
                }
                return Ok(content.html);
            }
            if status.challenge && !surfaced && started.elapsed() >= CHALLENGE_SURFACE_AFTER {
                let _ = window.show();
                let _ = window.set_focus();
                surfaced = true;
            }
        }
    }
}

fn reset(window: &WebviewWindow) {
    let _ = window.hide();
    let _ = window.navigate(blank_url());
}

fn blank_url() -> tauri::Url {
    "about:blank".parse().expect("about:blank 可解析")
}

fn eval_json<T: for<'de> Deserialize<'de>>(window: &WebviewWindow, script: &str) -> SourceResult<T> {
    let (tx, rx) = channel();
    window
        .eval_with_callback(script, move |value| {
            let _ = tx.send(value);
        })
        .map_err(|error| SourceError::Transport(error.to_string()))?;
    match rx.recv_timeout(EVAL_TIMEOUT) {
        Ok(text) => serde_json::from_str::<T>(&text)
            .map_err(|_| SourceError::Shape("取数窗口返回内容无法解析".to_string())),
        Err(_) => Err(SourceError::Timeout),
    }
}

#[derive(Deserialize)]
struct PageStatus {
    ready: bool,
    challenge: bool,
}

#[derive(Deserialize)]
struct PageContent {
    html: String,
}

pub fn probe_enabled() -> bool {
    matches!(std::env::var(PROBE_ENV), Ok(value) if value == "1")
}

static SHARED: OnceLock<Arc<WebFetch>> = OnceLock::new();

pub fn init(app: &AppHandle) {
    let fetch = Arc::new(WebFetch::start(WindowDriver::new(app.clone())));
    let _ = SHARED.set(fetch);
}

pub fn shared() -> Option<Arc<WebFetch>> {
    SHARED.get().cloned()
}

pub fn start_probe(app: &AppHandle) {
    let url = std::env::var(PROBE_URL_ENV).unwrap_or_else(|_| "https://example.com".to_string());
    let app = app.clone();
    thread::spawn(move || {
        let fetch = WebFetch::start(WindowDriver::new(app));
        let started = Instant::now();
        let outcome = fetch.fetch(Req::get(&url).timeout(30));
        let dir = crate::paths::data_dir();
        let record = match &outcome {
            Ok(html) => serde_json::json!({
                "ok": true,
                "url": url,
                "ms": started.elapsed().as_millis(),
                "len": html.len(),
                "head": html.chars().take(200).collect::<String>(),
            }),
            Err(error) => serde_json::json!({
                "ok": false,
                "url": url,
                "ms": started.elapsed().as_millis(),
                "error": error.search_text(),
            }),
        };
        let _ = std::fs::write(
            dir.join("web_fetch_probe.json"),
            serde_json::to_string_pretty(&record).unwrap_or_default(),
        );
        if let Ok(html) = &outcome {
            let _ = std::fs::write(dir.join("web_fetch_probe_raw.html"), html);
        }
        let state_text = if outcome.is_ok() { "成功" } else { "失败" };
        crate::log::warning(
            crate::log::SHELL,
            &format!(
                "取数通道探针：{state_text}，用时 {} ms",
                started.elapsed().as_millis()
            ),
        );
    });
}
