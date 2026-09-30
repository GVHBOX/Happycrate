use std::sync::Mutex;

use serde_json::Value;
use tauri::Manager;

use crate::api::Api;

pub struct AppState {
    pub api: Mutex<Api>,
    pub maxed: Mutex<bool>,
}

impl AppState {
    fn api(&self) -> std::sync::MutexGuard<'_, Api> {
        self.api.lock().unwrap_or_else(|e| e.into_inner())
    }
}

#[tauri::command]
fn list_sources(state: tauri::State<AppState>) -> Vec<Value> {
    state.api().list_sources()
}

#[tauri::command]
fn source_issues(state: tauri::State<AppState>) -> Vec<Value> {
    state.api().source_issues()
}

#[tauri::command]
fn toggle_source(state: tauri::State<AppState>, key: String, on: bool) -> bool {
    state.api().toggle_source(&key, on)
}

#[tauri::command]
fn reorder_sources(state: tauri::State<AppState>, keys: Vec<String>) -> bool {
    state.api().reorder_sources(&keys)
}

#[tauri::command]
fn set_auto_order(state: tauri::State<AppState>, on: bool) -> bool {
    state.api().set_auto_order(on)
}

#[tauri::command]
fn get_settings(state: tauri::State<AppState>) -> Value {
    state.api().get_settings()
}

#[tauri::command]
fn default_settings(state: tauri::State<AppState>) -> Value {
    state.api().default_settings()
}

#[tauri::command]
fn save_settings(state: tauri::State<AppState>, fields: Value) -> Value {
    state.api().save_settings(&fields)
}

#[tauri::command]
fn reload_query_roles(state: tauri::State<AppState>) -> bool {
    state.api().reload_query_roles()
}

#[tauri::command]
fn selftest(state: tauri::State<AppState>) -> Value {
    state.api().selftest()
}

#[tauri::command]
fn app_info(state: tauri::State<AppState>) -> Value {
    state.api().app_info()
}

#[tauri::command]
fn torrent_files(state: tauri::State<AppState>, payload: Value) -> Value {
    state.api().torrent_files(&payload)
}

#[tauri::command]
fn downloaders(state: tauri::State<AppState>) -> Vec<Value> {
    state.api().downloaders()
}

#[tauri::command]
fn deliver(state: tauri::State<AppState>, magnets: Vec<Value>, key: Option<String>) -> Value {
    let chosen = key.unwrap_or_default();
    state.api().deliver(&magnets, &chosen)
}

#[tauri::command]
fn probe_sources(state: tauri::State<AppState>, keys: Option<Vec<String>>) -> i64 {
    state.api().probe_sources(keys.as_deref())
}

#[tauri::command]
fn start_search(state: tauri::State<AppState>, query: String, page: Option<i64>) -> Value {
    let page = page.unwrap_or(1);
    state.api().start_search(&query, page)
}

#[tauri::command]
fn cancel_search(state: tauri::State<AppState>, token: Option<i64>) -> bool {
    state.api().cancel_search(token.unwrap_or(0))
}

#[tauri::command]
fn proxy_status(state: tauri::State<AppState>, force: bool) -> Value {
    state.api().proxy_status(force)
}

#[tauri::command]
fn open_logs(state: tauri::State<AppState>) -> bool {
    state.api().open_logs()
}

#[tauri::command]
fn win_min(window: tauri::Window) -> bool {
    window.minimize().is_ok()
}

#[tauri::command]
fn win_max(window: tauri::Window, state: tauri::State<AppState>) -> bool {
    let mut maxed = state.maxed.lock().unwrap_or_else(|e| e.into_inner());
    let outcome = if *maxed {
        window.unmaximize()
    } else {
        window.maximize()
    };
    if outcome.is_ok() {
        *maxed = !*maxed;
        return true;
    }
    false
}

#[tauri::command]
fn win_close(window: tauri::Window) -> bool {
    window.close().is_ok()
}

#[tauri::command]
fn set_window_tone(window: tauri::Window, color: String) -> bool {
    let value = color.trim();
    if !crate::api::hex_color_ok(value) {
        return false;
    }
    let channel = |from: usize| u8::from_str_radix(&value[from..from + 2], 16).unwrap_or(0);
    window
        .set_background_color(Some(tauri::window::Color(
            channel(1),
            channel(3),
            channel(5),
            255,
        )))
        .is_ok()
}

pub fn run() {
    let webview_args = "--disable-features=Translate,OptimizationHints,MediaRouter --disable-component-update --disable-background-networking --disk-cache-size=1048576";
    match std::env::var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS") {
        Ok(existing) if !existing.is_empty() => {
            std::env::set_var(
                "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
                format!("{existing} {webview_args}"),
            );
        }
        _ => {
            std::env::set_var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", webview_args);
        }
    }

    crate::log::setup(None);
    crate::log::install_panic_hook();

    if !crate::single::acquire() {
        crate::single::release();
        return;
    }

    crate::paths::ensure_dirs().expect("数据目录建不出来");
    crate::config::sweep_temp_files(&crate::paths::data_dir());

    let api = Api::new(None, None).boot();

    let outcome = tauri::Builder::default()
        .manage(AppState {
            api: Mutex::new(api),
            maxed: Mutex::new(false),
        })
        .invoke_handler(tauri::generate_handler![
            list_sources,
            source_issues,
            toggle_source,
            reorder_sources,
            set_auto_order,
            probe_sources,
            start_search,
            cancel_search,
            get_settings,
            default_settings,
            save_settings,
            reload_query_roles,
            selftest,
            app_info,
            open_logs,
            proxy_status,
            downloaders,
            deliver,
            torrent_files,
            win_min,
            win_max,
            win_close,
            set_window_tone,
        ])
        .setup(|app| {
            let window = app.get_webview_window("main").ok_or("找不到主窗口")?;
            window.set_focus()?;
            crate::log::info(
                crate::log::SHELL,
                &format!(
                    "{} v{} 就绪 · 界面已内嵌",
                    crate::api::APP_TITLE,
                    crate::api::APP_VERSION
                ),
            );
            let handle = window.clone();
            let push_gate = std::sync::Arc::new(std::sync::Mutex::new(()));
            let state = app.state::<AppState>();
            state
                .api
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .set_push(std::sync::Arc::new(move |event| {
                    let _guard = push_gate.lock().unwrap_or_else(|e| e.into_inner());
                    if handle.eval(&crate::search::js_of(&event)).is_err() {
                        crate::log::warning(crate::log::SHELL, "推送前端失败");
                    }
                }));
            Ok(())
        })
        .run(tauri::generate_context!());

    crate::single::release();
    outcome.expect("Tauri 启动失败");
}
