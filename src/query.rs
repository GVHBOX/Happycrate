use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Mutex;

use serde_json::{Map, Value};
use unicode_normalization::UnicodeNormalization;

use crate::paths;
use crate::util::{is_nd_digit, is_py_space};

pub const FILENAME: &str = "query_roles.json";

const BUILTIN_WORDS: [(&str, &[&str]); 7] = [
    (
        "QUALITY",
        &[
            "2160p", "1440p", "1080p", "1080i", "720p", "480p", "4k", "uhd", "8k", "bluray",
            "blu-ray", "bdrip", "brrip", "web-dl", "webdl", "webrip", "hdtv", "hdrip", "dvdrip",
            "remux", "bdmv", "hdr", "sdr", "10bit",
        ],
    ),
    (
        "CODEC",
        &[
            "x264", "x265", "h264", "h265", "h.264", "h.265", "hevc", "av1", "xvid", "vc1",
            "vc-1", "mpeg2",
        ],
    ),
    (
        "AUDIO",
        &[
            "atmos", "truehd", "dts", "ddp", "aac", "flac", "dolby", "5.1", "7.1",
        ],
    ),
    (
        "LANG",
        &[
            "中字", "中文字幕", "中英", "简中", "简体", "繁中", "繁體", "粤语", "粵語",
            "广东话", "廣東話", "双语", "雙語", "国语", "國語", "普通话", "chs", "cht", "gb",
            "big5",
        ],
    ),
    (
        "TYPE",
        &[
            "电影", "影片", "movie", "film", "游戏", "遊戲", "game", "单机", "單機", "动漫",
            "動漫", "动画", "動畫", "anime", "剧集", "劇集", "电视剧", "電視劇", "音乐", "音樂",
            "软件", "軟體", "电子书",
        ],
    ),
    (
        "GENRE",
        &[
            "射击", "射擊", "第三人称", "第三人稱", "第一人称", "第一人稱", "开放世界",
            "開放世界", "像素", "沙盒", "策略", "策略", "动作", "動作", "冒险", "冒險",
            "角色扮演", "恐怖", "喜剧", "喜劇", "科幻", "爱情", "愛情", "悬疑", "懸疑", "3d",
            "2d", "vr", "回合制", "即时", "即時",
        ],
    ),
    (
        "MISC",
        &[
            "合集", "全集", "完结", "完結", "未删减", "未刪減", "加长版", "加長版", "珍藏版",
            "修复", "修復", "batch", "pack", "complete", "proper", "repack",
        ],
    ),
];

const BUILTIN_VARIANTS: [(&str, &[&str]); 30] = [
    ("4k", &["2160p", "uhd", "2160", "4kuhd"]),
    ("2160p", &["4k", "uhd", "2160"]),
    ("1440p", &["2k", "qhd"]),
    ("1080p", &["fhd", "fullhd", "1920x1080"]),
    ("720p", &["hd", "1280x720"]),
    ("bluray", &["blu-ray", "bd", "bdrip", "brrip"]),
    ("blu-ray", &["bluray", "bd", "bdrip", "brrip"]),
    ("web-dl", &["webdl", "webrip", "web dl"]),
    ("webdl", &["web-dl", "webrip"]),
    ("webrip", &["web-dl", "webdl"]),
    ("remux", &["bdmv"]),
    ("x265", &["hevc", "h265", "h.265"]),
    ("x264", &["h264", "h.264", "avc"]),
    ("hevc", &["x265", "h265", "h.265"]),
    (
        "中字",
        &["中文字幕", "简中", "简体中文", "chs", "gb", "中文", "国语", "普通话"],
    ),
    ("粤语", &["粵語", "广东话", "廣東話", "cantonese"]),
    ("粵語", &["粤语", "广东话", "廣東話", "cantonese"]),
    ("双语", &["雙語", "中英", "bilingual"]),
    ("电影", &["影片", "movie", "film"]),
    ("影片", &["电影", "movie", "film"]),
    ("movie", &["电影", "影片", "film"]),
    ("游戏", &["遊戲", "game", "单机"]),
    ("遊戲", &["游戏", "game", "单机"]),
    ("game", &["游戏", "遊戲"]),
    ("动漫", &["動漫", "动画", "動畫", "anime"]),
    ("动画", &["動漫", "动漫", "動畫", "anime"]),
    ("第三人称", &["第三人稱", "third person", "third-person", "tps", "3rd person"]),
    ("第三人稱", &["第三人称", "third person", "third-person", "tps"]),
    ("射击", &["射擊", "shooter", "fps", "tps"]),
    ("开放世界", &["開放世界", "open world", "openworld"]),
];

pub struct Roles {
    pub words: Vec<(String, Vec<String>)>,
    pub variants: BTreeMap<String, Vec<String>>,
}

pub fn builtin_roles() -> Roles {
    Roles {
        words: BUILTIN_WORDS
            .iter()
            .map(|(role, words)| {
                (role.to_string(), words.iter().map(|w| w.to_string()).collect())
            })
            .collect(),
        variants: BUILTIN_VARIANTS
            .iter()
            .map(|(key, forms)| {
                (
                    key.to_string(),
                    forms.iter().map(|f| f.to_string()).collect(),
                )
            })
            .collect(),
    }
}

fn clean_list(items: &Value) -> Option<Vec<String>> {
    let list = items.as_array()?;
    if list.is_empty() {
        return None;
    }
    let cleaned: Vec<String> = list
        .iter()
        .map(|v| crate::config::py_str(v).trim().to_lowercase())
        .filter(|s| !s.is_empty())
        .collect();
    if cleaned.is_empty() {
        None
    } else {
        Some(cleaned)
    }
}

pub fn load_roles(path: &Path) -> Roles {
    let mut roles = builtin_roles();
    let Ok(text) = std::fs::read_to_string(path) else {
        return roles;
    };
    let Ok(raw) = serde_json::from_str::<Value>(&text) else {
        return roles;
    };
    if let Some(words) = raw.get("words").and_then(Value::as_object) {
        for (role, items) in words {
            if let Some(cleaned) = clean_list(items) {
                match roles.words.iter_mut().find(|(name, _)| name == role) {
                    Some(entry) => entry.1 = cleaned,
                    None => roles.words.push((role.clone(), cleaned)),
                }
            }
        }
    }
    if let Some(variants) = raw.get("variants").and_then(Value::as_object) {
        for (key, forms) in variants {
            if let Some(cleaned) = clean_list(forms) {
                roles
                    .variants
                    .insert(key.trim().to_lowercase(), cleaned);
            }
        }
    }
    roles
}

static ROLES: Mutex<Option<std::sync::Arc<Roles>>> = Mutex::new(None);

pub fn reload() {
    *ROLES.lock().unwrap() = None;
}

pub fn roles() -> std::sync::Arc<Roles> {
    let mut guard = ROLES.lock().unwrap();
    if let Some(found) = guard.as_ref() {
        return found.clone();
    }
    let loaded = std::sync::Arc::new(load_roles(&paths::data_dir().join(FILENAME)));
    *guard = Some(loaded.clone());
    loaded
}

fn is_ascii_printable(text: &str) -> bool {
    !text.is_empty()
        && text
            .chars()
            .all(|c| ('\u{20}'..='\u{7f}').contains(&c))
}

pub fn normalize(text: &str) -> String {
    let nfkc: String = text.nfkc().collect();
    let lowered = nfkc.to_lowercase();
    let mut separated = String::with_capacity(lowered.len());
    for c in lowered.chars() {
        if matches!(c, '_' | '+' | ',' | '/' | '|') {
            separated.push(' ');
        } else {
            separated.push(c);
        }
    }
    let mut collapsed = String::with_capacity(separated.len());
    let mut pending = false;
    for c in separated.chars() {
        if is_py_space(c) {
            pending = true;
            continue;
        }
        if pending && !collapsed.is_empty() {
            collapsed.push(' ');
        }
        pending = false;
        collapsed.push(c);
    }
    collapsed
}

fn uniq(values: &[String]) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for value in values {
        let text = value.trim().to_string();
        if !text.is_empty() && !out.contains(&text) {
            out.push(text);
        }
    }
    out
}

pub fn contains(token: &str, word: &str) -> bool {
    if word.is_empty() {
        return false;
    }
    if !is_ascii_printable(word) {
        return token.contains(word);
    }
    let hay = token.as_bytes();
    let needle = word.as_bytes();
    if needle.len() > hay.len() {
        return false;
    }
    for start in 0..=hay.len() - needle.len() {
        if &hay[start..start + needle.len()] != needle {
            continue;
        }
        let before_ok = start == 0 || !hay[start - 1].is_ascii_alphanumeric();
        let after = start + needle.len();
        let after_ok = after >= hay.len() || !hay[after].is_ascii_alphanumeric();
        if before_ok && after_ok {
            return true;
        }
    }
    false
}

pub fn season_forms(s: i64, e: i64) -> Vec<String> {
    let mut forms: Vec<String> = Vec::new();
    if s != 0 && e != 0 {
        forms.push(format!("s{s}e{e}"));
        forms.push(format!("s{s:02}e{e:02}"));
        forms.push(format!("s{s:02} e{e:02}"));
        forms.push(format!("e{e}"));
        forms.push(format!("ep{e}"));
    } else if s != 0 {
        forms.push(format!("s{s}"));
        forms.push(format!("s{s:02}"));
        forms.push(format!("season {s}"));
        forms.push(format!("第{s}季"));
    } else if e != 0 {
        forms.push(format!("第{e}集"));
        forms.push(format!("第{e}话"));
        forms.push(format!("第{e}話"));
        forms.push(format!("e{e}"));
        forms.push(format!("e{e:02}"));
        forms.push(format!("ep{e}"));
    }
    uniq(&forms)
}

fn all_digits_from(text: &str, from: usize, max: usize) -> Option<(i64, usize)> {
    let chars: Vec<char> = text.chars().collect();
    if from >= chars.len() {
        return None;
    }
    let mut count = 0usize;
    while from + count < chars.len()
        && is_nd_digit(chars[from + count])
        && count < max
    {
        count += 1;
    }
    if count == 0 {
        return None;
    }
    let digits: String = chars[from..from + count].iter().collect::<String>();
    digits.parse::<i64>().ok().map(|value| (value, count))
}

pub fn season_of(token: &str) -> Option<(i64, i64)> {
    let chars: Vec<char> = token.chars().collect();
    let lower: Vec<char> = token.to_lowercase().chars().collect();

    let starts_with = |pattern: &[char]| -> bool {
        lower.len() >= pattern.len() && lower[..pattern.len()] == *pattern
    };

    if starts_with(&['s']) {
        if let Some((s, used)) = all_digits_from(token, 1, 2) {
            let after = 1 + used;
            if after < chars.len() && lower[after] == 'e' {
                if let Some((e, used2)) = all_digits_from(token, after + 1, 3) {
                    if after + 1 + used2 == chars.len() {
                        return Some((s, e));
                    }
                }
            } else if after == chars.len() {
                return Some((s, 0));
            }
        }
    }

    if chars.first() == Some(&'第') {
        if let Some((number, used)) = all_digits_from(token, 1, usize::MAX) {
            let after = 1 + used;
            if after + 1 == chars.len() {
                match chars[after] {
                    '集' | '话' | '話' => return Some((0, number)),
                    '季' => return Some((number, 0)),
                    _ => {}
                }
            }
        }
    }

    if starts_with(&['e']) {
        let mut index = 1usize;
        if index < lower.len() && lower[index] == 'p' {
            index += 1;
        }
        if let Some((number, used)) = all_digits_from(token, index, 3) {
            if index + used == chars.len() {
                return Some((0, number));
            }
        }
    }

    let season_word: Vec<char> = "season".chars().collect();
    if starts_with(&season_word) {
        if let Some((number, used)) = all_digits_from(token, 6, 2) {
            if 6 + used == chars.len() {
                return Some((number, 0));
            }
        }
    }

    None
}

fn year_in(token: &str) -> Option<String> {
    let chars: Vec<char> = token.chars().collect();
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
        return Some(chars[i..i + 4].iter().collect());
    }
    None
}

pub fn parse_with(query: &str, table: &Roles) -> Value {
    let text = normalize(query);

    let mut flat: Vec<(String, String)> = Vec::new();
    for (role, words) in &table.words {
        for word in words {
            flat.push((word.clone(), role.clone()));
        }
    }

    let mut subject: Vec<Value> = Vec::new();
    let mut mods: Vec<Value> = Vec::new();
    let mut soft: Vec<Value> = Vec::new();

    let tokens: Vec<String> = text
        .split(' ')
        .filter(|t| !t.is_empty())
        .map(str::to_string)
        .collect();

    for token in &tokens {
        if let Some((s, e)) = season_of(token) {
            let mut entry = Map::new();
            entry.insert("role".to_string(), Value::from("SEASON"));
            entry.insert("text".to_string(), Value::from(token.clone()));
            entry.insert(
                "forms".to_string(),
                Value::Array(season_forms(s, e).into_iter().map(Value::from).collect()),
            );
            entry.insert("s".to_string(), Value::from(s));
            entry.insert("e".to_string(), Value::from(e));
            mods.push(Value::Object(entry));
            continue;
        }

        let token_chars = token.chars().count();
        if let Some(found) = year_in(token) {
            if token_chars <= 4 {
                let mut entry = Map::new();
                entry.insert("role".to_string(), Value::from("YEAR"));
                entry.insert("text".to_string(), Value::from(token.clone()));
                entry.insert(
                    "forms".to_string(),
                    Value::Array(vec![Value::from(found)]),
                );
                mods.push(Value::Object(entry));
                continue;
            }
        }

        let hits: Vec<String> = flat
            .iter()
            .filter(|(word, _)| contains(token, word))
            .map(|(word, _)| word.clone())
            .collect();
        if hits.is_empty() {
            subject.push(Value::from(token.clone()));
            continue;
        }

        let mut role = String::new();
        for (word, name) in &flat {
            if hits.contains(word) {
                role = name.clone();
                break;
            }
        }

        let mut forms: Vec<String> = vec![token.clone()];
        forms.extend(hits.iter().cloned());
        for word in &hits {
            if let Some(extra) = table.variants.get(word) {
                forms.extend(extra.iter().cloned());
            }
        }
        if let Some(extra) = table.variants.get(token) {
            forms.extend(extra.iter().cloned());
        }

        let mut entry = Map::new();
        entry.insert("text".to_string(), Value::from(token.clone()));
        entry.insert(
            "forms".to_string(),
            Value::Array(uniq(&forms).into_iter().map(Value::from).collect()),
        );
        if role == "QUALITY" || role == "CODEC" {
            entry.insert("role".to_string(), Value::from(role));
            mods.push(Value::Object(entry));
        } else {
            entry.insert("kind".to_string(), Value::from(role));
            soft.push(Value::Object(entry));
        }
    }

    let mut out = Map::new();
    out.insert("text".to_string(), Value::from(text));
    out.insert(
        "tokens".to_string(),
        Value::Array(tokens.into_iter().map(Value::from).collect()),
    );
    out.insert("subject".to_string(), Value::Array(subject));
    out.insert("mods".to_string(), Value::Array(mods));
    out.insert("soft".to_string(), Value::Array(soft));
    Value::Object(out)
}

pub fn parse(query: &str) -> Value {
    parse_with(query, &roles())
}

pub fn needles(parsed: &Value) -> Vec<String> {
    let Some(map) = parsed.as_object() else {
        return Vec::new();
    };
    let mut groups: Vec<Vec<String>> = Vec::new();
    groups.push(string_list(map.get("subject")));
    if let Some(Value::Array(list)) = map.get("soft") {
        for item in list {
            if let Some(entry) = item.as_object() {
                groups.push(string_list(entry.get("forms")));
            }
        }
    }
    let mut out: Vec<String> = Vec::new();
    for group in groups {
        for value in group {
            let text = value.trim().to_lowercase();
            if !text.is_empty() && !out.contains(&text) {
                out.push(text);
            }
        }
    }
    out
}

fn string_list(value: Option<&Value>) -> Vec<String> {
    match value {
        Some(Value::Array(list)) => list.iter().map(crate::config::py_str).collect(),
        _ => Vec::new(),
    }
}
