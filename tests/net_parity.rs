use std::fs;
use std::path::Path;

use happycrate::net::{bypass_with, parse_proxy, system_proxies};
use serde_json::Value;

fn cases() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity/net_cases.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

#[test]
fn parity_parse_proxy() {
    let data = cases();
    let rows = data["parse_proxy"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let input = row["in"].as_str().unwrap();
        let (mapping, err) = parse_proxy(input);
        let want: Vec<(String, String)> = row["mapping"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string()))
            .collect();
        let got: Vec<(String, String)> = mapping.into_iter().collect();
        assert_eq!(got, want, "parse_proxy({input:?}) 映射不一致");
        assert_eq!(err, row["err"].as_str().unwrap(), "parse_proxy({input:?}) 错误文本不一致");
    }
}

#[test]
fn parity_bypass() {
    let data = cases();
    let rows = data["bypass"].as_array().unwrap();
    assert!(!rows.is_empty());
    for row in rows {
        let host = row["host"].as_str().unwrap();
        let override_ = row["override"].as_str().unwrap();
        assert_eq!(
            bypass_with(host, override_),
            row["hit"].as_bool().unwrap(),
            "bypass_with({host:?}, {override_:?})"
        );
    }
}

#[test]
fn captcha_sign_survives_beyond_head_window() {
    let mut page = String::from("<!DOCTYPE html><html><head><title>btdig.com</title></head><body>");
    while page.len() < 6000 {
        page.push_str("<div style=\"margin:0;padding:0\">blocked</div>");
    }
    assert!(
        !happycrate::net::captcha_text(&page),
        "纯样式填充页不应判为验证码页"
    );
    page.push_str("<h1>One more step</h1><div id=\"g-recaptcha\"></div></body></html>");
    assert!(
        happycrate::net::captcha_text(&page),
        "标记落在 4096 字符之后的挑战页应被识别"
    );
}

#[test]
fn captcha_weak_sign_needs_two_hits() {
    let single = "<html><body><a href=\"/captcha\">x</a></body></html>";
    assert!(!happycrate::net::captcha_text(single));
    let double = "<html><body><a href=\"/captcha\">输入验证码</a></body></html>";
    assert!(happycrate::net::captcha_text(double));
}

#[test]
fn captcha_infrastructure_marker_is_not_a_wall() {
    let mut page = String::from(
        "<!DOCTYPE html><html><head><title>中出 磁力链接 - 小草磁力</title></head><body>",
    );
    while page.len() < 7000 {
        page.push_str("<div class=\"search-item\">结果</div>");
    }
    page.push_str("<style>span[data-href^=\"https://www.hcaptcha.com/\"] > #icon { color: red }</style>");
    page.push_str("<script src=\"/cdn-cgi/challenge-platform/scripts/jsd/main.js\"></script>");
    page.push_str("<a href=\"/help/captcha\">captcha</a>");
    assert!(
        !happycrate::net::captcha_text(&page),
        "正常结果页里的 Cloudflare 脚本与样式引用不得判为验证码页"
    );
}

#[test]
fn captcha_interstitial_phrase_still_wins() {
    let mut page = String::from("<!DOCTYPE html><html><head><title>example</title></head><body>");
    while page.len() < 7000 {
        page.push_str("<div>filler</div>");
    }
    page.push_str("<h1>Just a moment</h1>");
    assert!(
        happycrate::net::captcha_text(&page),
        "挑战页文案落在正文深处仍须识别"
    );
}

#[test]
fn live_registry_matches_python() {
    let python = Path::new("D:/AI/happycrate/.venv/Scripts/python.exe");
    if !python.is_file() {
        println!("跳过：找不到 Python 环境 {}", python.display());
        return;
    }
    let output = std::process::Command::new(python)
        .args([
            "-c",
            "import json, urllib.request; print(json.dumps(urllib.request.getproxies()))",
        ])
        .output()
        .expect("跑不动 Python");
    assert!(
        output.status.success(),
        "Python 侧失败：{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let parsed: Value = serde_json::from_slice(&output.stdout).expect("Python 输出不是 JSON");
    let keep = |key: &str| key == "http" || key == "https" || key == "ftp";

    let mut expected: Vec<(String, String)> = parsed
        .as_object()
        .unwrap()
        .iter()
        .filter(|(key, _)| keep(key))
        .map(|(key, value)| (key.clone(), value.as_str().unwrap().to_string()))
        .collect();
    let mut actual: Vec<(String, String)> = system_proxies()
        .into_iter()
        .filter(|(key, _)| keep(key))
        .collect();
    expected.sort();
    actual.sort();
    assert_eq!(
        actual, expected,
        "现场注册表/环境变量解析出的代理与 Python 的 getproxies() 不一致"
    );
    println!("现场代理解析与 Python 一致：{actual:?}");
}

fn vt_gate_html(nonce: &str, ch: &str) -> String {
    format!(
        "<!DOCTYPE html><html><head><title>正在验证浏览器…</title></head><body><p id=\"m\">正在验证您的浏览器，请稍候…</p><script>(function(){{var nonce = \"{nonce}\", ch = \"{ch}\";function h(s){{var x = 0x811c9dc5;for(var i=0;i<s.length;i++){{x^=s.charCodeAt(i);x=Math.imul(x,0x01000193)>>>0;}}return x>>>0;}}fetch(\"/__vt\",{{method:\"POST\",body:\"c=\"+encodeURIComponent(ch)+\"&a=\"+h(nonce)}});}})();</script></body></html>"
    )
}

#[test]
fn vt_gate_parses_live_template_and_computes_fnv1a() {
    use happycrate::net::{
        fnv1a32_utf16, origin_of, parse_set_cookies, parse_vt_gate, vt_form_body, VtGate,
    };

    assert_eq!(fnv1a32_utf16(""), 0x811c_9dc5);
    assert_eq!(fnv1a32_utf16("a"), 0xe40c_292c);

    let html = vt_gate_html("8e798bebe2eb494a814abe4a11c3cd37", "tok.a-b_c");
    let gate = parse_vt_gate(&html).expect("应解析出 /__vt 校验参数");
    assert_eq!(gate.nonce, "8e798bebe2eb494a814abe4a11c3cd37");
    assert_eq!(gate.ch, "tok.a-b_c");
    assert_eq!(
        vt_form_body(&VtGate {
            nonce: "a".to_string(),
            ch: "x y/z".to_string(),
        }),
        "c=x%20y%2Fz&a=3826002220&w=0"
    );

    assert!(parse_vt_gate("<html><title>Just a moment</title></html>").is_none());
    assert_eq!(
        origin_of("https://www.xccl263.xyz/search/kw-ubuntu-1.html").as_deref(),
        Some("https://www.xccl263.xyz")
    );
    assert_eq!(
        origin_of("http://127.0.0.1:8080/search?q=1").as_deref(),
        Some("http://127.0.0.1:8080")
    );

    let parsed = parse_set_cookies(&[
        "vt=abc123; Expires=Fri, 20-Nov-2026 20:16:08 GMT; Max-Age=21600; HttpOnly; Path=/",
        "stale=; Max-Age=0; Path=/",
    ])
    .expect("应提取出有效 Cookie");
    assert_eq!(parsed, ("vt=abc123".to_string(), 21540));
}

struct MockVtServer {
    addr: String,
    vt_posts: std::sync::Arc<std::sync::atomic::AtomicUsize>,
    active_cookie: std::sync::Arc<std::sync::Mutex<String>>,
    stop: std::sync::Arc<std::sync::atomic::AtomicBool>,
    handle: Option<std::thread::JoinHandle<()>>,
}

impl MockVtServer {
    fn start(initial_cookie: &str, reject_vt_post: bool) -> Self {
        use std::io::{Read, Write};
        use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
        use std::sync::{Arc, Mutex};

        let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("绑定回环端口失败");
        listener.set_nonblocking(true).expect("设置非阻塞失败");
        let port = listener.local_addr().unwrap().port();
        let addr = format!("http://127.0.0.1:{port}");
        let vt_posts = Arc::new(AtomicUsize::new(0));
        let active_cookie = Arc::new(Mutex::new(initial_cookie.to_string()));
        let stop = Arc::new(AtomicBool::new(false));

        let vt_posts_bg = vt_posts.clone();
        let active_cookie_bg = active_cookie.clone();
        let stop_bg = stop.clone();

        let handle = std::thread::spawn(move || {
            while !stop_bg.load(Ordering::Relaxed) {
                let mut stream = match listener.accept() {
                    Ok((s, _)) => s,
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                        std::thread::sleep(std::time::Duration::from_millis(10));
                        continue;
                    }
                    Err(_) => break,
                };
                let _ = stream.set_nonblocking(false);
                let _ = stream.set_read_timeout(Some(std::time::Duration::from_secs(2)));
                let mut buf = vec![0u8; 8192];
                let mut total = 0usize;
                loop {
                    let n = stream.read(&mut buf[total..]).unwrap_or(0);
                    if n == 0 {
                        break;
                    }
                    total += n;
                    if let Some(pos) = buf[..total].windows(4).position(|w| w == b"\r\n\r\n") {
                        let head = String::from_utf8_lossy(&buf[..pos]);
                        let content_len: usize = head
                            .lines()
                            .find_map(|l| {
                                let (k, v) = l.split_once(':')?;
                                if k.trim().eq_ignore_ascii_case("content-length") {
                                    v.trim().parse().ok()
                                } else {
                                    None
                                }
                            })
                            .unwrap_or(0);
                        let need = pos + 4 + content_len;
                        while total < need && total < buf.len() {
                            let m = stream.read(&mut buf[total..]).unwrap_or(0);
                            if m == 0 {
                                break;
                            }
                            total += m;
                        }
                        break;
                    }
                    if total >= buf.len() {
                        break;
                    }
                }
                let raw = String::from_utf8_lossy(&buf[..total]);
                let (head, body) = raw.split_once("\r\n\r\n").unwrap_or((&raw, ""));
                let first_line = head.lines().next().unwrap_or("");
                let mut parts = first_line.split_whitespace();
                let method = parts.next().unwrap_or("");
                let path = parts.next().unwrap_or("/");
                let cookie_hdr = head
                    .lines()
                    .find_map(|l| {
                        let (k, v) = l.split_once(':')?;
                        if k.trim().eq_ignore_ascii_case("cookie") {
                            Some(v.trim().to_string())
                        } else {
                            None
                        }
                    })
                    .unwrap_or_default();

                let wanted = active_cookie_bg.lock().unwrap().clone();
                let response = if method == "POST" && path == "/__vt" {
                    vt_posts_bg.fetch_add(1, Ordering::SeqCst);
                    let expected = happycrate::net::vt_form_body(&happycrate::net::VtGate {
                        nonce: "nonce123".to_string(),
                        ch: "ch.tok".to_string(),
                    });
                    if reject_vt_post || body.trim() != expected {
                        "HTTP/1.1 400 Bad Request\r\nContent-Length: 3\r\nConnection: close\r\n\r\nbad".to_string()
                    } else {
                        format!(
                            "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nSet-Cookie: vt={wanted}; Max-Age=21600; HttpOnly; Path=/\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
                        )
                    }
                } else if cookie_hdr == format!("vt={wanted}") {
                    let resp_body = format!("ok:{path}");
                    format!(
                        "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{resp_body}",
                        resp_body.len()
                    )
                } else {
                    let gate = vt_gate_html("nonce123", "ch.tok");
                    format!(
                        "HTTP/1.1 403 Forbidden\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{gate}",
                        gate.len()
                    )
                };
                let _ = stream.write_all(response.as_bytes());
                let _ = stream.flush();
            }
        });

        MockVtServer {
            addr,
            vt_posts,
            active_cookie,
            stop,
            handle: Some(handle),
        }
    }

    fn posts(&self) -> usize {
        self.vt_posts.load(std::sync::atomic::Ordering::SeqCst)
    }

    fn rotate_cookie(&self, next: &str) {
        *self.active_cookie.lock().unwrap() = next.to_string();
    }
}

impl Drop for MockVtServer {
    fn drop(&mut self) {
        self.stop.store(true, std::sync::atomic::Ordering::Relaxed);
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

#[test]
fn vt_http_client_solves_and_caches_cookie() {
    use happycrate::net::{HttpClient, DEFAULT_UA};
    use happycrate::sources::{Fetch, Req};

    let server = MockVtServer::start("good-1", false);
    let client = HttpClient::new_direct(DEFAULT_UA.to_string(), 0, 5).expect("创建客户端失败");

    let page1 = client
        .fetch(Req::get(&format!("{}/search/kw-ubuntu-1.html", server.addr)))
        .expect("首个 /__vt 校验页应自动通过并返回正文");
    assert_eq!(page1, "ok:/search/kw-ubuntu-1.html");
    assert_eq!(server.posts(), 1);

    let page2 = client
        .fetch(Req::get(&format!("{}/search/kw-ubuntu-2.html", server.addr)))
        .expect("后续请求应复用缓存 vt Cookie");
    assert_eq!(page2, "ok:/search/kw-ubuntu-2.html");
    assert_eq!(server.posts(), 1);
}

#[test]
fn vt_http_client_refreshes_expired_cookie_once_under_concurrency() {
    use happycrate::net::{HttpClient, DEFAULT_UA};
    use happycrate::sources::{Fetch, Req};

    let server = MockVtServer::start("good-1", false);
    let client =
        std::sync::Arc::new(HttpClient::new_direct(DEFAULT_UA.to_string(), 0, 5).expect("创建客户端失败"));

    let _ = client
        .fetch(Req::get(&format!("{}/search/kw-ubuntu-1.html", server.addr)))
        .expect("首次预热失败");
    assert_eq!(server.posts(), 1);

    server.rotate_cookie("good-2");

    let mut handles = Vec::new();
    for page in 2..=3 {
        let client = client.clone();
        let url = format!("{}/search/kw-ubuntu-{page}.html", server.addr);
        handles.push(std::thread::spawn(move || {
            let text = client.fetch(Req::get(&url)).expect("过期 Cookie 刷新后应成功");
            (page, text)
        }));
    }
    for handle in handles {
        let (page, text) = handle.join().unwrap();
        assert_eq!(text, format!("ok:/search/kw-ubuntu-{page}.html"));
    }
    assert_eq!(server.posts(), 2);
}

#[test]
fn vt_http_client_stops_when_post_fails() {
    use happycrate::model::SourceError;
    use happycrate::net::{HttpClient, DEFAULT_UA};
    use happycrate::sources::{Fetch, Req};

    let server = MockVtServer::start("good-1", true);
    let client = HttpClient::new_direct(DEFAULT_UA.to_string(), 0, 5).expect("创建客户端失败");

    let err = client
        .fetch(Req::get(&format!("{}/search/kw-ubuntu-1.html", server.addr)))
        .expect_err("/__vt 提交失败应回落为 HTTP 403");
    assert!(matches!(err, SourceError::Http { code: 403, .. }));
    assert_eq!(server.posts(), 1);
}
