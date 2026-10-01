use std::collections::BTreeMap;
use std::process::Command;
use std::sync::Mutex;
use std::time::Duration;

pub const MAGNET_CAP: usize = 200;

pub const EXE_CANDIDATES: [&str; 3] = [
    r"C:\Program Files (x86)\Thunder Network\Thunder\program\thunder.exe",
    r"C:\Program Files\Thunder Network\Thunder\program\thunder.exe",
    r"C:\Program Files (x86)\Thunder Network\Thunder\Thunder.exe",
];

pub const PROTOCOL_KEYS: [&str; 2] = [
    r"magnet\shell\open\command",
    r"thunder\shell\open\command",
];

pub const PROTOCOL_FLAG: &str = "-StartType:magnet";

const GAP_WARMUP: f64 = 0.2;
const GAP_BATCH: f64 = 0.05;
const GAP_MIN: f64 = 0.005;
const GAP_BUDGET: f64 = 2.0;
const WARMUP_TASKS: usize = 3;

pub struct DeliveryResult {
    pub added: usize,
    pub total: usize,
    pub errors: Vec<String>,
    pub method: String,
    pub ok: bool,
}

impl DeliveryResult {
    pub fn new(
        added: usize,
        total: usize,
        errors: Vec<String>,
        method: &str,
        ok: Option<bool>,
    ) -> Self {
        DeliveryResult {
            added,
            total,
            errors,
            method: method.to_string(),
            ok: ok.unwrap_or(added > 0),
        }
    }

    pub fn message(&self) -> String {
        if self.total == 0 {
            return "没有可提交的磁力链接".to_string();
        }
        if self.ok && self.added == self.total {
            return format!("已提交 {} 个任务", self.added);
        }
        if self.ok {
            return format!("已提交 {}/{} 个任务", self.added, self.total);
        }
        let detail = match self.errors.first() {
            Some(first) => format!("：{first}"),
            None => String::new(),
        };
        format!("提交失败（0/{}）{detail}", self.total)
    }
}

pub fn plan_gaps(count: usize, timeout: i64) -> Vec<f64> {
    if count <= 1 {
        return Vec::new();
    }
    let budget = 0.0f64.max(GAP_BUDGET.min(timeout.max(0) as f64));
    if budget <= 0.0 {
        return Vec::new();
    }
    let left = count - 1;
    let warm = WARMUP_TASKS.min(left);
    let ideal = warm as f64 * GAP_WARMUP + (left - warm) as f64 * GAP_BATCH;
    if ideal <= budget {
        let mut gaps = vec![GAP_WARMUP; warm];
        gaps.extend(std::iter::repeat(GAP_BATCH).take(left - warm));
        return gaps;
    }
    let share = budget / left as f64;
    vec![GAP_MIN.max(share); left]
}

pub fn clean_magnets(magnets: &[String]) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for raw in magnets {
        if raw.is_empty() {
            continue;
        }
        let text = raw.trim().to_string();
        if !text.to_lowercase().starts_with("magnet:") {
            continue;
        }
        if out.contains(&text) {
            continue;
        }
        out.push(text);
    }
    out
}

fn reg_default(key: &str) -> Option<String> {
    let candidates: Vec<String> = match std::env::var("SystemRoot") {
        Ok(root) => vec![format!(r"{root}\System32\reg.exe"), "reg.exe".to_string()],
        Err(_) => vec!["reg.exe".to_string()],
    };
    for exe in candidates {
        let Ok(output) = Command::new(&exe)
            .args(["query", &format!("HKCR\\{key}"), "/ve"])
            .output()
        else {
            continue;
        };
        if !output.status.success() {
            continue;
        }
        let text = String::from_utf8_lossy(&output.stdout);
        for line in text.lines() {
            let fields: Vec<&str> = line.split_whitespace().collect();
            if fields.len() < 3 {
                continue;
            }
            if !fields[0].contains("(默认)") && fields[0] != "(Default)" {
                continue;
            }
            let at = line.find(fields[2]).unwrap_or(0);
            return Some(line[at..].trim().to_string());
        }
    }
    None
}

fn quoted_exe(command: &str) -> Option<String> {
    let mut rest = command;
    while let Some(start) = rest.find('"') {
        let after = &rest[start + 1..];
        let Some(end) = after.find('"') else {
            return None;
        };
        let inner = &after[..end];
        if !inner.is_empty() && inner.ends_with(".exe") {
            return Some(inner.to_string());
        }
        rest = &after[end + 1..];
    }
    None
}

fn bare_exe(command: &str) -> Option<String> {
    let bytes: Vec<char> = command.chars().collect();
    for start in 0..bytes.len() {
        if start + 2 >= bytes.len() {
            break;
        }
        if !bytes[start].is_ascii_alphabetic() || bytes[start + 1] != ':' || bytes[start + 2] != '\\'
        {
            continue;
        }
        let mut end = start;
        while end < bytes.len() && !bytes[end].is_whitespace() {
            end += 1;
        }
        let run: String = bytes[start..end].iter().collect();
        if run.ends_with(".exe") {
            return Some(run);
        }
    }
    None
}

pub fn find_exe() -> Option<String> {
    for candidate in EXE_CANDIDATES {
        if std::path::Path::new(candidate).is_file() {
            return Some(candidate.to_string());
        }
    }
    if std::env::consts::OS != "windows" {
        return None;
    }
    for key in PROTOCOL_KEYS {
        let Some(command) = reg_default(key) else {
            continue;
        };
        let found = quoted_exe(&command).or_else(|| bare_exe(&command));
        if let Some(path) = found {
            if std::path::Path::new(&path).is_file() {
                let name = path
                    .rsplit(['\\', '/'])
                    .next()
                    .unwrap_or("")
                    .to_lowercase();
                if name.contains("thunder") {
                    return Some(path);
                }
            }
        }
    }
    None
}

pub struct DownloaderInfo {
    pub key: &'static str,
    pub label: &'static str,
}

pub fn all_downloaders() -> Vec<DownloaderInfo> {
    vec![DownloaderInfo {
        key: "thunder",
        label: "迅雷",
    }]
}

fn available_of(key: &str) -> bool {
    match key {
        "thunder" => find_exe().is_some(),
        _ => false,
    }
}

static AVAILABILITY: Mutex<Option<BTreeMap<String, bool>>> = Mutex::new(None);

fn cached_available(key: &str, refresh: bool) -> bool {
    let mut guard = AVAILABILITY.lock().unwrap_or_else(|e| e.into_inner());
    if refresh {
        guard.take();
    }
    let map = guard.get_or_insert_with(BTreeMap::new);
    if let Some(found) = map.get(key) {
        return *found;
    }
    let value = available_of(key);
    map.insert(key.to_string(), value);
    value
}

pub fn available_downloaders(refresh: bool) -> Vec<DownloaderInfo> {
    all_downloaders()
        .into_iter()
        .filter(|info| cached_available(info.key, refresh))
        .collect()
}

pub fn pick_default(preferred: &str, refresh: bool) -> Option<DownloaderInfo> {
    let all = all_downloaders();
    if !preferred.is_empty() {
        if let Some(found) = all.iter().find(|info| info.key == preferred) {
            if cached_available(found.key, refresh) {
                return Some(DownloaderInfo {
                    key: found.key,
                    label: found.label,
                });
            }
        }
    }
    available_downloaders(refresh).into_iter().next()
}

pub fn protocol_deliver(magnets: &[String], timeout: i64) -> DeliveryResult {
    let Some(exe) = find_exe() else {
        return DeliveryResult::new(0, magnets.len(), vec!["未找到迅雷主程序".to_string()], "protocol", None);
    };
    let mut added = 0usize;
    let mut errors: Vec<String> = Vec::new();
    let gaps = plan_gaps(magnets.len(), timeout);
    for (index, magnet) in magnets.iter().enumerate() {
        match Command::new(&exe)
            .arg(magnet)
            .arg(PROTOCOL_FLAG)
            .spawn()
        {
            Ok(_) => {
                added += 1;
                if let Some(gap) = gaps.get(index) {
                    std::thread::sleep(Duration::from_secs_f64(*gap));
                }
            }
            Err(error) => errors.push(format!("{error}")),
        }
    }
    if added > 0 {
        return DeliveryResult::new(added, magnets.len(), errors, "protocol", None);
    }
    if errors.is_empty() {
        errors.push("迅雷主程序启动失败".to_string());
    }
    DeliveryResult::new(0, magnets.len(), errors, "protocol", None)
}

pub fn add(magnets: &[String], timeout: i64) -> DeliveryResult {
    let items = clean_magnets(magnets);
    if items.is_empty() {
        return DeliveryResult::new(0, 0, vec!["没有有效的磁力链接".to_string()], "", None);
    }

    if !cached_available("thunder", false) {
        return DeliveryResult::new(
            0,
            items.len(),
            vec!["迅雷 未找到或不可用".to_string()],
            "",
            None,
        );
    }

    let result = protocol_deliver(&items, timeout);
    if result.ok {
        return result;
    }
    let reason = result
        .errors
        .first()
        .cloned()
        .unwrap_or_else(|| "未知原因".to_string());
    DeliveryResult::new(0, items.len(), vec![format!("协议拉起：{reason}")], "", None)
}
