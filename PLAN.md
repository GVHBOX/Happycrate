# happycrate 现状与决策记录

Rust + Tauri 2 重写版。**迁移已于 2026-09 完成**（v1.0.3 已发布），本文不再是施工方案，
只写「现在的实况」与「仍然生效的决策」。原始施工方案与全部过程教训（含金样方法论细节）
在 git 历史：`git show d65fb48:PLAN.md`。

## 1. 仓库现状

- 产品名 / Cargo 包名 / 可执行文件名一律 `happycrate`；目录叫 `happycrate-rust`
  只为与老 Python 仓区分。
- **GitHub `GVHBOX/Happycrate` 的 `main` 就是本仓**（2026-09-29 由本仓强制覆盖接管，
  工作分支 `main` 直接推）。老 Python 版已彻底清理下线，全仓完全自包含。
- tags：远端 `v1.0.0`（Python 首发快照）、`v1.0.2`、`v1.0.3`、`rust-v1.0.1/2/3`。
- 布局：单 crate 根布局——`tauri.conf.json` / `build.rs` 都在根，权限配置内联于 `tauri.conf.json`，
  不拆 workspace。前端 `web/` **编译期内嵌**进 exe（`frontendDist: "web"`），
  改 JS / CSS 必须重新 `cargo build`，不存在改文件即生效。
- 窗口：`decorations: false` 自绘标题栏。拖动靠 `web/index.html` 的
  `data-tauri-drag-region` 热区，由 `tauri.conf.json` 的
  `core:window:allow-start-dragging` 授权——删了它标题栏拖不动。
- 数据目录三分支（`src/paths.rs`）：环境变量 `HAPPYCRATE_DATA_DIR` → exe 旁 `data/`
  （便携模式）→ `%APPDATA%\Happycrate\data` 回退。**debug 编译的程序目录是仓库根**，
  所以 `cargo run` 用仓库根 `data\`；exe 直跑用 `target\release\data\`。
- 单实例 mutex：`Local\happycrate_rust_v1_SingleInstance_...`（带 `_rust`，与 Python 版区分）。
- `gen/` 是 tauri-build 产物；`target/`、`data/`、`.scratch/`、`.vscode/` 均已 gitignore。

## 2. 依赖清单（克制，每加一个都要写理由）

与 `Cargo.toml` 一一对应，多一个都不行：

| 依赖 | 理由 |
|---|---|
| `tauri` | 宿主：无边框窗口 + WebView2 + IPC |
| `serde` / `serde_json` | 三份 JSON 的读写与 IPC 载荷 |
| `reqwest`（rustls-tls-native-roots · gzip · brotli · http2） | HTTP。native-roots 读系统根证书（这些站点证书链杂，webpki 会误报） |
| `tokio`（rt-multi-thread · sync · time） | reqwest 的运行时；sync/time 支持请求与退避的即时取消与单调硬期限，不引新依赖 |
| `encoding_rs` | gb18030 / big5 解码（Python `_decode` 顺序 utf-8 → gb18030 → big5 → latin-1，中文站点走第二档，手写不来） |
| `unicode-normalization` | query 归一化要 NFKC（6,358 条真实标题里 367 条含全角/上标；中文输入法用户全角很常见） |
| `time`（local-offset） | `util::local_now` 日志时间戳（标准库没有本地时区） |

**明确不引**：`scraper`/`html5ever`（换解析器 = 主动制造与 Python 的差异）·
`regex`（不支持 lookaround，Python 正则逐条平移）· `anyhow`（`SourceError` 枚举让编译器
穷尽分支）· `socks`（Python 侧只支持 http/https 代理）· 日期库（ISO8601 手写约 60 行，
边界语义由 66 条对照锁住）· HTML 实体库（12 源 75,041 个实体实测只需 6 种命名实体，
20 行解码器覆盖 100%）。

## 3. 命令层（25 个，以 `host.rs` 的 generate_handler 为准）

两层结构：`src/api.rs` 放真实逻辑（可进对照表），`src/host.rs` 一行转发
（Tauri 命令处理函数没法单元测试，要窗口要 IPC）。

```
list_sources  source_issues  toggle_source  reorder_sources  set_auto_order
get_settings  default_settings  save_settings  reload_query_roles  selftest
app_info      torrent_files  downloaders  deliver  probe_sources
start_search  cancel_search  proxy_status  net_throughput  open_logs  open_repo
win_min  win_max  win_close  set_window_tone
```

推送方向 7 个钩子（`__onSearchStart/Source/Batch/Settled/Done`、`__onProbe(Done)`）
走 `WebviewWindow::eval()`，刻意不换 Tauri Channel（前端零改动）。`diagnostics`
命令不移植（§8）。

## 4. 测试体系（命根子——这个项目 90% 的坑在行为上，不在类型上）

- **金样**：`tests/fixtures/` 存 12 源的**原始响应体**，与 Python 侧跑出的期望
  （`golden.json`）逐字段 diff，不是只比条数；回放按 `(url, 规范化请求体)` 命中。
- **对照表**：`tests/parity/*.json` 固化了各模块的行为对照断言，不手写期望值，覆盖 util / core / outcome /
  config / paths / net / migrate / query / torrent 等模块。
- **流水线**：`tests/search_pipeline.rs` 对照整条搜索的事件序列（5 场景，3 MB）。
- **空金样是假绿**：条数为 0 的金样解析器写错也照样过；新增源要人工确认条数显著大于 0。
- **回放盲区**：fixture 不看请求头与 referer——改客户端默认头之后必须跑
  `cargo run --release --example live_smoke` 真机对照耗时
  （knaben 曾因此 8.9s → 48.9s，条数完全一样）。
- **版本号不进 parity**；读「本机实时状态」（注册表 / 系统代理）的断言要么现场对现场，
  要么只校验形态，否则是定时炸弹。
- 时序类测试断言不变量，不断言墙钟的精确计数（`tpb_budget` 教训）。

## 5. 构建与验收

```bash
cargo test                              # 金样 + 工具函数对照
cargo build --release                   # 产物 target\release\happycrate.exe，直接跑
python tools/scan_comment.py            # 铁律 1：零注释
python tools/scan_comment.py --selfcheck
python tools/check_front_hygiene.py     # 铁律 2：界面文案
```

- 发布门：`cargo check --all-targets` 零警告 + 干净克隆能编。
- `cargo clean` 会把 `target\{release,debug}\data` 的现行配置一起清掉（debug 编译用的仓库根
  `data\` 不受影响）。配置丢了应用会按 `DEFAULT_SOURCES` 与内置默认值自动重建，
  手工只需补两处：bitsearch 源的开关与排序、`progress_look` 进度条配色。
- exe 图标靠 `tauri.conf.json` 的 `bundle.icon`（`assets/icon.ico`）嵌入；
  图标由 `tools/make_icon.py` 从 `web/assets/app-256.png` 派生——那是用户自己设计的图标，
  只装容器，不重画不缩放。`bundle.active` 保持 false：便携应用装进 Program Files
  会让 `data\` 不可写、退化成 `%APPDATA%` 模式，等于改了用户的数据位置。

## 6. 版本变更史

版本号规则：小改动按 `1.0.4.01` → `1.0.4.99` 递增（两位，满 99 才进 `1.0.5`）。
展示版本（窗口标题、关于页、启动日志）以 `api::APP_VERSION` 为准；`Cargo.toml` 与
`tauri.conf.json` 的 `version` 只保留合法三段 semver，随进位才同步。

- **v1.0.1**：移除 `diagnostics` 命令；`source_issues` 降级为只报 `state == "err"`
  （健康持久化不存在，5 条窗口判不了 silent）。
- **v1.0.2**：海量搜索分块懒渲染（首屏 100 条滚动追加）、全局 15s 硬超时、
  IPC 串行化（`push_gate`）与锁容毒。
- **v1.0.3**：导航 Tabs、明暗主题、右键批量复制、冗余元素清理。
- **v1.0.3 之后**：TUN 探测修复（`ipconfig` 在中文 Windows 是 GBK，按 UTF-8 解码
  永远扫不出来）、出口状态四档、头部两簇、`net_throughput`（口径是解压后字节）。
- **v1.0.4**：搜索请求放大治理。
  - `runner()` 增加 `relax_futile`：上一轮 `reached == 0`（全是 timeout/net/blocked
    或压根没发请求）时不再放宽重搜——断网场景原本会跑满 3 轮（345 个请求）。
  - 新增 `hard_timeout_ms` 设置项（默认 45000）：到点 `cancel_batch` 并照常推 `Done`
    （带 `hardStopped`），只是不写缓存。`soft_deadline_ms` 仍然只管 UI。
  - `tpb::more_pages` 改用镜像轮询的 `deadline` 算每页超时，原先它拿的是源配置的
    原始 timeout，不受预算约束（单源最长约 75 s，会撞前端 60 s 看门狗）。
  - `js_of` 转义 U+2028 / U+2029：JSON 允许但 JS 字符串字面量不允许，未转义时整批
    `eval` 抛 SyntaxError 且静默丢批。
  - `probe` 改用动态任务队列（原静态 `step_by` 分片会让慢源串在同一条道上），
    单源超时封顶 8 s，整体预算 30 s。
  - `dedupe` 的哈希查找由线性扫描换成 HashMap，去掉 `expect("已登记的哈希必在输出中")`。
- **v1.0.4.01**：小草磁力按站点自报条数抓取，不再固定盲抓 4 页。
  - `xccl263::search_words` 先取第一页并解析「找到 N 条结果」，按 `ceil(N/20)`
    决定实际页数（上限仍 4 页）：小结果量从固定 4 个请求降到 1 个，减少触发站点
    限流（429/500）后部分页失败、条数静默偏少的概率。
  - N 为整页倍数且未达上限时多取一页（防计数滞后或取整）；抓取范围内失败的页
    补抓一次，且只补可恢复错误（429/5xx/超时/传输失败），验证码拦截、代理不可达、
    4xx 不重复请求；仍缺页按现有约定返回已取得的部分。
  - 第一页失败时退回旧版盲抓 2~4 页行为，请求量与旧版一致；新增
    `tests/xccl263_pages.rs` 固化上述分支。
- **v1.0.4.02**：小草磁力补抓加间隔第二轮。
  - 对拍实测（2 词 × 3 轮 + 网页同刻对照）：两侧清单逐条一致，未复现遗漏；
    站点限流窗口约 5~10 s，连发约 10 次请求即开始 429/500。
  - `search_words` 的失败页补抓保留原有立即补抓，其后「仍失败且可恢复」的页等
    `RETRY_PAUSE_MS`（2 s）再补一轮：把限流窗口内「补抓也失败 → 静默少见」的
    残余窗口压小。全部失败（可见报错）路径不变，取消/验证码/4xx 等不触发等待。
  - `tests/xccl263_pages.rs` 增加两轮补抓恢复用例；改 `exhausted_refetch`
    期望为 3 次尝试。
- **v1.0.4.03**：番号查询的检索面与排序。
  - `xccl263` 对单段番号查询（字母 2-12 位 + 可选中划线/下划线 + 数字 2-5 位，
    如 `MIAD-251`）补发「紧凑写法」变体检索（`MIAD251`），反向同理；两组结果
    按 info_hash 合并去重，变体失败静默保留主检索结果。
    证据（2026-10-11 真机实测）：“MIAD-251” 连字符形态返回 49 条模糊命中且不含
    目标条目，紧凑形态一次精确命中（与 javbus 同 hash）；“MIAD802” 反向补出
    连字符形态独有条目。其它源实测变体无增益（sukebei/knaben/apibay 两形态皆空、
    tpb 紧凑形态 0 条），故只改 xccl263。
  - 概览默认排序对番号查询增加命中层级：整串命中（含紧凑/分隔变体）→ 字母数字
    双命中 → 仅字母 → 仅数字 → 未命中，层内沿用原 miss/热度排序；非番号查询与
    列排序不变。消除首屏被“251”类无关命中与无关联合集占据的现象。
  - `tests/xccl263_pages.rs` 新增变体用例 5 条（双向、失败保留、纯词跳过、
    畸形番号跳过）。
- **v1.0.4.04**：内置浏览器取数通道（bt4g 试点）。
  - 新增 `src/web_fetch.rs` 取数通道：隐藏 WebView2 窗口（懒创建、独立数据目录
    `data/webview`）+ 单 worker 串行队列；经 `eval_with_callback` 取回整页 HTML
    （tauri 2.12 自带能力，页面侧无需任何权限，capability 零改动）；挑战页自动
    等待，超 8 秒窗口浮出供人工点验，通过后收回；取消/超时即复位 about:blank。
    被拦源（`sources::WEBVIEW_KEYS`）在 `search.rs` 按 key 路由改走该通道，
    其余 12 源与前端不变。
  - 新增第 13 个源 bt4g（bt4gprx.com）：搜索页解析标题/大小/做种/时间，
    `/magnet/{id}` 详情页取 infohash；fixtures 与 golden.json 入库，
    `tests/golden.rs` 增 `golden_bt4g`、fixture 源数改 13；`WEBVIEW_KEYS`
    之外同步 `DEFAULT_BASES`、分发表、`DEFAULT_SOURCES`（默认开启）与
    `OVERSEAS_KEYS`。
  - 对照表更新：api/config/migrate 三处对照按「新增内置源随默认配置补齐」语义
    追加 bt4g（37 个断言点逐用例核对，仅 bt4g 一项变化）。
  - 实测：隐藏窗口直接取回 bt4g 搜索结果页（未出现人工验证）；金样 3 条与
    BitSearch/BTDigg 侧哈希交叉一致。
  - `tests/web_fetch_queue.rs` 新增 5 条通道单测（回传、串行、超时、取消、
    错误透传）。
- **v1.0.4.05**：BTDigg 接入取数通道（第 14 个源）。
  - 新增 `src/sources/btdig.rs`：搜索页 `one_result` 块解析（标题、体积、
    哈希直接取自列表页磁力链接），单页 10 条；`WEBVIEW_KEYS`、`DEFAULT_BASES`、
    分发表、`DEFAULT_SOURCES`（默认开启，order 13）与 `OVERSEAS_KEYS` 同步。
  - fixtures 与 golden.json（10 条）入库；`tests/golden.rs` 增 `golden_btdig`、
    fixture 源数改 14。
  - 对照表更新：api/config/migrate 三处按「新增内置源随默认配置补齐」追加
    btdig（深比对仅 btdig 一项变化）。注意：遗留 Python 配置样本中本就含有
    btdig 项，迁移合并数因此 4 → 5（属正确合并行为，非回归）。
  - 实测：btdig 结果页可通过内置浏览器通道访问；条目哈希与既有源
    （BitSearch、小草磁力）交叉一致。
- **v1.0.4.08**：四源抓取深度修复（btdig/javbus/bt4g/小草磁力）。
  - btdig：查询空格一律用 `+`（原先 `%20` 会被站点边缘直接打回 nginx 默认页，
    多词查询恒 0 条；单测金样为单词查询所以从未暴露）。结果抓取 1 页扩到 8 页
    （10 条/页，跨页去重，空页即止）；fixture 补 p1–p7 共 7 页，金样 10 → 80 条。
  - javbus：搜索路径空格改用 `+`（站点自用格式；`%20` 形态 403 导致多词查询
    永远走拆词兜底）。多词查询改为「整串 + 逐词」合并去重；覆盖上限 12 部/词
    提到 30 部；新增限流恢复节奏——站点对突发约 40 次请求后回 429/1015、约 9 秒
    解封（真机实测），改为每波 20 部、波间隔 9 秒停顿、每轮把 429/超时失败项
    重排回队列，最多 3 轮、整源 30 秒预算封顶（避免贴着 45 秒硬截断被取消后
    整源丢结果）。fixture 补 18 部详情+磁力接口，金样 261 → 637 条。
  - bt4g：详情抓取上限 12 → 30（覆盖整页），去掉按「2 秒/条」折算的保守预算，
    改为给每次详情请求传入源内截止时刻、由真实耗时决定抓多少；取数通道轮询
    间隔 1200 ms → 400 ms（每页实测约 1.34 s → 约 1.0 s），详情吞吐随之提升。
  - 小草磁力：分页上限 4 → 10、MAX_HITS 200 → 400；fixture 补 5–10 页，
    金样 80 → 197 条（跨页去重后 197）。
  - `sources::pause` 从 xccl263 提为公共助手，javbus 复用；`xccl263_pages.rs`
    首屏失败用例、`relax_guard.rs` 请求数断言、`search_pipeline.json` 五场景中
    的小草事件与请求数随行为重生成（差异逐项核对仅限 xccl263 计数/条目、
    Done 汇总与 +6 请求）。
  - 真机实测（tokyo hot，探针实例 + CDP 记录）：btdig 0 → 80 条、
    javbus 75 → 330 条、bt4g 4/8 → 12 条、小草磁力 80 → 180/200 条；
    整次搜索 27.5 秒自然收尾，未触发硬截断。
- **v1.0.4.09**：取数通道按源分窗 + 落地地址校验。
  - `web_fetch` 由共享单通道改为按 `WEBVIEW_KEYS` 每源一条通道（各自隐藏
    窗口与串行队列，窗口标签 `fetch-{key}`，共用 `data/webview` 配置目录）：
    bt4g 与 btdig 不再互相排队。实测 btdig 8 页在分窗后约 11 秒收完
    （此前与 bt4g 争用约 24 秒），bt4g 在同样的 20 秒预算内由 7 条升至
    15 条（站点首页满页）。
  - 修掉「新窗口首个抓取命中旧文档」竞态：WebView2 导航提交前旧文档仍是
    complete，轮询可能把 about:blank 或上一个页面当成本次结果（表现为该源
    静默"无结果"）。状态脚本增加 `location.href`，只有落地地址与请求地址
    完全一致才接受页面；已实测两站四种 URL 形态均不改写地址。
  - 实测（tokyo hot）：btdig 80 条、bt4g 15 条、javbus 336 条、
    小草磁力 180 条，整次搜索 27.8 秒自然收尾。
- **v1.0.4.10**：BTDigg 抓取深度 8 → 16 页。
  - 分窗后取数窗口独享，8 页约 11 秒；上限提到 16 页（约 20 秒），
    仍在整次搜索既有节奏内（JAVBUS 约 30 秒为大头，btdig 不再拖尾）。
  - fixtures 补 p8–p15（该查询共 16 页，p15 为 2 条尾页），金样 80 → 152 条
    （跨页去重后 152，旧 80 条前缀逐条一致）。采集期间站点对命令行客户端
    持续回 429（同日密集抓取触发），实际经浏览器通道完成补采。
  - 真机实测（tokyo hot）：btdig 80 → 160 条，整次搜索 30.4 秒自然收尾。

## 7. 教训精选（每条都真踩过）

1. `re.sub` 是**全局替换**；`search` / `match` / `findall` 找到就停——两套语义要分开记。
2. strptime 的字段宽度**逐字段抄**：`%m` 不接受空格填充，`%M` / `%S` 一位数合法；凭印象必错。
3. Python 的 `\d` 是 Unicode Nd 类（匹配全角 `５`），`\s` 含 `\x1c`-`\x1f`——照 ASCII 写就漏。
4. reqwest 用 `connect_timeout` + `read_timeout`，**别用 `.timeout()`**（那是总时长，
   会误杀大响应体；Python 的 timeout 是 socket 语义，每次读重置）。
5. 本机系统代理**只在注册表**，reqwest 默认只认环境变量；`net.rs` 自己按
   手动 → 环境变量 → 注册表解析。`reg query` 在 Git-Bash 要写 `//v`、用 SystemRoot 全路径。
6. ProxyOverride 绕过列表用 fnmatch 语义（整体匹配、Windows 下忽略大小写）；
   短路逻辑在外层 `proxy_bypass_registry`，不属于内层匹配函数。
7. tao 0.37+ 的无边框 + resizable 窗口**自带整圈 WM_NCHITTEST 边缘拉伸**，不用自己写。
8. 迅雷 COM 在本机不可用（32 位 InprocServer32，64 位进程加载不了；`Dispatch` 报
   0x80040154），只走 `ProtocolMethod`（`thunder.exe <magnet> -StartType:magnet`）。
   `added` 计的是「进程启动成功」，不是「迅雷收下了」——COM 也没这能力，不是 bug。
9. 「注册表里有」不等于「能用」——ProgID 键存在但 CLSID 未注册，`Dispatch` 才是判据。
10. fixture 回放不看请求头；「测过了」不等于请求头被测过。
11. grep 核验调用点必须扫 `src/` + `tests/` + `tools/` 三处、禁用 head 截断——
    死代码清单曾因此错 4 处（2026-10-03 清理时编译器当场拦下）。

## 8. 已拍板决策（不再动的东西）

- **`web/` 前端完全在此仓维护**，老 Python 仓前端已随项目下线清理。
- **`src/util.rs` 不拆文件**（全是无状态纯函数，行数不是臃肿的判据，死代码和冗余才是）。
  触发点：超约 1,300 行或时间解析段继续膨胀时，把时间解析整块搬 `src/time.rs`。
- **diagnostics 命令不移植**，`source_issues` 只报 err；健康度不持久化——
  `health.json` 不生成，测速结果只在会话内存（`probe_seen`），重启即空。
  `state` 按「本次 outcome」而非 Python 的五次滚动窗口，是已知且接受的差异。
- **推送钩子不换 Tauri Channel**（eval 照抄现有 JS，前端零改动）。
- 相对时间解析（tpb 的 `today` / `Y-day`）把「现在」做成显式参数进金样，
  不放宽 diff——能严格就别放宽。
- 工程纪律（零注释、白描、.scratch 收纳、网络与代理）的权威在 `AGENTS.md`，本文不重抄。
