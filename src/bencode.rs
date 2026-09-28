use std::collections::BTreeMap;

pub const MAX_DEPTH: i64 = 32;

#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Int(i64),
    Bytes(Vec<u8>),
    List(Vec<Value>),
    Dict(BTreeMap<Vec<u8>, Value>),
}

fn byte_at(buf: &[u8], i: usize) -> u8 {
    if i < buf.len() {
        buf[i]
    } else {
        0
    }
}

fn find(buf: &[u8], needle: u8, from: usize) -> Result<usize, String> {
    buf[from..]
        .iter()
        .position(|b| *b == needle)
        .map(|offset| from + offset)
        .ok_or_else(|| "bencode 缺少结束标记".to_string())
}

fn parse_int(raw: &[u8]) -> Result<i64, String> {
    let text = std::str::from_utf8(raw).map_err(|_| "bencode 数字不是文本".to_string())?;
    text.trim()
        .parse::<i64>()
        .map_err(|_| "bencode 数字无法解析".to_string())
}

pub fn decode(buf: &[u8], start: usize, depth: i64) -> Result<(Value, usize), String> {
    if depth > MAX_DEPTH {
        return Err("bencode 嵌套过深".to_string());
    }
    let mut i = start;
    match byte_at(buf, i) {
        b'd' => {
            i += 1;
            let mut map: BTreeMap<Vec<u8>, Value> = BTreeMap::new();
            while byte_at(buf, i) != b'e' {
                let (key, next_key) = decode(buf, i, depth + 1)?;
                let (value, next_value) = decode(buf, next_key, depth + 1)?;
                if let Value::Bytes(raw) = key {
                    map.insert(raw, value);
                }
                i = next_value;
            }
            Ok((Value::Dict(map), i + 1))
        }
        b'l' => {
            i += 1;
            let mut seq: Vec<Value> = Vec::new();
            while byte_at(buf, i) != b'e' {
                let (value, next) = decode(buf, i, depth + 1)?;
                seq.push(value);
                i = next;
            }
            Ok((Value::List(seq), i + 1))
        }
        b'i' => {
            let end = find(buf, b'e', i)?;
            let number = parse_int(&buf[i + 1..end])?;
            Ok((Value::Int(number), end + 1))
        }
        _ => {
            let colon = find(buf, b':', i)?;
            let length = parse_int(&buf[i..colon])?;
            if length < 0 {
                return Err("bencode 字符串长度越界".to_string());
            }
            let length = length as usize;
            let begin = colon + 1;
            if begin + length > buf.len() {
                return Err("bencode 字符串长度越界".to_string());
            }
            Ok((Value::Bytes(buf[begin..begin + length].to_vec()), begin + length))
        }
    }
}

pub struct FileEntry {
    pub name: String,
    pub bytes: i64,
}

fn as_length(value: &Value) -> Result<i64, String> {
    match value {
        Value::Int(number) => Ok(*number),
        Value::Bytes(raw) => parse_int(raw),
        other => Err(format!("TypeError: 长度类型不对 ({other:?})")),
    }
}

fn as_bytes(value: &Value) -> Result<Vec<u8>, String> {
    match value {
        Value::Bytes(raw) => Ok(raw.clone()),
        other => Err(format!("AttributeError: 名称类型不对 ({other:?})")),
    }
}

pub fn decode_torrent_files(data: &[u8]) -> Result<Vec<FileEntry>, String> {
    let Ok((decoded, _)) = decode(data, 0, 0) else {
        return Ok(Vec::new());
    };
    let Value::Dict(top) = decoded else {
        return Ok(Vec::new());
    };
    let Some(Value::Dict(info)) = top.get(b"info".as_slice()) else {
        return Ok(Vec::new());
    };

    let mut out: Vec<FileEntry> = Vec::new();
    match info.get(b"files".as_slice()) {
        Some(Value::List(rows)) => {
            for row in rows {
                let Value::Dict(entry) = row else {
                    continue;
                };
                let Some(length) = entry.get(b"length".as_slice()) else {
                    continue;
                };
                let Some(path) = entry.get(b"path".as_slice()) else {
                    continue;
                };
                let Value::List(parts) = path else {
                    return Err("TypeError: 路径不是可迭代对象".to_string());
                };
                let joined: Vec<u8> = parts
                    .iter()
                    .filter_map(|part| match part {
                        Value::Bytes(raw) => Some(raw.clone()),
                        _ => None,
                    })
                    .collect::<Vec<Vec<u8>>>()
                    .join(&b'/');
                out.push(FileEntry {
                    name: String::from_utf8_lossy(&joined).to_string(),
                    bytes: as_length(length)?,
                });
            }
        }
        _ => {
            if let (Some(length), Some(name)) = (
                info.get(b"length".as_slice()),
                info.get(b"name".as_slice()),
            ) {
                out.push(FileEntry {
                    name: String::from_utf8_lossy(&as_bytes(name)?).to_string(),
                    bytes: as_length(length)?,
                });
            }
        }
    }
    Ok(out)
}
