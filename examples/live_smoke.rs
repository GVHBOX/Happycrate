use std::sync::Arc;
use std::time::Instant;

use happycrate::net::HttpClient;
use happycrate::sources::{apibay, bitsearch, eztv, knaben, nyaa};

const UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

fn main() {
    let client = Arc::new(
        HttpClient::new(UA.to_string(), 1, 20, "").expect("客户端构造失败"),
    );
    let resolved = client.resolved();
    println!("代理 {} {}", resolved.mode, resolved.addr);
    println!(
        "绕过 apibay.org = {}",
        happycrate::net::bypass("apibay.org", resolved)
    );
    println!();

    let jobs = ["apibay", "bitsearch", "eztv", "knaben", "nyaa"];
    let mut handles = Vec::new();
    for name in jobs {
        let client = client.clone();
        handles.push(std::thread::spawn(move || {
            let started = Instant::now();
            let outcome: Result<usize, String> = match name {
                "apibay" => apibay::search("", "ubuntu", &*client)
                    .map(|v| v.len())
                    .map_err(|e| e.search_text()),
                "bitsearch" => bitsearch::search("", "ubuntu", 1, &*client)
                    .map(|v| v.len())
                    .map_err(|e| e.search_text()),
                "eztv" => eztv::search("", "1080p", &*client)
                    .map(|v| v.len())
                    .map_err(|e| e.search_text()),
                "knaben" => knaben::search("", "ubuntu", 1, &*client)
                    .map(|v| v.len())
                    .map_err(|e| e.search_text()),
                _ => nyaa::family("", "frieren", 1, &*client, "nyaa", 14, 1100)
                    .map(|v| v.len())
                    .map_err(|e| e.search_text()),
            };
            (name, outcome, started.elapsed().as_millis())
        }));
    }

    let mut ok = 0usize;
    for handle in handles {
        let (name, outcome, ms) = handle.join().unwrap();
        match outcome {
            Ok(count) => {
                ok += 1;
                println!("{name:>9}  ok  {count:>5} 条  {ms:>6} ms");
            }
            Err(text) => println!("{name:>9}  失败  {text}  ({ms} ms)"),
        }
    }
    println!();
    println!("{ok}/5 个源返回结果");
}
