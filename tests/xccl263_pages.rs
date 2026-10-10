use std::collections::HashMap;
use std::sync::Mutex;

use happycrate::model::{SourceError, SourceResult};
use happycrate::sources::{xccl263, Fetch, Req};

fn page_no_of(url: &str) -> i64 {
    let tail = url.rsplit('/').next().unwrap_or("");
    let body = tail.strip_suffix(".html").unwrap_or(tail);
    body.rsplit('-').next().unwrap_or("").parse().unwrap_or(0)
}

fn block(hash: &str, title: &str) -> String {
    format!(
        "<div class=\"search-item detail-width\"><div class=\"item-title\"><h3><a title=\"{title}\" href=\"/hash/{hash}.html\"><b>{title}</b></a></h3></div><div class=\"item-bar\"><span>文件大小:\n<b class=\"cpill blue-pill\">1.2 GB</b>\n</span><span>创建时间:&nbsp;<b>2026-01-01</b></span><span>下载热度:&nbsp;<b>4</b></span></div></div>"
    )
}

fn page_html(total: i64, hashes: &[String]) -> String {
    let mut out = format!(
        "<html><body><div class=\"search-statu\"><span>找到{total}条结果（用时1毫秒）</span></div>"
    );
    for (index, hash) in hashes.iter().enumerate() {
        out.push_str(&block(hash, &format!("样本标题 {index}")));
    }
    out.push_str("</body></html>");
    out
}

fn hashes_for(start: usize, count: usize) -> Vec<String> {
    (0..count).map(|index| format!("{:040x}", start + index)).collect()
}

struct Script {
    served: HashMap<i64, String>,
    calls: Mutex<Vec<i64>>,
    failures: Mutex<HashMap<i64, usize>>,
}

impl Script {
    fn new(served: HashMap<i64, String>, failures: HashMap<i64, usize>) -> Script {
        Script {
            served,
            calls: Mutex::new(Vec::new()),
            failures: Mutex::new(failures),
        }
    }

    fn calls(&self) -> Vec<i64> {
        let mut calls = self.calls.lock().unwrap().clone();
        calls.sort();
        calls
    }
}

impl Fetch for Script {
    fn fetch(&self, req: Req) -> SourceResult<String> {
        let page_no = page_no_of(req.url);
        self.calls.lock().unwrap().push(page_no);
        if let Some(left) = self.failures.lock().unwrap().get_mut(&page_no) {
            if *left > 0 {
                *left -= 1;
                return Err(SourceError::Http {
                    code: 500,
                    body: String::new(),
                });
            }
        }
        match self.served.get(&page_no) {
            Some(body) => Ok(body.clone()),
            None => Err(SourceError::Http {
                code: 404,
                body: String::new(),
            }),
        }
    }
}

#[test]
fn total_drives_page_count() {
    let script = Script::new(
        HashMap::from([
            (1, page_html(25, &hashes_for(0, 20))),
            (2, page_html(25, &hashes_for(20, 5))),
        ]),
        HashMap::new(),
    );
    let items = xccl263::search("", "样例", 1, &script).expect("搜索失败");
    assert_eq!(items.len(), 25);
    assert_eq!(script.calls(), vec![1, 2]);
}

#[test]
fn small_total_uses_single_request() {
    let script = Script::new(
        HashMap::from([(1, page_html(6, &hashes_for(0, 6)))]),
        HashMap::new(),
    );
    let items = xccl263::search("", "样例", 1, &script).expect("搜索失败");
    assert_eq!(items.len(), 6);
    assert_eq!(script.calls(), vec![1]);
}

#[test]
fn full_page_total_fetches_one_more() {
    let script = Script::new(
        HashMap::from([
            (1, page_html(20, &hashes_for(0, 20))),
            (2, page_html(20, &[])),
        ]),
        HashMap::new(),
    );
    let items = xccl263::search("", "样例", 1, &script).expect("搜索失败");
    assert_eq!(items.len(), 20);
    assert_eq!(script.calls(), vec![1, 2]);
}

#[test]
fn failed_page_is_refetched() {
    let script = Script::new(
        HashMap::from([
            (1, page_html(45, &hashes_for(0, 20))),
            (2, page_html(45, &hashes_for(20, 20))),
            (3, page_html(45, &hashes_for(40, 5))),
        ]),
        HashMap::from([(2, 1)]),
    );
    let items = xccl263::search("", "样例", 1, &script).expect("搜索失败");
    assert_eq!(items.len(), 45);
    let calls = script.calls();
    assert_eq!(calls.iter().filter(|&&page| page == 2).count(), 2);
    assert_eq!(calls.iter().filter(|&&page| page == 3).count(), 1);
}

#[test]
fn exhausted_refetch_keeps_partial_result() {
    let script = Script::new(
        HashMap::from([
            (1, page_html(45, &hashes_for(0, 20))),
            (2, page_html(45, &hashes_for(20, 20))),
            (3, page_html(45, &hashes_for(40, 5))),
        ]),
        HashMap::from([(2, 99)]),
    );
    let items = xccl263::search("", "样例", 1, &script).expect("搜索失败");
    assert_eq!(items.len(), 25);
    let calls = script.calls();
    assert_eq!(calls.iter().filter(|&&page| page == 2).count(), 2);
}

#[test]
fn missing_page_is_not_refetched() {
    let script = Script::new(
        HashMap::from([
            (1, page_html(45, &hashes_for(0, 20))),
            (2, page_html(45, &hashes_for(20, 20))),
        ]),
        HashMap::new(),
    );
    let items = xccl263::search("", "样例", 1, &script).expect("搜索失败");
    assert_eq!(items.len(), 40);
    assert_eq!(script.calls(), vec![1, 2, 3]);
}

#[test]
fn first_page_failure_falls_back_to_rest() {
    let script = Script::new(
        HashMap::from([
            (1, page_html(45, &hashes_for(0, 20))),
            (2, page_html(45, &hashes_for(20, 20))),
            (3, page_html(45, &hashes_for(40, 5))),
            (4, page_html(45, &[])),
        ]),
        HashMap::from([(1, 1)]),
    );
    let items = xccl263::search("", "样例", 1, &script).expect("搜索失败");
    assert_eq!(items.len(), 45);
    assert_eq!(script.calls(), vec![1, 1, 2, 3, 4]);
}
