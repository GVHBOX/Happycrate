use std::path::{Path, PathBuf};
use std::sync::OnceLock;

pub const APP_NAME: &str = "happycrate";
pub const DATA_DIRNAME: &str = "data";
pub const LOGS_DIRNAME: &str = "logs";

pub const ENV_DATA_DIR: &str = "HAPPYCRATE_DATA_DIR";
pub const ENV_LOG_DIR: &str = "HAPPYCRATE_LOG_DIR";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Env,
    Portable,
    Fallback,
}

impl Mode {
    pub fn as_str(self) -> &'static str {
        match self {
            Mode::Env => "env",
            Mode::Portable => "portable",
            Mode::Fallback => "fallback",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Mode::Env => "环境变量指定",
            Mode::Portable => "便携模式",
            Mode::Fallback => "回退模式",
        }
    }
}

pub fn program_dir() -> PathBuf {
    if cfg!(debug_assertions) {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
    } else {
        std::env::current_exe()
            .ok()
            .and_then(|exe| exe.parent().map(Path::to_path_buf))
            .unwrap_or_else(|| PathBuf::from("."))
    }
}

pub fn appdata_dir() -> Option<PathBuf> {
    let base = std::env::var_os("APPDATA")?;
    let path = PathBuf::from(base);
    if !path.is_dir() {
        return None;
    }
    Some(path.join(APP_NAME))
}

fn missing_ancestors(target: &Path) -> Vec<PathBuf> {
    let mut made = Vec::new();
    let mut current = target.to_path_buf();
    while !current.exists() {
        made.push(current.clone());
        let Some(parent) = current.parent().map(Path::to_path_buf) else {
            break;
        };
        if parent == current {
            break;
        }
        current = parent;
    }
    made
}

pub fn is_writable(directory: &Path) -> bool {
    let made = missing_ancestors(directory);
    if std::fs::create_dir_all(directory).is_err() {
        return false;
    }
    let probe = directory.join(".happycrate-wtest");
    let ok = std::fs::write(&probe, b"").is_ok();
    let _ = std::fs::remove_file(&probe);
    for path in made {
        let _ = std::fs::remove_dir(&path);
    }
    ok
}

pub fn choose(
    env: Option<&Path>,
    portable: &Path,
    portable_writable: bool,
    appdata: Option<&Path>,
) -> (PathBuf, Mode) {
    if let Some(directory) = env {
        return (directory.to_path_buf(), Mode::Env);
    }
    if portable_writable {
        return (portable.to_path_buf(), Mode::Portable);
    }
    if let Some(base) = appdata {
        return (base.join(DATA_DIRNAME), Mode::Fallback);
    }
    (portable.to_path_buf(), Mode::Fallback)
}

fn env_dir() -> Option<PathBuf> {
    let raw = std::env::var_os(ENV_DATA_DIR)?;
    if raw.is_empty() {
        return None;
    }
    Some(PathBuf::from(raw))
}

pub fn resolve() -> (PathBuf, Mode) {
    let portable = program_dir().join(DATA_DIRNAME);
    let writable = is_writable(&portable);
    choose(
        env_dir().as_deref(),
        &portable,
        writable,
        appdata_dir().as_deref(),
    )
}

static CACHE: OnceLock<(PathBuf, Mode)> = OnceLock::new();

fn cached() -> &'static (PathBuf, Mode) {
    CACHE.get_or_init(resolve)
}

pub fn data_dir() -> PathBuf {
    cached().0.clone()
}

pub fn data_mode() -> Mode {
    cached().1
}

pub fn describe() -> (PathBuf, Mode, String) {
    let mode = data_mode();
    (data_dir(), mode, mode.label().to_string())
}

pub fn data_file(name: &str) -> PathBuf {
    data_dir().join(name)
}

pub fn sources_path() -> PathBuf {
    data_file("sources.json")
}

pub fn settings_path() -> PathBuf {
    data_file("settings.json")
}

pub fn health_path() -> PathBuf {
    data_file("health.json")
}

pub fn logs_dir() -> PathBuf {
    match std::env::var_os(ENV_LOG_DIR) {
        Some(value) if !value.is_empty() => PathBuf::from(value),
        _ => data_dir().join(LOGS_DIRNAME),
    }
}

pub fn log_path() -> PathBuf {
    logs_dir().join("happycrate.log")
}

pub fn ensure_dirs() -> std::io::Result<PathBuf> {
    let directory = data_dir();
    std::fs::create_dir_all(&directory)?;
    std::fs::create_dir_all(logs_dir())?;
    Ok(directory)
}
