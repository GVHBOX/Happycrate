use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;
use std::sync::Mutex;

use crate::log;

pub const MUTEX_NAME: &str = "Local\\happycrate_rust_v1_SingleInstance_7d4a9e2c6b1f8053";

const ERROR_ALREADY_EXISTS: u32 = 183;

#[link(name = "kernel32")]
extern "system" {
    fn CreateMutexW(
        attributes: *mut core::ffi::c_void,
        owner: i32,
        name: *const u16,
    ) -> *mut core::ffi::c_void;
    fn CloseHandle(handle: *mut core::ffi::c_void) -> i32;
    fn GetLastError() -> u32;
}

static HANDLE: Mutex<Option<usize>> = Mutex::new(None);

pub fn acquire() -> bool {
    let mut guard = match HANDLE.lock() {
        Ok(guard) => guard,
        Err(_) => return true,
    };
    if guard.is_some() {
        return true;
    }

    let wide: Vec<u16> = OsStr::new(MUTEX_NAME)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();

    unsafe {
        let handle = CreateMutexW(std::ptr::null_mut(), 0, wide.as_ptr());
        if handle.is_null() {
            log::warning(
                log::SINGLE,
                &format!(
                    "CreateMutexW 返回 NULL (last_error={})，放行不拦",
                    GetLastError()
                ),
            );
            return true;
        }
        let error = GetLastError();
        if error == ERROR_ALREADY_EXISTS {
            CloseHandle(handle);
            log::info(log::SINGLE, "检测到已有实例（互斥体已存在），本次退出");
            return false;
        }
        *guard = Some(handle as usize);
    }

    log::info(
        log::SINGLE,
        &format!("单实例互斥体已获取：{MUTEX_NAME}"),
    );
    true
}

pub fn release() -> bool {
    let mut guard = match HANDLE.lock() {
        Ok(guard) => guard,
        Err(_) => return false,
    };
    let Some(raw) = guard.take() else {
        return false;
    };
    unsafe {
        CloseHandle(raw as *mut core::ffi::c_void);
    }
    log::info(log::SINGLE, "单实例互斥体已释放");
    true
}
