use serde_json::Value;

use crate::model::Item;

const NAMED: &[(&str, char)] = &[
    ("amp", '&'),
    ("apos", '\''),
    ("atilde", 'ã'),
    ("copy", '©'),
    ("gt", '>'),
    ("lt", '<'),
    ("nbsp", '\u{a0}'),
    ("quot", '"'),
    ("times", '×'),
];

const WIN1252: [char; 32] = [
    '\u{20ac}', '\u{81}', '\u{201a}', '\u{192}', '\u{201e}', '\u{2026}', '\u{2020}', '\u{2021}',
    '\u{2c6}', '\u{2030}', '\u{160}', '\u{2039}', '\u{152}', '\u{8d}', '\u{17d}', '\u{8f}',
    '\u{90}', '\u{2018}', '\u{2019}', '\u{201c}', '\u{201d}', '\u{2022}', '\u{2013}', '\u{2014}',
    '\u{2dc}', '\u{2122}', '\u{161}', '\u{203a}', '\u{153}', '\u{9d}', '\u{17e}', '\u{178}',
];

fn strip_cdata(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(start) = rest.find("<![CDATA[") {
        out.push_str(&rest[..start]);
        let after = &rest[start + 9..];
        match after.find("]]>") {
            Some(end) => {
                out.push_str(&after[..end]);
                rest = &after[end + 3..];
            }
            None => {
                out.push_str(&rest[start..]);
                return out;
            }
        }
    }
    out.push_str(rest);
    out
}

fn charref(body: &str, hex: bool) -> Option<(char, usize)> {
    let digits: String = if hex {
        body.chars().take_while(|c| c.is_ascii_hexdigit()).collect()
    } else {
        body.chars().take_while(|c| c.is_ascii_digit()).collect()
    };
    if digits.is_empty() {
        return None;
    }
    let tail = &body[digits.len()..];
    if !tail.starts_with(';') {
        return None;
    }
    let code = u32::from_str_radix(&digits, if hex { 16 } else { 10 }).ok()?;
    let ch = if (0x80..=0x9f).contains(&code) {
        WIN1252[(code - 0x80) as usize]
    } else {
        char::from_u32(code).unwrap_or('\u{fffd}')
    };
    Some((ch, digits.len() + if hex { 3 } else { 2 }))
}

pub fn html_unescape(text: &str) -> String {
    if !text.contains('&') {
        return text.to_string();
    }
    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut i = 0usize;
    while i < bytes.len() {
        if bytes[i] != b'&' {
            let ch = text[i..].chars().next().unwrap_or('\0');
            out.push(ch);
            i += ch.len_utf8();
            continue;
        }
        let body = &text[i + 1..];
        let resolved = if let Some(rest) = body.strip_prefix("#x").or_else(|| body.strip_prefix("#X"))
        {
            charref(rest, true)
        } else if let Some(rest) = body.strip_prefix('#') {
            charref(rest, false)
        } else {
            let name: String = body
                .chars()
                .take_while(|c| c.is_ascii_alphanumeric())
                .collect();
            if name.is_empty() || !body[name.len()..].starts_with(';') {
                None
            } else {
                NAMED
                    .iter()
                    .find(|(n, _)| *n == name)
                    .map(|(_, c)| (*c, name.len() + 1))
            }
        };
        match resolved {
            Some((ch, consumed)) => {
                out.push(ch);
                i += 1 + consumed;
            }
            None => {
                out.push('&');
                i += 1;
            }
        }
    }
    out
}

pub fn unescape(text: &str) -> String {
    if text.is_empty() {
        return String::new();
    }
    let trimmed = py_trim(text);
    let unwrapped = if trimmed.contains("<![CDATA[") {
        strip_cdata(trimmed)
    } else {
        trimmed.to_string()
    };
    py_trim(&html_unescape(py_trim(&unwrapped))).to_string()
}

pub fn is_nd_digit(c: char) -> bool {
    c.is_ascii_digit() || ('\u{ff10}'..='\u{ff19}').contains(&c)
}

pub fn is_py_space(c: char) -> bool {
    c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')
}

pub fn py_trim(text: &str) -> &str {
    text.trim_matches(is_py_space)
}

pub fn collapse(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut pending = false;
    for c in text.chars() {
        if is_py_space(c) {
            pending = true;
            continue;
        }
        if pending && !out.is_empty() {
            out.push(' ');
        }
        pending = false;
        out.push(c);
    }
    out
}

pub fn clean_title(raw: &str) -> String {
    collapse(&unescape(raw))
}

pub fn text_of(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        _ => String::new(),
    }
}

pub fn to_int(value: &Value) -> Option<i64> {
    match value {
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64)),
        Value::Bool(b) => Some(i64::from(*b)),
        Value::String(s) => {
            if s.is_empty() {
                None
            } else {
                s.trim()
                    .parse::<f64>()
                    .ok()
                    .filter(|f| f.is_finite())
                    .map(|f| f as i64)
            }
        }
        _ => None,
    }
}

fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

fn parse_ymd(s: &str) -> Option<(i64, i64, i64)> {
    let b = s.as_bytes();
    if b.len() < 10 || b[4] != b'-' || b[7] != b'-' {
        return None;
    }
    if !b[0..4].iter().all(u8::is_ascii_digit)
        || !b[5..7].iter().all(u8::is_ascii_digit)
        || !b[8..10].iter().all(u8::is_ascii_digit)
    {
        return None;
    }
    let y = s[0..4].parse::<i64>().ok()?;
    let m = s[5..7].parse::<i64>().ok()?;
    let d = s[8..10].parse::<i64>().ok()?;
    if !(1..=12).contains(&m) || !(1..=31).contains(&d) {
        return None;
    }
    Some((y, m, d))
}

fn tz_offset(rest: &str) -> Option<i64> {
    if rest.starts_with('Z') || rest.starts_with('z') {
        return Some(0);
    }
    let sign = match rest.as_bytes().first() {
        Some(b'+') => 1,
        Some(b'-') => -1,
        _ => return None,
    };
    let digits: String = rest[1..]
        .chars()
        .filter(|c| c.is_ascii_digit())
        .collect();
    if digits.len() < 2 {
        return None;
    }
    let hh = digits[0..2].parse::<i64>().ok()?;
    let mm = if digits.len() >= 4 {
        digits[2..4].parse::<i64>().ok()?
    } else {
        0
    };
    Some(sign * (hh * 3600 + mm * 60))
}

pub fn ts_from_iso(text: &str) -> Option<f64> {
    if text.is_empty() {
        return None;
    }
    let raw = text.trim().replace('Z', "+00:00");
    if let Some(seconds) = parse_iso(&raw) {
        return Some(seconds);
    }
    let (y, m, d) = parse_ymd(text.trim())?;
    Some((days_from_civil(y, m, d) * 86400) as f64)
}

fn parse_iso(raw: &str) -> Option<f64> {
    let b = raw.as_bytes();
    if b.len() < 10 {
        return None;
    }
    let (y, mo, d) = parse_ymd(raw)?;
    let mut seconds = days_from_civil(y, mo, d) * 86400;
    if b.len() == 10 {
        return Some(seconds as f64);
    }
    if b[10] != b'T' && b[10] != b' ' {
        return Some(seconds as f64);
    }
    let time = raw.get(11..)?;
    let tb = time.as_bytes();
    if tb.len() < 5 || tb[2] != b':' {
        return None;
    }
    if !tb[0..2].iter().all(u8::is_ascii_digit) || !tb[3..5].iter().all(u8::is_ascii_digit) {
        return None;
    }
    let hh = time[0..2].parse::<i64>().ok()?;
    let mi = time[3..5].parse::<i64>().ok()?;
    if !(0..=23).contains(&hh) || !(0..=59).contains(&mi) {
        return None;
    }
    seconds += hh * 3600 + mi * 60;
    let mut rest = &time[5..];
    let mut frac = 0f64;
    if let Some(stripped) = rest.strip_prefix(':') {
        let sb = stripped.as_bytes();
        if sb.len() >= 2 && sb[0..2].iter().all(u8::is_ascii_digit) {
            let ss = stripped[0..2].parse::<i64>().ok()?;
            if !(0..=59).contains(&ss) {
                return None;
            }
            seconds += ss;
            rest = &stripped[2..];
        }
    }
    if let Some(stripped) = rest.strip_prefix('.') {
        let digits: String = stripped.chars().take_while(|c| c.is_ascii_digit()).collect();
        if !digits.is_empty() {
            let scale = 10f64.powi(digits.len() as i32);
            frac = digits.parse::<f64>().ok()? / scale;
            rest = &stripped[digits.len()..];
        }
    }
    let tail = rest.trim();
    let offset = if tail.is_empty() { 0 } else { tz_offset(tail)? };
    Some((seconds - offset) as f64 + frac)
}

pub fn quote(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for byte in value.as_bytes() {
        let c = *byte as char;
        if c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | '-' | '~') {
            out.push(c);
        } else {
            out.push_str(&format!("%{byte:02X}"));
        }
    }
    out
}

pub fn magnet_for(info_hash: &str, title: &str) -> String {
    let h = info_hash.trim();
    if h.is_empty() {
        return String::new();
    }
    let mut magnet = format!("magnet:?xt=urn:btih:{h}");
    if !title.is_empty() {
        magnet.push_str("&dn=");
        magnet.push_str(&quote(title));
    }
    magnet
}

pub fn is_hash40(value: &str) -> bool {
    value.len() == 40 && value.bytes().all(|b| b.is_ascii_hexdigit())
}

pub fn make_item(
    title: &str,
    info_hash: &str,
    size: i64,
    seeders: Option<i64>,
    leechers: Option<i64>,
    added: Option<serde_json::Number>,
    source: &str,
) -> Item {
    let clean = clean_title(title);
    let h = unescape(info_hash).trim().to_lowercase();
    Item {
        magnet: if h.is_empty() {
            String::new()
        } else {
            magnet_for(&h, &clean)
        },
        title: clean,
        info_hash: h,
        size,
        seeders,
        leechers,
        added,
        source: source.to_string(),
        files: None,
        fetch: None,
    }
}

pub fn num_from_f64(value: f64) -> Option<serde_json::Number> {
    serde_json::Number::from_f64(value)
}

pub fn num_from_i64(value: i64) -> Option<serde_json::Number> {
    Some(serde_json::Number::from(value))
}

const SIZE_SCAN_LIMIT: usize = 200;
const MAX_PLAUSIBLE_BYTES: f64 = 1152921504606846976.0;

fn size_unit(unit: char) -> f64 {
    match unit {
        'K' => 1024.0,
        'M' => 1048576.0,
        'G' => 1073741824.0,
        'T' => 1099511627776.0,
        'P' => 1125899906842624.0,
        _ => 1.0,
    }
}

fn clamp_size(num: f64, unit: char) -> i64 {
    let scaled = num * size_unit(unit);
    if !(scaled > 0.0 && scaled <= MAX_PLAUSIBLE_BYTES) {
        return 0;
    }
    scaled as i64
}

pub fn find_ci(hay: &[char], needle: &[char], from: usize) -> Option<usize> {
    if needle.is_empty() || hay.len() < needle.len() {
        return None;
    }
    for i in from..=hay.len() - needle.len() {
        if hay[i..i + needle.len()]
            .iter()
            .zip(needle)
            .all(|(a, b)| a.eq_ignore_ascii_case(b))
        {
            return Some(i);
        }
    }
    None
}

pub fn find_tag_end(chars: &[char], from: usize) -> Option<usize> {
    let mut i = from;
    while i < chars.len() {
        if chars[i] == '>' {
            return Some(i);
        }
        i += 1;
    }
    None
}

fn match_size(chars: &[char], start: usize) -> Option<(f64, char, usize)> {
    let n = chars.len();
    let mut i = start;
    let num_start = i;
    if i < n && chars[i] == '-' {
        i += 1;
    }
    let dstart = i;
    while i < n && chars[i].is_ascii_digit() && i - dstart < 12 {
        i += 1;
    }
    if i == dstart {
        return None;
    }
    if i < n && chars[i].is_ascii_digit() {
        return None;
    }
    let mut num_text: String = chars[num_start..i].iter().collect();
    if i < n && chars[i] == '.' {
        let fstart = i + 1;
        let mut j = fstart;
        while j < n && chars[j].is_ascii_digit() && j - fstart < 4 {
            j += 1;
        }
        if j == fstart {
            return None;
        }
        num_text.push('.');
        num_text.extend(chars[fstart..j].iter());
        i = j;
    }
    while i < n && is_py_space(chars[i]) {
        i += 1;
    }
    let unit = if i < n && matches!(chars[i], 'K' | 'M' | 'G' | 'T' | 'P') {
        let c = chars[i];
        i += 1;
        c
    } else {
        '\0'
    };
    if i < n && chars[i] == 'i' {
        i += 1;
    }
    if i < n && (chars[i] == 'B' || chars[i] == 'b') {
        i += 1;
    } else {
        return None;
    }
    if i < n && chars[i].is_ascii_alphanumeric() {
        return None;
    }
    let num = num_text.parse::<f64>().ok()?;
    Some((num, unit, i))
}

pub fn parse_size_text(text: &str) -> i64 {
    let scan: String = py_trim(text).chars().take(SIZE_SCAN_LIMIT).collect();
    if scan.is_empty() {
        return 0;
    }
    let chars: Vec<char> = scan.chars().collect();
    for start in 0..chars.len() {
        if let Some((num, unit, _)) = match_size(&chars, start) {
            if !num.is_finite() || num <= 0.0 {
                return 0;
            }
            return clamp_size(num, unit);
        }
    }
    match scan.parse::<f64>() {
        Ok(v) if v.is_finite() && v > 0.0 => clamp_size(v, '\0'),
        _ => 0,
    }
}

pub fn parse_size(value: &Value) -> i64 {
    match value {
        Value::Null => 0,
        Value::Bool(b) => i64::from(*b),
        Value::Number(n) => n
            .as_i64()
            .or_else(|| n.as_f64().map(|f| f as i64))
            .unwrap_or(0),
        Value::String(s) => {
            if s.is_empty() {
                0
            } else {
                parse_size_text(s)
            }
        }
        _ => 0,
    }
}

pub fn split_items(xml: &str) -> Vec<String> {
    let chars: Vec<char> = xml.chars().collect();
    let open: Vec<char> = "<item".chars().collect();
    let close: Vec<char> = "</item>".chars().collect();
    let mut out = Vec::new();
    let mut pos = 0usize;
    while let Some(s) = find_ci(&chars, &open, pos) {
        let Some(gt) = find_tag_end(&chars, s + open.len()) else {
            break;
        };
        let content_start = gt + 1;
        match find_ci(&chars, &close, content_start) {
            Some(e) => {
                out.push(chars[content_start..e].iter().collect());
                pos = e + close.len();
            }
            None => break,
        }
    }
    out
}

pub fn tag(chunk: &str, name: &str) -> String {
    if name.is_empty() {
        return String::new();
    }
    let chars: Vec<char> = chunk.chars().collect();
    let open: Vec<char> = format!("<{name}").chars().collect();
    let close: Vec<char> = format!("</{name}>").chars().collect();
    let Some(s) = find_ci(&chars, &open, 0) else {
        return String::new();
    };
    let Some(gt) = find_tag_end(&chars, s + open.len()) else {
        return String::new();
    };
    let content_start = gt + 1;
    match find_ci(&chars, &close, content_start) {
        Some(e) => py_trim(&chars[content_start..e].iter().collect::<String>()).to_string(),
        None => String::new(),
    }
}

pub fn tags(chunk: &str, names: &[&str]) -> Vec<String> {
    names.iter().map(|n| tag(chunk, n)).collect()
}

const MONTHS: [&str; 12] = [
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
];
const WEEKDAYS: [&str; 7] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

fn month_num(name: &str) -> Option<i64> {
    let lower = name.to_lowercase();
    MONTHS.iter().position(|m| *m == lower).map(|i| i as i64 + 1)
}

fn all_digits(s: &str, max: usize) -> Option<i64> {
    if s.is_empty() || s.len() > max || !s.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    s.parse::<i64>().ok()
}

fn parse_hms(token: &str) -> Option<(i64, i64, i64)> {
    let mut parts = token.split(':');
    let h = all_digits(parts.next()?, 2)?;
    let m = all_digits(parts.next()?, 2)?;
    let s = all_digits(parts.next()?, 2)?;
    if parts.next().is_some() || h > 23 || m > 59 || s > 59 {
        return None;
    }
    Some((h, m, s))
}

fn parse_tz(token: &str) -> Option<i64> {
    if token == "Z" {
        return Some(0);
    }
    let sign = match token.as_bytes().first() {
        Some(b'+') => 1,
        Some(b'-') => -1,
        _ => return None,
    };
    let body = &token[1..];
    let (hh, mm, ss) = match body.find(':') {
        Some(_) => {
            let mut parts = body.split(':');
            let h = all_digits(parts.next()?, 2)?;
            let m = all_digits(parts.next()?, 2)?;
            let s = match parts.next() {
                Some(p) => all_digits(p, 2)?,
                None => 0,
            };
            if parts.next().is_some() {
                return None;
            }
            (h, m, s)
        }
        None => {
            if body.len() != 4 && body.len() != 6 {
                return None;
            }
            let seconds = if body.len() == 6 {
                all_digits(&body[4..6], 2)?
            } else {
                0
            };
            (
                all_digits(&body[0..2], 2)?,
                all_digits(&body[2..4], 2)?,
                seconds,
            )
        }
    };
    if hh > 23 || mm > 59 || ss > 59 {
        return None;
    }
    Some(sign * (hh * 3600 + mm * 60 + ss))
}

fn rfc_try(tokens: &[&str], with_weekday: bool) -> Option<f64> {
    let mut i = 0usize;
    if with_weekday {
        let name = tokens.first()?.strip_suffix(',')?;
        if !WEEKDAYS.contains(&name.to_lowercase().as_str()) {
            return None;
        }
        i = 1;
    }
    let day = all_digits(tokens.get(i)?, 2)?;
    let month = month_num(tokens.get(i + 1)?)?;
    let year_text = tokens.get(i + 2)?;
    if year_text.len() != 4 {
        return None;
    }
    let year = all_digits(year_text, 4)?;
    let (h, m, s) = parse_hms(tokens.get(i + 3)?)?;
    let offset = match tokens.get(i + 4) {
        None => 0,
        Some(tz) => parse_tz(tz)?,
    };
    if tokens.len() > i + 5 {
        return None;
    }
    let days = days_from_civil(year, month, day);
    Some((days * 86400 + h * 3600 + m * 60 + s - offset) as f64)
}

pub fn ts_from_rfc(text: &str) -> Option<f64> {
    let raw = text.trim();
    if raw.is_empty() {
        return None;
    }
    let tokens: Vec<&str> = raw.split_whitespace().collect();
    rfc_try(&tokens, true).or_else(|| rfc_try(&tokens, false))
}

pub fn find_hex40(text: &str) -> Option<String> {
    let chars: Vec<char> = text.chars().collect();
    if chars.len() < 40 {
        return None;
    }
    for start in 0..=chars.len() - 40 {
        if chars[start..start + 40]
            .iter()
            .all(|c| c.is_ascii_hexdigit())
        {
            return Some(chars[start..start + 40].iter().collect::<String>().to_lowercase());
        }
    }
    None
}

pub fn find_after(text: &str, needle: &str) -> Option<String> {
    let start = text.find(needle)? + needle.len();
    let digits: String = text[start..]
        .chars()
        .take_while(|c| c.is_ascii_digit())
        .collect();
    if digits.is_empty() {
        None
    } else {
        Some(digits)
    }
}

pub fn findall_bounded(text: &str, open: &str, close: &str) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    let open: Vec<char> = open.chars().collect();
    let close: Vec<char> = close.chars().collect();
    let mut out = Vec::new();
    let mut pos = 0usize;
    while let Some(s) = find_ci(&chars, &open, pos) {
        let Some(gt) = find_tag_end(&chars, s + open.len()) else {
            break;
        };
        let cs = gt + 1;
        match find_ci(&chars, &close, cs) {
            Some(e) => {
                out.push(chars[cs..e].iter().collect());
                pos = e + close.len();
            }
            None => break,
        }
    }
    out
}

pub fn strip_tags(cell: &str, gap: &str) -> String {
    let chars: Vec<char> = cell.chars().collect();
    let mut out = String::new();
    let mut i = 0usize;
    while i < chars.len() {
        if chars[i] == '<' && i + 2 < chars.len() {
            if let Some(off) = chars[i + 1..].iter().position(|c| *c == '>') {
                if off >= 1 {
                    out.push_str(gap);
                    i = i + 1 + off + 1;
                    continue;
                }
            }
        }
        out.push(chars[i]);
        i += 1;
    }
    out
}

pub fn cell_text(cell: &str, gap: &str, unescape_html: bool) -> String {
    let stripped = strip_tags(cell, gap);
    if unescape_html {
        collapse(&unescape(&stripped))
    } else {
        collapse(&stripped)
    }
}

pub fn find_hex_after(text: &str, prefix: &str, len: usize) -> Option<String> {
    let mut from = 0usize;
    while let Some(p) = text[from..].find(prefix) {
        let start = from + p + prefix.len();
        let hex: String = text[start..]
            .chars()
            .take_while(|c| c.is_ascii_hexdigit())
            .collect();
        if hex.len() >= len {
            return Some(hex[..len].to_lowercase());
        }
        from = start;
    }
    None
}

fn is_word(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

fn bounded_runs<F: Fn(char) -> bool>(text: &str, ok: F, len: usize) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    let n = chars.len();
    let mut out = Vec::new();
    if n < len {
        return out;
    }
    let mut start = 0usize;
    while start <= n - len {
        if !chars[start..start + len].iter().all(|c| ok(*c)) {
            start += 1;
            continue;
        }
        let before = start == 0 || !is_word(chars[start - 1]);
        let after = start + len == n || !is_word(chars[start + len]);
        if before && after {
            out.push(chars[start..start + len].iter().collect());
            start += len;
            continue;
        }
        start += 1;
    }
    out
}

const B32_ALPHABET: &str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

fn b32_value(c: char) -> Option<u32> {
    B32_ALPHABET.find(c).map(|i| i as u32)
}

pub fn b32_to_hex(text: &str) -> Option<String> {
    let upper: Vec<char> = text.to_uppercase().chars().collect();
    if upper.len() % 8 != 0 {
        return None;
    }
    let mut bits: u32 = 0;
    let mut pending: u32 = 0;
    let mut out = String::new();
    for c in upper {
        bits = (bits << 5) | b32_value(c)?;
        pending += 5;
        if pending >= 8 {
            pending -= 8;
            out.push_str(&format!("{:02x}", (bits >> pending) & 0xff));
        }
    }
    if pending != 0 {
        return None;
    }
    Some(out)
}

fn is_hex40(c: char) -> bool {
    c.is_ascii_hexdigit()
}

fn is_b32(c: char) -> bool {
    B32_ALPHABET.contains(c)
}

pub fn hash_from_text(text: &str) -> String {
    if text.is_empty() {
        return String::new();
    }
    if let Some(run) = bounded_runs(text, is_hex40, 40).into_iter().next() {
        return run.to_lowercase();
    }
    for cand in bounded_runs(text, is_b32, 32) {
        if let Some(hex) = b32_to_hex(&cand) {
            if hex.len() == 40 && hex.chars().any(|c| c != '0') {
                return hex;
            }
        }
    }
    String::new()
}

pub fn hash_from_magnet(magnet: &str) -> String {
    if magnet.is_empty() {
        return String::new();
    }
    if let Some(run) = bounded_runs(magnet, is_hex40, 40).into_iter().next() {
        return run.to_lowercase();
    }
    for cand in bounded_runs(magnet, is_b32, 32) {
        if let Some(hex) = b32_to_hex(&cand) {
            return hex;
        }
    }
    String::new()
}

pub fn find_title_attr(row: &str) -> Option<String> {
    let mut from = 0usize;
    while let Some(p) = row[from..].find("href=\"/view/") {
        let ds = from + p + "href=\"/view/".len();
        let digits: String = row[ds..]
            .chars()
            .take_while(|c| c.is_ascii_digit())
            .collect();
        if digits.is_empty() {
            from = ds;
            continue;
        }
        let after = ds + digits.len();
        if !row[after..].starts_with('"') {
            from = ds;
            continue;
        }
        let seg_start = after + 1;
        let seg_end = row[seg_start..]
            .find('>')
            .map(|i| seg_start + i)
            .unwrap_or(row.len());
        let region = &row[seg_start..seg_end];
        let mut end = region.len();
        while let Some(pos) = region[..end].rfind("title=\"") {
            let cs = seg_start + pos + 7;
            let run: String = row[cs..].chars().take_while(|c| *c != '"').collect();
            let n = run.chars().count();
            if n >= 2 && n <= 400 && row[cs..].chars().nth(n) == Some('"') {
                return Some(run);
            }
            end = pos;
        }
        from = ds;
    }
    None
}

pub fn find_torrent_path(row: &str) -> Option<String> {
    let mut from = 0usize;
    while let Some(p) = row[from..].find("href=\"/download/") {
        let ds = from + p + "href=\"/download/".len();
        let digits: String = row[ds..]
            .chars()
            .take_while(|c| c.is_ascii_digit())
            .collect();
        let after = ds + digits.len();
        if !digits.is_empty() && row[after..].starts_with(".torrent\"") {
            return Some(format!("/download/{digits}.torrent"));
        }
        from = ds;
    }
    None
}

fn has_trailing_offset(raw: &str) -> bool {
    let b: Vec<char> = raw.chars().collect();
    let n = b.len();
    if n >= 5 {
        let seg = &b[n - 5..];
        if (seg[0] == '+' || seg[0] == '-') && seg[1..5].iter().all(|c| c.is_ascii_digit()) {
            return true;
        }
    }
    if n >= 6 {
        let seg = &b[n - 6..];
        if (seg[0] == '+' || seg[0] == '-')
            && seg[1..3].iter().all(|c| c.is_ascii_digit())
            && seg[3] == ':'
            && seg[4..6].iter().all(|c| c.is_ascii_digit())
        {
            return true;
        }
    }
    false
}

pub fn ts_from_naive_cn(text: &str) -> Option<f64> {
    let raw = text.trim();
    if raw.is_empty() || raw.ends_with('Z') || has_trailing_offset(raw) {
        return None;
    }
    parse_iso(raw).map(|secs| secs - 28800.0)
}

pub fn ts_cn_or_iso(text: &str) -> Option<f64> {
    match ts_from_naive_cn(text) {
        Some(v) if v != 0.0 => Some(v),
        _ => ts_from_iso(text),
    }
}

fn strp_num(s: &str, min: usize, max: usize) -> Option<i64> {
    let t = s.trim();
    if t.len() < min || t.len() > max || !t.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    t.parse::<i64>().ok()
}

pub fn ts_from_cn_slash(text: &str) -> Option<f64> {
    ts_from_cn_date(text, '/')
}

fn strp_month(text: &str) -> Option<i64> {
    if text.is_empty() || text.len() > 2 || !text.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    text.parse::<i64>().ok()
}

fn cn_date_core(raw: &str, sep: char, allow_time: bool) -> Option<f64> {
    let parts: Vec<&str> = raw.split(sep).collect();
    if parts.len() != 3 || parts[0].len() != 4 {
        return None;
    }
    let y = strp_num(parts[0], 4, 4)?;
    let m = strp_month(parts[1])?;
    if !(1..=12).contains(&m) {
        return None;
    }
    let tail: Vec<&str> = parts[2].split_whitespace().collect();
    if tail.is_empty() || tail.len() > 2 {
        return None;
    }
    let d = strp_num(tail[0], 1, 2)?;
    let mut seconds = civil_stamp(y, m, d)? * 86400 - 28800;
    if tail.len() == 2 {
        if !allow_time {
            return None;
        }
        let fields: Vec<&str> = tail[1].split(':').collect();
        if fields.len() != 2 && fields.len() != 3 {
            return None;
        }
        let h = strp_num(fields[0], 1, 2)?;
        let mi = strp_num(fields[1], 1, 2)?;
        let s = if fields.len() == 3 {
            strp_num(fields[2], 1, 2)?
        } else {
            0
        };
        if h > 23 || mi > 59 || s > 59 {
            return None;
        }
        seconds += h * 3600 + mi * 60 + s;
    }
    Some(seconds as f64)
}

pub fn ts_from_cn_date(text: &str, sep: char) -> Option<f64> {
    let raw = py_trim(text);
    if raw.is_empty() {
        return None;
    }
    cn_date_core(raw, sep, true)
}

pub fn ts_from_cn_ymd(text: &str) -> Option<f64> {
    let raw = py_trim(text);
    if raw.is_empty() {
        return None;
    }
    cn_date_core(raw, '-', false)
}

pub fn cn_date(text: &str) -> Option<f64> {
    match ts_from_naive_cn(text) {
        Some(v) if v != 0.0 => Some(v),
        _ => ts_from_cn_slash(text),
    }
}


pub fn findall_marked(text: &str, open: &str, marker: &str, close: &str) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    let open: Vec<char> = open.chars().collect();
    let marker: Vec<char> = marker.chars().collect();
    let close: Vec<char> = close.chars().collect();
    let mut out = Vec::new();
    let mut pos = 0usize;
    while let Some(s) = find_ci(&chars, &open, pos) {
        let Some(gt) = find_tag_end(&chars, s + open.len()) else {
            break;
        };
        if find_ci(&chars[s..gt], &marker, 0).is_some() {
            let cs = gt + 1;
            match find_ci(&chars, &close, cs) {
                Some(e) => {
                    out.push(chars[cs..e].iter().collect());
                    pos = e + close.len();
                    continue;
                }
                None => break,
            }
        }
        pos = s + 1;
    }
    out
}

pub fn find_b32_after(text: &str, prefix: &str, len: usize) -> Option<String> {
    let mut from = 0usize;
    while let Some(p) = text[from..].find(prefix) {
        let start = from + p + prefix.len();
        let run: String = text[start..]
            .chars()
            .take_while(|c| B32_ALPHABET.contains(c.to_ascii_uppercase()))
            .collect();
        if run.len() >= len {
            return Some(run[..len].to_string());
        }
        from = start;
    }
    None
}

fn match_size_ci(chars: &[char], start: usize) -> Option<(usize, usize)> {
    let n = chars.len();
    let mut i = start;
    while i < n && chars[i].is_ascii_digit() && i - start < 12 {
        i += 1;
    }
    if i == start || (i < n && chars[i].is_ascii_digit()) {
        return None;
    }
    if i < n && chars[i] == '.' {
        let fstart = i + 1;
        let mut j = fstart;
        while j < n && chars[j].is_ascii_digit() && j - fstart < 4 {
            j += 1;
        }
        if j == fstart {
            return None;
        }
        i = j;
    }
    let after_num = i;
    let mut probe = i;
    while probe < n && is_py_space(chars[probe]) {
        probe += 1;
    }
    if probe < n && matches!(chars[probe].to_ascii_uppercase(), 'K' | 'M' | 'G' | 'T' | 'P') {
        probe += 1;
        if probe < n && matches!(chars[probe], 'i' | 'I') {
            probe += 1;
        }
        if probe < n && matches!(chars[probe], 'B' | 'b') {
            return Some((start, probe + 1));
        }
        probe = after_num;
    }
    if probe < n && matches!(chars[probe], 'B' | 'b') {
        return Some((start, probe + 1));
    }
    None
}

pub fn size_from_title(title: &str) -> i64 {
    if title.is_empty() {
        return 0;
    }
    let chars: Vec<char> = title.chars().collect();
    let n = chars.len();
    for start in 0..n {
        if !matches!(chars[start], '[' | '(' | '【') {
            continue;
        }
        let mut i = start + 1;
        while i < n && is_py_space(chars[i]) {
            i += 1;
        }
        let Some((token_start, end)) = match_size_ci(&chars, i) else {
            continue;
        };
        let mut j = end;
        while j < n && is_py_space(chars[j]) {
            j += 1;
        }
        if j < n && matches!(chars[j], ']' | ')' | '】') {
            let captured: String = chars[token_start..end].iter().collect();
            return parse_size_text(&captured);
        }
    }
    0
}

pub fn ts_from_cn_dash(text: &str) -> Option<f64> {
    let raw = py_trim(text);
    if raw.is_empty() {
        return None;
    }
    let head: String = raw.chars().take(10).collect();
    cn_date_core(&head, '-', true)
}

pub fn local_parts(iso: &str) -> Option<(i64, i64, i64)> {
    let raw = py_trim(iso);
    let (date_part, rest) = match raw.split_once('T') {
        Some(pair) => pair,
        None => raw.split_once(' ')?,
    };
    let (y, m, d) = parse_ymd(date_part)?;
    let bytes = rest.as_bytes();
    if bytes.len() < 5 || bytes[2] != b':' {
        return None;
    }
    if !bytes[0..2].iter().all(u8::is_ascii_digit) || !bytes[3..5].iter().all(u8::is_ascii_digit) {
        return None;
    }
    let h = all_digits(&rest[0..2], 2)?;
    let mi = all_digits(&rest[3..5], 2)?;
    let s = if bytes.len() >= 8 && bytes[5] == b':' {
        if !bytes[6..8].iter().all(u8::is_ascii_digit) {
            return None;
        }
        all_digits(&rest[6..8], 2)?
    } else {
        0
    };
    if h > 23 || mi > 59 || s > 59 {
        return None;
    }
    let mut off_at = None;
    for (i, c) in rest.char_indices() {
        if i > 0 && (c == '+' || c == '-') {
            off_at = Some(i);
            break;
        }
    }
    let offset = tz_offset(&rest[off_at?..])?;
    Some((y, days_from_civil(y, m, d) * 86400 + h * 3600 + mi * 60 + s, offset))
}

fn days_in_month(year: i64, month: i64) -> i64 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => {
            if (year % 4 == 0 && year % 100 != 0) || year % 400 == 0 {
                29
            } else {
                28
            }
        }
        _ => 0,
    }
}

pub fn civil_stamp(year: i64, month: i64, day: i64) -> Option<i64> {
    if month < 1 || month > 12 || day < 1 || day > days_in_month(year, month) {
        return None;
    }
    Some(days_from_civil(year, month, day))
}

pub fn find_hash40(text: &str) -> Option<String> {
    if text.is_empty() {
        return None;
    }
    bounded_runs(text, is_hex40, 40)
        .into_iter()
        .next()
        .map(|r| r.to_lowercase())
}

pub fn quote_plus(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for byte in value.as_bytes() {
        let c = *byte as char;
        if c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | '-' | '~') {
            out.push(c);
        } else if c == ' ' {
            out.push('+');
        } else {
            out.push_str(&format!("%{byte:02X}"));
        }
    }
    out
}

#[derive(Clone, Copy)]
pub struct LocalNow {
    pub naive: i64,
    pub offset: i64,
    pub year: i64,
}

fn fallback_now() -> LocalNow {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    LocalNow {
        naive: secs,
        offset: 0,
        year: 1970,
    }
}

pub fn local_now() -> LocalNow {
    let Ok(stamp) = time::OffsetDateTime::now_local() else {
        return fallback_now();
    };
    let offset = i64::from(stamp.offset().whole_seconds());
    let naive = stamp.unix_timestamp() + offset;
    LocalNow {
        naive,
        offset,
        year: stamp.year() as i64,
    }
}

pub fn local_now_from_iso(iso: &str) -> Option<LocalNow> {
    let (year, naive, offset) = local_parts(iso)?;
    Some(LocalNow {
        naive,
        offset,
        year,
    })
}

pub fn local_stamp(now: &LocalNow, sep: char) -> String {
    let days = floor_div(now.naive, 86400);
    let secs = now.naive - days * 86400;
    let (year, month, day) = civil_from_days(days);
    format!(
        "{year:04}-{month:02}-{day:02}{sep}{:02}:{:02}:{:02}",
        secs / 3600,
        (secs % 3600) / 60,
        secs % 60
    )
}

pub fn civil_from_days(days: i64) -> (i64, i64, i64) {
    let z = days + 719468;
    let era = (if z >= 0 { z } else { z - 146096 }) / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    (if month <= 2 { y + 1 } else { y }, month, day)
}

pub fn floor_div(a: i64, b: i64) -> i64 {
    let quotient = a / b;
    if (a % b != 0) && ((a < 0) != (b < 0)) {
        quotient - 1
    } else {
        quotient
    }
}
