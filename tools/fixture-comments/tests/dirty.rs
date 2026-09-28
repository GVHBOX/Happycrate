// 测试也属于核心源码
use std::fs;

#[test]
fn t() {
    assert!(fs::metadata(".").is_ok());
}
