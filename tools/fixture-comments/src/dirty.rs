//! crate 级文档注释
use std::fmt;

/* 块注释 */
pub fn a() -> u8 {
    1 // 行尾注释
}

/// 文档注释
pub fn b() -> u8 {
    2
}

/* 跨行
   块注释 */
pub const C: u8 = 3;

pub fn d() -> fmt::Result {
    let s = "https://x";
    let _ = s;
    Ok(())
}
