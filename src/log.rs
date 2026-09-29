use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};

use crate::paths;

static WRITE_LOCK: Mutex<()> = Mutex::new(());

pub const ROOT: &str = "happycrate";
pub const API: &str = "happycrate.app.api";
pub const SOURCES: &str = "happycrate.app.sources";
pub const CONFIG: &str = "happycrate.app.config";
pub const DOWNLOADERS: &str = "happycrate.app.downloaders";
pub const MIGRATE: &str = "happycrate.app.migrate";
pub const SHELL: &str = "happycrate.app.shell";
pub const SINGLE: &str = "happycrate.app.single";

const MAX_BYTES: u64 = 1024 * 1024;
const BACKUPS: usize = 3;
const ENV_LEVEL: &str = "HAPPYCRATE_LOG_LEVEL";

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Level {
    Debug,
    Info,
    Warning,
    Error,
}

impl Level {
    fn label(self) -> &'static str {
        match self {
            Level::Debug => "DEBUG",
            Level::Info => "INFO",
            Level::Warning => "WARNING",
            Level::Error => "ERROR",
        }
    }
}

fn parse_level(text: &str) -> Option<Level> {
    match text.trim().to_uppercase().as_str() {
        "DEBUG" | "10" => Some(Level::Debug),
        "INFO" | "20" => Some(Level::Info),
        "WARNING" | "WARN" | "30" => Some(Level::Warning),
        "ERROR" | "40" => Some(Level::Error),
        "CRITICAL" | "FATAL" | "50" => Some(Level::Error),
        _ => None,
    }
}

static LEVEL: OnceLock<Level> = OnceLock::new();
static FILE: OnceLock<PathBuf> = OnceLock::new();

pub fn setup(level: Option<&str>) -> bool {
    let _ = FILE.set(paths::log_path());
    let chosen = level
        .and_then(parse_level)
        .or_else(|| std::env::var(ENV_LEVEL).ok().and_then(|v| parse_level(&v)))
        .unwrap_or(Level::Info);
    LEVEL.set(chosen).is_ok()
}

fn threshold() -> Level {
    *LEVEL.get_or_init(|| {
        std::env::var(ENV_LEVEL)
            .ok()
            .and_then(|v| parse_level(&v))
            .unwrap_or(Level::Info)
    })
}

pub fn install_panic_hook() {
    std::panic::set_hook(Box::new(|info| {
        let text = match info.payload().downcast_ref::<&str>() {
            Some(message) => (*message).to_string(),
            None => match info.payload().downcast_ref::<String>() {
                Some(message) => message.clone(),
                None => "未知 panic".to_string(),
            },
        };
        let place = info
            .location()
            .map(|at| format!("{}:{}:{}", at.file(), at.line(), at.column()))
            .unwrap_or_default();
        write(Level::Error, SHELL, &format!("程序异常退出：{text}（{place}）"));
    }));
}

fn backup_path(path: &Path, index: usize) -> PathBuf {
    let mut name = path.as_os_str().to_string_lossy().to_string();
    name.push_str(&format!(".{index}"));
    PathBuf::from(name)
}

fn rotate(path: &Path) {
    for index in (1..BACKUPS).rev() {
        let from = backup_path(path, index);
        let to = backup_path(path, index + 1);
        if !from.exists() {
            continue;
        }
        if to.exists() {
            let _ = fs::remove_file(&to);
        }
        let _ = fs::rename(&from, &to);
    }
    let first = backup_path(path, 1);
    if first.exists() {
        let _ = fs::remove_file(&first);
    }
    let _ = fs::rename(path, &first);
}

fn append(line_text: &str) -> bool {
    let _guard = WRITE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let Some(path) = FILE.get() else {
        return false;
    };
    if let Some(directory) = path.parent() {
        if fs::create_dir_all(directory).is_err() {
            return false;
        }
    }
    let pending = line_text.as_bytes().len() as u64;
    let current = fs::metadata(path).map(|meta| meta.len()).unwrap_or(0);
    if current > 0 && current + pending >= MAX_BYTES {
        rotate(path);
    }
    match OpenOptions::new().create(true).append(true).open(path) {
        Ok(mut file) => file.write_all(line_text.as_bytes()).is_ok() && file.flush().is_ok(),
        Err(_) => false,
    }
}

pub fn write(level: Level, target: &str, message: &str) {
    if level < threshold() {
        return;
    }
    let now = crate::util::local_now();
    let line = format!(
        "{} [{}] {}: {}\n",
        crate::util::local_stamp(&now, ' '),
        level.label(),
        target,
        message
    );
    let _ = append(&line);
}

pub fn debug(target: &str, message: &str) {
    write(Level::Debug, target, message);
}

pub fn info(target: &str, message: &str) {
    write(Level::Info, target, message);
}

pub fn warning(target: &str, message: &str) {
    write(Level::Warning, target, message);
}

pub fn error(target: &str, message: &str) {
    write(Level::Error, target, message);
}
