use serde::Serialize;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct FetchTarget {
    pub url: String,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Item {
    pub title: String,
    pub info_hash: String,
    pub size: i64,
    pub seeders: Option<i64>,
    pub leechers: Option<i64>,
    pub added: Option<serde_json::Number>,
    pub source: String,
    pub magnet: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub files: Option<Vec<serde_json::Value>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fetch: Option<FetchTarget>,
}

impl Item {
    pub fn into_value(self) -> serde_json::Value {
        serde_json::to_value(self).expect("Item 可序列化")
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum SourceError {
    Shape(String),
    Blocked(String),
    Http { code: u16, body: String },
    Timeout,
    TooLarge { limit: usize },
    Transport(String),
    ProxyUnreachable(String),
    Cancelled,
    MissingFixture { url: String, body: Option<String> },
}

impl SourceError {
    pub fn search_text(&self) -> String {
        match self {
            SourceError::Shape(m) => format!("ShapeError: {m}"),
            SourceError::Blocked(m) => m.clone(),
            SourceError::Http { code, .. } => format!("HTTP {code}"),
            SourceError::Timeout => "TimeoutError: timed out".to_string(),
            SourceError::TooLarge { limit } => {
                format!("TooLarge: 响应超过 {limit} 字节上限")
            }
            SourceError::Transport(m) => format!("URLError: {m}"),
            SourceError::ProxyUnreachable(m) => m.clone(),
            SourceError::Cancelled => crate::outcome::CANCEL_TEXT.to_string(),
            SourceError::MissingFixture { url, .. } => {
                format!("MissingFixture: 缺少 {url}")
            }
        }
    }
}

pub type SourceResult<T> = Result<T, SourceError>;
