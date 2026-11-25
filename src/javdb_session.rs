use std::sync::atomic::{AtomicUsize, Ordering};

use tauri::webview::{NewWindowResponse, PageLoadEvent};
use tauri::{AppHandle, Manager, Url, WebviewUrl, WebviewWindowBuilder, WindowEvent};

pub const KEY: &str = "javdb";
pub const WINDOW: &str = "javdb-session";

static REVISION: AtomicUsize = AtomicUsize::new(0);

const SIGNED_IN: &str = r#"
Boolean(document.querySelector('a[href="/logout"], form[action="/logout"], a[href="/users/sign_out"], form[action="/users/sign_out"]'))
|| Array.from(document.querySelectorAll('.navbar a')).some(a => /^(登出|退出登[录錄入]|log\s*out|sign\s*out)$/i.test(a.textContent.trim()))
"#;

pub fn revision() -> usize {
    REVISION.load(Ordering::SeqCst)
}

pub fn signed_in() -> bool {
    revision() % 2 != 0
}

pub fn set_signed_in(app: &AppHandle, signed_in: bool) {
    let changed = REVISION.fetch_update(Ordering::SeqCst, Ordering::SeqCst, |revision| {
        ((revision % 2 != 0) != signed_in).then_some(revision + 1)
    });
    if changed.is_ok() {
        if let Some(main) = app.get_webview_window("main") {
            let _ = main.eval(format!(
                "window.__onJavdbSession && window.__onJavdbSession({signed_in})"
            ));
        }
    }
}

pub fn login_path(url: &Url) -> bool {
    matches!(
        url.path().trim_end_matches('/'),
        "/login" | "/users/sign_in"
    )
}

pub fn open(app: &AppHandle, base: &str) -> Result<(), String> {
    if signed_in() {
        return Ok(());
    }
    let mut url = Url::parse(base).map_err(|_| "JavDB 地址无效".to_string())?;
    let official = url.scheme() == "https" && url.host_str() == Some("javdb.com");
    let local = matches!(url.scheme(), "http" | "https")
        && matches!(url.host_str(), Some("127.0.0.1" | "[::1]" | "localhost"));
    if (!official && !local) || !url.username().is_empty() || url.password().is_some() {
        return Err("JavDB 登录地址须为官网或本机地址".to_string());
    }
    url.set_path("/login");
    url.set_query(None);
    url.set_fragment(None);
    let origin = url.origin();
    if let Some(window) = app.get_webview_window(WINDOW) {
        if !window.is_visible().map_err(|err| err.to_string())? {
            window.navigate(url).map_err(|err| err.to_string())?;
            window.show().map_err(|err| err.to_string())?;
        }
        return window.set_focus().map_err(|err| err.to_string());
    }
    let title = format!("JavDB 登录 · {}", origin.ascii_serialization());
    let mut builder = WebviewWindowBuilder::new(app, WINDOW, WebviewUrl::External(url))
        .title(title)
        .inner_size(920.0, 740.0)
        .incognito(true)
        .data_directory(crate::paths::data_dir().join("webview-javdb"))
        .on_navigation(move |url| url.origin() == origin)
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .on_page_load(|window, page| {
            if page.event() == PageLoadEvent::Finished && !login_path(page.url()) {
                let session = window.clone();
                let _ = window.eval_with_callback(SIGNED_IN, move |state| {
                    if state == "true" && session.hide().is_ok() {
                        set_signed_in(session.app_handle(), true);
                    }
                });
            }
        });
    if let Some(main) = app.get_webview_window("main") {
        builder = builder.owner(&main).map_err(|err| err.to_string())?;
    }
    let window = builder.build().map_err(|err| err.to_string())?;
    let app = app.clone();
    window.on_window_event(move |event| {
        if matches!(event, WindowEvent::Destroyed) {
            set_signed_in(&app, false);
        }
    });
    Ok(())
}
