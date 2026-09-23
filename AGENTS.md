# happycrate 作业规程

磁力搜索聚合与下载投递工具。Python 3.11+ / pywebview，Windows 便携应用。
人看的项目说明在 `README.md`，本文件只讲 agent 该遵守的作业规矩。

## 4条铁律

### 1. 代码零注释

源码里不写注释、不写 docstring，名字起清楚就行。
例外只有两种：工具指令（`# noqa` 这类）、被运行时真正读取的字符串。
整理存量代码时，已有注释属于清除对象。

### 2. 界面不加说明字

界面只写「它是什么」和「出了什么问题」，不写「怎么用」。
禁止解释性与引导性文字，例如「点击这里进入自定义界面」「该字段显示在列表的来源列」。

允许出现的只有五类：

- 字段名
- 必填标记 `*`
- 出错时的具体原因
- 禁用态的原因
- 空状态文案

需要示范格式时用 placeholder，不要额外加一行说明。

#### 这条也管输出文本，不只是界面控件

诊断、回执、日志以外的任何「给人看」的字符串都算界面。踩过的坑：

- 中文标签当字段名（`现象` / `明细` / `建议` / `位置` / `对照`）——这不是界面，是注释漏进了产品
- 括号里挂解释（`连接失败（需要换地址或查网络）`）——后半句是引导语
- 把面向 AI 的排查细节摊给用户（`app/sources.py :: _search_bitsearch`、`http5xx`）

正确做法是**分两层**：

| 面向  | 内容                                           | 出口                         |
| --- | -------------------------------------------- | -------------------------- |
| 用户  | 名称 + 具体原因（`HTTP 500`、`最近 5 次请求均为 0 条`）       | `Api.source_issues()` → 弹窗 |
| AI  | 全量结构化数据（events / outcomes / peers / adapter） | `Api.diagnostics()` → 复制按钮 |

给 AI 的那份用 JSON 而非中文标签，字段名就是 `key` / `count` / `ms` / `adapter`。
`tests/test_front_hygiene.py` 有护栏禁止引导语回流。

### 3. 非源码一律进 `.scratch/`

报告、备份、脚本、截图、数据导出、临时中间物，全部进 `.scratch/`。
允许留在根目录的只有：源码（`app/`、`main.py`、`tests/`）、资源（`assets/`）、
仓库元文件（`README.md`、`LICENSE`、`pyproject.toml`、`happycrate.spec`、
`happycrate.bat`、`.gitignore`、`.gitattributes`、`AGENTS.md`）、运行时数据（`data/`）、构建产物（`dist/`、`build/`）。

`.scratch/` 整体不进版本库，`.scratch/reports/` 的成品报告也不例外，交付时用原生
Windows 路径（`D:\...`）引用，不要用 `/d/...` 这种 shell 风格路径。

## 4.网络与代理

程序走不走代理由 `app/sources.py :: _opener` 决定：设置里填了 `proxy` 就用它，
没填则 `urlopen` 走 `urllib.request.getproxies()`（Windows 读系统/IE 代理，**PAC 脚本读不到**）。
设置页「关于 → 网络出口」显示实际用的是「手动设置 x」/「跟随系统 x」/「未检测到代理」。

**排查网络问题前先问用户，不要自己反复试。**

连不上的原因跨好几层：目标站点、代理工具、TUN 还是系统代理、PAC、安全软件、地区封锁。
这些只有用户知道，试探是试不出来的。正确顺序：

1. 一次实测拿到错误原文（`Tunnel 502` / `451` / `timed out` 等）
2. 把「网络出口显示什么 + 错误原文 + 浏览器里能不能开」一起告诉用户
3. 等用户确认再动手

禁止：串行/并发反复试探、反复重装 Runtime、把环境问题当成代码问题改代码。

## 提交纪律

- `.scratch/` 不进版本库，不需要 `git add`。
- `happycrate.spec` 是手写构建配方，必须跟踪。`.gitignore` 里 `*.spec` 会误伤它，
  靠 `!happycrate.spec` 放行——别删那行。
- `data/sources.json` 是核心资产，已纳入版本管理（`.gitignore` 用 `data/*` 排除整个目录、
  再用 `!data/sources.json` 放行它，别把这两行合并成 `data/`——那样例外不会生效）。

## 构建与测试

**改代码不用打包。** `app/` 和 `web/` 都是外置的（不编译进 exe）：

- 改 `app/*.py` → 改 `dist/happycrate/_internal/app/` 里那份，重启生效

- 改 `web/*` → 改 `dist/happycrate/_internal/web/` 里那份，刷新生效

- 手工复制容易把路径写错（历史上出现过 `dist/happycrate/_internal/data` 这种错位文件），
  统一走 `.venv/Scripts/python.exe tools/sync-dist.py`

- 只有**新增或删除第三方依赖**才需要重新打包

- 打包**必须用项目 .venv**：`./.venv/Scripts/python.exe -m PyInstaller happycrate.spec --noconfirm`。
  全局 python（3.14，无 pywebview）打出来是空壳：`import webview` 变成命名空间包，
  启动即 `no attribute 'create_window'`，且不报构建错误。

- 程序从 `dist/happycrate/happycrate.exe` 运行，根目录不再放 exe 和 `_internal/`。
  别把它们同步回根目录——那样很容易留下过期的旧副本（体积一模一样，看不出来）。

- `build/` 是打包中间产物，每次打包自动生成，可随时删。

- 打包会删 `dist/happycrate/` 重建（166+ 文件），可能触发沙箱的批量删除阈值。
  真拦了就先手工 `rmSync('dist/happycrate')` 再跑打包。

- 源码外置靠 `happycrate.spec` 里的 `a.pure` 过滤（`m[0] != "app" and not m[0].startswith("app.")`）。
  升级 PyInstaller 后若失效，表现是「改了代码重启不生效」—— 很好发现，重新确认这行即可。

- mock 的 startSearch 按源逐个投放（约 2.3s），E2E/探针等搜索完成必须等
  `HC.views.search.st.busy === false`，只等行数会在 DOM 仍在变化时跑测试。

- `tests/e2e/hc-e2e-test.mjs` 是无头浏览器端到端测试（617 行，CDP 协议驱动），
  能自动跑完搜索/框选/全选/弹窗/主题切换等 60+ 项。它每次运行会在 `.scratch/tmp`
  生成一个 ~53 MB 的 Chrome profile，**跑完记得清 `.scratch/tmp`**。

## 工具

三个地方，别搞混：

| 位置 | 性质 | 说明 |
| --- | --- | --- |
| `happycrate.bat` | 启动器 | 无参数跑 `dist` 里的 exe；`dev` 最小化跑源码；`web` 起本地服务器 8123 |
| `tests/` | 测试 | 单元测试（587 项）· `front_smoke.cjs` 等 5 个源码校验 · `e2e/hc-e2e-test.mjs` 端到端 |
| `tools/` | 生产工具 | 代码体检扫描器 · dist 同步 · 护栏回归。**清单见 `tools/README.md`** |

**写新脚本或工具之前先读 `tools/README.md`——已有的一律复用，不要重写。**

一次性的东西（复现、截图、临时分析）扔 `.scratch/tools/`，用完清掉。
那里的东西不进版本库，也不该攒。

```bash
# 单元测试（587 项）
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"

# 改完源码同步到 dist（不用重新打包）
.venv/Scripts/python.exe tools/sync-dist.py

# 代码体检
.venv/Scripts/python.exe tools/scan/scan_py.py

# 端到端；每次生成 ~53MB profile，跑完清 .scratch/tmp
node tests/e2e/hc-e2e-test.mjs
```

## 边界

本工具**不涉及账号体系**：不登录、不保存任何站点的用户名或令牌。
讯雷只是「被唤起的下载工具」，登录与配额由它自己处理。
