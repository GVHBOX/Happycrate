# happycrate 作业规程

磁力搜索聚合与下载投递工具。Python 3.11+ / pywebview，Windows 便携应用。
人看的项目说明在 `README.md`，本文件只讲 agent 该遵守的作业规矩。

## 三条铁律

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

### 3. 非源码一律进 `.ai/`

报告、备份、脚本、截图、数据导出、临时中间物，全部进 `.ai/`。
允许留在根目录的只有：源码（`app/`、`main.py`、`tests/`）、资源（`assets/`）、
仓库元文件（`README.md`、`LICENSE`、`pyproject.toml`、`happycrate.spec`、
`happycrate.bat`、`.gitignore`、`.gitattributes`、`AGENTS.md`）、运行时数据（`data/`）、构建产物（`dist/`、`build/`）。

`.ai/` 整体不进版本库，`.ai/reports/` 的成品报告也不例外，交付时用原生
Windows 路径（`D:\...`）引用，不要用 `/d/...` 这种 shell 风格路径。

## 产品边界

只做四件事：**源 / 查询 / 结果 / 投递**。

明确不做：搜索历史、收藏夹、资源库、账号与同步、分享链接、订阅与关键词监控、
内置播放器与下载管理、多语言、前端框架。

不做前端框架是为了保住「双击 index.html 就能看到成品」的双模机制，不要引入构建步骤。

## 架构分层

```
web/   界面。HTML/CSS/JS，不含业务规则
app/   Python 后端。api.py 是给 JS 的唯一门面
```

两层之间只有一条 JSON 通道。Python 不持有任何界面状态，前端不持有任何业务规则。

`web/js/api.js` 检测 `window.pywebview`：存在走真机，不存在走 mock。
**同一份前端，两种跑法**——浏览器直接打开 index.html 就是可玩原型。

## 结果条目字段

后端给前端的每条结果是**已经格式化好的**，前端不要再算一遍：

`hash / title / size / sizeText / seeders / leechers / added / addedText / magnet / sources[]`

## 源健康度

两种坏法必须分开：

- **A 连不上**：超时、DNS 失败、403/503、代理不通。用户换镜像地址即可。
- **B 连上但抠不出东西**：HTTP 200 正常但解析出 0 条。站点改版，必须改适配器代码。

坏法 B 最隐蔽，界面必须明确写「疑似改版」，并给出一键复制的诊断信息
（含 `app/sources.py :: _search_xxx` 这样的适配器位置）。

健康度 = 最近 5 次结果的滑动窗口，按成功比例判定。不后台轮询，搜索时顺带记录。
连续异常 5 次自动排到最后，**不禁用，仍然会试**。

## 提交纪律

- `.ai/` 不进版本库，不需要 `git add`。
- `happycrate.spec` 是手写构建配方，必须跟踪。`.gitignore` 里 `*.spec` 会误伤它，
  靠 `!happycrate.spec` 放行——别删那行。
- `data/sources.json` 是核心资产，已纳入版本管理（`.gitignore` 用 `data/*` 排除整个目录、
  再用 `!data/sources.json` 放行它，别把这两行合并成 `data/`——那样例外不会生效）。
  改动前先备份到 `.ai/backups/`。

## 构建与测试

**改代码不用打包。** `app/` 和 `web/` 都是外置的（不编译进 exe）：

- 改 `app/*.py` → 改 `dist/happycrate/_internal/app/` 里那份，重启生效
- 改 `web/*` → 改 `dist/happycrate/_internal/web/` 里那份，刷新生效
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
- `.rows` 是列向 flex 容器，行高会被压缩塞满视口；行高调节（.roomy）靠
  `flex:none` 才能生效。
- `tests/e2e/hc-e2e-test.mjs` 是无头浏览器端到端测试（520 行，CDP 协议驱动），
  能自动跑完搜索/框选/全选/弹窗/主题切换等 30+ 项。它每次运行会在 `.ai/tmp`
  生成一个 ~53 MB 的 Chrome profile，**跑完记得清 `.ai/tmp`**。

## 边界

本工具**不涉及账号体系**：不登录、不保存任何站点的用户名或令牌。
讯雷只是「被唤起的下载工具」，登录与配额由它自己处理。
