# tools/ · 现成的轮子

> **新会话先读这份。写任何新脚本之前也先读这份——已有的一律复用，别重写。**
> 命令一律从项目根目录执行，需要 Python 的一律用项目 `.venv`。

## 新会话起手（按顺序，别跳）

```bash
git status --short                               # 1. 工作区干净吗
git log --oneline -12                            # 2. 上次做到哪
.venv/Scripts/python.exe tools/check-all.py      # 3. 现状是不是绿的（约 13s）
```

第 3 步一次给出：单测项数、7 个扫描器各自的结果与耗时、dist 是否同步、mypy 类型检查。
**不要自己拼命令去统计规模或跑测试**——那条命令已经算好了。

然后按下面的决策表找轮子；找不到再考虑写新的。

## 我要做 X → 用哪个轮子

| 我要… | 用 | 命令 |
| --- | --- | --- |
| 改完代码，想知道有没有弄坏 | `check-all.py` | `.venv/Scripts/python.exe tools/check-all.py` |
| 怀疑有测试改了我的真实配置 | `check-all.py` | 同上，看「单元测试」那行末尾的「数据目录未受影响 / 被改动 N 个」 |
| 提交前把关 | `pre-commit.py` | 同上；`--install` 可挂进 `.git/hooks` |
| 改了 `app/` 或 `web/`，让 dist 生效 | `sync-dist.py` | `.venv/Scripts/python.exe tools/sync-dist.py`（**不用重新打包**） |
| 找某个函数 / 常量 / 类名在哪 | `scan/refs.py` | `... tools/scan/refs.py format_size` |
| 查死代码、多返回元组、版本漂移 | `scan/scan_py.py` | 单跑；`check-all.py` 里已含 |
| 查 CSS 变量孤儿、重复选择器、硬编码白底 | `scan/scan_css.py` | 同上 |
| 查后端方法有没有前端调用（双向） | `scan/scan_api.py` | 同上 |
| 查超长函数、重复代码块 | `scan/scan_bloat.py` | 同上 |
| 查「结构相同但名字不同」的复制漂移 | `scan/scan_dupfunc.py` | 同上 |
| 查源适配器参数是不是真被读 | `scan/scan_adapter.py` | 同上 |
| 查有没有人在核心源码里写注释 / docstring | `scan/scan_comment.py` | 同上，`check-all.py` 里已含 |
| 加了一条新护栏，想证明它真能拦住东西 | `guard-regression.py` | `--list` 看清单，`--case <关键字>` 只跑相关的 |
| 单测红了一次、重跑又绿（怀疑偶发） | `flaky-probe.py` | `.venv/Scripts/python.exe tools/flaky-probe.py 5`（连跑 N 遍统计复现率） |
| 端到端跑一遍真实界面 | `tests/e2e/hc-e2e-test.mjs` | `node tests/e2e/hc-e2e-test.mjs`（**跑完清 `.scratch/tmp`**） |
| 量化某个关键词能召回多少、值不值得扩 | `hc-adult-coverage.py` | `... tools/hc-adult-coverage.py --query SSIS --pages 10`（联网） |
| 评估一个新磁力源值不值得加（连通性 / 可解析性） | `hc-source-candidates.py` | `... tools/hc-source-candidates.py`；`--only <key>` 只跑几个、`--dump <key>` 落盘看结构（联网） |
| 核对「源自报总数」与「实际取回」的缺口 | `hc-recall-audit.py` | `... tools/hc-recall-audit.py 1080p matrix`；`--fresh` 打印各源到达时间 |
| 网络连不上，想知道是哪一层的问题 | `hc-net-probe.py` | `... tools/hc-net-probe.py --source <源>`；`--control` 加对照组，`--wait N` 区分瞬时/持续 |
| 跑完全部检查（含 E2E / 反向注入） | `check-all.py` | `--full` 加 E2E、`--guard` 加反向注入、`--all` 全跑 |
| 清理 E2E 残留的浏览器进程 | `clean-e2e.py` | `.venv/Scripts/python.exe tools/clean-e2e.py` |

## 完整清单

### check-all.py · 一键全检

默认档约 14s：单测 + 7 个扫描器 + dist 同步检查 + mypy。
**只有「基线之外的新增项」才让退出码非 0**（原因见下）。

单测那一步还会顺手验一件事：**跑测试前后真实数据目录（`data/*.json`）的
`(md5, mtime_ns)` 必须一模一样**。测试由 `tests/__init__.py` 统一隔离到临时目录，
一旦哪个测试绕过了隔离、写到用户真配置上，这一步会直接点名是哪个文件。
（只比 md5 抓不到「覆写的内容跟原来一样」，所以连 mtime 一起比。）

```bash
.venv/Scripts/python.exe tools/check-all.py              # 默认
.venv/Scripts/python.exe tools/check-all.py --full       # 加 E2E
.venv/Scripts/python.exe tools/check-all.py --guard      # 加反向注入（约 5min）
.venv/Scripts/python.exe tools/check-all.py --all
.venv/Scripts/python.exe tools/check-all.py --update-baseline
```

### 代码体检（scan/）

对全项目做静态扫描，不依赖运行环境。每个都是独立脚本，结果输出到 stdout。

| 脚本 | 查什么 |
| --- | --- |
| `scan_py.py` | 死代码 · 多返回元组长度不一致 · 重复定义 · 版本号漂移 · 异常吞噬 |
| `scan_css.py` | CSS 变量双向孤儿 · 顶层重复选择器 · 硬编码白底 · 裸 z-index |
| `scan_api.py` | 后端 Api 方法 ↔ 前端调用，双向差集 |
| `scan_bloat.py` | 超长函数 · ≥7 行重复代码块 · 跨文件重复字面量 |
| `scan_dupfunc.py` | 结构逐字相同、但名字不同的函数（复制漂移） |
| `scan_adapter.py` | 源适配器的参数是否真被函数体读取 |
| `scan_comment.py` | 核心源码（`app/`、`web/`、`main.py`、`tests/`）里出现的注释与 docstring —— 铁律 1。`tools/` 明确豁免，`# noqa` 一类工具指令算例外 |
| `api_contract.py` | 不是扫描器，是**共用口径**：「前端调用集合」怎么认（静态 `pywebview.api.x` + `call("x")` 动态派发 + Python 侧 `bridge.boot()` 这类调用点）。`scan_api.py` 与 `tests/test_contract.py` 都从这里取数，两边不可能再各说各话；想改口径只改这一处 |
| `refs.py` | 查一个名字在全项目的出现位置（不传参数则现跑 scan_py 取死代码清单，不读落盘快照） |

```bash
.venv/Scripts/python.exe tools/scan/scan_py.py
.venv/Scripts/python.exe tools/scan/refs.py format_size
```

**校准反例在 `scan/fixture/`。** 改动任何扫描器之后，用它验证「真的会报错」。
报不出来就是扫描器坏了，不是代码干净。这条别省：

```bash
SCAN_ROOT=tools/scan/fixture .venv/Scripts/python.exe tools/scan/scan_py.py
```

必须报出这些，多一个少一个都不对：

| 期望 | 说明 |
| --- | --- |
| `dead_code` 含 `DEAD_CONST` / `never_used` / `multi_arity` | 死常量、死函数、多返回长度 |
| `tuple_arity` 含 `multi_arity` 与 `inner` | 同一函数返回 2 元组又返回 4 元组 |
| `dup_definitions` **只含** `repeated_name` | 同文件重复定义要报；`overloaded` 用了 `@overload`，不许报 |
| `swallow` 含 `quiet_swallow` | 真正的静默吞 |
| `swallow_try_next` 含 `keep_trying` | 循环里跳候选，算观察项不算问题 |

`scan_comment.py` 有自己一棵校准树（`scan/fixture-comments/`），
不跟 `fixture/` 混用，免得把 scan_py 那张「多一个少一个都不对」的期望表搅脏：

```bash
SCAN_ROOT=tools/scan/fixture-comments .venv/Scripts/python.exe tools/scan/scan_comment.py
```

必须报出：`py_comments` 2 · `py_docstrings` 1 · `js_comments` 2 · `css_comments` 1 · `html_comments` 1。
必须**不**报：`# noqa: E501`（工具指令算例外）、字符串里的 `https://`、
正则 `/https?:\/\//`、模板字面量里的 `//`。这几条是它的误报面，动剥离逻辑时先跑这一发。

### 类型检查（mypy）

`app/` 与 `main.py` 的类型检查，配置在 `pyproject.toml` 的 `[tool.mypy]`：

```bash
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/python.exe -m mypy app
```

`check_untyped_defs = true` 是开着的 —— 没标注解的函数体也检查，
不然一多半代码会被跳过，看着全绿其实没查。

**它已经在 `check-all.py` 与 `pre-commit.py` 里了**（增量跑约 0.2s，全量首次几秒），
不用再单独记一条命令。没装 mypy 时那一步显示「跳过（未安装 mypy）」而不是静默通过 ——
护栏不该因为谁少装了 dev 依赖就卡死提交，但也不该假装查过了。

### 项目工具

| 脚本 | 用途 |
| --- | --- |
| `sync-dist.py` | 把 `app/` 与 `web/` 同步进 `dist/happycrate/_internal/`。改完源码**不用重新打包**，跑它 + 重启程序即可生效 |
| `check-all.py` | 一键全检，见上 |
| `pre-commit.py` | 提交前检查：快检 + 挡住「改了源码忘了 sync-dist」（这个坑不会让任何测试变红）。`--install` 装进 `.git/hooks`，`--no-tests` 跳过单测 |
| `guard-regression.py` | 反向测试护栏：故意把已修好的缺陷改回去，看护栏是否真的报错。**每加一条新护栏后都要跑**。`--list` 看全部条目，`--case <关键字>` 只跑匹配的（全量实测约 20s） |
| 同上 · 两种失败别搞混 | 跑完会分三栏：**拦住**（护栏生效）· **漏过**（注入了但护栏没红，说明护栏有洞）· **锚点失效**（注入的目标文件改过了，脚本里那串旧文字找不到 —— 这时护栏**根本没被验过**，要去更新脚本的旧串，不是去查测试） |
| `flaky-probe.py` | 把整套单测连跑 N 遍（默认 10），统计每个失败点的复现次数。用来区分「真 flaky」和「当次环境抖动」。命令自带 `-t .`，不会污染真实数据目录 |
| `clean-e2e.py` | 清理 E2E 遗留的无头浏览器进程与 `.scratch/tmp` 下的 profile。只结束命令行含 `.scratch/tmp` 的浏览器进程，不碰用户自己开的 |
| `hc-adult-coverage.py` | 量化某个关键词在各源的召回上限，用来评估「值不值得再扩」。**要联网**，慢 |
| `hc-source-candidates.py` | 批量评估候选磁力源：走 app 自己的 HTTP 通路测连通性 / 可解析性，并按「能不能吐磁力」给判定。**加源之前先跑它**，别拿浏览器打开页面当依据。**要联网**，慢 |
| `hc-recall-audit.py` | 核对「源自报总数」与「实际取回条数」的缺口；`--fresh` 额外打印每个源的结果到达时间，用于确认首屏没变慢。**要联网** |
| `hc-net-probe.py` | 探测代理与连通性：单源探测、`--control` 加海外源对照组、`--wait N` 隔 N 秒重探同一 URL（区分瞬时与持续失败）。**排查网络时用，别自己反复试探** |

后三个是从 `.scratch/tools/` 救回来的（2026-09-24）：原目录改名后它们的路径全部失效，
移进来时把 `parents[2]` 改成了 `parents[1]` 并逐个实跑验证过。
**凡是移动过位置的脚本，都要重算一遍 `parents[N]` 并实跑** —— 这是第 10 轮踩过的坑。

### 关于 `scan/baseline.json`

扫描器当前就会报、且已知不是缺陷的项记在这里。`check-all.py` 只比对
**基线之外的新增项** —— 否则天天飘红，最后会跟没人跑的护栏一样被习惯性忽略。

以前这里压着几条已知非缺陷，现在扫描器自己认得出来了，不用再靠基线兜：

| 曾经的项 | 现在怎么排除 |
| --- | --- |
| `scan_adapter` 几个源不读 `page` | 读源码里的 `_pageless` 标记，和 `PAGELESS_KEYS` 同一个真相源 |
| `scan_py` 的 `run` / `get` | 只在同一个文件内判重，跨文件同名不算重复 |
| `scan_api` 的 `boot` | `scan/api_contract.py` 解析 Python 侧调用点（`app/shell.py` 的 `bridge.boot()`），调用点没了它就会被报出来 |
| 一多半 `swallow` | 循环内跳候选、或失败后还有后续处理的，归到 `swallow_try_next`，可查不计数 |

`swallow_try_next` 是观察项：能查，但不让退出码非 0。
扫一遍看它：`tools/scan/scan_py.py` 输出里就有。文件里带 `_读我` 字段说明。

## 没有现成轮子时：先判放哪，再动手

|  | 判据 | 去处 |
| --- | --- | --- |
| **资产** | 下轮还会用 | 进 `tools/`，**并在本文件登记**（决策表 + 清单各加一行） |
| **草稿** | 一次性：复现某个 bug、截图、数值探测、专项审计 | 扔 `.scratch/tools/`，用完清掉 |

登记不是走过场：**没写进本文件的工具等于不存在**，下一轮一定会重写一遍。

**检查类脚本（名字带 check / scan / audit）必须无副作用**——跑完 `git status` 要跟跑之前一样。
曾经有个版本在「检查 dist 同步」时真的调了 `sync-dist.py`，等于跑一次全检顺手把 dist 改了。

## 和 `.scratch/tools/` 的分工

|  | `tools/`（这里） | `.scratch/tools/` |
| --- | --- | --- |
| 进版本库 | 是 | 否 |
| 性质 | 团队资产 | 本地草稿 |
| 判断标准 | 下轮还会用 | 一次性调试、复现、截图 |
| 生命周期 | 长期维护 | 用完即弃，可随时删 |

## 环境

- Bash 的 `ls` / `wc` / `which` 直接可用，**不需要**改 `PATH`。别引入任何指向用户目录的路径。
- `.venv` **没有 pytest**，只能用 `unittest discover`。
- `discover` **必须带 `-t .`**：`python -m unittest discover -t . -s tests -p "test_*.py"`。
  不带 `-t` 时 top-level 目录会被当成 `tests/`，模块以裸名导入，`tests/__init__.py`
  **不会执行**，数据目录隔离就失效了（测试会写用户的真配置，而 `data/*` 被
  gitignore，git status 看不出来）。所有入口（check-all / pre-commit / CI / README）都已带 `-t`。
- 命令行文本里**不能出现 "PowerShell" 字样**（heredoc 内容也算），会被安全策略拦截。
- **查「是谁改了数据目录」**：`check-all.py` 只会说「`data/*.json` 被改动」，不说是谁。
  临时给 `app.config.atomic_write_json` 套一层，把 `traceback.format_stack()[-6:-1]` 打出来，
  再跑一次单测，输出里就是具体测试文件与行号（`tests/test_source_relevance.py` 当年就是这么抓出来的）。
- `.mypy_cache/` 不用管：mypy 自己会在里面写一个内容为 `*` 的 `.gitignore`，整块对 git 隐形；
  删了也零代价（16 个文件重跑 0.25s）。同理 `__pycache__/`、`.pytest_cache/`、`.ruff_cache/` 都可随时删。
- 打包必须用项目 `.venv`；全局 python 3.14 打出来是空壳。
- frozen 应用的日志在 **exe 旁边**的 `data/logs/`，不是项目根目录那份。

## 省上下文的三条

1. **别通读巨型文件**：`app/sources.py` 2,138 行、`web/js/views/search.js` 1,710 行。先 Grep 拿行号，再按 150~300 行读。
2. **别自己写统计脚本**：规模和体检结果 `check-all.py` 一次给全。
3. **规模数字别抄**：要数字就现算。写下来的计数一定会漂移（AGENTS.md 曾写 587 项，实测 599）。
