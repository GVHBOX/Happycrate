# happycrate

磁力搜索聚合与下载投递工具。Windows 便携应用，纯本地运行，无需登录。

![happycrate 工具截图](assets/readme_preview.jpg)

## 功能

- **源**　内置 8 个公开索引站，支持自定义 RSS / JSON 源；测速标记健康度，连续异常的源自动排到最后
- **查询**　一个关键词并发搜索所有启用的源
- **结果**　跨源去重合并，按体积 / 时间 / 做种排序，批量勾选
- **投递**　右键复制磁力链接或标题，一键发送到迅雷
- **诊断**　区分「连不上」与「解析 0 条」，异常源给出一键复制的诊断信息

## 运行

需要 Python 3.11+（不支持 3.14）。pywebview 锁 5.4，6.x 在 Windows 上有桥接缺陷。

```bash
pip install -e .
python main.py
```

打包：`pyinstaller happycrate.spec`
