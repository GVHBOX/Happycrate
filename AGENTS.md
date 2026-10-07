# happycrate 作业规程（Rust 版）

全量自包含 Rust + Tauri 2，前端 `web/` 编译期内嵌。产品名、包名、可执行文件名一律叫 `happycrate`。
依赖清单与理由、版本史在 `PLAN.md`，本文件只讲规矩。
当前版本 1.0.4，`GVHBOX/Happycrate` 的 `main` 是唯一主线，工作分支就是 `main`，直接推。

## 4 条铁律

### 1. 代码零注释

核心源码 = `src/`、`tests/`、`web/`：不写注释、不写 docstring，名字起清楚就行。
Rust 的 `///` 与 `//!` 也算注释，一样禁止。
`tools/` 不算核心源码，注释照常写，别去清理。例外只有：工具指令、被运行时真正读取的字符串。
`#[derive]` 之类的属性、`#[allow(...)]` 不算注释。

**机器强制**：`tools/scan_comment.py`。校准件在 `tools/fixture-comments/`：
`clean.rs` 的 URL、raw string、字符字面量、生命周期不得误报，`dirty.rs` 的 6 行必须命中。

```bash
python tools/scan_comment.py            # 输出 JSON，全空 = 绿
python tools/scan_comment.py --selfcheck
```

### 2. 克制白描，说人话（界面、文档与日志）

客观、克制、白描：只陈述事实与结果，不加戏、不教导、不向上汇报。
适用于所有给人看的文字：UI、命令行提示、Toast/弹窗、README、诊断日志。

- 禁止营销级与绝对化修饰词（“极致”、“企业级”之类），不造玄学大词，用平实的工程事实陈述。
- 界面与回执只讲最终结果，不报备内部执行路径；报错只讲具体阻断原因，不带自我安抚与免责废话；
  动词用白话（启动/停止/重启/退出），不生造借代词（“回收”=重启、“脱机”=后台运行，都是反例）。
- 日志只为事后排查：时间、对象、PID/端口/路径、状态码、关键耗时、错误原文。
  禁止表演式输出（“XX 模块就绪”、“通道已启用”）。
- 界面零说明字：只写「它是什么（字段/状态）」和「出了什么问题」。
  允许五类：字段名、必填 `*`、出错具体原因、禁用态原因、空状态占位（示范用 placeholder，不加说明行）。
  禁止解释引导、括号挂解释、把 AI 排查细节摊给用户。
  AI 层出口走 `source_issues`：全量结构化，字段英文（`key` / `count` / `ms` / `adapter`）。

**机器强制**：`python tools/check_front_hygiene.py`。
它是关键词黑名单，英文文案扫不到，新增文案仍要人工判断。

### 3. 非源码一律进 `.scratch/`

报告、备份、脚本、截图、数据导出、临时中间物全进 `.scratch/`，不进版本库；
交付用原生 Windows 路径 `D:\...`，不用 `/d/...`。
根目录只允许：`src/`、`tests/`、`web/`、`assets/`、`tools/`、`examples/`、`capabilities/`、
`build.rs`、`Cargo.toml`、`Cargo.lock`、`tauri.conf.json`、`README.md`、`LICENSE`、
`AGENTS.md`、`PLAN.md`、`.gitignore`、`data/`（debug 数据目录，gitignored）、`target/`、`gen/`。
`gen/` 是 tauri-build 每次编译生成的 schema，勿手改。
`assets/icon.ico` 由 `python tools/make_icon.py` 从 `web/assets/app-256.png` 派生——
用户自己设计的图标，只装容器，不重画不缩放；改图标路径时同步 `tauri.conf.json` 的 `bundle.icon`。
`assets/` 另有 README 引用的 `ui_screenshot.png` 与 `core_features_preview.mp4`。
不往 `.workbuddy/` 写东西，也不重建它。
不写跨会话的记忆/日志文件，权威在本文件与 `PLAN.md`。

### 4. 网络与代理

本机是系统代理（`http://127.0.0.1:7890`），不是 TUN。
Rust 侧 `reqwest` 不读 Windows 系统代理，必须显式构造；
`cargo` 与 fixture 采集脚本走 `HTTPS_PROXY` / `HTTP_PROXY`。
排查网络问题先问用户，不要自己反复试：
一次实测拿错误原文（`Tunnel 502` / `451` / `timed out`）→
连「网络出口显示什么 + 浏览器能不能开」一起报给用户 → 等确认。
禁止：反复试探、反复重装 Runtime、把环境问题当成代码问题改代码。

## 维护纪律

- 不随意发明：任何行为改动先过固化金样（`tests/fixtures/`、`tests/parity/`）回归。
- 加依赖要在 `PLAN.md` §2 写理由。
  已明确不引：`regex`（不支持 lookaround）、日期库、HTML 实体库、`scraper`/`html5ever`、`anyhow`。

## 测试与检查

```bash
cargo test                              # 金样 + 工具函数对照
python tools/scan_comment.py            # 铁律 1
python tools/scan_comment.py --selfcheck
python tools/check_front_hygiene.py     # 铁律 2
```

- **金样 diff 才是验收**：`cargo test` 绿只说明类型对，90% 的坑在行为上（12 个站点适配器的 quirk）。
- **空金样是假的绿**：条数为 0 的 golden.json 解析器写错也照样通过；
  新增源人工确认条数显著大于 0 且覆盖多条响应。
- 金样与对照表全部固化在仓：`tests/fixtures/`（12 源原始响应与期望解析）、
  `tests/parity/*.json`（各模块对照，含 `search_pipeline.json` 流水线事件序列）、
  `tests/legacy/` + `tests/parity/migrate_cases.json`（老配置迁移样本）。
- 前端排障：`web/js/diagnostics.js`，`Ctrl+Shift+D` 呼出，无常驻按钮，非遗留物。
- 日志：`<数据目录>/logs/happycrate.log`，1 MB × 3 轮转
  （`2026-09-28 20:57:35 [INFO] happycrate.app.api: …`），级别用 `HAPPYCRATE_LOG_LEVEL`。
  只记应用级事件（启动、缓存命中、放松检索、每源结果/失败、代理/验证码降级、配置读写、迁移、单实例）；
  适配器内部细分提示（退回 RSS、N 页失败）刻意不记。
- **交付真实性（防假交付）**：「代码写完」不等于「生效交付」，
  交付闭环 = 目标路径二进制完成**原位物理覆盖**且运行最新代码；
  严禁别名副本（`_new.exe`）与产物滞留临时构建目录。
  覆盖 `target/release/happycrate.exe` 遇旧实例文件锁（`WinError 32` / `LNK1104`）时，
  **已获授权**精准 taskkill 本项目自身构建的旧进程后立即原位覆盖，并如实回执（含 PID）；
  不得扩大到宿主环境其他进程。
  自测必须有新产物运行的证据（新 PID、新启动日志、新时间戳），严禁在旧进程残余输出上假验证。
- 发布验收：`cargo check` 零警告 + 干净克隆能编。

## 环境事实

- 起给人用的测试版：`cargo build --release` 后直接跑 `target\release\happycrate.exe`
  （便携模式，数据在 exe 旁 `data\`）。不需要环境变量，不需要启动器脚本（用户明确不要）。
- **`cargo clean` 会把 `target\release\data`（exe 的现行配置）一起清掉**（`cargo build` 不会）。
  配置丢了应用会按代码默认值自动重建，手工只需补两处：bitsearch 源的开关与排序、
  `progress_look` 进度条配色。
- debug 版数据目录是仓库根 `data\`：`paths::program_dir()` 在 debug 下返回
  `CARGO_MANIFEST_DIR`（`paths.rs` 写死），`cargo run`（不带 `--release`）用这一份，
  与 exe 直跑不是同一目录。
- Rust 1.98.1 + MSVC。Bash 工具 PATH 被破坏，每条命令前：
  `export PATH="/c/Users/GVH/.workbuddy/binaries/PortableGit/versions/1.2.0/usr/bin:/c/Users/GVH/.cargo/bin:$PATH"`
  （后者是 cargo 用的）。
- **验证窗口内行为走 CDP**：`node tools/cdp_eval.mjs 9222 '<JS 表达式>'`，起应用前设两个环境变量：

  ```
  HAPPYCRATE_DATA_DIR=<种子目录>          # 铁律：绝不指向真实数据目录
  WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222
  ```

  这是唯一能验证「前端能不能真调到后端」的手段（单元测试覆盖不到 Tauri 参数编组与
  `withGlobalTauri`）。每次起应用都要先设 `HAPPYCRATE_DATA_DIR`，否则一次点击就写脏真实配置。
- **E2E 要真走界面**：别直接调 `HC.api.startSearch`，先在页面里包一层记录器，再往搜索框回车：

  ```js
  ["__onSearchStart","__onSearchSource","__onSearchBatch","__onSearchSettled","__onSearchDone"]
    .forEach(function(k){ var o = window[k];
      window[k] = function(d){ window.__rec.push({h:k.substring(2), d:d}); return o.apply(null, arguments); }; });
  document.getElementById("heroInp").value = "ubuntu";
  document.getElementById("heroInp").onkeydown({key: "Enter"});
  ```

  记录器存的事件名**不带 `__`**。截图走 CDP 的 `Page.captureScreenshot`（cdp_eval.mjs 只能求值）。
- **回放不看请求头**：fixture 回放只按 (url, 请求体) 取响应，
  `Referer`/`Accept`/`Accept-Language`/`Content-Type` 写错一律不报；
  这类缺陷只有真机对照能抓（漏了 `Accept-Language` 让 knaben 从 8 秒变 49 秒）。
  改客户端默认头后跑 `cargo run --release --example live_smoke` 比耗时。
  网络诊断可用 `cargo run --example net_probe`（打印代理来源、绕过表、TUN 适配器）。
- **Bash 工具的 heredoc 会吃掉一层反斜杠**（带引号的 `<<'EOF'` 也一样）：
  不在 heredoc 里写任何反斜杠，用编辑工具写文件，或用 `std::path::MAIN_SEPARATOR` 这类常量绕开。
- `web/` 前端完全在此仓维护。

## 边界

不涉及账号体系：不登录、不保存站点用户名或令牌。迅雷只是被唤起的下载工具，
登录与配额由它自己处理。
