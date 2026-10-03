# happycrate 作业规程（Rust 重写版）

`D:\AI\happycrate` 的 Rust 重写版：Rust + Tauri 2 后端，前端 `web/` 从原项目整份带走。
**目录叫 `happycrate-rust` 只是为了跟老 Python 仓并存；产品名、包名、可执行文件名一律叫 `happycrate`。**
仓库现状、依赖理由与版本史在 `PLAN.md`，本文件只讲规矩。

**当前阶段：v1.0.3 已发布，本仓已是 GitHub 上的主线** —— `GVHBOX/Happycrate` 的 `main`
已被本仓强制覆盖（2026-09-29），Python 版源码在远端只剩 tag `v1.0.0`（指向首发根提交）。
本地 `D:\AI\happycrate` 仍保有 Python 版全部提交。详见 `PLAN.md` §1。

工作分支就是 `main`，直接推。`rust-rewrite` 分支已删除，别再建同名的。

## 4 条铁律

### 1. 代码零注释

核心源码 = `src/`、`tests/`、`web/`：不写注释、不写 docstring，名字起清楚就行。
Rust 的 `///` 与 `//!` 也算注释，一样禁止。

`tools/` 不算核心源码，那里的 docstring / 注释照常写，别去清理。
例外只有：工具指令、被运行时真正读取的字符串。
用 `#[derive]` 之类的属性、`#[allow(...)]` 不算注释，不在管辖内。
整理存量代码时，已有注释是清除对象（只清核心源码里的）。

**机器强制**：`tools/scan_comment.py`（`--selfcheck` 走校准件反向注入）。
校准件在 `tools/fixture-comments/`：`clean.rs` 里的 URL、raw string、字符字面量、生命周期
都不得误报，`dirty.rs` 的 6 行必须命中。

```bash
python tools/scan_comment.py            # 输出 JSON，全空 = 绿
python tools/scan_comment.py --selfcheck
```

### 2. 克制白描，说人话（界面、文档与日志）

核心哲学：**客观、克制、白描**。只陈述事实与结果，不加戏、不教导、不向上汇报，坚决摒弃技术装腔。
本条适用于所有给人看的文字：UI 界面、命令行提示、Toast/弹窗、文档 README、诊断日志。

1. **拒绝概念通胀，禁止大词包装**：
   - 严禁堆砌营销级与绝对化修饰词（如“极致”、“彻底”、“神级”、“企业级”、“物理级”）。
   - 讲机制不讲噱头：写真实机制，不造玄学大词；用最平实的工程事实陈述，自信源于代码本身，不靠形容词壮胆。
2. **结果导向，禁止报备与邀功**：
   - 界面、回执与 Toast 只告诉用户「最终结果」，不向上级汇报内部执行路径（严禁写“已调用底层接口触发…”、“服务正自动拉起…”）。
   - 报错只讲具体阻断原因，严禁掺杂自我安抚与免责式废话（如“操作已中止，核心系统未受任何影响”）。
   - 动词与短语一律用白话通识（“启动/停止/重启/退出”），禁止生造冷门借代词（如把“重启”写成“回收”，把“后台独立运行”写成“脱机运行”）。
3. **日志具备诊断价值，拒绝表演式输出**：
   - 诊断日志的唯一意义是**事后排查与故障定位**，只记录确定性事实：时间、对象、PID/端口/路径、状态码、关键耗时、错误原文。
   - 严禁打印毫无信息增益的赛博表演日志（如一连串“XX 模块就绪”、“通道已启用”、“守护逻辑已载入”）。
4. **界面零说明字（Zero UI Noise）**：
   - 界面只写「它是什么（字段/状态）」和「出了什么问题（错误具体原因）」，坚决不写「怎么用（引导/解释/教导）」。禁止解释性与引导性文字。
   - 允许五类：字段名 · 必填标记 `*` · 出错的具体原因 · 禁用态的原因 · 空状态占位文案。示范格式用 placeholder，不加说明行。
   - 禁止：中文标签当字段名 · 括号挂解释 · 把 AI 排查细节摊给用户。
   - 两层出口 —— 用户层：名称 + 具体原因；AI 层：全量结构化数据、字段用英文（`key` / `count` / `ms` / `adapter`），走 `source_issues`。

**机器强制**：`python tools/check_front_hygiene.py`（静态扫描前端违规说明文案）。
注意它是**关键词黑名单**，只挡已知说法；中英文都要过一遍（英文文案扫不到），新增文案仍要人工判断，别因为扫描绿了就放行。

### 3. 非源码一律进 `.scratch/`

报告、备份、脚本、截图、数据导出、临时中间物全进 `.scratch/`。根目录只允许：
源码（`src/`、`tests/`）、资源（`web/`、`assets/`）、仓库元文件（`README.md`、`LICENSE`、
`Cargo.toml`、`Cargo.lock`、`tauri.conf.json`、`capabilities/`、
`build.rs`、`.gitignore`、`tools/`、`AGENTS.md`、`PLAN.md`）、`examples/`、`target/`、`gen/`、
`data/`（**debug 版跑出来的数据目录**，见下，已在 `.gitignore` 里）。

`gen/` 是 `tauri-build` 每次编译生成的 schema，已进 `.gitignore`，不要手改。
`assets/icon.ico` 由 `python tools/make_icon.py` 从 `web/assets/app-256.png` 派生——
**那是用户自己设计的图标，只装容器，不重画不缩放**。`assets/` 里另有 README 用的
截图 `ui_screenshot.png` 与演示视频 `core_features_preview.mp4`（README 引用）。改图标路径时记得同步 `tauri.conf.json` 的 `bundle.icon`。

- `.scratch/` 整体不进版本库（成品报告也一样）；交付用原生 Windows 路径 `D:\...`，不用 `/d/...`。
- **不往 `.workbuddy/` 写东西，也不重建它。**
- **不写跨会话的记忆 / 日志文件。** 权威在 `AGENTS.md` 与 `PLAN.md`。

### 4. 网络与代理

本机是**系统代理**（`http://127.0.0.1:7890`），不是 TUN。
Rust 侧 `reqwest` **不读 Windows 系统代理**，必须显式构造代理；
`cargo` 与 fixture 采集脚本也一样，走 `HTTPS_PROXY` / `HTTP_PROXY` 环境变量。

**排查网络问题前先问用户，不要自己反复试。** 原因跨好几层（目标站点 / 代理工具 /
TUN 还是系统代理 / PAC / 安全软件 / 地区封锁），只有用户知道。
顺序：一次实测拿错误原文（`Tunnel 502` / `451` / `timed out`）→ 连「网络出口显示什么 +
浏览器能不能开」一起告诉用户 → 等确认。
禁止：反复试探、反复重装 Runtime、把环境问题当成代码问题改代码。

## 迁移纪律

- **不发明。** 任何行为改动先对照 Python 侧金样（`tests/fixtures/`、`tests/parity/`）。
  顺手重构会让金样 diff 无法判断「是重写错了还是重构改的」。
- **Python 版已下线**（2026-09-29 用户拍板切换，并行期跳过）；
  本地 `D:\AI\happycrate` 保留全史，仅作行为参照，不再改动。
- 加了依赖要在 `PLAN.md` §2 写理由。

## 测试与检查

```bash
cargo test                              # 金样 + 工具函数对照
python tools/scan_comment.py            # 铁律 1
python tools/scan_comment.py --selfcheck
python tools/check_front_hygiene.py     # 铁律 2
```

- **金样 diff 才是验收**：`cargo test` 绿只说明类型对，不说明行为对。
  这个项目 90% 的坑在行为上（12 个站点适配器的 quirk）。
- **空金样是假的绿。** 条数为 0 的 golden.json 解析器写错也照样通过。
  新增源时人工确认条数显著大于 0 且覆盖多条响应，别只看测试是绿的。
- 金样表与工具函数对照表都由 Python 侧生成，**不手写**：
  - `tools/capture_fixtures.py` → `tests/fixtures/`
  - `tools/legacy_generators/gen_*.py` → `tests/parity/*.json`（一个模块一份对照表）
  - `tools/legacy_generators/gen_search_pipeline.py` → `tests/parity/search_pipeline.json`
    （整条搜索流水线的事件序列，最贵的一份，3 MB）
  - `tools/legacy_generators/gen_migrate_parity.py` → `tests/legacy/` + `tests/parity/migrate_cases.json`
    （老配置迁移；老目录是**合成**的边角样本，不搬用户真实数据进仓库）
- **前端排障工具**：`web/js/diagnostics.js` 为前端运行时错误收集器，由快捷键 `Ctrl+Shift+D` 呼出，界面不设常驻按钮，不是未清理遗留物。
- **真实数据兼容性**用 `tools/check_data_compat.py <写到哪> [参照]`：
  拿 Python 自己的 config/settings 去加载 Rust 写过的目录，再看逐键差异。
  **不要比字节**——Rust 侧 serde 的键是排序过的，Python 保持插入序，文件名内容都合法。
- **日志**：`<数据目录>/logs/happycrate.log`，1 MB × 3 轮转，格式与 Python 版一致
  （`2026-09-28 20:57:35 [INFO] happycrate.app.api: …`）。
  级别用环境变量 `HAPPYCRATE_LOG_LEVEL`（DEBUG/INFO/WARNING/ERROR）。
  **只搬了应用级日志**（启动、缓存命中、放松检索、每个源的结果/失败、代理/验证码降级、
  配置读写、迁移、单实例）——12 个适配器内部那些「退回 RSS / 有 N 页失败」的细分提示
  **没有搬**，这是刻意的子集。

- **交付真实性与热更新进程接管授权（防假交付）**：
  核心原则：**「代码写完」不等于「生效交付」**。在桌面应用、后台服务与常驻守护进程开发中，用户通常习惯将程序固定到系统快捷入口或便携目录直接唤起即测。必须以**目标路径的二进制产物完成原位物理覆盖、且加载运行最新代码**为交付闭环。严禁新建别名副本（如 `_new.exe`）或仅将产物留在临时构建目录。
  1. **严格区分「源码编辑」与「运行态生效」**：严禁将“代码已修改”等同于“已生效完成”。
  2. **热更新进程接管授权（主动解除文件锁与端口占用）**：
     - **正式接管授权**：在编译生成或原位覆盖目标二进制（`target/release/happycrate.exe`）时，若遭遇旧实例正在运行引发的文件锁（Windows `WinError 32` / `Device or resource busy` / `LNK1104`），**AI 获得正式授权主动接管并终止占用资源的旧进程**（精准定位目标 PID 执行 `taskkill /PID <pid> /F` 或对应系统命令）。
     - **原位物理覆盖**：解除占用后，必须立即完成原目标路径文件的原位物理覆盖写入，确保用户调起直接是最新构建产物。
     - **严格限定接管边界**：仅限终止由本项目自身构建运行的旧版进程，严禁扩大范围，绝不触碰用户宿主环境或其他系统关键进程。
     - **如实通报执行结果**：触发接管后，回执中必须如实陈述事实（例如 `已自动终止旧版进程（PID: xxx）并完成原位覆盖交付`）。
  3. **验收凭证原则（拒绝幽灵验证）**：自测必须有新产物运行的确定性证据（如新 PID、新启动日志、最新文件时间戳），严禁在旧进程残余输出上做假验证。
- **干净克隆验收门（Clean Clone Test）**：
  发布前验收靠：`cargo check` 零警告 + **干净克隆能编**（在空目录 `git clone` 后编译，能过才算没把构建必需文件漏在仓库外）。

```bash
# 采集 / 重采 fixture（要用 happycrate 的 venv，因为要 import app 包）
cd /d D:\AI\happycrate
.venv\Scripts\python.exe D:\AI\happycrate-rust\tools\capture_fixtures.py
.venv\Scripts\python.exe D:\AI\happycrate-rust\tools\capture_fixtures.py --query=nyaa:frieren nyaa
.venv\Scripts\python.exe D:\AI\happycrate-rust\tools\legacy_generators\gen_util_parity.py
```

## 环境事实

- **怎么起给人用的测试版**：`cargo build --release` 之后**直接跑 exe**——
  `target\release\happycrate.exe`（`cargo run --release` 等价）。
  走的是**便携模式**，数据在 exe 旁边的 `data\`：`target\release\data`。
  **不需要环境变量，也不需要启动器脚本**（曾经做过一个 .bat，用户明确不要）。
  `.scratch\test-data` 是真实配置的母本副本，`target\release\data` 铺一份给 exe 直跑用
  （debug 编译用仓库根 `data\`，见下条，不用铺）。
  **`cargo clean` 会把 target 里的配置一起清掉**（`cargo build` 不会），重铺就是从母本再复制一次。
- **debug 版的数据目录是仓库根的 `data\`，不是 `target\debug\data\`**：
  `paths::program_dir()` 在 debug 下返回 `CARGO_MANIFEST_DIR`（`paths.rs` 里写死的），
  所以便携目录 = `<仓库>\data`。这是照 Python 的语义来的（源码运行 → 包目录旁边）。
  `cargo run`（不加 `--release`）用的是这一份，跟 exe 直跑不是同一个目录，别被绕晕。
  这个目录已进 `.gitignore`。
- Rust 1.98.1 + MSVC（`~/.cargo/bin`）。Bash 里跑 cargo 要先
  `export PATH="/c/Users/GVH/.cargo/bin:$PATH"`。
- Bash 工具的 PATH 被破坏，每条命令前要
  `export PATH="/c/Users/GVH/.workbuddy/binaries/PortableGit/versions/1.2.0/usr/bin:$PATH"`。
- **验证窗口内的东西要走 CDP**：`tools/cdp_eval.mjs` 用 WebView2 的远程调试口
  在页面里跑一段 JS。起应用时带上两个环境变量：

  ```
  HAPPYCRATE_DATA_DIR=<种子目录>          # 铁律：绝不指向真实数据目录
  WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222
  ```

  然后 `node tools/cdp_eval.mjs 9222 '<JS 表达式>'`。
  这是唯一能验证「前端能不能真调到后端」的手段——单元测试覆盖不到 Tauri 的参数编组与
  `withGlobalTauri` 是否生效。**每次起应用都要先设 `HAPPYCRATE_DATA_DIR`**，
  否则一次点击就写脏真实配置。
- **E2E 要真的走界面**：想验搜索就别直接调 `HC.api.startSearch`，那绕过了视图层。
  正确做法是先在页面里包一层记录器，再往搜索框里回车：

  ```js
  ["__onSearchStart","__onSearchSource","__onSearchBatch","__onSearchSettled","__onSearchDone"]
    .forEach(function(k){ var o = window[k];
      window[k] = function(d){ window.__rec.push({h:k.substring(2), d:d}); return o.apply(null, arguments); }; });
  document.getElementById("heroInp").value = "ubuntu";
  document.getElementById("heroInp").onkeydown({key: "Enter"});
  ```

  记录器存的事件名**不带 `__`**（`k.substring(2)`），复查时别再写成 `__onSearchSource`。
  截界面走 CDP 的 `Page.captureScreenshot`（`cdp_eval.mjs` 只能求值，截图要单写一段）。
- **回放不看请求头**：fixture 回放只按 (url, 请求体) 取响应，`Referer`、`Accept`、
  `Accept-Language`、`Content-Type` 写错它一律不报。**这类缺陷只有真机对照能抓**
  （已经栽过一次：漏了 `Accept-Language`，knaben 从 8 秒变 49 秒，条数却一模一样）。
  改客户端默认头之后，跑一次 `cargo run --release --example live_smoke` 比耗时。
- **Bash 工具的 heredoc 会吃掉一层反斜杠**（`<<'EOF'` 这种带引号的也一样）：
  两个反斜杠变成一一个。后果是 Python / Rust 里的转义序列被静默改写——
  Unicode 码点转义直接语法错误，字符字面量里的转义让 Rust 报「只能有一个字符」。
  **规则：不在 heredoc 里写任何反斜杠**——用编辑工具写文件，或改用
  `std::path::MAIN_SEPARATOR` 这类常量绕开。
- **沙箱批量删除阈值 50 个文件**：采集脚本一次跑 12 个源会触发。
  所以 `capture_fixtures.py` **不清理旧响应体**——`meta.json` 是唯一真相源，
  回放只看它列出的文件，遗留的不会被引用。
- **依赖克制**：允许的依赖清单与理由在 `PLAN.md` §2，**看表，不在这里抄**。
  已经明确不引：`regex`（不支持 lookaround）· 日期库 · HTML 实体库 · `scraper`/`html5ever`
  · `anyhow`。加依赖要在 §2 补理由。
- **`web/` 是复制来的，要立刻冻结原项目的 `web/`**，改动只在 Rust 仓做。
  确认没漂：`diff -rq "D:/AI/happycrate-rust/web" "D:/AI/happycrate/web"`。
- **单实例 mutex 已换名**：Rust 版用 `Local\happycrate_rust_v1_SingleInstance_...`（带 `_rust`），
  与 Python 版的 `Local\happycrate_v1_SingleInstance_7d4a9e2c6b1f8053` 区分，不会互抢。

## 边界

不涉及账号体系：不登录、不保存站点用户名或令牌。迅雷只是被唤起的下载工具，
登录与配额由它自己处理。
