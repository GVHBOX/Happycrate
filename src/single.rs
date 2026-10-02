use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;
use std::sync::Mutex;

use crate::log;

pub const MUTEX_NAME: &str = "Local\\happycrate_rust_v1_SingleInstance_7d4a9e2c6b1f8053";

const ERROR_ALREADY_EXISTS: u32 = 183;
const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
const GW_OWNER: u32 = 4;
const SW_SHOW: i32 = 5;
const SW_RESTORE: i32 = 9;

#[link(name = "kernel32")]
extern "system" {
    fn CreateMutexW(
        attributes: *mut core::ffi::c_void,
        owner: i32,
        name: *const u16,
    ) -> *mut core::ffi::c_void;
    fn CloseHandle(handle: *mut core::ffi::c_void) -> i32;
    fn GetLastError() -> u32;
    fn GetCurrentProcessId() -> u32;
    fn GetCurrentThreadId() -> u32;
    fn OpenProcess(
        desired_access: u32,
        inherit_handle: i32,
        process_id: u32,
    ) -> *mut core::ffi::c_void;
    fn QueryFullProcessImageNameW(
        process: *mut core::ffi::c_void,
        flags: u32,
        exe_name: *mut u16,
        size: *mut u32,
    ) -> i32;
}

#[link(name = "user32")]
extern "system" {
    fn EnumWindows(
        enum_func: unsafe extern "system" fn(*mut core::ffi::c_void, isize) -> i32,
        l_param: isize,
    ) -> i32;
    fn GetWindowThreadProcessId(
        hwnd: *mut core::ffi::c_void,
        process_id: *mut u32,
    ) -> u32;
    fn GetWindowTextW(
        hwnd: *mut core::ffi::c_void,
        string: *mut u16,
        max_count: i32,
    ) -> i32;
    fn GetWindowTextLengthW(hwnd: *mut core::ffi::c_void) -> i32;
    fn GetWindow(hwnd: *mut core::ffi::c_void, cmd: u32) -> *mut core::ffi::c_void;
    fn IsIconic(hwnd: *mut core::ffi::c_void) -> i32;
    fn ShowWindow(hwnd: *mut core::ffi::c_void, cmd_show: i32) -> i32;
    fn SetForegroundWindow(hwnd: *mut core::ffi::c_void) -> i32;
    fn BringWindowToTop(hwnd: *mut core::ffi::c_void) -> i32;
    fn SetFocus(hwnd: *mut core::ffi::c_void) -> *mut core::ffi::c_void;
    fn GetForegroundWindow() -> *mut core::ffi::c_void;
    fn AttachThreadInput(id_attach: u32, id_attach_to: u32, attach: i32) -> i32;
    fn AllowSetForegroundWindow(process_id: u32) -> i32;
}

static HANDLE: Mutex<Option<usize>> = Mutex::new(None);

struct TargetWindow {
    hwnd: *mut core::ffi::c_void,
    pid: u32,
}

unsafe extern "system" fn enum_windows_callback(
    hwnd: *mut core::ffi::c_void,
    lparam: isize,
) -> i32 {
    let result = &mut *(lparam as *mut Option<TargetWindow>);
    let cur_pid = GetCurrentProcessId();
    let mut pid: u32 = 0;
    GetWindowThreadProcessId(hwnd, &mut pid);

    if pid == 0 || pid == cur_pid {
        return 1;
    }

    if !GetWindow(hwnd, GW_OWNER).is_null() {
        return 1;
    }

    let mut matches = false;

    let len = GetWindowTextLengthW(hwnd);
    if len > 0 {
        let mut buf = vec![0u16; (len + 1) as usize];
        let read = GetWindowTextW(hwnd, buf.as_mut_ptr(), len + 1);
        if read > 0 {
            let title = String::from_utf16_lossy(&buf[..read as usize]);
            let lower = title.to_lowercase();
            if lower.contains("happycrate") {
                matches = true;
            }
        }
    }

    if !matches {
        let h_proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if !h_proc.is_null() {
            let mut name_buf = [0u16; 1024];
            let mut size = name_buf.len() as u32;
            if QueryFullProcessImageNameW(h_proc, 0, name_buf.as_mut_ptr(), &mut size) != 0 {
                let path = String::from_utf16_lossy(&name_buf[..size as usize]);
                let lower = path.to_lowercase();
                if lower.ends_with("happycrate.exe") || lower.ends_with("happycrate") {
                    matches = true;
                }
            }
            CloseHandle(h_proc);
        }
    }

    if matches {
        *result = Some(TargetWindow { hwnd, pid });
        return 0;
    }

    1
}

pub fn activate_existing_instance() -> bool {
    let mut found: Option<TargetWindow> = None;
    unsafe {
        EnumWindows(
            enum_windows_callback,
            &mut found as *mut Option<TargetWindow> as isize,
        );
    }

    let Some(target) = found else {
        log::info(log::SINGLE, "未找到已有实例的可见窗口");
        return false;
    };

    unsafe {
        AllowSetForegroundWindow(target.pid);

        let fg_hwnd = GetForegroundWindow();
        let cur_thread = GetCurrentThreadId();
        let fg_thread = if !fg_hwnd.is_null() {
            GetWindowThreadProcessId(fg_hwnd, std::ptr::null_mut())
        } else {
            0
        };
        let target_thread = GetWindowThreadProcessId(target.hwnd, std::ptr::null_mut());

        if fg_thread != 0 && fg_thread != cur_thread {
            AttachThreadInput(cur_thread, fg_thread, 1);
        }
        if target_thread != 0 && target_thread != cur_thread {
            AttachThreadInput(cur_thread, target_thread, 1);
        }

        if IsIconic(target.hwnd) != 0 {
            ShowWindow(target.hwnd, SW_RESTORE);
        } else {
            ShowWindow(target.hwnd, SW_SHOW);
        }

        BringWindowToTop(target.hwnd);
        SetForegroundWindow(target.hwnd);
        SetFocus(target.hwnd);

        if fg_thread != 0 && fg_thread != cur_thread {
            AttachThreadInput(cur_thread, fg_thread, 0);
        }
        if target_thread != 0 && target_thread != cur_thread {
            AttachThreadInput(cur_thread, target_thread, 0);
        }
    }

    log::info(
        log::SINGLE,
        &format!("已将已有实例窗口 (PID: {}) 唤起至前台", target.pid),
    );
    true
}

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
            log::info(log::SINGLE, "检测到已有实例（互斥体已存在），激活窗口并退出");
            activate_existing_instance();
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
