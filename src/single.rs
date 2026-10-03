use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;
use std::sync::Mutex;

use crate::log;

pub const MUTEX_NAME: &str = "Local\\happycrate_rust_v1_SingleInstance_7d4a9e2c6b1f8053";
pub const HWND_MAP_NAME: &str = "Local\\happycrate_rust_v1_Hwnd_7d4a9e2c6b1f8053";
pub const PROP_NAME: &str = "Happycrate_MainWindow_7d4a9e2c6b1f8053";

const ERROR_ALREADY_EXISTS: u32 = 183;
const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
const PAGE_READWRITE: u32 = 0x04;
const FILE_MAP_ALL_ACCESS: u32 = 0x000F001F;
const FILE_MAP_READ: u32 = 0x0004;
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
    fn CreateFileMappingW(
        file: *mut core::ffi::c_void,
        attributes: *mut core::ffi::c_void,
        protect: u32,
        max_size_high: u32,
        max_size_low: u32,
        name: *const u16,
    ) -> *mut core::ffi::c_void;
    fn OpenFileMappingW(
        desired_access: u32,
        inherit_handle: i32,
        name: *const u16,
    ) -> *mut core::ffi::c_void;
    fn MapViewOfFile(
        file_mapping: *mut core::ffi::c_void,
        desired_access: u32,
        file_offset_high: u32,
        file_offset_low: u32,
        number_of_bytes_to_map: usize,
    ) -> *mut core::ffi::c_void;
    fn UnmapViewOfFile(base_address: *const core::ffi::c_void) -> i32;
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
    fn IsWindow(hwnd: *mut core::ffi::c_void) -> i32;
    fn IsIconic(hwnd: *mut core::ffi::c_void) -> i32;
    fn ShowWindow(hwnd: *mut core::ffi::c_void, cmd_show: i32) -> i32;
    fn SetForegroundWindow(hwnd: *mut core::ffi::c_void) -> i32;
    fn BringWindowToTop(hwnd: *mut core::ffi::c_void) -> i32;
    fn SetFocus(hwnd: *mut core::ffi::c_void) -> *mut core::ffi::c_void;
    fn GetForegroundWindow() -> *mut core::ffi::c_void;
    fn AttachThreadInput(id_attach: u32, id_attach_to: u32, attach: i32) -> i32;
    fn AllowSetForegroundWindow(process_id: u32) -> i32;
    fn SetPropW(
        hwnd: *mut core::ffi::c_void,
        string: *const u16,
        data: *mut core::ffi::c_void,
    ) -> i32;
    fn GetPropW(
        hwnd: *mut core::ffi::c_void,
        string: *const u16,
    ) -> *mut core::ffi::c_void;
    fn RemovePropW(
        hwnd: *mut core::ffi::c_void,
        string: *const u16,
    ) -> *mut core::ffi::c_void;
}

static HANDLE: Mutex<Option<usize>> = Mutex::new(None);
static MAP_HANDLE: Mutex<Option<usize>> = Mutex::new(None);
static REGISTERED_HWND: Mutex<Option<usize>> = Mutex::new(None);

fn to_wide(s: &str) -> Vec<u16> {
    OsStr::new(s).encode_wide().chain(std::iter::once(0)).collect()
}

pub fn register_main_window(hwnd: *mut core::ffi::c_void) {
    if hwnd.is_null() {
        return;
    }
    unsafe {
        let wide_prop = to_wide(PROP_NAME);
        SetPropW(hwnd, wide_prop.as_ptr(), 1usize as *mut core::ffi::c_void);

        let wide_map = to_wide(HWND_MAP_NAME);
        let h_map = CreateFileMappingW(
            usize::MAX as *mut core::ffi::c_void,
            std::ptr::null_mut(),
            PAGE_READWRITE,
            0,
            8,
            wide_map.as_ptr(),
        );
        if !h_map.is_null() {
            let ptr = MapViewOfFile(h_map, FILE_MAP_ALL_ACCESS, 0, 0, 8);
            if !ptr.is_null() {
                *(ptr as *mut u64) = hwnd as usize as u64;
                UnmapViewOfFile(ptr);
            }
            if let Ok(mut g) = MAP_HANDLE.lock() {
                *g = Some(h_map as usize);
            }
        }
    }
    if let Ok(mut g) = REGISTERED_HWND.lock() {
        *g = Some(hwnd as usize);
    }
}

fn bring_hwnd_to_front(hwnd: *mut core::ffi::c_void) -> bool {
    unsafe {
        if IsWindow(hwnd) == 0 {
            return false;
        }

        let mut target_pid: u32 = 0;
        let target_thread = GetWindowThreadProcessId(hwnd, &mut target_pid);
        if target_pid != 0 {
            AllowSetForegroundWindow(target_pid);
        }

        let fg_hwnd = GetForegroundWindow();
        let cur_thread = GetCurrentThreadId();
        let fg_thread = if !fg_hwnd.is_null() {
            GetWindowThreadProcessId(fg_hwnd, std::ptr::null_mut())
        } else {
            0
        };

        if fg_thread != 0 && fg_thread != cur_thread {
            AttachThreadInput(cur_thread, fg_thread, 1);
        }
        if target_thread != 0 && target_thread != cur_thread {
            AttachThreadInput(cur_thread, target_thread, 1);
        }

        if IsIconic(hwnd) != 0 {
            ShowWindow(hwnd, SW_RESTORE);
        } else {
            ShowWindow(hwnd, SW_SHOW);
        }

        BringWindowToTop(hwnd);
        SetForegroundWindow(hwnd);
        SetFocus(hwnd);

        if fg_thread != 0 && fg_thread != cur_thread {
            AttachThreadInput(cur_thread, fg_thread, 0);
        }
        if target_thread != 0 && target_thread != cur_thread {
            AttachThreadInput(cur_thread, target_thread, 0);
        }
    }
    true
}

unsafe extern "system" fn enum_windows_callback(
    hwnd: *mut core::ffi::c_void,
    lparam: isize,
) -> i32 {
    let result = &mut *(lparam as *mut Option<*mut core::ffi::c_void>);
    let cur_pid = GetCurrentProcessId();
    let mut pid: u32 = 0;
    GetWindowThreadProcessId(hwnd, &mut pid);

    if pid == 0 || pid == cur_pid {
        return 1;
    }

    if !GetWindow(hwnd, GW_OWNER).is_null() {
        return 1;
    }

    let wide_prop = to_wide(PROP_NAME);
    if GetPropW(hwnd, wide_prop.as_ptr()) as usize == 1 {
        *result = Some(hwnd);
        return 0;
    }

    let h_proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
    if h_proc.is_null() {
        return 1;
    }
    let mut name_buf = [0u16; 1024];
    let mut size = name_buf.len() as u32;
    let ok = QueryFullProcessImageNameW(h_proc, 0, name_buf.as_mut_ptr(), &mut size);
    CloseHandle(h_proc);

    if ok == 0 {
        return 1;
    }

    let path = String::from_utf16_lossy(&name_buf[..size as usize]);
    let lower_path = path.to_lowercase();
    if !lower_path.ends_with("happycrate.exe") {
        return 1;
    }

    let len = GetWindowTextLengthW(hwnd);
    if len > 0 {
        let mut buf = vec![0u16; (len + 1) as usize];
        let read = GetWindowTextW(hwnd, buf.as_mut_ptr(), len + 1);
        if read > 0 {
            let title = String::from_utf16_lossy(&buf[..read as usize]);
            let lower_title = title.to_lowercase();
            if lower_title.contains("antigravity") || lower_title.contains("code") {
                return 1;
            }
        }
    }

    *result = Some(hwnd);
    0
}

pub fn activate_existing_instance() -> bool {
    let wide_map = to_wide(HWND_MAP_NAME);
    unsafe {
        let h_map = OpenFileMappingW(FILE_MAP_READ, 0, wide_map.as_ptr());
        if !h_map.is_null() {
            let ptr = MapViewOfFile(h_map, FILE_MAP_READ, 0, 0, 8);
            if !ptr.is_null() {
                let raw_hwnd = *(ptr as *const u64) as usize;
                UnmapViewOfFile(ptr);
                CloseHandle(h_map);
                if raw_hwnd != 0 {
                    let hwnd = raw_hwnd as *mut core::ffi::c_void;
                    if bring_hwnd_to_front(hwnd) {
                        log::info(log::SINGLE, "已通过共享内存定位并激活已有实例窗口");
                        return true;
                    }
                }
            } else {
                CloseHandle(h_map);
            }
        }
    }

    let mut found: Option<*mut core::ffi::c_void> = None;
    unsafe {
        EnumWindows(
            enum_windows_callback,
            &mut found as *mut Option<*mut core::ffi::c_void> as isize,
        );
    }

    if let Some(hwnd) = found {
        if bring_hwnd_to_front(hwnd) {
            log::info(log::SINGLE, "已通过窗口遍历定位并激活已有实例窗口");
            return true;
        }
    }

    log::info(log::SINGLE, "未找到已有实例的可见窗口");
    false
}

pub fn acquire() -> bool {
    let mut guard = match HANDLE.lock() {
        Ok(guard) => guard,
        Err(_) => return true,
    };
    if guard.is_some() {
        return true;
    }

    let wide = to_wide(MUTEX_NAME);

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
    if let Ok(mut g) = REGISTERED_HWND.lock() {
        if let Some(raw) = g.take() {
            unsafe {
                let wide_prop = to_wide(PROP_NAME);
                RemovePropW(raw as *mut core::ffi::c_void, wide_prop.as_ptr());
            }
        }
    }

    if let Ok(mut g) = MAP_HANDLE.lock() {
        if let Some(raw) = g.take() {
            unsafe {
                CloseHandle(raw as *mut core::ffi::c_void);
            }
        }
    }

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
