# happycrate 迁移方案（Rust 重写版）

**命名**：仓库目录 `D:\AI\happycrate-rust`（跟老 Python 仓 `D:\AI\happycrate` 区分），
但产品名 / Cargo 包名 / 可执行文件名一律 `happycrate`。

把 `D:\AI\happycrate` 的 Python 后端换成 **Rust + Tauri 2**，前端 `web/` 整体带走。
本文是施工方案，不是设计散文：每条都对应可执行的一步，每阶段有独立止损点。

---

## 0. 目标与不做什么

**做**：后端语言换成 Rust，宿主换成 Tauri 2，UI 与数据格式不变，老用户 `data/` 直接可用。

**不做**（写在这里是为了后面别临时加）：

- 不改 UI 结构、不换前端框架、不加构建步骤
- 不改三个 JSON 的格式（`sources.json` / `settings.json` / `health.json`）
- 不顺手重构适配器逻辑——先 1:1 复现，复现完了再谈优化
- 不新增搜索源、不改 outcome 分类体系

顺手重构是这次迁移最大的失败模式：它会让金样 diff 无法判断"是重写错了还是重构改的"。

---

## 1. 必须 1:1 复现的契约（Rust 侧照抄，不许发明）

### 1.1 结果条目结构（sources.py `_mk`）

```jsonc
{
  "title": "清洗后的标题",      // 空白折叠 + HTML 实体反转义
  "info_hash": "小写",          // 空串合法
  "size": 0,                    // int，解析失败归 0
  "seeders": null,              // int | null
  "leechers": null,             // int | null
  "added": null,                // int | null（时间戳）
  "source": "源 key",
  "magnet": "由 info_hash + title 拼出；无 hash 时为空串",
  "files": [...]                // 仅当有文件时才出现该字段
}
```

`files` 缺失与 `files: []` 语义不同，序列化时要区分（`Option<Vec<_>>`）。

### 1.2 `search_one` 返回契约

`(key, items, err, ms)`——`err` 是**面向用户的短文本**，不是 Rust 的 `Error`。
`ms` 是整数毫秒。出错时 `items` 为空列表，不得为 `null`。

### 1.3 16 种 outcome（`api.py`）

| 常量 | state | 触发 |
|---|---|---|
| `ok` | ok | 正常返回 |
| `empty` | empty | 返回 0 条 |
| `slow` | ok | 超过软截止仍未返回但最终成功 |
| `timeout` | err | 超时 |
| `net` | err | 网络不可达 / 代理不可达 |
| `http403` | err | 403 |
| `http429` | warn | 429 |
| `http5xx` | err | 5xx |
| `http4xx` | warn | 其他 4xx |
| `cancel` | na | 用户停止 |
| `parse` | warn | 解析出 0 条但页面非空 |
| `http451` | err | 451 地区封锁 |
| `blocked` | err | 人机验证墙 |
| `shape` | warn | 页面结构与预期不符 |
| `login` | warn | 登录墙 |
| `unknown` | warn | 兜底 |

**判定顺序必须与 Python 一致**——这是编译期帮不上忙的地方，只能靠金样测试。

### 1.4 12 个源

| key | 标签 | 分页 |
|---|---|---|
| `apibay` | 海盗湾 | pageless |
| `nyaa` | Nyaa | 分页 |
| `mikan` | 蜜柑计划 | pageless（RSS） |
| `dmhy` | 动漫花园 | pageless（RSS） |
| `sukebei` | Sukebei | 分页 |
| `eztv` | EZTV | pageless |
| `bitsearch` | BitSearch | 分页 |
| `knaben` | Knaben | 分页（JSON API） |
| `tpb` | TPB镜像 | 分页（镜像轮换） |
| `xccl263` | 小草磁力 | 分页 |
| `javbus` | JavBus | 分页（多词） |
| `javdb` | JavDB | 分页（登录墙） |

### 1.5 设置项（26 个键，含 min/max/choices 校验）

`ui_font_size` 的 choices 是 `[14, 18, 22]`，`min=12 / max=24` 只是夹取边界，**不是选项清单**。
校验失败的处理沿用现状：备份成 `.broken.json` 再回退默认，路径经 `app_info()["recovered"]` 出口。

### 1.6 数据目录解析顺序（`paths.py`）

1. 环境变量 `HAPPYCRATE_DATA_DIR` / `HAPPYCRATE_LOG_DIR`
2. 程序目录旁 `data/`（便携模式）
3. `%APPDATA%` 回退

三种模式下文件布局一致：`sources.json` / `settings.json` / `health.json` / `logs/` / 可选 `query_roles.json`。

---

## 2. 依赖清单（克制，每加一个都要写理由）

```toml
[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-single-instance = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
regex = "1"
url = "2"
reqwest = { version = "0.12", default-features = false,
            features = ["rustls-tls-native-roots", "gzip", "brotli"] }
tokio = { version = "1", features = ["sync", "macros"] }
windows = { version = "0.58", features = ["Win32_UI_WindowsAndMessaging",
            "Win32_System_Threading", "Win32_System_Registry",
            "Win32_Graphics_Dwm", "Win32_Foundation", "Win32_UI_Shell"] }
```

规则：

- **不引入 `scraper` / `html5ever`。** 理由：金样 diff 要的是与 Python 逐字段一致，
  换解析器等于主动制造差异；且体积 +3MB 起。沿用 Python 的正则，逐条平移。
- **不引入 `socks`。** Python 侧 urllib 只支持 http/https 代理，Rust 侧保持一致。
- **不引入 `anyhow`。** 适配器错误用 `enum SourceError`，让编译器逼你穷尽分支——
  这正是你选 Rust 想要的东西，别用 `anyhow` 把它抹掉。
- TLS 用 `rustls-tls-native-roots`（读系统根证书），不要 `webpki-roots`：
  这些站点证书链杂，内置根证书会误报。
- 单实例用插件，不自己写 mutex 逻辑（`tauri-plugin-single-instance` 已覆盖）。
- `windows` crate 只开用到的 feature，逐个开，别用全量。

---

## 3. 目录布局

```
D:\AI\happycrate-rust\
├─ Cargo.toml
├─ tauri.conf.json
├─ src\
│  ├─ main.rs          入口：tauri Builder + 19 个 command 注册
│  ├─ api.rs           command 实现（薄壳，转发到 domain 模块）
│  ├─ bridge.rs        push 通道
│  ├─ config.rs        settings schema / 校验 / 读写 / .broken.json 回退
│  ├─ paths.rs         数据目录解析
│  ├─ log.rs           文件日志
│  ├─ store.rs         health.json
│  ├─ migrate.rs       老格式迁移
│  ├─ query.rs         关键词词表 + query_roles.json 覆盖
│  ├─ net.rs           reqwest client：UA / 代理 / 超时 / SSL 降级 / TUN 探测
│  ├─ outcome.rs       16 种 outcome 判定与分类
│  ├─ core.rs          dedupe + 合并
│  ├─ search.rs        并发调度（JoinSet + CancellationToken）
│  ├─ shell.rs         无边框窗口 + WM_NCHITTEST + 窗口控制
│  ├─ downloader.rs    迅雷探测与投递
│  └─ sources\
│     ├─ mod.rs        注册表 + trait
│     └─ <12 个适配器>.rs
├─ web\                从 happycrate 复制，只改 api.js
├─ tests\
│  ├─ fixtures\        12 源 × 各态真实响应
│  └─ golden.rs        金样 diff
└─ PLAN.md
```

**单 crate，不拆 workspace。** 拆 crate 的唯一理由是编译变慢，等 release 构建超过 2 分钟再说。

### 模块映射（Python → Rust）

| Python | 行数 | Rust | 备注 |
|---|---:|---|---|
| `sources.py` | 2,426 | `sources/` 12 个文件 + `net.rs` | 高风险区，金样测试主战场 |
| `api.py` | 1,158 | `api.rs` + `search.rs` | 24 个方法，19 个暴露给前端 |
| `config.py` | 599 | `config.rs` | schema 直译 |
| `shell.py` | 327 | `shell.rs` + Tauri 配置 | 无边框 / 边缘拉伸 / 窗口控制 |
| `query.py` | 266 | `query.rs` | 词表直译 |
| `core.py` | 257 | `core.rs` | dedupe + 合并规则 |
| `paths.py` | 141 | `paths.rs` | 目录解析顺序照抄 |
| `migrate.py` | 138 | `migrate.rs` | 老版本格式迁移 |
| `log.py` | 117 | `log.rs` | |
| `single.py` | 105 | 插件 | 不再自己实现 |
| `downloaders/` | 393 | `downloader.rs` | COM 降级为进程启动，见 §6 |
| `store.py` / `runtime.py` | 44 | `store.rs` | |

---

## 4. 桥接层（前端改动量 = 22 处调用 + 2 处宿主）

### 4.1 调用方向（已完成）

`api.js` 的 live 分支：

```js
window.pywebview.api.list_sources().then(coerce)
```

改成：

```js
invoke("list_sources").then(coerce)
```

`window.HC.api.*` 的对外形状**保持不变**，所以 `search.js` / `settings.js` / `sources.js`
三个视图（合计 3,474 行）一行不动。

**实际暴露的 21 个 command**：

`list_sources` `toggle_source` `reorder_sources` `set_auto_order` `start_search`
`cancel_search` `torrent_files` `get_settings` `default_settings` `save_settings`
`reload_query_roles` `selftest` `app_info` `open_logs` `proxy_status` `downloaders`
`deliver` + 窗口类 4 个：`win_min` `win_max` `win_close` `set_window_tone`

比 Python 的 19 个多 `start_search` / `cancel_search`（原先漏数了），
少 `probe_sources` / `diagnostics` / `source_issues`（健康探测暂缓，见 §9.0.5）。

**`api.js` 里另有两处不能只改名字**：

- `live()` 的探测对象从 `window.pywebview.api.start_search` 换成 `window.__TAURI__.core.invoke`
  （`withGlobalTauri: true` 已在 `tauri.conf.json` 里开着）。**漏了这一步的后果不是报错，
  是静默走 mock 分支**——前端会拿假数据当真的显示。
- `index.html` 的拖拽区从 pywebview 的魔法类 `<div class="tb-drag pywebview-drag-region">`
  换成 `data-tauri-drag-region`，配套在 capability 里加 `core:window:allow-start-dragging`
  （drag region 走的是 IPC，受 ACL 管）。窗口按钮那 4 个是自定义 command，**不受 ACL 管**，
  所以 `core:default` 就够，不要去加一堆 `allow-minimize` 之类的。

### 4.2 推送方向（已完成）

7 个全局钩子：`__onProbe` `__onProbeDone` `__onSearchStart` `__onSearchSource`
`__onSearchBatch` `__onSearchSettled` `__onSearchDone`。

用 `WebviewWindow::eval()` 照抄现有 JS 字符串（`search::js_of`），这 7 个钩子一个字不改。
理由：先让 E2E 跑起来；换 Tauri Channel 前端要加 listen，是纯成本、没有用户可见收益——
**不换**。

---

## 5. Windows 宿主细节

| 能力 | Python 现状 | Rust 做法 |
|---|---|---|
| 无边框窗口 | Tauri `decorations: false` | 同 |
| 边缘拉伸 | `shell.py` ctypes 子类化 + `WM_NCHITTEST` | `windows` crate 做同样的 `SetWindowLongPtrW`，或 Tauri 的 `startResizeDragging`；**先用后者**，不够再上 Win32 |
| 单实例 | `kernel32` mutex | 插件 |
| TUN 探测 | `ipconfig` 子进程扫描，30s 缓存 | 同样跑 `ipconfig`，同样 30s 缓存；**确认它不在首屏路径上** |
| 迅雷投递 | COM `ThunderAgent.Agent.1`（首选）+ `ProtocolMethod`（兜底） | **只实现 ProtocolMethod**：`thunder.exe <magnet> -StartType:magnet`。见 §5.1 |
| 剪贴板 | pywebview / Python | Tauri 自带 |

### 5.1 迅雷 COM：已确认是死代码，直接删，零行为变化

本机只读探测（四个注册表视图全查：`HKCR`、`HKLM\Software\Classes`、
`HKLM\Software\WOW6432Node\Classes`、`HKCU\Software\Classes`）：

- ProgID `ThunderAgent.Agent.1` 存在，CLSID = `{485463B7-8FB2-4B3B-B29B-8B919B0EACCE}`
- 该 CLSID **只存在于 32 位视图** `WOW6432Node`，64 位视图与 HKCR 都查不到
- 它是 **`InprocServer32`**（`BHO\ThunderAgent10.1.27.624.dll`），不是 LocalServer32（EXE）
- 宿主进程是 **64 位**（Python 3.13.14 AMD64）

**64 位进程无法加载 32 位进程内 COM DLL**，且未注册 DllSurrogate。
→ 现状 `com_available()` 恒为 `False`，`ComMethod.available()` 恒假，
**现在 100% 走的是 `ProtocolMethod`**。删掉 COM 不改变任何行为。

顺带澄清：**"迅雷没开时拉起它并让它识别磁力链接"不是 COM 的功劳，是 `ProtocolMethod` 的**——
`Popen([thunder.exe, magnet, "-StartType:magnet"])` 直接启动主程序并传参，绕过 `magnet://`
协议关联，所以也不会被其他接管磁力的工具干扰。这个能力在 Rust 侧原样保留。

### 5.2 迅雷还能优化的两处（可选）

1. **`thunder://` 兜底**：现在靠 3 个硬编码路径 + 注册表找 exe，路径一变就失效。
   可加 `thunder://`（编码为 `AA<url>ZZ` 再 base64）+ `ShellExecuteW` 兜底，
   走已注册的协议处理器，不依赖 exe 路径。本机 `thunder\shell\open\command` 已注册到迅雷。
2. **批量投递**：现在 200 条 = 200 次进程启动（间隔预算 2s）。
   可实测 `thunder.exe m1 m2 m3 -StartType:magnet` 是否一次收多条；**未验证，别先假设**。

**已知局限（不是 bug）**：`ProtocolMethod` 的 `added` 计的是"进程启动成功"，
不是"迅雷确实收下了任务"。COM 也没这个能力，迁移不解决它。

---

## 6. 分阶段路线

| 阶段 | 内容 | 验收（不过不许进下一阶段） |
|---|---|---|
| **P0 fixture** ✅ | 12 源各抓真实响应 + 请求体，Python 侧跑出输出存为金样 | 已完成：12/12 源、130 个响应体、25 MB |
| **P1 适配器** ✅ | 12 个站点适配器 | **12/12 全过**：金样 diff 全零，共 6,358 条真实结果逐字段一致 |
| **P1 收尾** ✅ | `core`（去重 / 结构评分）· `outcome`（16 种分类 / 健康窗口） | 已完成：5,367 条结构评分 + 10 组去重 + 128 条 outcome 对照全绿 |
| **P1 共享 helper** ✅ | 尺寸 · 七个时间解析 · XML 标签 · HTML 抽取器 · base32 · 哈希提取 | 360 条对照全绿（27 组） |
| **P2 网络层** ✅ | 代理解析 · `reqwest` 客户端 · 超时 · 重试 · TLS 降级 · 解码 · TUN · **tpb 镜像时间预算** | 已完成：真机跑通 5/5 个源，条数与金样一致 |
| **P3 宿主** ✅ | `web/` ✅ · 壳 ✅ · 地基 ✅ · **命令层 21/21** ✅ · `api.js` 换 invoke ✅ · **CDP 真机 E2E** ✅ | 已完成：21 个命令全过；界面真的跑了一次 10 源真实搜索（§9.0.15） |
| **P4 收尾** ✅ | 日志 ✅ · 老配置迁移 ✅ · 单实例 ✅ · 边缘拉伸 ✅（tao 自带） · 打包 ✅（单文件 exe） · **真实 data 兼容 diff** ✅ | 已完成：迁移逐字段对齐 Python；Rust 写过的 data 目录 Python 照样读得动（§9.0.16） |
| **P5 切换** | 并行跑满一个周期，E2E + 真机搜索无回归 | 才允许把 Python 版下线 |

**纪律 1**：Python 版全程不动，两条腿并行到 P5。
**纪律 2**：不要从 P3 开始做。搭 Tauri 壳是全程最好玩、最容易产生"看起来能跑"幻觉的一步。

**表里的规模数字会漂**（重采 fixture、加对照表都会变）。要用数字就现算，别抄上面的：

```bash
python -c "import json,glob,os; print('响应体', sum(len(json.load(open(m,encoding='utf-8'))['captures']) for m in glob.glob('tests/fixtures/*/meta.json')))"
python -c "import json,glob; print('金样', sum(len(json.load(open(g,encoding='utf-8')).get('items') or []) for g in glob.glob('tests/fixtures/*/golden.json')))"
python -c "import json,glob; print('对照表', sum(len(v) for f in glob.glob('tests/parity/*.json') for v in json.load(open(f,encoding='utf-8')).values() if isinstance(v,list)))"
```

---

## 6.1 v1.0.1 变更：移除 diagnostics，source_issues 降级为只报 fail

**决策（2026-09-29）**：`diagnostics` 命令不移植，前端一并删干净。它是给 AI 排查用的
全量结构化 JSON，终端用户用不到；保留它等于为一条排查通道长期承担两个命令的维护成本。

删的东西：`api.js` 的 `diagnostics` 方法及其 mock 分支、`sources.js` 的「诊断原文」折叠块
与「复制诊断信息」按钮，以及随之失效的 `highlightJson` / `SEMANTIC` / `adapterName` /
`adapterLocation` / `stamp`。`js/diagnostics.js` **不删**——它是前端运行时错误收集器
（`window.onerror` + 调用耗时记录），跟这个命令不是一回事，同名而已。

**`source_issues` 只报 fail，不报 empty，不做 peer 对比。** 原因是数据基础不存在，不是偷工：

| Python 侧依赖 | Rust 侧现状 |
|---|---|
| `health.json` 持久化 | `paths::health_path()` 定义了但**无人调用**，文件根本不生成 |
| 每个源最近 5 条 `outcomes` | `probe_seen` 是 `BTreeMap`，`insert` 覆盖，**只有 1 条** |
| `events[]`（含 `round`） | 完全没有，`peer_stats` 无从算起 |
| 跨会话累积 | 纯内存，**重启即空** |

`window_empty()` 要 5 条窗口才判 silent，只有 1 条就永远为假；把判定降到「单次 empty 就报」
会让测速词没命中就误报异常，比不报更糟。所以：**只报 `state == "err"` 的源**（超时 / 403 /
网络失败 / 被拦截），这类是真故障，零误报。

empty 类型与 peer 对比等 health 持久化补上再做。补的时候要动的是：新增 health store
（读写 `health.json`、记 `events` 带 `round`）、让 `start_search` 也写 health（现在只有
`probe_sources` 写）、`config.save()` 别再 strip health。

**版本号不进 parity。** 升到 v1.0.1 后 `parity_app_info` 挂了一次：`tests/parity/api_cases.json`
里的 `version` 是 Python 侧跑出来的 `1.0.0`，而断言拿它跟 Rust 侧比。版本号是各仓的发布标识，
不是跨仓行为契约，让 parity 锁死它只会逼两仓永远同步发版。

改法：`tests/api_parity.rs` 的 version 断言改为对照本仓 `happycrate::api::APP_VERSION` 常量。
`api_cases.json` 里那 7 个 `version` 字段仍由 `gen_api_parity.py` 生成，但不再参与断言——
重跑生成器也不会把测试打挂。

## 6.2 仓库结构变更：main 已由本仓接管（2026-09-29）

**P5 没有做，是用户直接拍板切换的。** 原计划「两版并行跑满一个周期再下线 Python 版」
被跳过，理由是两版并存本身就是负担。

做过的事：

```
git push --force origin rust-rewrite:main    # ff599eb 覆盖 f41a7f4
git push origin --delete rust-rewrite         # 本地与远端的分支都已删，工作分支统一为 main
```

覆盖后的实际状态：

| 引用 | 指向 | 内容 |
|---|---|---|
| `main` | `ff599eb` | 本仓（Rust + Tauri），仓库语言已自动识别为 Rust |
| tag `v1.0.0` | `42117c8` | Python 版**首发根提交**，`git log v1.0.0` 只有 1 条 |
| tag `rust-v1.0.1` | `ff599eb` | 本仓 v1.0.1 |
| Release `v1.0.0` | — | 附件 `happycrate-v1.0.0-win64.zip`（13.2 MB），成品仍可下载 |
| Release `rust-v1.0.1` | — | 附件 `happycrate-v1.0.1.exe`（13.8 MB） |

**一个容易被忽略的后果**：`v1.0.0` tag 指向的是**根提交**，所以 Python 版在 GitHub 上
只剩「首发那一刻」的源码快照；它之后的 8 个提交（演示视频瘦身、README 多轮迭代、
列表渲染合帧优化等）在远端已失去所有引用，会被后台 GC 回收。
**本地 `D:\AI\happycrate` 保有全部 9 个提交**，要恢复随时能推。

另注：Python 版本地仓与远端在覆盖前**已经分叉**——远端有 2 个网页上改的 README 提交
（`5b2de30` / `f41a7f4`），本地有 2 个未推的提交（`dd28aae` 列表渲染减负 / `a2bd5a2`
README 与源数量护栏）。覆盖 main 后，远端那 2 个 README 编辑消失，本地这 2 个仍在。

## 6.3 v1.0.2 变更：海量搜索分块懒渲染、硬超时与 IPC 串行化（2026-09-30）

针对真机大词搜索卡死与偶发闪退的彻底加固：

1. **分块按需懒渲染**：首屏限制 100 条，滚动无限追加；全选、复制等批量操作依然基于内存全量数据，毫秒级拷走数千条磁力，彻底消除 WebView2 海量 DOM 插入造成的线程冻结假死。
2. **硬超时与主动取消**：全局 HTTP 请求设置 15s 硬超时防挂死；前端超时主动向后端广播取消信号，爬虫循环检查 CancellationToken 快速刹车退出。
3. **IPC 串行化与容错**：WebView2 `eval` 推送加互斥锁 `push_gate`，杜绝并发轰炸 COM 接口导致的闪退；工作线程增加 panic 隔离；互斥锁全流程防中毒回退。
4. **体验微调**：设置中保存代理立即动态生效，无需重启应用。

## 7. 金样测试（整个方案的成败点）

`tests/golden.rs` 的形状：

```
for (source, fixture) in fixtures {
    let expected = load_golden(source);      // Python 输出，一次性生成后锁定
    let actual   = parse(source, &fixture.body);
    assert_eq!(normalize(actual), normalize(expected));
}
```

要点：

- fixture 存**原始响应体**（HTML/XML/JSON），不存解析结果——解析结果由两边各自跑出来
- diff 要**逐字段**，不要只比条数。条数对了字段错了是最常见的静默回归
- 浮点/时间字段不进 diff（`ms` 是计时，每次不同）
- 新增一个源 = 加一份 fixture + 跑一次 Python 生成金样，**不允许手写金样**

没有这一层，Rust 的编译器只能保证代码类型正确，保证不了行为正确——
而这个项目 90% 的坑在行为上。

**对照时已知不检查的一项**：数字的整/浮类型。`added` 在 Python 侧有时是 `int`
（来自 `_to_int`）、有时是 `float`（来自 `_ts_from_iso`），JSON 下游都当 Number 用，
所以 `compare` 把两侧数字统一成 `f64` 再比。代价是 `size: 0` 与 `size: 0.0` 这类
差异不会报警——值错会报，类型错不报。

### 7.1 实测得到的三个设计决定（P0/P1 期间验证）

1. **fixture 必须记录请求体，不能只记 URL。**
   knaben 的 7 页请求打的是**同一个 URL**，靠 POST body 里的 `from` 区分。
   只记 URL 会让「响应 ↔ 页码」的对应关系丢失，同一份响应被当成每一页。
   → `meta.json` 的每个 capture 带 `request_body`，回放按 `(url, 规范化请求体)` 命中。
   副产品：**回放同时验证了 Rust 侧的请求序列**——请求体写错会直接报 fixture 缺失。

2. **不引入 HTML 实体库。** 实测 12 个源共 75,041 个实体，命名实体只有 6 种
   （`&amp;` `&nbsp;` `&gt;` `&times;` `&copy;` `&atilde;`），其余全是数字实体。
   一个约 20 行的解码器 + 32 项 windows-1252 映射覆盖 100%。
   已知不覆盖：HTML5 **免分号遗留实体**（`&not` → `¬`），需要 2231 条实体表，
   实测零出现；若将来出现，金样 diff 会先报警。

3. **不引日期库。** ISO8601 → Unix 时间戳用 `days_from_civil` 手写约 60 行，无依赖。
   边界语义（朴素时间按 UTC、`Z`、`±HHMM`、小数秒）由 `tests/parity` 的 66 条对照锁住。

### 7.2 对照表（`tests/parity`）

| 表 | 组 | 条 | 生成器 |
|---|---:|---:|---|
| `util_cases.json` | 27 | 360 | `tools/gen_util_parity.py` |
| `core_cases.json` | 2 | 5,367 | `tools/gen_core_parity.py` |
| `outcome_cases.json` | 4 | 128 | `tools/gen_outcome_parity.py` |

下面这一节讲 `util_cases` 的构成；另两张表同理——**全部由 Python 侧实际行为生成，不手写期望值**。

### 7.2.1 `util_cases` 的构成（27 组 360 条）

除了金样，另有一张对照表锁住最容易悄悄跑偏的 helper：
文本（`unescape` / `collapse` / `quote`）· 数值（`to_int` / `parse_size`）·
时间（`ts_from_iso` / `ts_from_rfc` / `ts_from_naive_cn` / `ts_from_cn_slash` / `ts_from_cn_dash` / `cn_date`）·
XML（`tag` / `split_items`）· HTML（`cell_text` / `cell_text_unescaped` /
`find_title_attr` / `find_torrent_path` / `findall_marked`）·
哈希（`find_hex_after` / `b32_to_hex` / `hash_from_text` / `hash_from_magnet`）。

- 表由 `tools/gen_util_parity.py` 从 **Python 侧实际行为**生成，不手写
- 改 Python 侧就重新生成
- **Rust 侧不手写期望值**。校准件式的「先看输出再填期望」是自欺，
  必须由 Python 跑一遍产生。

这张表在 P1 期间当场抓到 **6 个真 bug**：

| bug | 根因 |
|---|---|
| hex 实体长度算错 | `&#x…;` 的 `#x` 前缀少算 1，每次解码多吐一个字符 |
| 朴素 ISO 丢失时分 | 无时区后缀时直接判失败，回退到只取日期 |
| `\s` 语义不一致 | Python 的 `\s` 含 `\x1c`-`\x1f`，Rust `is_whitespace` 不含 |
| `parse_size` 上限抄错 | `1024**6` 写成 1 PiB（实际 1 EiB），差 1024 倍 |
| `strptime` 的 `%m` 被放宽 | Python 里 `%m` **不接受**空格填充（`2026/ 8/28` 失败），`%d` 接受 |
| `%M` / `%S` 被收紧 | Python 里是 `[0-5]\d\|\d`，**一位数合法**（`05:3` 等于 `05:03`） |
| `_cell_text` 的 gap 默认值记错 | Python 里**默认是空串**，`gap=" "` 要显式传。相邻标签时结果不同：`12<b>GB</b>` → Python `12GB`，我写成空格版成了 `12 GB` |
| 日期没校验 | `days_from_civil` 只算偏移不查合法性，`2026/02/30` 会被接受；Python 的 `strptime` 会拒绝 |
| `\d` 不是 ASCII 数字 | Python 的 `\d` 是 Unicode 的 **Nd 类**，匹配全角 `５`；我用了 `is_ascii_digit` |
| `Season N` 没被识别 | `season\s*\d+` 那股分支挂在了 `'e'` 上，它是 `'S'` 开头 |

中间两条是同一类错误：**照直觉写 strptime 的字段宽度**。
`_strptime.TimeRE` 的正则得逐字段抄，不能凭印象。

上表最后四条更值得记，因为它们**不改行为、只改边界**，跑真机数据看不出来：

- `gap` 默认值是空串。只有当标签紧贴文字时才暴露（`12<b>GB</b>`），
  真实页面里恰好都有空白包着，所以 480 条 dmhy 金样照样全绿。
  这类差异**必须靠参数化对照表**，靠金样抓不到。
- 日期合法性校验。`2026/02/30` 这种输入真实站点不会给，
  但一旦出现，Python 返回 None、我返回一个错位的时间戳——静默错误数据。
- `\d` 的 Unicode 语义。`第　５　季` 这种全角数字在中文标题里是真实的，
  而结构评分直接影响**多源同名时选哪个标题**，所以这条会改用户看到的结果。
  修法是加一个 `is_nd_digit`（ASCII + 全角 U+FF10–FF19）。
  **已知残留**：其他 Nd 区块（阿拉伯-印度数字、天城文等）没覆盖——本项目标题里不会出现，
  且 5,367 个真实标题的全量对照已确认无差异。8 个日期/尺寸解析函数仍按 ASCII 数字，
  理由是那些字段是机器生成的，全角数字不会出现；一旦出现只是降级成 0/None，不会算错。

### 7.3 空金样是假的绿（P1 期间踩到）

sukebei 第一次采集用 `ubuntu` 查出 **0 条**，nyaa 用 `ubuntu` 只有 **1 条**——
这种金样**解析器写错也照样通过**，等于没测。
换成 `sukebei:1080p`（1046 条）与 `nyaa:frieren`（1026 条）才有意义。

**规则：每个源的金样条数必须显著大于 0，并且要覆盖多条响应。**
`tests/golden.rs` 的自检只保证文件存在，保证不了它有内容——
新增源时人工确认条数，别只看测试是绿的。

---

## 8. 工程纪律

**见 `AGENTS.md`**——4 条铁律与迁移纪律的权威在那份文件里，这里不重抄，避免两处漂移。

两条与本文档强相关的，摘出来提醒：

- 铁律 1 的范围是 `src/`、`tests/`、`web/`。**`tests/` 算核心源码，零注释**；
  例外是 `tools/`（本文件提到的采集器与生成器都在那儿，照常写 docstring）。
  机器强制：`python tools/scan_comment.py --selfcheck`。
- 金样表与工具函数对照表**由 Python 侧生成，不手写**；生成器在 `tools/`。

---

## 9. 风险登记册

| 风险 | 等级 | 应对 |
|---|---|---|
| 12 个适配器静默回归 | **高** | P1 金样 diff，不过不进 P2 |
| outcome 判定顺序与 Python 不一致 | **高** | 同左，逐条 fixture 覆盖 16 种 |
| 迅雷行为差异 | **已消除** | COM 经注册表证实为死代码，删它零行为变化（§5.1） |
| `file://` → Tauri asset 协议 | 低 | 已确认前端零 fetch/XHR/localStorage |
| 依赖膨胀导致体积与编译时间失控 | 中 | 每加一个依赖写理由；release > 2min 再考虑拆 crate |
| 迁移期新功能双头维护 | 中 | 迁移期 Python 版冻结，只修致命 bug |
| **单实例 mutex 撞车** | 中 | Rust 版在 P5 之前必须换 mutex 名，否则与 Python 版抢同一把锁、起不来 |
| **`web/` 双份漂移** | 中 | 复制到 Rust 仓后冻结 Python 仓的 `web/`，见 §10 |

---

## 10. 三个决策（已拍板）

### 9.0 P2 网络层：本机代理只在注册表里（已实测）

**实测结论**：这台机器 `HTTP_PROXY` 等环境变量**一个都没有**，
代理只在 `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`：
`ProxyEnable=1` · `ProxyServer=127.0.0.1:7890` · `ProxyOverride` 42 条（LAN + `<local>`）。

**这为什么是要命的一条**：`reqwest` 默认只认环境变量。
如果照默认做，Rust 版会**拿不到代理**，12 个站点全部连不上——而且报出来的是「网络失败」，
看起来像站点挂了，不像配置错了。

**做法**：`src/net.rs` 自己解析代理，顺序与 Python 一致
（手动设置 → 环境变量 → 注册表），读注册表用 `reg query`（不加依赖）。
解析出来后**显式喂给 `reqwest::Proxy`**，同时 `.no_proxy()` 关掉它自己的检测。

**绕过列表（ProxyOverride）也实现了**：CPython 用的是 `fnmatch`（整体匹配、Windows 下忽略大小写），
不是正则。`[seq]` 字符集未实现（本项目路径上不会出现）。
**短路逻辑放对层**：`proxyEnable/proxyOverride 为空则返回 false` 属于外层
`proxy_bypass_registry`，**不属于内层匹配函数**——内层遇到空模式要能匹配空主机。

**超时语义**：Python 的 `timeout` 是 **socket 超时（每次读重置）**，不是总时长。
对应 `reqwest` 的 `connect_timeout` + `read_timeout`，**不要用 `.timeout()`**（那是总时长，
大响应体会被误杀）。

**读注册表要注意**：`reg query` 在 MSYS/Git-Bash 里会被路径转换吃掉 `/v`，要写 `//v`；
Rust 里用 `SystemRoot\System32
eg.exe` 全路径，避免 PATH 被沙箱破坏时找不到。

### 9.0.1 P2 客户端的实测数字与坑（第一次引依赖）

**依赖代价**（第一次明显变化，实测）：

| 项 | 之前 | 现在 |
|---|---|---|
| 直接依赖 | 2 | **5**（`encoding_rs` · `reqwest` · `serde` · `serde_json` · `tokio`） |
| 依赖树总包数 | 11 | **268** |
| 冷编译 | < 1 秒 | **21 秒** |
| `target/`（debug） | 几乎为 0 | **约 1 GB** |

**`reqwest` 的两个 API 坑**：

1. **超时要用 `connect_timeout` + `read_timeout`，不要用 `.timeout()`。**
   前者对应 Python 的 socket 超时（每次读重置），后者是「从连接到响应体读完」的总时长——
   用在 5 MB 的 RSS 上会把正常响应杀掉。
2. **`tls_danger_accept_invalid_certs` 在 `rustls-tls-native-roots` 这组 feature 下不可用**
   （文档说需要 `default-tls` / `native-tls` / `rustls`），只能用已弃用的
   `danger_accept_invalid_certs`。

**`encoding_rs` 是为了 gb18030/big5**：Python 的 `_decode` 顺序是
utf-8 → gb18030 → big5 → latin-1。中文站点（mikan / dmhy / xccl263 / javbus）会走到第二档，
只试 utf-8 会得到乱码。这一档没法手写，是这次唯一「必须引依赖」的地方。

**`Fetch` 现在要带请求上下文**：真机联网需要 Referer 与自定义头
（xccl263 / javbus / javdb 都要求，knaben 的 JSON POST 要 Content-Type），
tpb 还要按请求 `retries=0`。所以 `Fetch` 收一个 `Req`（url / data / referer / headers / retries / timeout）。

**已知覆盖缺口**：夹具回放按 `(url, 请求体)` 命中，**不看 headers 与 referer**。
所以「头写错了」这类回归金样测不出来，只能靠真机 smoke。记在这，别以为金样全绿就万事大吉。

### 9.0.2 P3 起点：`web/` 已复制并核对

`diff -rq web D:/AI/happycrate/web` 无差异；**铁律1 扫描在搬过来的 14 个前端文件上全空**
——说明原项目的前端卫生标准与本仓一致，不需要清理存量。

**Tauri 布局选择**：文档给的默认布局是 `src-tauri/` 子目录 + 独立 crate，
但本仓是「根 crate 放 lib」的形状。方案 §3 的根目录白名单本来就列了 `tauri.conf.json`，
所以走**根布局**：`tauri.conf.json` / `build.rs` / `capabilities/` / `src/main.rs` 都在根，
lib 由 `tests/` 复用，bin 只做窗口宿主。好处是 `cargo test` 与 `cargo run` 同一个 crate，不用配 workspace。

**`withGlobalTauri: true` 是必须的**：前端是没有打包器的纯 JS，
靠 `window.pywebview.api` 这种全局桥接（`web/js/api.js` 里 19 处 `live()` 判断）。
Tauri 不打开这个开关，`window.__TAURI__` 就不存在，前端会一路走 mock 分支。

### 9.0.3 命令层的地基先搬：`paths` + `config`

计划把 `config` 放在 P4，但依赖顺序不允许——`Api` 的 22 个命令几乎都要读写配置。
所以先搬了 `src/paths.rs` 与 `src/config.rs`，共 62 条对照：

| 表 | 组 | 条 | 覆盖 |
|---|---|---:|---|
| `paths_cases.json` | 2 | 10 | 数据目录三分支（env / 便携 / 回退）· 模式文案 |
| `config_cases.json` | 6 | 52 | 加载规范化 19 · 访问器 9 · 超时夹取 28 · 损坏路径 4 · 数据目录路径 |

**`HAPPYCRATE_DATA_DIR` → `MODE_ENV` 这条分支是隔离机制的支点**：P0–P4 的测试与试用
全靠它指向种子副本，P5 才切真实目录。

### 9.0.4 死代码体检抓到 13 个零引用：要分清「移植」和「发明」

搬完配置层，体检报出 13 个 `pub fn` 零引用。**不能一刀切删掉**：

- `Config::replace_order` —— **我自己编的**。重排序逻辑其实在 `api.py` 的 `reorder_sources` 里，
  不在 `Config` 上。已删。
- 其余 12 个（`enabled_keys` / `all_keys` / `order_locked` / `strip_health` / `set_enabled` /
  `set_order_locked` / `sweep_temp_files` / `describe` / `ensure_dirs` / `health_path` /
  `settings_path` / `log_path`）—— **逐个 grep 确认 Python 里都在用**，是真实 API 的忠实移植，
  只是调用方（命令层）还没写。

**判据**：零引用不是罪名，「有没有对端」才是。真实 API 的移植 + 补上对照 = 留着；
凭想象加的 = 删。这 12 个现在全有对照覆盖，等命令层写完自然就有调用方。

### 9.0.5 健康探测暂缓（用户决定，2026-09-28）

**原话**：「健康探测先不加，这功能我在犹豫，实际上我用到这个功能很少很少。」

**因此不做**：`HealthStore`（`health.json`）· `probe_sources` · `source_issues` ·
`diagnostics` · `_demote_bad` / `_persist_health` / `_mark` / `_probe_worker`。
搜索路径里的**健康记录**一并摘掉（只做搜索，不落历史）。

**保留**：`outcome.rs` 的 `classify` / `state_of` / `outcome_text` ——
`classify` 与 `outcome_text` 还负责**每个源的错误文案**（搜索结果里要显示），不是健康专用；
`state_of` / `window_empty` 只有测试在调，但它们是从已验证的 Python 逻辑 1:1 移植的，留着。

**已知后果（未处理，等用户定）**：前端 `js/views/sources.js` 的
**「测速」按钮**与**「异常源」弹窗**会调不存在的命令。
`api.js` 那条路径**没有 catch**，所以那两个动作会**一直停在忙碌态**——
不是崩溃，但也不好受。源列表本身不受影响：`api.js` 的 `coerce` 对缺失的 `health`
会补成空对象，状态列显示为空。

**两个选项**（都需要用户拍板，不能自己动）：
① 先留着，等确定了再实现或删；
② 把那两个入口从 `web/` 里摘掉——**这是改用户界面，必须单独确认**。

### 9.0.6 关键词解析（`query`）：为 NFKC 引一个依赖，有数据支撑

`query.normalize` 用 `unicodedata.normalize("NFKC", ...)`，**Rust 标准库没有 Unicode 归一化**。

**先量了才决定**：6,358 条真实标题里 **367 条含 NFKC 会改动的字符**——
上标（`7³ACG`）、连字（`Æ` → `AE`）、全角（`４ｋ` → `4k`）。
而这个应用的用户群用中文输入法，**全角数字字母是很常见的输入状态**，
不归一化就是"输 `１０８０Ｐ` 搜不到 `1080p`"。
所以引 `unicode-normalization`（unicode-rs 官方维护，纯 Rust）。

**这个依赖是写在对照表之外的判定**：先用数据确认影响面，再引；
不是"看起来应该有"就加。

### 9.0.7 对照表又一次抓到漏抄：变体表少了一条

`_BUILTIN_VARIANTS` 有 **30** 条，我抄成了 29 条，漏掉 `"开放世界"`。
是 `parse("射击 开放世界 第三人称")` 这个用例撞出来的——
**手抄长表必然出错，这就是为什么要一条一条跟原表对齐**。

同轮还删掉两个「自己编的」：`query::roles_path`（Python 里没有这个函数，是内联拼的路径）。
`query::reload` 是真实 API（`reload_query_roles` 命令要调），保留并补了缓存/重载的验证。

### 9.0.8 命令层：分两层，否则没法验证

**Tauri 的命令处理函数是没法单元测试的**（要窗口、要 IPC）。所以切成两层：

- `src/api.rs`：命令的真实逻辑，持有 `Config` / `Settings`，可对照
- `src/host.rs`：命令包装只有一行转发

这样 18 组命令场景能进对照表；胶水那一层用 CDP 真机验（见 AGENTS 的环境事实）。

**实测结果**（`tools/cdp_eval.mjs`）：`window.__TAURI__.core.invoke` 存在；
`list_sources` 返回 12 个源 / 10 个启用；`toggle_source` 后变 11；
`save_settings` 传越界值返回中文原因；`reorder_sources` 后写回的
`sources.json` 里 `orderLocked=true`、顺序正确。
**且所有写盘都落在种子里，真实 APPDATA 目录从未被创建。**

### 9.0.9 又一次栽在「`re.sub` 是全局替换」上

`_redact` 用 `_URL_USERINFO_RE.sub("***", ...)`，**`re.sub` 默认替换全部**。
我按「只替第一处」写了，于是 `http://a:b@h, http://c:d@i` 只脱敏了前半段——
**后半段凭据会原样显示在界面上**。

`re.sub` 与 `re.search` 是两套语义，要分开记：
`search` / `match` / `findall` 是「找」（找到就停），`sub` 是「换全部」，`subn` 还带计数。
前面 `title_link` 那次记的是「贪婪回溯取最后一个」——**同一条正则的不同调用方式，行为完全不同**。

### 9.0.10 命令总数是 24，不是 19（本方案早先数错了）

用 `inspect.getmembers(Api)` 数了一遍：**前端要调的命令共 24 个**。

健康类 3 个（`probe_sources` / `source_issues` / `diagnostics`）已暂缓 → **目标 21 个**。

**已完成 15 个**（全部过了 CDP 真机验证）：
源管理 4（`list_sources` `toggle_source` `reorder_sources` `set_auto_order`）·
设置 4（`get_settings` `default_settings` `save_settings` `reload_query_roles`）·
信息 3（`selftest` `app_info` `open_logs`）· 窗口 4（`win_min` `win_max` `win_close` `set_window_tone`）。

**剩 6 个**：`start_search` · `cancel_search` · `torrent_files` · `deliver` · `downloaders` · `proxy_status`。

**教训**：早先按「源管理 4 + 搜索 3 + 设置 4 + 投递 2 + 其他 6」估成 19，
把窗口那三个和 `diagnostics` 漏算了。**依赖清单要数出来，不能估。**

### 9.0.11 `proxy_status`：把「决策 / 组装」与「探测」切开

这个方法里混着两件事：

- **决策与组装**（选哪个代理、门控、字段形状）——纯逻辑，该被对照表覆盖
- **探测**（TCP 连端口、走代理访问探测地址、扫 TUN 网卡）——真网络 I/O，喂不了桩

所以切成 `pick()` + `status_from()`（纯）+ `probe_port()` / `probe_works()` / `tun_adapter()`（真 I/O）。
**门控规则**（`portOk` 只在 mode≠none 时算、`works` 只在 portOk 时算、`tun` 只在 mode=none 时扫）
落在纯函数里，8 组桩对照全覆盖。

**真机结果与 Python 逐字段一致**：

```
Rust   {"addr":"http://127.0.0.1:7890","mode":"system","portOk":true,
        "systemOn":true,"tun":"","works":true}
Python {"mode":"system","addr":"http://127.0.0.1:7890","portOk":true,
        "works":true,"systemOn":true,"tun":""}
```

`works:true` 说明**真的走代理访问成功了**——这是 `reqwest` 代理配置正确的最硬证据。
缓存也验了：2 秒内两次不带 force，`checkedAt` 完全相同（15 秒 TTL 生效）。

顺带把客户端缓存键从「秒」改成「毫秒」——探测超时是 1.5 秒，按秒取整会变成 1 或 2 秒，
与 Python 的 `PROBE_TIMEOUT = 1.5` 对不上。

### 9.0.12 计划里关于迅雷 COM 的那句话，结论对、理由错

本方案早先写的是「注册表证实 COM 是死代码」。**复验发现：`ThunderAgent.Agent.1`
这个 ProgID 键在 HKCR 里是存在的**（值是 "Agent Class"）。

真正证明它不可用的是 `Dispatch` 本身：

```
win32com.client.Dispatch("ThunderAgent.Agent.1")
→ com_error (-2147221164, '没有注册类')      # 0x80040154 CLASS_NOT_REGISTERED
```

即：**ProgID 键在、但它指向的 CLSID 没注册**（迅雷没装 COM 组件）。
项目自己也算出 `methods: [('com', 'COM 接口', False), ('protocol', '协议拉起', True)]`
——`com_available()` 返回 False。

**所以「只实现 ProtocolMethod」这个决定是对的，但依据要换成 `Dispatch` 失败**。
只查键是否存在会得出相反的结论——这是个真实的教训：**"注册表里有"不等于"能用"**。

另外本机实测：`magnet\shell\open\command` 与 `thunder\shell\open\command` 都注册了，
指向 `C:\Program Files (x86)\Thunder Network\Thunder\program\thunder.exe`（文件存在）
→ `find_exe()` 走第一个硬编码路径就命中。

**没验的那一条**：真的启动迅雷投递任务——**没做**，因为那会往用户真实的下载列表里加任务。
留待用户明确同意后再试。

### 9.0.13 种子清单：两条路径都要验

`torrent_files` 有两种输入，走完全不同的分支：

- 地址以 `.torrent` 结尾 → **直接取种子文件**
- 否则 → **先取 HTML 页，从里面找 `<a href="…torrent">` 链接**，再取那个

第二条正是 mikan / dmhy 的形态（它们的 `fetch.url` 是网页不是种子）。
只验第一条会漏掉一半逻辑。

**真机结果**（与 Python 逐条一致）：

```
nyaa 直链     → {"ok":true,"共":10}   文件如 [Erai-raws] Sousou no Frieren …mkv  784.1 MB
mikan 网页页  → {"ok":true,"共":39}   文件如 Sousou no Frieren 2023 S00E01…mkv   13.9 MB
```

页内找链接那一步的两个正则（绝对地址优先、其次根相对）在手写时用的是
**贪婪回溯**：内容必须**以 `.torrent` 结尾**才算命中，不是"包含"。用 `contains` 会误抓。

### 9.0.14 搜索编排（`start_search` / `cancel_search`）：对照整个事件序列，不是对照函数

这是 P3 最后一块，也是最好验证的一块——**因为它没有函数边界，只有「推给前端什么」**。

`src/search.rs` 照抄 `Api._search_worker`，但把推送目标做成可注入的：

```rust
pub enum Event { Start(Value), Source(Value), Batch(Value), Settled(Value), Done(Value) }
pub fn js_of(event: &Event) -> String        // 拼成 window.__onSearchXxx && window.__onSearchXxx({...})
pub fn execute<F: Fetch + Sync>(job: &Job, fetch: &F, sink: &(dyn Fn(Event) + Sync))
pub fn spawn(job, http: Arc<HttpClient>, sink: Option<Arc<Sink>>)
```

于是**整条流水线可以在离线 fixture 上跑**：`tools/gen_search_pipeline.py`
把 `sources.http_get` 换成回放器，直接调 `Api._search_worker`，记录它推出去的每一条 js；
`tests/search_pipeline.rs` 喂同一批 fixture，比对 Rust 的事件序列。

**5 个场景**（3.0 MB 金样）：

| 场景 | 覆盖 |
|---|---|
| `ubuntu_first` | 5 源并发扇出 · 去重合并 · `raw/dup/total` 计数 · 条目投影 |
| `ubuntu_cached` | **0 次请求**命中缓存 · `cached:true` 载荷 · 只重打失败源 |
| `relax_round` | 第一轮全 404 → 全部走 `http4xx/warn` → 放松关键词 → 第二轮命中 |
| `cancelled` | 取消令牌：**一条推送都不许有** |
| `keep_duplicates` | `hash|key` 的 ikey 分支 · 不合并跨源重复 |

**三个必须写死的输入**，否则同一份表在不同机器上跑不出同一个结果：

- 「现在」冻结成 `2026-09-28 19:15:00+08:00`（`core.datetime` 与 `sources.datetime` 都要打桩，
  tpb 的相对时间用的是后者）
- **系统代理与 TUN 都打桩成「没有」** —— 全源失败时的提示文案走 `proxy_hint_for`，
  不钉住的话，本机有代理就出「系统代理 … 连不上」，没代理就出「网络请求失败」
- `max_workers=1`、`soft_deadline_ms=0`

**已知的两个放松**（都是时序行为，改不动）：

1. **跨源之间的先后是竞态**：Python 的 `on_start` 来自工作线程、`on_source` 来自主线程，
   两者不同步。所以对照前**按 key 稳定排序**（同一个 key 内部的顺序照比）。
   `tests/search_pipeline.rs` 与生成器用同一个排序。
2. **软截止的 `__onSearchSettled` 没进金样**：它要求「3 秒到了但源还没跑完」，
   回放是瞬间完成的，钉不住。**真机 E2E 已经验证**（见 §9.0.15）。

**刻意砍掉的（用户 2026-09-28 决定，见 §9.0.5）**：`HealthStore` / `_mark` / `_typical_ms`。
后果是两个字段降级，前端表现基本不变：

- `onSearchSource.state` 改成 `state_of([本次 outcome])`（Python 是最近 5 次滚动窗口）。
  全新健康库时两者**完全一致**；攒够历史后可能不同——Python 会在「最近 3 次失败但这次成功」
  时仍显示失败红点，Rust 显示成功。**Rust 这个更准**，但确实是差异。
- `onSearchStart.typical_ms` 恒为 0 → 前端不显示「约 Xs」的进度预估。

另外 `sources::Scoped`（`Req` 装饰器）一次解决两件事：**per-request 超时**
（Python 每个请求都带 `timeout=源配置的 timeout`，Rust 适配器原本用的是客户端默认值）
与**批次令牌注入**。12 个适配器一行没改。

### 9.0.15 真机 E2E：从界面触发一次真实搜索

`HAPPYCRATE_DATA_DIR` 指向种子目录 + `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222`
起应用，用 CDP 在页面里注入记录器（包住 5 个 `window.__onSearchXxx`），
再**真的往搜索框里回车**（`#heroInp` → `onkeydown({key:"Enter"})`）。

实测（10 个默认启用源，查询 `ubuntu`）：

```
事件：onSearchStart×10  onSearchSource×10  onSearchBatch×6  onSearchSettled×1  onSearchDone×1
收尾：total 892  raw 1456  dup 564  errors {}
每源：海盗湾 236 · Nyaa 1 · 蜜柑 无结果 · 动漫花园 2 · Sukebei 无结果 · EZTV 无结果
      TPB镜像 600 · Knaben 537 · 小草磁力 80 · JavBus 无结果
界面：结果区 237 行、徽标「共 762 条」、10 个源块
```

**`__onSearchSettled` 就是在这里验的**——金样里钉不住的那条。

**真机对照又抓到一个回放抓不到的缺陷**：Rust 客户端只发了 `User-Agent`，
漏了 Python `http_get` **恒定发送**的 `Accept: */*` 与 `Accept-Language: zh-CN,zh;q=0.9,en;q=0.8`。
后果可观测：同一个 knaben 请求（7 页、831 条）——

| 客户端 | 耗时 |
|---|---:|
| Python（带齐 3 个头） | 8.9 s |
| Rust 补头前 | **48.9 s**（每条 ~7 秒） |
| Rust 补头后 | **8.2 s** |

条数三个版本完全一样。补法是在 `HttpClient::client` 的 `default_headers` 里加这两个默认头
（与 Python 的 `hdrs` 字典一一对应），客户端缓存键不用变——头是常量。

**回放不看请求头，所以这类缺陷只有真机能抓**。这是 fixture 方案的已知盲区，
别因为它"测过了"就以为请求头也被测过。

### 9.0.16 P4 收尾：日志 · 迁移 · 单实例 · 边缘拉伸 · 打包 · 真实数据兼容

**① 命名**：产品名 / Cargo 包名 / 可执行文件名统一成 `happycrate`
（目录仍叫 `happycrate-rust`，只为跟老 Python 仓区分）。crate 名 `happycrate` 后
18 个 rs 文件的 `use happycrate_rust::…` 全部跟着改。

**② 日志（`src/log.rs`）**：不引 `log` crate，手写 90 行——**Rust 标准库没有日志**，
为这点东西引依赖不划算。行为照抄 `logging.handlers.RotatingFileHandler`：
`logs/happycrate.log`，1 MB × 3 轮转（先 `.2→.3`、再 `.1→.2`、最后 `log→.1`），
格式 `%(asctime)s [%(levelname)s] %(name)s: %(message)s`，
目标名照 Python 的 logger 名（`happycrate.app.api` / `.sources` / `.config` / `.migrate` /
`.shell` / `.single`），级别用 `HAPPYCRATE_LOG_LEVEL`。

- 每次写**现开现写现 flush**，不常驻句柄：崩了也不丢、用户删日志文件也不会写进已删除的 inode。
- 多一个 Python 没有的东西：**panic 钩子**。GUI 子系统下 panic 是静默的，
  不留一行日志就没法查（`windows_subsystem = "windows"` 连 stderr 都没有）。
- **刻意只搬应用级日志**：12 个适配器内部的「退回 RSS / 有 N 页失败 / 详情页要登入」
  这些细分提示没搬。搜索级的「源 X 返回 N 条 / 源 X 失败：msg」已经能覆盖定位需求。

**③ 老配置迁移（`src/migrate.rs`）**：这台机器上真有 `D:\AI\CLB\data`（上一代产品名 CLB），
所以**不是纸上功能**——第一次跑 debug 版就真的触发了，日志里写着
「已迁移旧配置：7 项设置、8 个数据源（来自 D:\AI\CLB\data）」。

金样用**合成的**边角老目录（`tests/legacy/`），刻意塞满：未知键、越界值、
`timeout: "abc"`、已下线的 `btdig`、空 key、非对象项、空白 base。Python 跑一遍存金样，
Rust 在同一个老目录上跑（`CLB_DATA_DIR` 指过去）逐字段比 → **一次通过**。

**④ 单实例（`src/single.rs`）**：直接 `extern "system"` 声明 `CreateMutexW` / `CloseHandle` /
`GetLastError`，**零新依赖**。行为与 Python 一致（第二实例静默退出，不抢焦点）。
互斥体名故意带 `_rust`：并行期两版要能同时开着。
实测：起第二个 → 进程数仍是 1。

**⑤ 边缘拉伸：不用写代码**。查 tao 0.37.1 源码
`src/platform_impl/windows/event_loop.rs` 的 `WM_NCHITTEST` 分支——
**无边框 + resizable + 非最大化/全屏 时它自己就做整圈命中测试**
（`border_x = SM_CXFRAME`、DPI 缩放，四个角也覆盖）。
Python 版当年得用 ctypes 子类化窗口过程去补，Rust 这层是白送的。
**剩下只能人工确认**：CDP 造的鼠标事件进不了 Windows 的命中测试。

**⑥ 打包：交付物就是那个单文件 exe**，不装安装包。`cargo build --release` →
`target\release\happycrate.exe`（14 MB，界面已内嵌、图标已内嵌——实测 exe 里能找到
`assets/icon.ico` 的图片数据）。`bundle.active` 保持 `false`
（但 `bundle.icon` 已显式配成 `["assets/icon.ico"]`，**别删**：图标靠这一项嵌进 exe，
目录改名而这里不改就会静默丢掉 exe 图标）：
**这个应用是便携式的**（数据在 exe 旁边），装进 Program Files 反而会让 `data\` 不可写、
退化成 `%APPDATA%` 模式，等于改了用户的数据位置。

**⑦ 真实 data 兼容（P4 的验收点）**：真实 `data/` 的副本让 Rust 读写一轮
（切一个源 + 存一次设置 + 跑一次搜索），然后：

- `tools/check_data_compat.py`：**用 Python 自己的 config/settings 去加载**那份目录 →
  加载成功、无损坏备份、只出现预期的三处差异、源集合与顺序没变、`sources.json` 里没残留
  `health`、`health.json` 字节一致。**通过。**
- 一个坑顺手澄清：`saveSettings({ui_font_size: 16})` 存进去变成 18 —— 不是 bug，
  `ui_font_size` 有 `choices = [14, 18, 22]`，16 会被吸附到最近的合法值。
  **取值域看 `choices`，别把 `min/max` 当成选项清单。**
- 另一个观察：Rust 存设置会写全 26 个键，用户的真实文件只有 18 个（少了 8 个 `sound*`）。
  原因是 Python 那边的 `SETTING_SPECS` 加了音效项之后**还没存过一次**。
  两边都是「整份 data 落盘」，所以行为一致，不是差异。

**⑧ 两个测试的环境依赖，都在这轮暴露了**（都不是产品 bug，是测试写法问题）：

- `api_parity` 的 `parity_api_commands` 原先调 `Api::boot()`，而金样是 Python 用
  `_cfg.load() + _settings.load()` 造的（**故意不 boot**，跳过迁移）。Rust 这轮给 boot 加了迁移，
  于是测试跑起来真的去 `D:\AI\CLB\data` 迁了一次，把源顺序都改了。
  **修法：测试照抄生成器的调用序列，不 boot。** 迁移有自己的金样（`migrate_cases.json`）。
- `parity_app_info` 里那条「系统代理描述」，金样记的是抓取时的系统状态
  （当时 `ProxyEnable=1` → "跟随系统 http://127.0.0.1:7890"），
  而这台机器中途把系统代理关了（`ProxyEnable=0`，`ProxyServer` 还留着）→
  Rust 正确地说"未检测到代理"，测试却红。
  **修法：那一条只校验形态**（要么 `跟随系统 …` 要么 `未检测到代理`），
  系统的代理判定逻辑本来就有 232 条 `net_cases.json` 在覆盖，不需要在这里再绑一次真实注册表。
- `net_parity` 的 `live_registry_matches_python` 原来是拿**抓取时的快照**比现场注册表，
  同一个坑。**修法：改成现场对现场**——起一个子进程跑
  `python -c "import urllib.request; print(urllib.request.getproxies())"`，
  跟 Rust 的 `system_proxies()` 现比。找不到 venv 就跳过（打印一行说明），不假装通过。
  这样代理开着关着都是绿的，而且真的在防「两边解析不一致」。
  `net_cases.json` 里那个 `_live` 快照从此只是**当时环境的一份记录**，测试不再依赖它。
- **教训：任何读「本机实时状态」的断言，都是定时炸弹。** 要么现场对现场，要么只校验形态。

**⑨ 窗口关掉之后，`.run()` 后面的代码根本不会执行。** 日志里永远看不到
「单实例互斥体已释放」，一度以为是崩溃。查了源码：
`tauri::Builder::run` → `App::run` → tao 的 `EventLoop::run` 返回类型是 **`!`**，
内部走 `run_return(...)` 之后直接 `std::process::exit(exit_code)`
（`tao-0.37.1/src/platform_impl/windows/event_loop.rs:221`）。
所以 `crate::single::release()` 与 `outcome.expect(...)` 是**够不到的死代码**。
**不影响正确性**：进程一退出，系统自动释放命名互斥体——
实测新实例能立刻拿到（日志里 21:23:09 那次就是前一个实例退掉之后起来的）。
留着那两行是因为「万一哪天 Tauri 改成正常返回」，但别指望看到日志。

  **代理开关是会来回变的**：这一轮里 `ProxyEnable` 先 0 后 1（用户自己切的），
  这正是上面两条测试踩雷的现实原因。

**⑩ 「测速 / 异常源」的现状（等用户拍板，代码没动）**：

- **测速**：数据源页工具栏上一个**看得见、点得动、没反应**的按钮（转圈停在忙碌态）。
  这是用户唯一真正会踩到的假按钮。
- **异常源**：入口是标题旁那个「N 个异常」链接，N = 健康状态为 `err` 的源数量
  （`store.badCount()` → `stateCount("err")`）。Rust 侧没有健康度，
  `source_view` 把 `state_of(空)` 算成 `na`，于是 **N 恒为 0 → 链接不渲染 → 弹窗打不开**。
  **也就是说它在 Rust 版里是够不到的死路径，既不伤用户也不给用户任何东西。**
- 判断写进了 `.scratch/异常源判断.html`：建议**摘掉测速按钮**、异常源先不做；
  真要做「结论」就做一句话摘要（纯前端 20 行，零后端），而不是搬整套健康度。
  **动界面必须用户点头，已问，等回复。**

**⑪ 「测速」用户决定保留 → 本轮补上了（`src/probe.rs`，约 120 行）**

- **它跟「异常源」不绑定**：两者只是共用一份「健康记录」。测速单独也能成立。
  用户要的是「按钮点下去，每行出延迟」，不需要历史表，所以**没搬健康度**：
  不写 `health.json`、每次搜索也不记账、更不会自动重排源顺序。
- 照抄 Python 的部分：探测词 `test` / 兜底 `1080p`（首个词 0 条才换词，**报错不换**）、
  最多 8 路并发、空启用列表直接推 `__onProbeDone`、载荷 `{key,state,ms,err,outcome}`、
  收尾推 `__onProbeDone`（无参数，`js_of` 里特判）。
- **一处刻意的偏离**：`state` 用 `state_of([本次 outcome])`，而不是 Python 的五次滚动窗口
  （同上一条：没有历史表）。`ms` 是实测值，用户要看的就是它。
- **一处新增的会话内记忆**：`Api::probe_seen`（内存里一张 key→本次结果 的表），
  `list_sources` 会把它叠进 `health` 视图。**不做这一步的后果很具体**：
  测速完切到搜索页再切回来，数字全变回「—」，看起来就像按钮又坏了。
  跨重启不保留（Python 靠 health.json 保留）——这是没做健康度的直接代价，跟用户说明过。
- 多打了一行 Python 没有的日志：`测速 <key>：N 条 <ms>ms（outcome）`。
  没有持久化时，日志是唯一的痕迹；也正是靠这行才看清「knaben 测速为什么这么久」。
- **没有金样**（Python 侧那套探测载荷依赖健康度窗口，比不了）。只在真机验过：
  10 个启用源全部出了延迟（1.2s–31s），`__onProbeDone` 收尾、离开页面再回来数字还在。
  它的逻辑都很薄，复用的全是已有金样覆盖过的零件（`sources::search` /
  `classify` / `outcome_text` / `state_of`）。

**⑫ 顺手发现：Rust 的多页源是「串行拉页」，Python 是 6 路并发**

`grep -l "thread::scope\|spawn" src/sources/*.rs` → **零命中**。
Python 侧 `_gather_pages` 给 apibay/nyaa/sukebei/dmhy/eztv/bitsearch/knaben/javbus/javdb
都开了池（2–6 路），Rust 侧全是一个 `for` 循环一页一页来。
对**最终结果没有影响**（各源都把页收进 `BTreeMap<页号, …>` 再按序合并，金样也全绿），
影响的是**等待时间**：API 不稳时串行会把超时叠加成倍。

**但这轮的 A/B 测量被污染了**：测 Python 时系统代理是开/关来回切的
（`live_smoke` 报 `代理 none`，说明那一次是直连；apibay 直连 17.1 秒、走代理 0.7 秒，
差 20 倍）。所以「串行 vs 并发」到底差多少**目前没有可信数字**。
**要做一次干净的对照：两边都显式指定 `http://127.0.0.1:7890`**，别依赖系统代理开关。
**先不动代码**：这是约 10 个适配器文件的改动（金样能兜正确性，但合并/失败计数要原样保留），
  值不值由用户定；这也是 P5 的第一项待办。

**⑬ `tpb_budget` 那条测试会在大负载下闪断**：它断言「预算 2 秒时只试 1 个镜像」，
而预算是**墙钟**——`let deadline = now + 2s` 之后如果测试线程被抢占超过 1 秒，
进循环时 `left` 已经归零，于是一个镜像都不试，断言从「1 个」变成「0 个」而炸。
单跑必过、全量并发跑才偶发。**改成断言不变量**：
至少试 1 个、**没有把 4 个镜像全试一遍**、首个请求的超时落在 1~2 秒（由剩余预算决定而不是源配置的 15 秒）、
总耗时 < 5 秒。这样既保住「时间预算真的生效」这个信号，又不跟调度器抢时钟。
**教训：时序测试不要断言墙钟的精确计数。**

### 9.1 tpb 的时钟依赖：把它做成参数，不要放宽 diff

tpb 的 `added` 字段里有一类值是**相对时间**：`today 12:34` / `Y-day 12:34`，
解析结果依赖「现在几点」。同理 `MM-DD 12:34` 的年份在「未来超过一天」时要回退一年。

**做法**：Rust 侧把「现在」做成显式参数（`now_iso`），采集器在 `meta.json` 里记下
`captured_local`（带时区偏移的本地时刻），金样测试把它传进去。
这样 diff 仍然**逐字段严格**，`added` 不用排除。

这条如果偷懒——直接把 `added` 从 diff 里踢掉——就丢掉了一整类回归的探测能力。
**能严格就别放宽**：先把不确定的输入变成参数，再放宽。

顺带：镜像轮换的时间预算（Python 里用 `time.monotonic()` 卡总时长）**暂未实现**，
fixture 回放里每页都是本地读取、瞬间完成，行为一致。
**P2 做网络层时必须补上**，否则一个死镜像会按 N × 超时 拖住整个源。

### 10.0 `src/util.rs` 不拆文件（附拆分触发点）

现在 1,031 行、46 个 `pub fn`，是仓库里最大的单个文件。**刻意不拆**：

- 全是无状态的纯函数，彼此不耦合；拆成 `text.rs` / `time.rs` / `hash.rs` 只是搬到别的文件，
  每个适配器却要多写好几行 `use`。
- 行数不是臃肿的判据——**死代码和冗余才是**。体检方式是数 `pub fn` 的引用数：
  `pub fn` 46 个，零引用 0 个。

**触发点写在这里（核心源码不允许写注释，所以规则放文档）**：
若 `util.rs` 超过约 1,300 行，或时间解析那一段继续膨胀（目前约 300 行），
就把时间解析整块搬到 `src/time.rs`。在那之前不动。

### 10.1 迅雷：不保留 COM，只做 ProtocolMethod

理由见 §5.1——COM 在本机已是死代码，删它零行为变化。
"拉起未运行的迅雷"这个能力由 `ProtocolMethod` 提供，原样保留。

### 10.2 `web/`：复制，并且立刻冻结 Python 仓的前端

**不用 symlink**，三条理由：

1. Windows 创建目录符号链接要管理员权限或开发者模式；
   Git for Windows 在 `core.symlinks=false` 的机器上会把链接签出成**一个写着路径的文本文件**，
   构建静默失败。
2. Rust 仓是继任者，必须**自包含**。symlink 指向 `D:\AI\happycrate\web` 意味着
   Python 仓一归档、Rust 仓就断。
3. 复制的真实代价是"双份漂移"，而这个代价可以靠**冻结**消除，不靠 symlink：

**做法**：复制一份到 `D:\AI\happycrate-rust\web\`，同时**冻结 Python 仓的 `web/`**
（迁移期本就要求 Python 版只修致命 bug）。前端改动只在 Rust 仓做。
这样两个源不会同时动，漂移风险归零。

兜底：需要确认没漂，一条命令的事——

```
diff -rq "D:/AI/happycrate-rust/web" "D:/AI/happycrate/web"
```

### 10.3 `data/`：P0–P4 隔离，P4 才切真实目录

**隔离的好处**：

- 真实数据零风险：Rust 版写坏了也不会动你的 `sources.json` / `settings.json`
- **给你一个更强的验证手段**：可以把 Rust 写出的 `settings.json` 与 Python 写出的
  **逐字节 diff**。共用一个目录会把这个信号冲掉
- 可以随时删掉重来

**隔离的代价**：要先把真实数据复制一份做种子；真实启用源上的兼容性要到 P4 才暴露。

**共用能拿到的**：随时验证真实兼容性。
**共用的风险**（实测确认过两件事后收窄）：

- 好消息：`config.py` 的写入是原子的（`tempfile.mkstemp` + `os.replace`），
  所以不会出现"写一半被另一个进程读到"的损坏
- 剩下的真风险是**内容级覆盖**：两边都写 `settings.json` / `health.json`，后写覆盖先写。
  如果 Rust 写了个 Python 不认识的字段再被 Python 写回，字段会丢
- 还有一条更要命的：**单实例 mutex 同名会直接让 Rust 版起不来**
  （`Local\happycrate_v1_SingleInstance_7d4a9e2c6b1f8053`）。并行期必须换名

**做法**：

```
# P0–P3：Rust 版指向种子目录
set HAPPYCRATE_DATA_DIR=D:\AI\happycrate-rust\.scratch\data-seed

# 种子 = 真实 data/ 的一次性复制
xcopy /E /I "D:\AI\happycrate\data" "D:\AI\happycrate-rust\.scratch\data-seed"

# P4：做一次兼容测试 —— 再复制一份真实 data/，让 Rust 读写，diff 输出与 Python 的差异
# P5：确认无差异后，才让 Rust 版直接用便携模式的真实 data/
```

**并行期纪律**：Rust 版用不同的 mutex 名（例如 `happycrate_rust_v1_SingleInstance_...`），
否则两版不能同时开着。
