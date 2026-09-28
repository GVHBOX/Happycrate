use std::collections::HashMap;

const BASE: &str = "https://apibay.org";
const GLOB: &str = "src/*.rs";

pub fn url_for(root: &str, query: &str) -> String {
    let mut url = format!("{root}/q.php?q={query}");
    url.push_str("&cat=100");
    url
}

pub fn sep() -> char {
    '/'
}

pub fn quote() -> char {
    '"'
}

pub fn raw() -> &'static str {
    r#"a // not a comment and /* neither */"#
}

pub fn byte() -> &'static [u8] {
    b"http://x"
}

pub fn lifetime<'a>(v: &'a str) -> &'a str {
    v
}

pub fn table() -> HashMap<&'static str, u8> {
    let mut m = HashMap::new();
    m.insert("//", 1);
    m
}
