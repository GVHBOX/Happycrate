# happycrate

磁力搜索聚合与下载投递工具。v1.0.0，Windows 便携应用。

聚合公开索引站的搜索结果，去重合并后交给下载工具。纯本地运行，不登录、不保存任何站点的账号信息。

## 它做什么

- **源**　内置 8 个公开索引站，可加自定义源（RSS / JSON / HTML）
- **查询**　一个关键词并发搜所有启用的源
- **结果**　去重、排序、筛选
- **投递**　复制磁力链接，或交给迅雷

## 界面是 Web 技术写的，但它不是网页

双击 `happycrate.exe` 启动，出来的是原生窗口——没有地址栏、没有标签页、不需要你先开浏览器。
窗口内部用 Windows 自带的 WebView2 渲染 HTML/CSS/JS，这一层在日常使用中看不见。

## 目录

```
app/     Python 后端。api.py 是给界面的唯一门面
web/     界面。HTML / CSS / JS
data/    运行时配置与日志
```

`web/index.html` 可以直接用浏览器打开：检测不到后端时自动切换到示例数据，
所有交互与动效都能正常玩。这份文件就是产品的真实界面，不是单独的原型稿。

## 数据源会坏，程序会告诉你

源失效分两种：连不上（换镜像地址即可），以及连上了但抠不出东西（站点改版，需要改解析代码）。
后者最隐蔽，界面会明确标出「疑似改版」，并提供一键复制的诊断信息。

## 开发

需要 Python 3.11+（3.14 不行）。

```bash
python -m venv .venv
.venv/Scripts/pip install -e .
.venv/Scripts/pip install pyinstaller
python main.py
```

**pywebview 锁在 5.4，不要升。** 6.x 在 Windows 上有桥接缺陷：窗口能开、页面能加载完，
但 `window.pywebview.api` 注不进去，界面会静默退回示例数据。5.4 实测连续启动 5/5 一次通过。
如果哪天要升级，先跑 `python main.py` 看日志里有没有「界面桥接就绪」，拿不到这句就是坏了。

打包：

```bash
pyinstaller happycrate.spec
```

作业规程见 `AGENTS.md`。
