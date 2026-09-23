# tools/ · 现成的轮子

> **新会话先读这份。写任何新脚本之前也先读这份——已有的一律复用，别重写。**
> 命令一律从项目根目录执行，需要 Python 的一律用项目 `.venv`。

## 新会话起手（按顺序，别跳）

```bash
git -C "D:/AI/happycrate" status --short        # 1. 工作区干净吗
git log --oneline -12                            # 2. 上次做到哪
.venv/Scripts/python.exe tools/check-all.py      # 3. 现状是不是绿的（约 19s）
```

第 3 步一次给出：单测项数、6 个扫描器各自的结果与耗时、dist 是否同步。
**不要自己拼命令去统计规模或跑测试**——那条命令已经算好了。

然后按下面的决策表找轮子；找不到再考虑写新的。

## 我要做 X → 用哪个轮子

| 我要… | 用 | 命令 |
| --- | --- | --- |
| 改完代码，想知道有没有弄坏 | `check-all.py` | `.venv/Scripts/python.exe tools/check-all.py` |
| 提交前把关 | `pre-commit.py` | 同上；`--install` 可挂进 `.git/hooks` |
| 改了 `app/` 或 `web/`，让 dist 生效 | `sync-dist.py` | `.venv/Scripts/python.exe tools/sync-dist.py`（**不用重新打包**） |
| 找某个函数 / 常量 / 类名在哪 | `scan/refs.py` | `... tools/scan/refs.py format_size` |
| 查死代码、多返回元组、版本漂移 | `scan/scan_py.py` | 单跑；`check-all.py` 里已含 |
| 查 CSS 变量孤儿、重复选择器、硬编码白底 | `scan/scan_css.py` | 同上 |
| 查后端方法有没有前端调用（双向） | `scan/scan_api.py` | 同上 |
| 查超长函数、重复代码块 | `scan/scan_bloat.py` | 同上 |
| 查「结构相同但名字不同」的复制漂移 | `scan/scan_dupfunc.py` | 同上 |
| 查源适配器参数是不是真被读 | `scan/scan_adapter.py` | 同上 |
| 加了一条新护栏，想证明它真能拦住东西 | `guard-regression.py` | `--list` 看清单，`--case <关键字>` 只跑相关的 |
| 端到端跑一遍真实界面 | `tests/e2e/hc-e2e-test.mjs` | `node tests/e2e/hc-e2e-test.mjs`（**跑完清 `.scratch/tmp`**） |
| 量化某个关键词能召回多少、值不值得扩 | `hc-adult-coverage.py` | `... tools/hc-adult-coverage.py --query SSIS --pages 10`（联网） |
| 核对「源自报总数」与「实际取回」的缺口 | `hc-recall-audit.py` | `... tools/hc-recall-audit.py 1080p matrix`；`--fresh` 打印各源到达时间 |
| 网络连不上，想知道是哪一层的问题 | `hc-net-probe.py` | `... tools/hc-net-probe.py --source <源>`；`--control` 加对照组，`--wait N` 区分瞬时/持续 |
| 跑完全部检查（含 E2E / 反向注入） | `check-all.py` | `--full` 加 E2E、`--guard` 加反向注入、`--all` 全跑 |
| 清理 E2E 残留的浏览器进程 | `clean-e2e.py` | `.venv/Scripts/python.exe tools/clean-e2e.py` |

## 完整清单

### check-all.py · 一键全检

默认档约 19s：单测 + 6 个扫描器 + dist 同步检查。
**只有「基线之外的新增项」才让退出码非 0**（原因见下）。

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
| `refs.py` | 查一个名字在全项目的出现位置（不传参数则读 scan_py 的输出） |

```bash
.venv/Scripts/python.exe tools/scan/scan_py.py
.venv/Scripts/python.exe tools/scan/refs.py format_size
```

**校准反例在 `scan/fixture/`。** 改动任何扫描器之后，用它验证「真的会报错」——
`scan_py.py` 扫 fixture 必须报出 `DEAD_CONST`、`never_used`、`multi_arity`。
报不出来就是扫描器坏了，不是代码干净。这条别省。

### 项目工具

| 脚本 | 用途 |
| --- | --- |
| `sync-dist.py` | 把 `app/` 与 `web/` 同步进 `dist/happycrate/_internal/`。改完源码**不用重新打包**，跑它 + 重启程序即可生效 |
| `check-all.py` | 一键全检，见上 |
| `pre-commit.py` | 提交前检查：快检 + 挡住「改了源码忘了 sync-dist」（这个坑不会让任何测试变红）。`--install` 装进 `.git/hooks`，`--no-tests` 跳过单测 |
| `guard-regression.py` | 反向测试护栏：故意把已修好的缺陷改回去，看护栏是否真的报错。**每加一条新护栏后都要跑**。`--list` 看全部条目，`--case <关键字>` 只跑匹配的（全量约 5min，过滤后几秒） |
| `clean-e2e.py` | 清理 E2E 遗留的无头浏览器进程与 `.scratch/tmp` 下的 profile。只结束命令行含 `.scratch/tmp` 的浏览器进程，不碰用户自己开的 |
| `hc-adult-coverage.py` | 量化某个关键词在各源的召回上限，用来评估「值不值得再扩」。**要联网**，慢 |
| `hc-recall-audit.py` | 核对「源自报总数」与「实际取回条数」的缺口；`--fresh` 额外打印每个源的结果到达时间，用于确认首屏没变慢。**要联网** |
| `hc-net-probe.py` | 探测代理与连通性：单源探测、`--control` 加海外源对照组、`--wait N` 隔 N 秒重探同一 URL（区分瞬时与持续失败）。**排查网络时用，别自己反复试探** |

后三个是从 `.scratch/tools/` 救回来的（2026-09-24）：原目录改名后它们的路径全部失效，
移进来时把 `parents[2]` 改成了 `parents[1]` 并逐个实跑验证过。
**凡是移动过位置的脚本，都要重算一遍 `parents[N]` 并实跑** —— 这是第 10 轮踩过的坑。

### 关于 `scan/baseline.json`

扫描器当前就会报、且已知不是缺陷的项记在这里。`check-all.py` 只比对
**基线之外的新增项** —— 否则天天飘红，最后会跟没人跑的护栏一样被习惯性忽略。

基线里混进了两条**已知非缺陷**（`scan_adapter` 里几个源不读 `page` 是
`PAGELESS_KEYS` 显式契约；`scan_py` 的 `run` / `get` 是通用词假活）。
治本的做法是让扫描器自己排除它们，压在基线里只是权宜。文件里带 `_读我` 字段说明。

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
- 命令行文本里**不能出现 "PowerShell" 字样**（heredoc 内容也算），会被安全策略拦截。
- 打包必须用项目 `.venv`；全局 python 3.14 打出来是空壳。
- frozen 应用的日志在 **exe 旁边**的 `data/logs/`，不是项目根目录那份。

## 省上下文的三条

1. **别通读巨型文件**：`app/sources.py` 2,138 行、`web/js/views/search.js` 1,710 行。先 Grep 拿行号，再按 150~300 行读。
2. **别自己写统计脚本**：规模和体检结果 `check-all.py` 一次给全。
3. **规模数字别抄**：要数字就现算。写下来的计数一定会漂移（AGENTS.md 曾写 587 项，实测 599）。
