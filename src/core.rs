use serde_json::{Map, Value};

use crate::config::py_str;

use crate::util::{is_nd_digit, is_py_space};

const MAX_ALT_TITLES: usize = 8;

const MARKERS_P1: [&str; 9] = [
    "2160p", "1440p", "1080p", "1080i", "720p", "480p", "4k", "uhd", "8k",
];
const MARKERS_P2: [&str; 13] = [
    "x264", "x265", "h264", "h.264", "h265", "h.265", "hevc", "av1", "vc1", "vc-1", "xvid",
    "mpeg2", "mpeg-2",
];
const MARKERS_P3: [&str; 12] = [
    "blu-ray", "bluray", "bdrip", "brrip", "web-dl", "webdl", "webrip", "hdtv", "hdrip",
    "dvdrip", "remux", "bdmv",
];
const MARKERS_P6: [&str; 9] = [
    "atmos", "truehd", "dts", "ddp", "aac", "flac", "5.1", "7.1", "dolby",
];

fn find_ci(text: &[char], needle: &[char], from: usize) -> Option<usize> {
    if needle.is_empty() || text.len() < needle.len() {
        return None;
    }
    for i in from..=text.len() - needle.len() {
        if text[i..i + needle.len()]
            .iter()
            .zip(needle)
            .all(|(a, b)| a.eq_ignore_ascii_case(b))
        {
            return Some(i);
        }
    }
    None
}

fn has_marker(chars: &[char], markers: &[&str]) -> bool {
    markers.iter().any(|m| {
        let needle: Vec<char> = m.chars().collect();
        find_ci(chars, &needle, 0).is_some()
    })
}

fn digit_count(chars: &[char], from: usize, max: usize) -> usize {
    let mut i = from;
    while i < chars.len() && is_nd_digit(chars[i]) && i - from < max {
        i += 1;
    }
    i - from
}

fn has_episode(chars: &[char]) -> bool {
    for i in 0..chars.len() {
        let c = chars[i];
        if (c == 's' || c == 'S') && i + 1 < chars.len() && is_nd_digit(chars[i + 1]) {
            return true;
        }
        if c == '第' {
            let mut j = i + 1;
            while j < chars.len() && is_py_space(chars[j]) {
                j += 1;
            }
            let d = digit_count(chars, j, usize::MAX);
            if d > 0 {
                let mut k = j + d;
                while k < chars.len() && is_py_space(chars[k]) {
                    k += 1;
                }
                if k < chars.len() && matches!(chars[k], '集' | '话' | '季') {
                    return true;
                }
            }
        }
        if (c == 's' || c == 'S') && i + 6 <= chars.len() {
            let needle: Vec<char> = "season".chars().collect();
            if find_ci(chars, &needle, i) == Some(i) {
                let mut j = i + 6;
                while j < chars.len() && is_py_space(chars[j]) {
                    j += 1;
                }
                if digit_count(chars, j, usize::MAX) > 0 {
                    return true;
                }
            }
        }
        if c == 'e' || c == 'E' {
            let mut j = i + 1;
            if j < chars.len() && (chars[j] == 'p' || chars[j] == 'P') {
                j += 1;
            }
            while j < chars.len() && is_py_space(chars[j]) {
                j += 1;
            }
            if digit_count(chars, j, 3) > 0 {
                return true;
            }
        }
    }
    false
}

fn has_year(chars: &[char]) -> bool {
    for i in 0..chars.len() {
        if i + 4 > chars.len() {
            break;
        }
        if i > 0 && is_nd_digit(chars[i - 1]) {
            continue;
        }
        let two: String = chars[i..i + 2].iter().collect();
        if two != "19" && two != "20" {
            continue;
        }
        if !is_nd_digit(chars[i + 2]) || !is_nd_digit(chars[i + 3]) {
            continue;
        }
        if i + 4 < chars.len() && is_nd_digit(chars[i + 4]) {
            continue;
        }
        return true;
    }
    false
}

const SIZE_UNITS: [&str; 6] = ["B", "KB", "MB", "GB", "TB", "PB"];

pub fn format_time_relative(value: &Value, now: &crate::util::LocalNow) -> String {
    if value.is_null() || matches!(value, Value::String(text) if text.is_empty()) {
        return String::new();
    }
    let stamp = match value {
        Value::Number(n) => n.as_f64(),
        Value::Bool(flag) => Some(if *flag { 1.0 } else { 0.0 }),
        Value::String(text) => text.trim().parse::<f64>().ok(),
        _ => None,
    };
    let Some(stamp) = stamp else {
        return String::new();
    };
    if !stamp.is_finite() || stamp <= 0.0 {
        return String::new();
    }

    let now_stamp = (now.naive - now.offset) as f64;
    let seconds = now_stamp - stamp;
    if seconds < 60.0 {
        return "刚刚".to_string();
    }
    if seconds < 3600.0 {
        return format!("{} 分钟前", (seconds / 60.0).floor() as i64);
    }
    if seconds < 21600.0 {
        return format!("{} 小时前", (seconds / 3600.0).floor() as i64);
    }

    let local = stamp as i64 + now.offset;
    let days = crate::util::floor_div(now.naive, 86400) - crate::util::floor_div(local, 86400);
    let day_seconds = local - crate::util::floor_div(local, 86400) * 86400;
    let clock = format!("{:02}:{:02}", day_seconds / 3600, (day_seconds % 3600) / 60);
    if days == 0 {
        return format!("今天 {clock}");
    }
    if days == 1 {
        return format!("昨天 {clock}");
    }
    if days < 7 {
        return format!("{days} 天前");
    }
    let (year, month, day) = crate::util::civil_from_days(crate::util::floor_div(local, 86400));
    format!("{year:04}-{month:02}-{day:02}")
}

pub fn magnet_of(item: &Value) -> String {
    let Some(map) = item.as_object() else {
        return String::new();
    };
    let existing = map.get("magnet").map(py_str).unwrap_or_default();
    if existing.to_lowercase().starts_with("magnet:") {
        return existing;
    }
    let hash = map
        .get("info_hash")
        .map(py_str)
        .unwrap_or_default()
        .trim()
        .to_string();
    if hash.is_empty() {
        return String::new();
    }
    let title = map.get("title").map(py_str).unwrap_or_default();
    crate::util::magnet_for(&hash, &title)
}

pub fn min_len_message(min_len: i64) -> String {
    format!("关键字至少 {min_len} 个字符")
}

pub fn format_size(value: &Value) -> String {
    if value.is_null() || matches!(value, Value::String(text) if text.is_empty()) {
        return String::new();
    }
    let number = match value {
        Value::Number(n) => n.as_f64(),
        Value::Bool(flag) => Some(if *flag { 1.0 } else { 0.0 }),
        Value::String(text) => text.trim().parse::<f64>().ok(),
        _ => None,
    };
    let Some(mut value) = number else {
        return String::new();
    };
    if !value.is_finite() || value <= 0.0 {
        return String::new();
    }
    let mut index = 0usize;
    while value >= 1024.0 && index < SIZE_UNITS.len() - 1 {
        value /= 1024.0;
        index += 1;
    }
    if index == 0 {
        return format!("{value:.0} {}", SIZE_UNITS[index]);
    }
    format!("{value:.1} {}", SIZE_UNITS[index])
}

pub fn structure_score(title: &str) -> i64 {
    let chars: Vec<char> = title.chars().collect();
    let mut score = 0i64;
    if has_marker(&chars, &MARKERS_P1) {
        score += 1;
    }
    if has_marker(&chars, &MARKERS_P2) {
        score += 1;
    }
    if has_marker(&chars, &MARKERS_P3) {
        score += 1;
    }
    if has_episode(&chars) {
        score += 1;
    }
    if has_year(&chars) {
        score += 1;
    }
    if has_marker(&chars, &MARKERS_P6) {
        score += 1;
    }
    score
}

fn as_int(value: &Value) -> Option<i64> {
    match value {
        Value::Null => None,
        Value::Bool(b) => Some(i64::from(*b)),
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64)),
        Value::String(s) => {
            if s.is_empty() {
                return None;
            }
            let trimmed = s.trim();
            if trimmed.is_empty() {
                return None;
            }
            trimmed.parse::<i64>().ok()
        }
        _ => None,
    }
}

fn numeric(values: &[&Value], positive_only: bool) -> Vec<i64> {
    values
        .iter()
        .filter_map(|v| as_int(v))
        .filter(|n| !positive_only || *n > 0)
        .collect()
}

fn merge_peak(values: &[&Value]) -> Value {
    match numeric(values, false).into_iter().max() {
        Some(n) => Value::from(n),
        None => Value::Null,
    }
}

fn merge_size(values: &[&Value]) -> Value {
    Value::from(numeric(values, true).into_iter().max().unwrap_or(0))
}

fn merge_earliest(values: &[&Value]) -> Value {
    Value::from(numeric(values, true).into_iter().min().unwrap_or(0))
}

fn title_text(value: &Value) -> String {
    let text = match value {
        Value::Null => String::new(),
        Value::Bool(b) => {
            if *b {
                "True".to_string()
            } else {
                String::new()
            }
        }
        Value::Number(n) => n.to_string(),
        Value::String(s) => s.clone(),
        _ => String::new(),
    };
    text.trim().to_string()
}

fn merge_titles(titles: &[&Value]) -> Vec<Value> {
    let mut out: Vec<String> = Vec::new();
    for title in titles {
        let text = title_text(title);
        if !text.is_empty() && !out.contains(&text) {
            out.push(text);
        }
    }
    out.truncate(MAX_ALT_TITLES);
    out.into_iter().map(Value::String).collect()
}

fn source_list(item: &Map<String, Value>) -> Vec<Value> {
    let mut out: Vec<String> = Vec::new();
    if let Some(Value::Array(names)) = item.get("sources") {
        for name in names {
            let text = title_text(name);
            if !text.is_empty() {
                out.push(text);
            }
        }
    }
    if let Some(src) = item.get("source") {
        let text = title_text(src);
        if !text.is_empty() && !out.contains(&text) {
            out.push(text);
        }
    }
    out.into_iter().map(Value::String).collect()
}

const HANDLED_KEYS: [&str; 7] = [
    "sources", "altTitles", "seeders", "leechers", "size", "added", "title",
];

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(false),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

fn richness(item: &Map<String, Value>) -> i64 {
    let mut score = 0i64;
    if item.get("info_hash").map(truthy).unwrap_or(false) {
        score += 2;
    }
    if item.get("size").map(truthy).unwrap_or(false) {
        score += 1;
    }
    if item.get("seeders").map(|v| !v.is_null()).unwrap_or(false) {
        score += 1;
    }
    if item.get("added").map(truthy).unwrap_or(false) {
        score += 1;
    }
    score
}

fn title_rank(item: &Map<String, Value>) -> (i64, i64) {
    let title = item
        .get("title")
        .map(title_text)
        .unwrap_or_default();
    (structure_score(&title), richness(item))
}

fn lower_hash(item: &Map<String, Value>) -> String {
    item.get("info_hash")
        .map(title_text)
        .unwrap_or_default()
        .to_lowercase()
}

pub fn dedupe(items: &[Value]) -> Vec<Value> {
    let mut by_hash: Vec<(String, Map<String, Value>)> = Vec::new();
    let mut out: Vec<Value> = Vec::new();

    for item in items {
        let Some(entry) = item.as_object() else {
            out.push(item.clone());
            continue;
        };
        let hash = lower_hash(entry);
        if hash.is_empty() {
            out.push(item.clone());
            continue;
        }

        let position = by_hash.iter().position(|(h, _)| *h == hash);
        let Some(index) = position else {
            let mut merged = entry.clone();
            merged.insert("sources".to_string(), Value::Array(source_list(entry)));
            merged.insert(
                "altTitles".to_string(),
                Value::Array(merge_titles(&[entry.get("title").unwrap_or(&Value::Null)])),
            );
            by_hash.push((hash, merged.clone()));
            out.push(Value::Object(merged));
            continue;
        };

        let mut cur = by_hash[index].1.clone();
        let mut sources: Vec<String> = match cur.get("sources") {
            Some(Value::Array(names)) => names.iter().map(title_text).collect(),
            _ => Vec::new(),
        };
        for name in source_list(entry) {
            let text = title_text(&name);
            if !sources.contains(&text) {
                sources.push(text);
            }
        }
        cur.insert(
            "sources".to_string(),
            Value::Array(sources.into_iter().map(Value::String).collect()),
        );

        let mut titles: Vec<Value> = match cur.get("altTitles") {
            Some(Value::Array(list)) => list.clone(),
            _ => Vec::new(),
        };
        titles.push(cur.get("title").cloned().unwrap_or(Value::Null));
        titles.push(entry.get("title").cloned().unwrap_or(Value::Null));
        if let Some(Value::Array(list)) = entry.get("altTitles") {
            titles.extend(list.iter().cloned());
        }
        let refs: Vec<&Value> = titles.iter().collect();
        cur.insert("altTitles".to_string(), Value::Array(merge_titles(&refs)));

        if title_rank(entry) > title_rank(&cur) {
            cur.insert(
                "title".to_string(),
                entry.get("title").cloned().unwrap_or(Value::Null),
            );
        }

        let null = Value::Null;
        cur.insert(
            "seeders".to_string(),
            merge_peak(&[cur.get("seeders").unwrap_or(&null), entry.get("seeders").unwrap_or(&null)]),
        );
        cur.insert(
            "leechers".to_string(),
            merge_peak(&[cur.get("leechers").unwrap_or(&null), entry.get("leechers").unwrap_or(&null)]),
        );
        cur.insert(
            "size".to_string(),
            merge_size(&[cur.get("size").unwrap_or(&null), entry.get("size").unwrap_or(&null)]),
        );
        cur.insert(
            "added".to_string(),
            merge_earliest(&[cur.get("added").unwrap_or(&null), entry.get("added").unwrap_or(&null)]),
        );

        for (key, value) in entry {
            if HANDLED_KEYS.contains(&key.as_str()) {
                continue;
            }
            if truthy(value) && !cur.get(key).map(truthy).unwrap_or(false) {
                cur.insert(key.clone(), value.clone());
            }
        }

        by_hash[index].1 = cur.clone();
        let slot = out
            .iter()
            .position(|v| {
                v.as_object()
                    .map(|o| lower_hash(o) == hash)
                    .unwrap_or(false)
            })
            .expect("已登记的哈希必在输出中");
        out[slot] = Value::Object(cur);
    }

    out
}
