# happycrate 作业规程

磁力搜索聚合与下载投递工具（Python 3.11+ / pywebview / Windows 便携应用）。项目说明在 `README.md`，本文件只讲规矩。

## 4 条铁律

### 1. 代码零注释

核心源码 = `app/`、`web/`、`main.py`、`tests/`：不写注释、不写 docstring，名字起清楚就行。
`tools/` 不算核心源码，那里的 docstring / 注释照常写，别去清理。
例外只有：工具指令（`# noqa`）、被运行时真正读取的字符串。整理存量代码时，已有注释是清除对象（只清核心源码里的）。
机器强制：`tools/scan/scan_comment.py`（已进 `check-all`），校准件在 `tools/scan/fixture-comments/`。

### 2. 界面不加说明字

只写「它是什么」和「出了什么问题」，不写「怎么用」。禁止解释性与引导性文字。
允许五类：字段名 · 必填标记 `*` · 出错的具体原因 · 禁用态的原因 · 空状态文案。示范格式用 placeholder，不加说明行。

**这条管所有「给人看」的字符串**（诊断、回执、日志以外的都算界面）。禁止：中文标签当字段名（`现象` / `明细`）· 括号挂解释（`连接失败（需要换地址或查网络）`）· 把 AI 排查细节摊给用户（`app/sources.py :: _search_bitsearch`）。

两层出口 —— 用户层：名称 + 具体原因，走 `Api.source_issues()` 弹窗；AI 层：全量结构化数据、字段用英文（`key` / `count` / `ms` / `adapter`），走 `Api.diagnostics()` 复制按钮。
`tests/test_front_hygiene.py` 有护栏禁止引导语回流。该扫描器覆盖 `app/` 那几个门面文件，
且**不再跳过含 `#` 的行** —— 往注释里写引导语两头都躲不掉。

### 3. 非源码一律进 `.scratch/`

报告、备份、脚本、截图、数据导出、临时中间物全进 `.scratch/`。根目录只允许：源码（`app/`、`main.py`、`tests/`）、资源（`assets/`）、仓库元文件（`README.md`、`LICENSE`、`pyproject.toml`、`happycrate.spec`、`happycrate.bat`、`.gitignore`、`.gitattributes`、`.github/`、`AGENTS.md`）、`data/`、`dist/`、`build/`。

- `.scratch/` 整体不进版本库（成品报告也一样）；交付用原生 Windows 路径 `D:\...`，不用 `/d/...`。
- **不往 `.workbuddy/` 写东西，也不重建它**（宿主强制新建，项目不用）。
- **不写跨会话的记忆 / 日志文件。** 权威在 `AGENTS.md` 与 `tools/README.md`。

### 4. 网络与代理

走不走代理由 `app/sources.py :: _opener` 决定：填了 `proxy` 就用它，没填则 `urlopen` 走 `urllib.request.getproxies()`（Windows 读系统 / IE 代理，**PAC 读不到**）。设置页「关于 → 网络出口」显示实际出口。

**排查网络问题前先问用户，不要自己反复试。** 原因跨好几层（目标站点 / 代理工具 / TUN 还是系统代理 / PAC / 安全软件 / 地区封锁），只有用户知道。顺序：一次实测拿错误原文（`Tunnel 502` / `451` / `timed out`）→ 连「网络出口显示什么 + 浏览器能不能开」一起告诉用户 → 等确认。
禁止：反复试探、反复重装 Runtime、把环境问题当成代码问题改代码。

## 提交纪律

- `.scratch/` 不进版本库，不需要 `git add`。
- `happycrate.spec` 必须跟踪：`.gitignore` 里 `*.spec` 会误伤它，靠 `!happycrate.spec` 放行，别删那行。
- `data/sources.json` 已纳入版本管理：`data/*` 排除目录 + `!data/sources.json` 放行，这两行别合并成 `data/`（合并了例外不生效）。

## 构建与测试

**改代码不用打包** —— `app/` 和 `web/` 都外置（不编译进 exe）：

- 改 `app/*.py` → 同步改 `dist/happycrate/_internal/app/` 那份，重启生效；改 `web/*` → 同步改 `_internal/web/` 那份，刷新生效
- 手工复制容易写错路径，统一走 `tools/sync-dist.py`；只有**增删第三方依赖**才需要重新打包

- 打包**必须用项目 .venv**（全局 python 3.14 无 pywebview，打出空壳：启动 `no attribute 'create_window'` 且不报构建错误）
- 程序从 `dist/happycrate/happycrate.exe` 运行，根目录不放 exe 和 `_internal/`——同步回去会留下看不出来的过期副本
- `build/` 可随时删；打包会删 `dist/happycrate/` 重建（166+ 文件），可能触发沙箱删除阈值，拦了就先 `rmSync`
- 源码外置靠 `happycrate.spec` 的 `a.pure` 过滤（`m[0] != "app" and not m[0].startswith("app.")`）；升级 PyInstaller 若失效，表现是「改了代码重启不生效」
- mock 的 startSearch 按源逐个投放（约 2.3s），E2E / 探针等搜索完成必须等 `HC.views.search.st.busy === false`，只等行数会在 DOM 仍在变化时跑测试
- `tests/e2e/hc-e2e-test.mjs` 是 CDP 驱动的 E2E。行数与断言条数别抄进文档，跑一次数 `ok` / `FAIL` 行。
  每个浏览器用自己那份 `.scratch/tmp/hc-e2e-<时间戳>/<序号>` profile（共用一份会让第二个内核读到上一个
  留下的 `DevToolsActivePort` 而死在 `ws-open-failed`）。**正常情况下脚本自己删 profile**（开头还会扫掉
  上次残留）；只有它打印「profile 仍被占用」时才需要 `tools/clean-e2e.py`

## 环境事实（排查前先看）

- **有两套运行时数据目录**，别混着看：源码模式（`python main.py`）写仓库根 `data/`；打包模式写**exe 旁边**的 `dist/happycrate/data/`。看当前用的是哪个：设置 → 关于 → 数据目录。
- **关键词词表只有一份真源**：`app/query.py` 的 `_BUILTIN_WORDS` / `_BUILTIN_VARIANTS`。想临时扩词表可以在数据目录放 `query_roles.json`（`words` / `variants` 两段，会整体覆盖对应 role），但**它不进版本库**，改完不留痕。改完点设置 → 关于里的「重新载入」。
- **配置文件读不出来时不静默**：`config.py :: _load_json` 会把它备份成同名的 `.broken.json` 再回退默认，
  路径经 `app_info()["recovered"]` 出口 → 关于页「已恢复默认」一行 + 启动 toast 一次。新增消费点别改文案里的
  「损坏」二字（铁律 2 只允许「出了什么问题 + 具体原因」）。
- **设置页点击即生效的四样**：主题 / 字号 / 品牌色 / 进度条外观改的是全局 DOM 与 CSS 变量，不是等保存才动。
  所以三条「放弃未保存改动」的路径（`tryClose` · `leaveGuard` · `_clkKey`）都必须先 `revertApplied()`
  → 复用 `HC.applySettings`，否则界面停在被丢弃的样式上直到重载。**加第五个即时控件时同理**，
  护栏 `DiscardRevertsPreviewTest` 会盯住这条。音量不在其列——sfx 是播放时才读 `HC.settings`。
- **视图 mount 期抛的异常，前端护栏基本看不见**：`settings.js` 的 `Promise.all([...]).catch()` 会把
  `fill()` 里的错误直接涂成关于页一行「设置加载失败」，**不进 `window.__errs`**，于是 E2E 的
  `no-window-errors` 与全量单测照样全绿——实测过一次 `lookRange is not defined` 就是这么溜过去的。
  这类问题只有断言具体界面内容的 E2E 步骤能抓（当时是 `netbar` 等待超时暴露的）。改完 `web/` 别只跑单测。
- **根目录若出现 `nul` 之类的保留名文件**：Git Bash 里 `ls`/`wc` 能读，但 `rm nul` 和
  PowerShell 的 `'\\?\D:\...'` 都会失败（MSYS 把前导 `\\` 吃成一个 `\`）。可用形式是
  `rm -f '//?/D:/AI/happycrate/nul'`。它通常是 `dir /b /s` 的报错被重定向出来的，165 字节左右，直接删。

## 工具

**开工先跑 `tools/check-all.py`（十几秒，`--all` 加 E2E 与反向注入）**：单测项数、7 个扫描器结果与耗时、dist 是否同步、mypy 类型检查，一次拿到。别自己拼命令统计规模。
**找轮子 / 写新脚本之前先读 `tools/README.md`**：按「我要做 X」列了决策表，已有的一律复用。

- `happycrate.bat` 启动器：无参数跑 dist 的 exe · `dev` 跑源码 · `web` 起 8123 本地服务器
- `tests/` 测试：单测（项数以 check-all 实测为准）· 7 个源码校验 · `e2e/hc-e2e-test.mjs`
- **单测必须带 `-t .`**：`.venv/Scripts/python.exe -m unittest discover -t . -s tests -p "test_*.py"`。不带 `-t` 时 `tests/__init__.py` 不执行，数据目录隔离失效，测试会写用户真配置（`data/*` 被 gitignore，看不出来）
- `tools/` 生产工具：**一键全检** · 代码体检扫描器 · dist 同步 · 护栏回归 · 提交前检查（清单见 `tools/README.md`）

`tools/` 是长期资产：**不许以「清理」「整理」为名删除或重写**，判定标准只有一条——下轮还会不会用。用完即弃的才放 `.scratch/tools/`（用完清掉）。

```bash
.venv/Scripts/python.exe tools/check-all.py            # 一键全检（--full 加 E2E · --guard 加反向注入 · --update-baseline 重设基线）
.venv/Scripts/python.exe tools/sync-dist.py            # 改完源码同步到 dist，不用重新打包
.venv/Scripts/python.exe tools/pre-commit.py --install # 提交前检查，挡「改了源码忘了同步 dist」
```

其余命令（单测 / 反向注入 / 代码体检 / E2E）见 `tools/README.md`。

## 边界

不涉及账号体系：不登录、不保存站点用户名或令牌。迅雷只是被唤起的下载工具，登录与配额由它自己处理。
