use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::{channel, Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, LazyLock, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant};

use serde::Deserialize;
use tauri::webview::{PageLoadEvent, Webview, WebviewBuilder};
use tauri::window::{Color, WindowBuilder};
use tauri::{
    AppHandle, LogicalSize, Manager, PhysicalPosition, PhysicalSize, Position, Rect, Size,
    WebviewUrl, Window, WindowEvent,
};

use crate::model::{SourceError, SourceResult};
use crate::sources::{batch_alive, Fetch, Req};

pub fn label_for(key: &str) -> String {
    format!("fetch-{key}")
}

fn bar_label_for(key: &str) -> String {
    format!("fetch-{key}-bar")
}

fn view_label_for(key: &str) -> String {
    format!("fetch-{key}-view")
}

fn display_label(key: &str) -> &str {
    match key {
        "bt4g" => "BT4G",
        "btdig" => "BTDigg",
        "probe" => "探针",
        other => other,
    }
}

const POLL_INTERVAL: Duration = Duration::from_millis(400);
const CHALLENGE_POLL_INTERVAL: Duration = Duration::from_millis(200);
const POLL_SLICE: Duration = Duration::from_millis(200);
const BATCH_POLL: Duration = Duration::from_millis(200);
const WAIT_GRACE: Duration = Duration::from_millis(600);
const EVAL_TIMEOUT: Duration = Duration::from_secs(10);
const WINDOW_CREATE_TIMEOUT: Duration = Duration::from_secs(12);
const DEFAULT_TIMEOUT_SECS: u64 = 30;
pub const CHALLENGE_TIMEOUT: Duration = Duration::from_secs(120);
const BATCH_GROUP: usize = 10;
const BATCH_ITEM_TIMEOUT_MS: u64 = 8000;
const PROBE_ENV: &str = "HAPPYCRATE_WEBFETCH_PROBE";
const PROBE_URL_ENV: &str = "HAPPYCRATE_WEBFETCH_PROBE_URL";

const FLOAT_W: f64 = 460.0;
const FLOAT_H: f64 = 300.0;
const BAR_H: f64 = 38.0;
const FLOAT_MIN_W: f64 = 360.0;
const FLOAT_MIN_H: f64 = 220.0;
const FLOAT_MAX_W: f64 = 560.0;
const FLOAT_MAX_H: f64 = 720.0;
const STAGGER_X: i32 = 46;
const STAGGER_Y: i32 = 38;

const STATUS_SCRIPT: &str = r##"
(function () {
  try {
    var title = document.title || "";
    var lead = document.querySelector("h1, h2");
    var note = lead && lead.textContent ? lead.textContent.toLowerCase() : "";
    var challenge = /just a moment|请稍候|正在验证|安全验证|checking your browser|attention required|verify you are human/i.test(title)
      || /one more step|please complete the security check|verify you are human|checking if the site connection is secure|正在验证|安全验证|请稍候/i.test(note)
      || !!document.querySelector("#challenge-running, #challenge-stage, .cf-browser-verification, #cf-challenge-running, .cf-turnstile, iframe[src*='challenges.cloudflare.com'], #g-recaptcha, .g-recaptcha, iframe[src*='recaptcha'], form[action*='recaptcha'], .h-captcha, iframe[src*='hcaptcha.com']");
    var bodyText = document.body && document.body.textContent ? document.body.textContent : "";
    var interstitial = /^security check$/i.test(title.trim())
      && (/verifying your browser/i.test(bodyText) || !!(document.head && /cf_chl_out/.test(document.head.innerHTML)));
    var needW = 0;
    var needH = 0;
    if (challenge) {
      var frames = document.querySelectorAll("iframe");
      for (var i = 0; i < frames.length; i++) {
        var f = frames[i];
        var fs = getComputedStyle(f);
        if (fs.display === "none" || fs.visibility === "hidden") continue;
        var r = f.getBoundingClientRect();
        if (r.width > 10 && r.height > 10 && r.left > -500 && r.top > -500) {
          var isPop = !!f.closest(".__hc_popup");
          needW = Math.max(needW, Math.ceil(r.width + (isPop ? 48 : 36)));
          needH = Math.max(needH, Math.ceil(r.height + (isPop ? 36 : 72)));
        }
      }
      if (document.getElementById("__hc_ch_style") && document.body && !document.querySelector(".__hc_popup")) {
        needH = Math.max(needH, Math.ceil(document.body.scrollHeight));
      }
    }
    var href = String(location.href || "");
    var navigation = performance.getEntriesByType("navigation")[0];
    var err = "";
    if (href.indexOf("chrome-error://") === 0) {
      var errText = (document.body && (document.body.innerText || document.body.textContent)) || "";
      var match = errText.match(/\bERR_[A-Z0-9_]+\b/);
      err = match ? match[0] : "";
    }
    return {
      ready: document.readyState === "complete" && !interstitial,
      challenge: challenge,
      href: href,
      http: navigation && navigation.responseStatus || 0,
      err: err,
      needW: needW,
      needH: needH
    };
  } catch (error) {
    return { ready: false, challenge: false, href: "", err: "", needW: 0, needH: 0 };
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

const BATCH_START: &str = r##"
(function () {
  var pending = { items: null };
  window.__hc_r = pending;
  var urls = __URLS__;
  var limit = __ITEM_TIMEOUT_MS__;
  var failed = { status: 0, url: "", html: "" };
  Promise.all(urls.map(function (u) {
    return new Promise(function (done) {
      var timer = setTimeout(function () { done(failed); }, limit);
      fetch(u, { credentials: "same-origin" }).then(function (r) {
        return r.text().then(function (t) { clearTimeout(timer); done({ status: r.status, url: r.url, html: t }); });
      }).catch(function () { clearTimeout(timer); done(failed); });
    });
  })).then(function (items) {
    if (window.__hc_r === pending) pending.items = items;
  });
})();
"##;

const BATCH_POLL_SCRIPT: &str = "window.__hc_r && window.__hc_r.items ? window.__hc_r : null";

const BATCH_CLEAR: &str = "window.__hc_r = null";

type ThemeProvider = Arc<dyn Fn() -> (String, String) + Send + Sync>;
type ChallengeHook = Arc<dyn Fn(Option<i64>) + Send + Sync>;

static CHALLENGE_HOOK: OnceLock<ChallengeHook> = OnceLock::new();
static CHALLENGE_DONE_HOOK: OnceLock<Arc<dyn Fn() + Send + Sync>> = OnceLock::new();
static THEME_PROVIDER: OnceLock<ThemeProvider> = OnceLock::new();
static APP_HANDLE: OnceLock<AppHandle> = OnceLock::new();
static SHUTTING_DOWN: AtomicBool = AtomicBool::new(false);
static ACTIVE_CHALLENGES: AtomicUsize = AtomicUsize::new(0);
static SURFACED: LazyLock<Mutex<Vec<String>>> = LazyLock::new(|| Mutex::new(Vec::new()));
static SLOTS: LazyLock<Mutex<HashMap<String, Arc<SlotState>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

struct SlotState {
    dismissed: AtomicBool,
    challenged: Arc<AtomicBool>,
    committed_url: Mutex<Option<tauri::Url>>,
}

impl SlotState {
    fn new() -> Self {
        SlotState {
            dismissed: AtomicBool::new(false),
            challenged: Arc::new(AtomicBool::new(false)),
            committed_url: Mutex::new(None),
        }
    }

    fn enter_challenge(&self) -> ChallengeGuard {
        let prev = self.challenged.swap(true, Ordering::SeqCst);
        if !prev {
            ACTIVE_CHALLENGES.fetch_add(1, Ordering::SeqCst);
        }
        ChallengeGuard {
            flag: self.challenged.clone(),
        }
    }
}

struct ChallengeGuard {
    flag: Arc<AtomicBool>,
}

impl Drop for ChallengeGuard {
    fn drop(&mut self) {
        if self.flag.swap(false, Ordering::SeqCst) {
            let _ = ACTIVE_CHALLENGES.fetch_update(Ordering::SeqCst, Ordering::SeqCst, |v| {
                Some(v.saturating_sub(1))
            });
        }
    }
}

pub fn has_active_challenge() -> bool {
    ACTIVE_CHALLENGES.load(Ordering::SeqCst) > 0
}

fn slot_for(key: &str) -> Arc<SlotState> {
    let mut guard = SLOTS.lock().unwrap_or_else(|e| e.into_inner());
    guard
        .entry(key.to_string())
        .or_insert_with(|| Arc::new(SlotState::new()))
        .clone()
}

fn is_shutting_down() -> bool {
    SHUTTING_DOWN.load(Ordering::SeqCst)
}

pub fn on_challenge_surfaced(hook: ChallengeHook) {
    let _ = CHALLENGE_HOOK.set(hook);
}

pub fn on_challenge_passed(hook: Arc<dyn Fn() + Send + Sync>) {
    let _ = CHALLENGE_DONE_HOOK.set(hook);
}

pub fn set_theme_provider(provider: ThemeProvider) {
    let _ = THEME_PROVIDER.set(provider);
}

fn current_theme() -> (String, String) {
    match THEME_PROVIDER.get() {
        Some(provider) => provider(),
        None => ("light".to_string(), String::new()),
    }
}

fn bg_color(theme: &str) -> Color {
    if theme == "dark" {
        Color(19, 20, 25, 255)
    } else {
        Color(255, 255, 255, 255)
    }
}

fn invoke_hook(cell: &OnceLock<Arc<dyn Fn() + Send + Sync>>) {
    if let Some(hook) = cell.get() {
        hook();
    }
}

pub trait Driver: Send + Sync {
    fn load(&self, url: &str, deadline: Instant, batch: Option<i64>) -> SourceResult<String>;

    fn challenge_flag(&self) -> Option<Arc<AtomicBool>> {
        None
    }

    fn batch(&self, urls: &[String], deadline: Instant, batch: Option<i64>) -> Vec<SourceResult<String>> {
        let mut out = Vec::with_capacity(urls.len());
        for url in urls {
            let res = self.load(url, deadline, batch);
            let cancelled = matches!(res, Err(SourceError::Cancelled));
            out.push(res);
            if cancelled {
                while out.len() < urls.len() {
                    out.push(Err(SourceError::Cancelled));
                }
                break;
            }
        }
        out
    }
}

enum Job {
    One {
        url: String,
        deadline: Instant,
        batch: Option<i64>,
        reply: Sender<SourceResult<String>>,
    },
    Many {
        urls: Vec<String>,
        deadline: Instant,
        batch: Option<i64>,
        reply: Sender<Vec<SourceResult<String>>>,
    },
}

pub struct WebFetch {
    tx: Sender<Job>,
    closed: Arc<AtomicBool>,
    challenge_flag: Option<Arc<AtomicBool>>,
}

impl WebFetch {
    pub fn start<D: Driver + 'static>(driver: D) -> WebFetch {
        let (tx, rx) = channel();
        let closed = Arc::new(AtomicBool::new(false));
        let challenge_flag = driver.challenge_flag();
        let worker_closed = closed.clone();
        thread::spawn(move || worker_loop(driver, rx, worker_closed));
        WebFetch {
            tx,
            closed,
            challenge_flag,
        }
    }

    pub fn close(&self) {
        self.closed.store(true, Ordering::SeqCst);
    }

    fn stopped(&self) -> bool {
        self.closed.load(Ordering::SeqCst) || is_shutting_down()
    }
}

fn wait_reply<T>(
    rx: Receiver<T>,
    deadline: Instant,
    batch: Option<i64>,
    closed: &AtomicBool,
    challenge_flag: Option<&AtomicBool>,
) -> Result<T, SourceError> {
    let mut give_up = deadline + WAIT_GRACE;
    let mut extended = false;
    loop {
        if closed.load(Ordering::SeqCst) || is_shutting_down() {
            return Err(SourceError::Cancelled);
        }
        if let Some(token) = batch {
            if !batch_alive(token) {
                return Err(SourceError::Cancelled);
            }
        }
        match rx.recv_timeout(POLL_SLICE) {
            Ok(result) => return Ok(result),
            Err(RecvTimeoutError::Timeout) => {
                if !extended && challenge_flag.is_some_and(|flag| flag.load(Ordering::SeqCst)) {
                    extended = true;
                    give_up = give_up.max(Instant::now() + CHALLENGE_TIMEOUT + WAIT_GRACE);
                }
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

fn effective_deadline(req: &Req) -> Instant {
    let by_timeout = Instant::now()
        + Duration::from_secs(req.timeout.unwrap_or(DEFAULT_TIMEOUT_SECS).max(1));
    match req.deadline {
        Some(given) => given.min(by_timeout),
        None => by_timeout,
    }
}

impl Fetch for WebFetch {
    fn fetch(&self, req: Req) -> SourceResult<String> {
        if self.stopped() {
            return Err(SourceError::Cancelled);
        }
        if req.url.is_empty() {
            return Err(SourceError::Transport("取数地址为空".to_string()));
        }
        let deadline = effective_deadline(&req);
        let (reply, rx) = channel();
        let job = Job::One {
            url: req.url.to_string(),
            deadline,
            batch: req.batch,
            reply,
        };
        if self.tx.send(job).is_err() {
            return Err(SourceError::Transport("取数通道不可用".to_string()));
        }
        match wait_reply(
            rx,
            deadline,
            req.batch,
            &self.closed,
            self.challenge_flag.as_deref(),
        ) {
            Ok(result) => result,
            Err(error) => Err(error),
        }
    }

    fn fetch_many(&self, reqs: Vec<Req>) -> Vec<SourceResult<String>> {
        let count = reqs.len();
        if count == 0 {
            return Vec::new();
        }
        if self.stopped() {
            return (0..count).map(|_| Err(SourceError::Cancelled)).collect();
        }
        if reqs.iter().any(|req| req.url.is_empty()) {
            return reqs
                .iter()
                .map(|_| Err(SourceError::Transport("取数地址为空".to_string())))
                .collect();
        }
        let mut deadline = effective_deadline(&reqs[0]);
        for req in reqs.iter().skip(1) {
            deadline = deadline.min(effective_deadline(req));
        }
        let batch = reqs.iter().find_map(|req| req.batch);
        let urls: Vec<String> = reqs.iter().map(|req| req.url.to_string()).collect();
        let (reply, rx) = channel();
        let job = Job::Many {
            urls,
            deadline,
            batch,
            reply,
        };
        if self.tx.send(job).is_err() {
            return (0..count)
                .map(|_| Err(SourceError::Transport("取数通道不可用".to_string())))
                .collect();
        }
        match wait_reply(
            rx,
            deadline,
            batch,
            &self.closed,
            self.challenge_flag.as_deref(),
        ) {
            Ok(results) => results,
            Err(error) => (0..count).map(|_| Err(error.clone())).collect(),
        }
    }
}

fn worker_loop<D: Driver>(driver: D, rx: Receiver<Job>, closed: Arc<AtomicBool>) {
    while let Ok(job) = rx.recv() {
        let stopped = closed.load(Ordering::SeqCst) || is_shutting_down();
        match job {
            Job::One {
                url,
                deadline,
                batch,
                reply,
            } => {
                let result = if stopped {
                    Err(SourceError::Cancelled)
                } else if Instant::now() >= deadline {
                    Err(SourceError::Timeout)
                } else if let Some(token) = batch {
                    if batch_alive(token) {
                        driver.load(&url, deadline, Some(token))
                    } else {
                        Err(SourceError::Cancelled)
                    }
                } else {
                    driver.load(&url, deadline, None)
                };
                let _ = reply.send(result);
            }
            Job::Many {
                urls,
                deadline,
                batch,
                reply,
            } => {
                let count = urls.len();
                let results = if stopped {
                    (0..count).map(|_| Err(SourceError::Cancelled)).collect()
                } else if Instant::now() >= deadline {
                    (0..count).map(|_| Err(SourceError::Timeout)).collect()
                } else if let Some(token) = batch {
                    if batch_alive(token) {
                        driver.batch(&urls, deadline, Some(token))
                    } else {
                        (0..count).map(|_| Err(SourceError::Cancelled)).collect()
                    }
                } else {
                    driver.batch(&urls, deadline, None)
                };
                let _ = reply.send(results);
            }
        }
    }
}

#[derive(Clone)]
struct WindowHandles {
    window: Window,
    bar: Webview,
    view: Webview,
}

pub struct WindowDriver {
    app: AppHandle,
    key: String,
    label: String,
    slot: Arc<SlotState>,
    handles: Mutex<Option<WindowHandles>>,
    last_origin: Mutex<Option<String>>,
}

impl WindowDriver {
    pub fn new(app: AppHandle, key: String) -> WindowDriver {
        let label = label_for(&key);
        let slot = slot_for(&key);
        WindowDriver {
            app,
            key,
            label,
            slot,
            handles: Mutex::new(None),
            last_origin: Mutex::new(None),
        }
    }

    fn set_origin(&self, origin: Option<String>) {
        *self.last_origin.lock().unwrap_or_else(|e| e.into_inner()) = origin;
    }

    fn origin(&self) -> Option<String> {
        self.last_origin
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
    }

    fn clear_window(&self) {
        *self.handles.lock().unwrap_or_else(|e| e.into_inner()) = None;
        self.set_origin(None);
        remove_surfaced(&self.key);
    }

    fn handles(&self) -> SourceResult<WindowHandles> {
        if is_shutting_down() {
            return Err(SourceError::Cancelled);
        }
        {
            let mut guard = self.handles.lock().unwrap_or_else(|e| e.into_inner());
            if let Some(found) = guard.as_ref() {
                if self.app.get_window(&self.label).is_some()
                    && self.app.get_webview(&view_label_for(&self.key)).is_some()
                {
                    return Ok(found.clone());
                }
                *guard = None;
                self.set_origin(None);
                remove_surfaced(&self.key);
            }
        }
        let created = self.create()?;
        *self.handles.lock().unwrap_or_else(|e| e.into_inner()) = Some(created.clone());
        Ok(created)
    }

    fn create(&self) -> SourceResult<WindowHandles> {
        if is_shutting_down() {
            return Err(SourceError::Cancelled);
        }
        let profile: PathBuf = crate::paths::data_dir().join("webview");
        let (tx, rx) = channel();
        let app = self.app.clone();
        let key = self.key.clone();
        let win_label = self.label.clone();
        self.app
            .run_on_main_thread(move || {
                if is_shutting_down() {
                    let _ = tx.send(Err("应用正在退出".to_string()));
                    return;
                }
                let outcome = build_challenge_window(&app, &key, &win_label, profile)
                    .map_err(|error| error.to_string());
                let _ = tx.send(outcome);
            })
            .map_err(|error| SourceError::Transport(error.to_string()))?;
        if is_shutting_down() {
            return Err(SourceError::Cancelled);
        }
        match rx.recv_timeout(WINDOW_CREATE_TIMEOUT) {
            Ok(Ok(handles)) => {
                if is_shutting_down() {
                    let _ = handles.window.destroy();
                    return Err(SourceError::Cancelled);
                }
                Ok(handles)
            }
            Ok(Err(message)) => {
                if is_shutting_down() {
                    Err(SourceError::Cancelled)
                } else {
                    Err(SourceError::Transport(message))
                }
            }
            Err(_) => Err(SourceError::Transport("取数窗口创建超时".to_string())),
        }
    }
}

fn bar_url(key: &str, theme: &str, brand: &str) -> String {
    format!(
        "challenge.html?key={}&label={}&theme={}&brand={}",
        crate::util::quote(key),
        crate::util::quote(display_label(key)),
        crate::util::quote(theme),
        crate::util::quote(brand)
    )
}

fn apply_child_bounds(window: &Window, bar: &Webview, view: &Webview, size: PhysicalSize<u32>) {
    let scale = window.scale_factor().unwrap_or(1.0);
    let bar_h = ((BAR_H * scale).round() as u32).min(size.height);
    let _ = bar.set_bounds(Rect {
        position: Position::Physical(PhysicalPosition::new(0, 0)),
        size: Size::Physical(PhysicalSize::new(size.width, bar_h)),
    });
    let _ = view.set_bounds(Rect {
        position: Position::Physical(PhysicalPosition::new(0, bar_h as i32)),
        size: Size::Physical(PhysicalSize::new(
            size.width,
            size.height.saturating_sub(bar_h),
        )),
    });
}

fn build_challenge_window(
    app: &AppHandle,
    key: &str,
    win_label: &str,
    profile: PathBuf,
) -> tauri::Result<WindowHandles> {
    let (theme, brand) = current_theme();
    let tone = bg_color(&theme);
    let mut builder = WindowBuilder::new(app, win_label)
        .title("Happycrate 取数窗口")
        .visible(false)
        .skip_taskbar(true)
        .decorations(false)
        .shadow(false)
        .resizable(true)
        .inner_size(FLOAT_W, FLOAT_H)
        .min_inner_size(FLOAT_MIN_W, FLOAT_MIN_H)
        .background_color(tone);
    if let Some(main_win) = app.get_window("main") {
        builder = builder.owner(&main_win)?;
    }
    let win = builder.build()?;
    let size = win.inner_size()?;
    let scale = win.scale_factor().unwrap_or(1.0);
    let bar_h = ((BAR_H * scale).round() as u32).min(size.height);

    let bar_builder = WebviewBuilder::new(
        bar_label_for(key),
        WebviewUrl::App(bar_url(key, &theme, &brand).into()),
    )
    .background_color(tone);
    let bar = win.add_child(
        bar_builder,
        PhysicalPosition::new(0, 0),
        PhysicalSize::new(size.width, bar_h),
    )?;

    let slot = slot_for(key);
    let view_builder = WebviewBuilder::new(
        view_label_for(key),
        WebviewUrl::External(blank_url()),
    )
    .on_page_load(move |_, page| {
        if page.event() == PageLoadEvent::Started {
            *slot.committed_url.lock().unwrap_or_else(|e| e.into_inner()) =
                Some(page.url().clone());
        }
    })
    .data_directory(profile)
    .background_color(tone);
    let view = win.add_child(
        view_builder,
        PhysicalPosition::new(0, bar_h as i32),
        PhysicalSize::new(size.width, size.height.saturating_sub(bar_h)),
    )?;

    let win_resize = win.clone();
    let bar_resize = bar.clone();
    let view_resize = view.clone();
    let app_close = app.clone();
    let key_close = key.to_string();
    win.on_window_event(move |event| match event {
        WindowEvent::Resized(new_size) => {
            apply_child_bounds(&win_resize, &bar_resize, &view_resize, *new_size);
        }
        WindowEvent::CloseRequested { api, .. } => {
            if !is_shutting_down() {
                api.prevent_close();
                dismiss_with_app(&app_close, &key_close);
            }
        }
        _ => {}
    });

    Ok(WindowHandles {
        window: win,
        bar,
        view,
    })
}

fn push_surfaced(key: &str) -> usize {
    let mut guard = SURFACED.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(idx) = guard.iter().position(|item| item == key) {
        return idx;
    }
    guard.push(key.to_string());
    guard.len() - 1
}

fn remove_surfaced(key: &str) {
    let mut guard = SURFACED.lock().unwrap_or_else(|e| e.into_inner());
    guard.retain(|item| item != key);
}

fn target_dimensions(need_w: f64, need_h: f64) -> (f64, f64) {
    let w = if need_w > FLOAT_W {
        need_w.clamp(FLOAT_W, FLOAT_MAX_W)
    } else {
        FLOAT_W
    };
    let h = if need_h > FLOAT_H - BAR_H {
        (need_h + BAR_H + 12.0).clamp(FLOAT_H, FLOAT_MAX_H)
    } else {
        FLOAT_H
    };
    (w, h)
}

fn place_window(app: &AppHandle, win: &Window, w: f64, h: f64, slot_idx: usize) {
    let scale = win.scale_factor().unwrap_or(1.0);
    let win_w = (w * scale).round() as i32;
    let win_h = (h * scale).round() as i32;

    let main_win = app.get_window("main");
    let monitor = main_win
        .as_ref()
        .and_then(|m| m.current_monitor().ok().flatten())
        .or_else(|| win.current_monitor().ok().flatten());

    let (mut x, mut y) = match main_win.as_ref() {
        Some(m) => {
            let min = m.is_minimized().unwrap_or(false);
            match (min, m.outer_position(), m.outer_size()) {
                (false, Ok(mp), Ok(ms)) if mp.x > -10000 && mp.y > -10000 => (
                    mp.x + (ms.width as i32 - win_w) / 2,
                    mp.y + (ms.height as i32 - win_h) / 2,
                ),
                _ => (0, 0),
            }
        }
        None => (0, 0),
    };

    if x == 0 && y == 0 {
        if let Some(mon) = monitor.as_ref() {
            let wa = mon.work_area();
            x = wa.position.x + (wa.size.width as i32 - win_w) / 2;
            y = wa.position.y + (wa.size.height as i32 - win_h) / 2;
        }
    }

    if slot_idx > 0 {
        let step_x = (f64::from(STAGGER_X) * scale).round() as i32;
        let step_y = (f64::from(STAGGER_Y) * scale).round() as i32;
        x += step_x * slot_idx as i32;
        y += step_y * slot_idx as i32;
    }

    if let Some(mon) = monitor.as_ref() {
        let wa = mon.work_area();
        let max_x = (wa.position.x + wa.size.width as i32 - win_w).max(wa.position.x);
        let max_y = (wa.position.y + wa.size.height as i32 - win_h).max(wa.position.y);
        x = x.clamp(wa.position.x, max_x);
        y = y.clamp(wa.position.y, max_y);
    }

    let _ = win.set_position(Position::Physical(PhysicalPosition::new(x, y)));
}

fn apply_look_script(theme: &str, brand: &str) -> String {
    let t = serde_json::to_string(theme).unwrap_or_else(|_| "\"light\"".to_string());
    let b = serde_json::to_string(brand).unwrap_or_else(|_| "\"\"".to_string());
    format!("window.__hcApplyLook && window.__hcApplyLook({t}, {b});")
}

fn challenge_style_script(dark: bool) -> String {
    let (bg, fg, muted, border, thumb, shadow) = if dark {
        (
            "#131419",
            "#E7E9F2",
            "#9095A9",
            "#34364A",
            "rgba(255,255,255,.16)",
            "0 14px 36px rgba(0,0,0,.55)",
        )
    } else {
        (
            "#FFFFFF",
            "#1E1F2E",
            "#676E7E",
            "#E2E5EC",
            "rgba(13,13,31,.16)",
            "0 12px 32px rgba(13,13,31,.14)",
        )
    };
    let css = r##"html{margin:0!important;padding:0!important;min-height:100%!important;width:100%!important;background:__BG__!important;display:flex!important;flex-direction:column!important;justify-content:center!important;align-items:stretch!important;overflow-x:auto!important;overflow-y:auto!important;border-left:1px solid __BORDER__!important;border-right:1px solid __BORDER__!important;border-bottom:1px solid __BORDER__!important;box-sizing:border-box!important;}
html::-webkit-scrollbar,body::-webkit-scrollbar{width:6px;height:6px;}
html::-webkit-scrollbar-thumb,body::-webkit-scrollbar-thumb{background:__THUMB__;border-radius:3px;}
html::-webkit-scrollbar-track,body::-webkit-scrollbar-track{background:transparent;}
body{margin:0 auto!important;padding:16px 18px!important;min-height:0!important;height:auto!important;width:100%!important;max-width:100%!important;background:__BG__!important;color:__FG__!important;box-sizing:border-box!important;display:flex!important;flex-direction:column!important;align-items:center!important;text-align:center!important;font-family:"Noto Sans SC","Microsoft YaHei UI",-apple-system,sans-serif!important;}
body *:not(.__hc_popup):not(.__hc_popup *):not(.__hc_backdrop):not(iframe):not(.g-recaptcha):not(.g-recaptcha *):not(#g-recaptcha):not(#g-recaptcha *):not(.h-captcha):not(.h-captcha *):not(.cf-turnstile):not(.cf-turnstile *){max-width:100%!important;min-width:0!important;box-sizing:border-box!important;}
body>div:not(.__hc_popup):not(.__hc_backdrop):not(.__hc_clutter):not(.footer):not([style*="z-index"]),body>form,body>center,body>main,.main-wrapper,main,#main,.container,.wrapper,#cf-wrapper,#cf-error-details,#cf-wrapper div:not(.__hc_popup):not(.__hc_popup *):not(.__hc_clutter):not(.g-recaptcha):not(.g-recaptcha *):not(#g-recaptcha):not(#g-recaptcha *):not(.h-captcha):not(.h-captcha *):not(.cf-turnstile):not(.cf-turnstile *),.cf-wrapper,.cf-section:not(.__hc_clutter),.cf-columns,.cf-column:not(.__hc_clutter),.w-240,header,section:not(.__hc_clutter),section>div:not(.__hc_clutter):not(.g-recaptcha):not(#g-recaptcha):not(.h-captcha):not(.cf-turnstile),table,tbody,tr,th,td,center,article{margin:0 auto!important;padding:0!important;min-height:0!important;height:auto!important;width:100%!important;max-width:100%!important;float:none!important;position:static!important;background:transparent!important;border:0!important;box-shadow:none!important;display:flex!important;flex-direction:column!important;align-items:center!important;justify-content:center!important;text-align:center!important;}
.main-content{margin:0 auto!important;padding:0!important;width:100%!important;max-width:100%!important;background:transparent!important;border:0!important;box-shadow:none!important;display:flex!important;flex-direction:column!important;align-items:center!important;text-align:center!important;}
h1,h2,h3,.h1,#cf-wrapper h1,#cf-wrapper h2,#cf-wrapper .cf-subheadline,header h1,header span,header p{margin:0 0 8px!important;padding:0!important;font-size:15px!important;line-height:1.45!important;font-weight:600!important;color:__FG__!important;white-space:normal!important;word-break:break-word!important;max-width:100%!important;width:auto!important;}
p,.core-msg,#cf-wrapper p{margin:0 0 10px!important;padding:0!important;font-size:12.5px!important;line-height:1.45!important;color:__MUTED__!important;white-space:normal!important;word-break:break-word!important;max-width:100%!important;}
hr,#cf-wrapper .cf-screenshot-container,#cf-wrapper [class*="screenshot"],#cf-wrapper [class*="captcha-info"],#cf-wrapper .cf-error-footer,.cf-screenshot-container,[class*="screenshot"],[class*="captcha-info"],.cf-error-footer,#cf-please-wait,.footer,footer,#cf-wrapper .__hc_clutter,.__hc_clutter{display:none!important;}
#challenge-stage,#challenge-running,.cf-browser-verification,#cf-challenge-running,#challenge-form,#g-recaptcha,.g-recaptcha,.h-captcha,.cf-turnstile,form{margin:8px auto!important;width:auto!important;max-width:100%!important;display:flex!important;flex-direction:column!important;align-items:center!important;justify-content:center!important;}
.__hc_backdrop{position:fixed!important;inset:0!important;top:0!important;left:0!important;width:100%!important;height:100%!important;background:__BG__!important;opacity:.98!important;z-index:1999999998!important;border-left:1px solid __BORDER__!important;border-right:1px solid __BORDER__!important;border-bottom:1px solid __BORDER__!important;box-sizing:border-box!important;}
.__hc_popup{position:fixed!important;top:50%!important;left:50%!important;right:auto!important;bottom:auto!important;transform:translate(-50%,-50%)!important;margin:0!important;z-index:2000000000!important;border:1px solid __BORDER__!important;border-radius:10px!important;overflow:hidden!important;box-shadow:__SHADOW__!important;background:#fff!important;}
.__hc_arrow{display:none!important;}"##
        .replace("__BG__", bg)
        .replace("__FG__", fg)
        .replace("__MUTED__", muted)
        .replace("__BORDER__", border)
        .replace("__THUMB__", thumb)
        .replace("__SHADOW__", shadow);
    let literal = serde_json::to_string(&css).unwrap_or_else(|_| "\"\"".to_string());
    r##"(function(){
var css=__LITERAL__;
var id='__hc_ch_style';
var s=document.getElementById(id);
if(!s){
  s=document.createElement('style');
  s.id=id;
  var nc=document.querySelector('[nonce]');
  if(nc){var nv=nc.nonce||nc.getAttribute('nonce');if(nv)s.setAttribute('nonce',nv);}
  (document.head||document.documentElement).appendChild(s);
}
if(s.textContent!==css)s.textContent=css;
var ok=false;
try{ok=!!(s.sheet&&s.sheet.cssRules&&s.sheet.cssRules.length);}catch(e){}
if(!ok&&typeof CSSStyleSheet==='function'&&document.adoptedStyleSheets){
  try{
    if(!window.__hcChSheet)window.__hcChSheet=new CSSStyleSheet();
    window.__hcChSheet.replaceSync(css);
    if(document.adoptedStyleSheets.indexOf(window.__hcChSheet)<0){
      document.adoptedStyleSheets=document.adoptedStyleSheets.concat([window.__hcChSheet]);
    }
  }catch(e){}
}
if(window._cf_chl_opt)return;
function setCls(el,c,on){
  if(el.classList.contains(c)!==!!on)el.classList.toggle(c,!!on);
}
function setImp(el,k,v){
  if(el.style.getPropertyValue(k)!==v||el.style.getPropertyPriority(k)!=='important'){
    el.style.setProperty(k,v,'important');
  }
}
var widgets=document.querySelectorAll('.g-recaptcha,#g-recaptcha,.h-captcha,.cf-turnstile,#challenge-stage,#challenge-running,iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare.com"]');
for(var wi=0;wi<widgets.length;wi++){
  var anchor=widgets[wi].closest('.g-recaptcha,#g-recaptcha,.h-captcha,.cf-turnstile,#challenge-stage,#challenge-running')||widgets[wi];
  if(anchor.closest('.__hc_popup'))continue;
  var p=anchor.parentElement;
  while(p&&p!==document.body&&p!==document.documentElement){
    if(!p.classList.contains('__hc_popup')){
      setImp(p,'width','100%');
      setImp(p,'max-width','100%');
      setImp(p,'min-width','0');
      setImp(p,'margin-left','auto');
      setImp(p,'margin-right','auto');
      setImp(p,'padding-left','0');
      setImp(p,'padding-right','0');
      setImp(p,'float','none');
      setImp(p,'transform','none');
      setImp(p,'display','flex');
      setImp(p,'flex-direction','column');
      setImp(p,'align-items','center');
      var kids=p.children;
      for(var ki=0;ki<kids.length;ki++){
        var sib=kids[ki];
        if(sib===anchor||sib.contains(anchor))continue;
        if(sib.tagName==='HEADER'||sib.querySelector('header,iframe,form,input,button,h1,.g-recaptcha,#g-recaptcha,.h-captcha,.cf-turnstile,#challenge-stage,#challenge-running,.__hc_popup'))continue;
        var stxt=(sib.textContent||'').toLowerCase();
        var sr=sib.getBoundingClientRect();
        var ssvg=sib.querySelector('svg');
        var sbig=ssvg&&ssvg.getBoundingClientRect().width>48;
        if(sbig||/^\s*$/.test(stxt)&&sr.height>40||/why do i have to complete|what can i do to prevent|cloudflare ray id|performance & security by/.test(stxt)){
          setCls(sib,'__hc_clutter',true);
          setImp(sib,'display','none');
        }
      }
    }
    p=p.parentElement;
  }
}
var blocks=document.querySelectorAll('#cf-wrapper section,#cf-wrapper div,section>div,main>div,.cf-column,[class*="column"]');
for(var j=0;j<blocks.length;j++){
  var blk=blocks[j];
  if(blk.id==='cf-wrapper'||blk.id==='cf-error-details'||blk.querySelector('header,iframe,form,input,button,.g-recaptcha,#g-recaptcha,.h-captcha,.cf-turnstile,#challenge-stage,#challenge-running,.__hc_popup'))continue;
  var txt=(blk.textContent||'').toLowerCase();
  var r=blk.getBoundingClientRect();
  var bigSvg=blk.querySelector('svg');
  var svgBig=bigSvg&&bigSvg.getBoundingClientRect().width>48;
  if(svgBig||(/^\s*$/.test(txt)&&r.height>40)||/why do i have to complete|what can i do to prevent|cloudflare ray id|performance & security by/.test(txt)){
    setCls(blk,'__hc_clutter',true);
    setImp(blk,'display','none');
  }
}
var divs=document.querySelectorAll('body>div');
var hasPopup=false;
for(var i=0;i<divs.length;i++){
  var el=divs[i];
  var big=el.querySelector("iframe[src*='bframe'],iframe[title*='challenge'],iframe[src*='hcaptcha.com'][src*='challenge']");
  if(big){
    var cs=getComputedStyle(el);
    var r=big.getBoundingClientRect();
    var open=cs.display!=='none'&&cs.visibility!=='hidden'&&r.height>150&&r.width>150&&r.top>-500&&r.left>-500;
    setCls(el,'__hc_popup',open);
    if(open)hasPopup=true;
    for(var k=0;k<el.children.length;k++){
      var ch=el.children[k];
      var kc=getComputedStyle(ch);
      setCls(ch,'__hc_arrow',open&&!ch.querySelector('iframe')&&(ch.offsetWidth<=24||kc.pointerEvents==='none'));
    }
  }else{
    setCls(el,'__hc_popup',false);
    var st=getComputedStyle(el);
    var z=parseInt(st.zIndex||'0',10);
    var isOv=(st.position==='fixed'||st.position==='absolute')&&z>=100000&&!el.querySelector('iframe')&&st.display!=='none'&&st.visibility!=='hidden';
    setCls(el,'__hc_backdrop',isOv);
  }
}
if(!hasPopup){
  for(var i=0;i<divs.length;i++){
    setCls(divs[i],'__hc_backdrop',false);
  }
}
})();"##
        .replace("__LITERAL__", &literal)
}
fn sync_window_theme(handles: &WindowHandles, theme: &str, brand: &str) {
    let tone = bg_color(theme);
    let _ = handles.window.set_background_color(Some(tone));
    let _ = handles.view.set_background_color(Some(tone));
    let _ = handles.bar.eval(apply_look_script(theme, brand));
    let _ = handles.view.eval(challenge_style_script(theme == "dark"));
}

fn surface_window(app: &AppHandle, key: &str, handles: &WindowHandles) -> (f64, f64) {
    let slot_idx = push_surfaced(key);
    let (w, h) = (FLOAT_W, FLOAT_H);
    let (theme, brand) = current_theme();
    let handles_main = handles.clone();
    let app_main = app.clone();
    let _ = app.run_on_main_thread(move || {
        sync_window_theme(&handles_main, &theme, &brand);
        let _ = handles_main.window.set_size(Size::Logical(LogicalSize::new(w, h)));
        if let Ok(size) = handles_main.window.inner_size() {
            apply_child_bounds(&handles_main.window, &handles_main.bar, &handles_main.view, size);
        }
        place_window(&app_main, &handles_main.window, w, h, slot_idx);
        let _ = handles_main.window.show();
        let _ = handles_main.window.set_focus();
    });
    (w, h)
}

fn grow_window(
    app: &AppHandle,
    handles: &WindowHandles,
    cur_w: &mut f64,
    cur_h: &mut f64,
    need_w: f64,
    need_h: f64,
) {
    let (next_w, next_h) = target_dimensions(need_w, need_h);
    let target_w = next_w.max(*cur_w).min(FLOAT_MAX_W);
    let target_h = next_h.max(*cur_h).min(FLOAT_MAX_H);
    if target_w <= *cur_w + 8.0 && target_h <= *cur_h + 8.0 {
        return;
    }
    *cur_w = target_w;
    *cur_h = target_h;
    let handles_main = handles.clone();
    let app_main = app.clone();
    let _ = app.run_on_main_thread(move || {
        let _ = handles_main
            .window
            .set_size(Size::Logical(LogicalSize::new(target_w, target_h)));
        if let Ok(size) = handles_main.window.inner_size() {
            apply_child_bounds(&handles_main.window, &handles_main.bar, &handles_main.view, size);
        }
        let scale = handles_main.window.scale_factor().unwrap_or(1.0);
        let win_w = (target_w * scale).round() as i32;
        let win_h = (target_h * scale).round() as i32;
        let monitor = app_main
            .get_window("main")
            .and_then(|m| m.current_monitor().ok().flatten())
            .or_else(|| handles_main.window.current_monitor().ok().flatten());
        if let (Some(mon), Ok(pos)) = (monitor, handles_main.window.outer_position()) {
            let wa = mon.work_area();
            let max_x = (wa.position.x + wa.size.width as i32 - win_w).max(wa.position.x);
            let max_y = (wa.position.y + wa.size.height as i32 - win_h).max(wa.position.y);
            let cx = pos.x.clamp(wa.position.x, max_x);
            let cy = pos.y.clamp(wa.position.y, max_y);
            if cx != pos.x || cy != pos.y {
                let _ = handles_main
                    .window
                    .set_position(Position::Physical(PhysicalPosition::new(cx, cy)));
            }
        }
    });
}

fn hide_window(key: &str, handles: &WindowHandles) {
    remove_surfaced(key);
    let _ = handles.window.hide();
}

impl Driver for WindowDriver {
    fn challenge_flag(&self) -> Option<Arc<AtomicBool>> {
        Some(self.slot.challenged.clone())
    }

    fn load(&self, url: &str, deadline: Instant, batch: Option<i64>) -> SourceResult<String> {
        if is_shutting_down() {
            return Err(SourceError::Cancelled);
        }
        self.slot.dismissed.store(false, Ordering::SeqCst);
        let target = url
            .parse::<tauri::Url>()
            .map_err(|_| SourceError::Transport(format!("取数地址无法解析：{url}")))?;
        let handles = self.handles()?;
        if handles.window.is_visible().unwrap_or(false) {
            hide_window(&self.key, &handles);
        }
        *self.slot.committed_url.lock().unwrap_or_else(|e| e.into_inner()) = None;
        handles
            .view
            .navigate(target)
            .map_err(|error| SourceError::Transport(error.to_string()))?;
        let mut active_deadline = deadline;
        let mut _challenge_guard: Option<ChallengeGuard> = None;
        let mut surfaced = false;
        let mut cur_w = FLOAT_W;
        let mut cur_h = FLOAT_H;
        loop {
            if is_shutting_down() || self.slot.dismissed.load(Ordering::SeqCst) {
                reset(&self.key, &handles);
                self.set_origin(None);
                return Err(SourceError::Cancelled);
            }
            if let Some(token) = batch {
                if !batch_alive(token) {
                    reset(&self.key, &handles);
                    self.set_origin(None);
                    return Err(SourceError::Cancelled);
                }
            }
            let left = active_deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                reset(&self.key, &handles);
                self.set_origin(None);
                return Err(SourceError::Timeout);
            }
            let step = if surfaced {
                CHALLENGE_POLL_INTERVAL
            } else {
                POLL_INTERVAL
            };
            thread::sleep(left.min(step));
            if is_shutting_down() || self.slot.dismissed.load(Ordering::SeqCst) {
                reset(&self.key, &handles);
                self.set_origin(None);
                return Err(SourceError::Cancelled);
            }
            if self.app.get_window(&self.label).is_none()
                || self.app.get_webview(&view_label_for(&self.key)).is_none()
            {
                self.clear_window();
                return Err(SourceError::Cancelled);
            }
            if Instant::now() >= active_deadline {
                reset(&self.key, &handles);
                self.set_origin(None);
                return Err(SourceError::Timeout);
            }
            let status: PageStatus = match eval_json(&handles.view, STATUS_SCRIPT) {
                Ok(status) => status,
                Err(SourceError::Shape(_)) | Err(SourceError::Timeout) => continue,
                Err(other) => {
                    self.clear_window();
                    return Err(other);
                }
            };
            let (committed, origin) = {
                let url = self.slot.committed_url.lock().unwrap_or_else(|e| e.into_inner());
                let origin = url.as_ref()
                    .filter(|url| url.as_str() == status.href)
                    .and_then(origin_of_url);
                (url.as_ref().is_some_and(|url| url.scheme() != "about"), origin)
            };
            let error = if status.ready && status.href.starts_with("chrome-error://") && (surfaced || committed) {
                let detail = if status.err.is_empty() {
                    "页面加载失败".to_string()
                } else {
                    format!("页面加载失败：{}", status.err)
                };
                Some(SourceError::Transport(detail))
            } else if status.ready && !status.challenge && status.http >= 400 && origin.is_some() {
                Some(SourceError::Http { code: status.http, body: String::new() })
            } else {
                None
            };
            if let Some(error) = error {
                if !surfaced {
                    reset(&self.key, &handles);
                }
                self.set_origin(None);
                return Err(error);
            }
            let Some(origin) = origin else {
                continue;
            };
            if status.ready && !status.challenge {
                if surfaced {
                    hide_window(&self.key, &handles);
                }
                let content: PageContent = eval_json(&handles.view, CONTENT_SCRIPT)?;
                if content.html.is_empty() {
                    return Err(SourceError::Shape("取数窗口返回空页面".to_string()));
                }
                if surfaced {
                    invoke_hook(&CHALLENGE_DONE_HOOK);
                }
                self.set_origin(Some(origin));
                return Ok(content.html);
            }
            if status.challenge {
                let (theme, _) = current_theme();
                if !surfaced {
                    let (w, h) = surface_window(&self.app, &self.key, &handles);
                    cur_w = w;
                    cur_h = h;
                    surfaced = true;
                    _challenge_guard = Some(self.slot.enter_challenge());
                    active_deadline = active_deadline.max(Instant::now() + CHALLENGE_TIMEOUT);
                    if let Some(hook) = CHALLENGE_HOOK.get() {
                        hook(batch);
                    }
                } else {
                    let _ = handles.view.eval(challenge_style_script(theme == "dark"));
                    grow_window(
                        &self.app,
                        &handles,
                        &mut cur_w,
                        &mut cur_h,
                        status.need_w,
                        status.need_h,
                    );
                }
            }
        }
    }

    fn batch(&self, urls: &[String], deadline: Instant, batch: Option<i64>) -> Vec<SourceResult<String>> {
        let count = urls.len();
        if is_shutting_down() {
            return (0..count).map(|_| Err(SourceError::Cancelled)).collect();
        }
        let mut results: Vec<Option<SourceResult<String>>> = (0..count).map(|_| None).collect();
        let handles = match self.handles() {
            Ok(handles) => handles,
            Err(error) => return (0..count).map(|_| Err(error.clone())).collect(),
        };
        let home = self.origin();
        let mut pending: Vec<usize> = Vec::new();
        for (index, url) in urls.iter().enumerate() {
            let same = match (&home, url.parse::<tauri::Url>().ok()) {
                (Some(home), Some(parsed)) => origin_of_url(&parsed).as_deref() == Some(home.as_str()),
                _ => false,
            };
            if same {
                pending.push(index);
            } else {
                let res = self.load(url, deadline, batch);
                let cancelled = matches!(res, Err(SourceError::Cancelled));
                results[index] = Some(res);
                if cancelled {
                    for slot in results.iter_mut() {
                        if slot.is_none() {
                            *slot = Some(Err(SourceError::Cancelled));
                        }
                    }
                    return results
                        .into_iter()
                        .map(|result| result.unwrap_or(Err(SourceError::Cancelled)))
                        .collect();
                }
            }
        }
        let mut offset = 0usize;
        while offset < pending.len() {
            if is_shutting_down() || self.slot.dismissed.load(Ordering::SeqCst) {
                for index in &pending[offset..] {
                    results[*index] = Some(Err(SourceError::Cancelled));
                }
                break;
            }
            if let Some(token) = batch {
                if !batch_alive(token) {
                    for index in &pending[offset..] {
                        results[*index] = Some(Err(SourceError::Cancelled));
                    }
                    break;
                }
            }
            if Instant::now() >= deadline {
                for index in &pending[offset..] {
                    results[*index] = Some(Err(SourceError::Timeout));
                }
                break;
            }
            let end = (offset + BATCH_GROUP).min(pending.len());
            let group: Vec<usize> = pending[offset..end].to_vec();
            let group_urls: Vec<String> = group.iter().map(|&i| urls[i].to_string()).collect();
            let outcome = in_page_fetch(&handles.view, &group_urls, deadline, batch, &self.slot);
            match outcome {
                Ok(items) => {
                    for (index, item) in group.iter().zip(items.into_iter()) {
                        results[*index] = Some(item.into_html());
                    }
                }
                Err(error) => {
                    let cancelled = matches!(error, SourceError::Cancelled);
                    for index in &group {
                        results[*index] = Some(Err(error.clone()));
                    }
                    if cancelled {
                        for index in &pending[end..] {
                            results[*index] = Some(Err(SourceError::Cancelled));
                        }
                        break;
                    }
                }
            }
            offset = end;
        }
        results
            .into_iter()
            .map(|result| result.unwrap_or(Err(SourceError::Timeout)))
            .collect()
    }
}

fn origin_of_url(url: &tauri::Url) -> Option<String> {
    if url.scheme() == "about" {
        return None;
    }
    let host = url.host_str()?;
    Some(match url.port_or_known_default() {
        Some(port) => format!("{}://{}:{}", url.scheme(), host, port),
        None => format!("{}://{}", url.scheme(), host),
    })
}

fn in_page_fetch(
    view: &Webview,
    urls: &[String],
    deadline: Instant,
    batch: Option<i64>,
    slot: &SlotState,
) -> SourceResult<Vec<BatchItem>> {
    let list = serde_json::to_string(urls)
        .map_err(|_| SourceError::Transport("批量取数地址序列化失败".to_string()))?;
    let starter = BATCH_START
        .replace("__URLS__", &list)
        .replace("__ITEM_TIMEOUT_MS__", &BATCH_ITEM_TIMEOUT_MS.to_string());
    view.eval(starter)
        .map_err(|error| SourceError::Transport(error.to_string()))?;
    loop {
        if is_shutting_down() || slot.dismissed.load(Ordering::SeqCst) {
            let _ = view.eval(BATCH_CLEAR);
            return Err(SourceError::Cancelled);
        }
        if let Some(token) = batch {
            if !batch_alive(token) {
                let _ = view.eval(BATCH_CLEAR);
                return Err(SourceError::Cancelled);
            }
        }
        if Instant::now() >= deadline {
            let _ = view.eval(BATCH_CLEAR);
            return Err(SourceError::Timeout);
        }
        thread::sleep(BATCH_POLL);
        if is_shutting_down() || slot.dismissed.load(Ordering::SeqCst) {
            return Err(SourceError::Cancelled);
        }
        let ready: Option<BatchReady> = match eval_json(view, BATCH_POLL_SCRIPT) {
            Ok(value) => value,
            Err(SourceError::Shape(_)) | Err(SourceError::Timeout) => continue,
            Err(other) => return Err(other),
        };
        let Some(ready) = ready else {
            continue;
        };
        let _ = view.eval(BATCH_CLEAR);
        if ready.items.len() != urls.len() {
            return Err(SourceError::Shape("批量取数条数不符".to_string()));
        }
        return Ok(ready.items);
    }
}

fn reset(key: &str, handles: &WindowHandles) {
    hide_window(key, handles);
    let _ = handles.view.navigate(blank_url());
}

fn blank_url() -> tauri::Url {
    "about:blank".parse().expect("about:blank 可解析")
}

fn eval_json<T: for<'de> Deserialize<'de>>(view: &Webview, script: &str) -> SourceResult<T> {
    let (tx, rx) = channel();
    view.eval_with_callback(script, move |value| {
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
    #[serde(default)]
    href: String,
    #[serde(default)]
    err: String,
    #[serde(default)]
    http: u16,
    #[serde(default, rename = "needW")]
    need_w: f64,
    #[serde(default, rename = "needH")]
    need_h: f64,
}

#[derive(Deserialize)]
struct PageContent {
    html: String,
}

#[derive(Deserialize)]
struct BatchItem {
    status: u16,
    url: String,
    html: String,
}

impl BatchItem {
    fn into_html(self) -> SourceResult<String> {
        if (200..300).contains(&self.status) && !self.html.is_empty() {
            return Ok(self.html);
        }
        Err(SourceError::Transport("页内取数失败".to_string()))
    }
}

#[derive(Deserialize)]
struct BatchReady {
    items: Vec<BatchItem>,
}

struct JavdbDriver(AppHandle);

impl Driver for JavdbDriver {
    fn load(&self, url: &str, deadline: Instant, batch: Option<i64>) -> SourceResult<String> {
        use crate::{javdb_session, sources::javdb};

        let login_required = || SourceError::Blocked(javdb::LOGIN_TEXT.to_string());
        let view = self.0.get_webview(javdb_session::WINDOW).ok_or_else(login_required)?;
        if !javdb_session::signed_in() {
            return Err(login_required());
        }
        let target = url
            .parse::<tauri::Url>()
            .map_err(|err| SourceError::Transport(err.to_string()))?;
        let current = view.url().map_err(|err| SourceError::Transport(err.to_string()))?;
        if target.origin() != current.origin() {
            return Err(SourceError::Transport("JavDB 登录地址与取数地址不同".to_string()));
        }

        let slot = slot_for(javdb_session::WINDOW);
        let mut items = in_page_fetch(&view, &[url.to_string()], deadline, batch, &slot)?;
        let item = items
            .pop()
            .ok_or_else(|| SourceError::Shape("JavDB 取数无返回".to_string()))?;
        let landing = item.url.parse::<tauri::Url>().ok();
        if landing
            .as_ref()
            .is_some_and(|landed| landed.origin() != target.origin())
        {
            return Err(SourceError::Transport("JavDB 跳转至其他站点".to_string()));
        }
        if item.status == 401
            || landing.as_ref().is_some_and(javdb_session::login_path)
            || javdb::login_wall(&item.html)
        {
            javdb_session::set_signed_in(&self.0, false);
            return Err(login_required());
        }
        let blocked = if matches!(item.status, 403 | 429) {
            crate::net::captcha_wall(item.html.as_bytes())
        } else {
            crate::net::captcha_text(&item.html)
        };
        if blocked {
            return Err(SourceError::Blocked(crate::outcome::BLOCKED_TEXT.to_string()));
        }
        if item.status >= 400 {
            return Err(SourceError::Http {
                code: item.status,
                body: String::new(),
            });
        }
        item.into_html()
    }
}

pub fn probe_enabled() -> bool {
    matches!(std::env::var(PROBE_ENV), Ok(value) if value == "1")
}

static CHANNELS: OnceLock<HashMap<&'static str, Arc<WebFetch>>> = OnceLock::new();

pub fn init(app: &AppHandle) {
    let _ = APP_HANDLE.set(app.clone());
    let mut channels = HashMap::new();
    for key in crate::sources::WEBVIEW_KEYS {
        let driver = WindowDriver::new(app.clone(), (*key).to_string());
        channels.insert(*key, Arc::new(WebFetch::start(driver)));
    }
    channels.insert(
        crate::javdb_session::KEY,
        Arc::new(WebFetch::start(JavdbDriver(app.clone()))),
    );
    let _ = CHANNELS.set(channels);
}

pub fn shared(key: &str) -> Option<Arc<WebFetch>> {
    if key == crate::javdb_session::KEY && !crate::javdb_session::signed_in() {
        return None;
    }
    CHANNELS.get()?.get(key).cloned()
}

fn dismiss_with_app(app: &AppHandle, key: &str) -> bool {
    if key.is_empty() {
        return false;
    }
    slot_for(key).dismissed.store(true, Ordering::SeqCst);
    remove_surfaced(key);
    if let Some(window) = app.get_window(&label_for(key)) {
        let _ = window.hide();
    }
    if let Some(view) = app.get_webview(&view_label_for(key)) {
        let _ = view.navigate(blank_url());
    }
    true
}

pub fn dismiss(key: &str) -> bool {
    let Some(app) = APP_HANDLE.get() else {
        return false;
    };
    dismiss_with_app(app, key)
}

pub fn refresh_theme() {
    let Some(app) = APP_HANDLE.get() else {
        return;
    };
    let keys: Vec<String> = SURFACED
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .clone();
    if keys.is_empty() {
        return;
    }
    let (theme, brand) = current_theme();
    for key in keys {
        if let (Some(window), Some(bar), Some(view)) = (
            app.get_window(&label_for(&key)),
            app.get_webview(&bar_label_for(&key)),
            app.get_webview(&view_label_for(&key)),
        ) {
            let handles = WindowHandles { window, bar, view };
            sync_window_theme(&handles, &theme, &brand);
        }
    }
}

pub fn shutdown() {
    SHUTTING_DOWN.store(true, Ordering::SeqCst);
    SURFACED.lock().unwrap_or_else(|e| e.into_inner()).clear();
    if let Some(channels) = CHANNELS.get() {
        for fetch in channels.values() {
            fetch.close();
        }
    }
}

pub fn start_probe(app: &AppHandle) {
    let url = std::env::var(PROBE_URL_ENV).unwrap_or_else(|_| "https://example.com".to_string());
    let app = app.clone();
    thread::spawn(move || {
        let fetch = WebFetch::start(WindowDriver::new(app, "probe".to_string()));
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
