"""反向测试：故意把已修好的缺陷改回去，看护栏是否报错。

护栏「全绿」只证明当前代码不违规；只有把它改坏后确实报错，
才证明它真的在防回归。

用法：
  .venv/Scripts/python.exe tools/guard-regression.py                # 全跑 38 条（约 5min）
  .venv/Scripts/python.exe tools/guard-regression.py --list         # 列出全部 case
  .venv/Scripts/python.exe tools/guard-regression.py --case 外观参数   # 只跑名字含它的

日常只加了某一条护栏时，用 --case 过滤到十几秒，别为了一次改动等满 5 分钟。
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")

IMPORT_CLEAR = (
    "            self._cfg.save()\n"
    "            sources.reload_from_config(self._cfg)\n"
    "            self._cache_clear()\n"
    '            return {"ok": True, "added": added, "updated": updated,'
    ' "message": msg}'
)
IMPORT_NO_CLEAR = IMPORT_CLEAR.replace(
    "            self._cache_clear()\n", "")

CASES = [
    (
        "高亮回退：hlTitle 又在转义串上匹配",
        "web/js/views/search.js",
        '    var out = "", last = 0, m;',
        '    return esc(text).replace(st.hlRe, '
        '\'<mark class="hl">$&</mark>\');\n'
        '    var out = "", last = 0, m;',
        "tests/test_front_smoke.py",
    ),
    (
        "来源列回退：适配器又写中文标签",
        "app/sources.py",
        '            source="knaben",',
        '            source="Knaben",',
        "tests/test_xccl263.py",
    ),
    (
        "警戒线回退：buildProg 又读 HC.settings",
        "web/js/views/search.js",
        "    if (st.progLineOn && st.deadline > 0){",
        "    if (HC.settings && HC.settings.progress_line !== false){",
        "tests/test_front_hygiene.py",
    ),
    (
        "护栏回退：诊断原文又直接摊出来",
        "web/js/views/sources.js",
        "'<details class=\"logbox\"><summary>'",
        "'<div class=\"logbox\">'",
        "tests/test_front_hygiene.py",
    ),
    (
        "测试收集回退：unittest.main 之后又插测试类",
        "tests/test_adapter_contract.py",
        'if __name__ == "__main__":\n    unittest.main()',
        'if __name__ == "__main__":\n    unittest.main()\n\n\n'
        'class InsertedAfterMain(unittest.TestCase):\n'
        '    def test_x(self):\n        self.assertTrue(True)',
        "tests/test_front_hygiene.py",
    ),
    (
        "文案回退：又写引导语",
        "app/sources.py",
        'NET_FAIL_TEXT = "网络请求失败"',
        'NET_FAIL_TEXT = "网络请求失败，请检查网络连接。"',
        "tests/test_front_hygiene.py",
    ),
    (
        "mock 回退：又漏 progress_line",
        "web/js/api.js",
        "progress_line: true",
        "",
        "tests/test_front_hygiene.py",
    ),
    (
        "凭据回退：源列表又不脱敏",
        "app/api.py",
        "    return str(value) if raw else _redact(value)",
        "    return str(value)",
        "tests/test_contract.py",
    ),
    (
        "线程收尾回退：start_search 的测试又不等 worker",
        "tests/test_contract.py",
        "            self.await_search_threads(before)",
        "            pass",
        "tests/test_front_hygiene.py",
    ),
    (
        "缓存恢复回退：又硬写 state=ok",
        "app/api.py",
        '                state = "ok" if count else "empty"',
        '                state = "ok"',
        "tests/test_front_hygiene.py",
    ),
    (
        "缓存失效回退：导入源后不清缓存",
        "app/api.py",
        IMPORT_CLEAR,
        IMPORT_NO_CLEAR,
        "tests/test_contract.py",
    ),
    (
        "日志脱敏回退：log_url 又原样返回带查询串的 URL",
        "app/sources.py",
        '    return urllib.parse.urlunsplit(\n        (parts.scheme, parts.netloc, parts.path, "…", parts.fragment))',
        '    return str(url or "")',
        "tests/test_contract.py",
    ),
    (
        "探测副作用回退：is_writable 又留下目录",
        "app/paths.py",
        '    missing = _created_by_us(target)',
        '    missing = []',
        "tests/test_contract.py",
    ),
    (
        "README 回退：目录表又漏目录",
        "README.md",
        "| `assets/` | 图标与 README 截图                               |\n",
        "",
        "tests/test_front_hygiene.py",
    ),
    (
        "README 回退：源清单又漏源",
        "README.md",
        "、Knaben",
        "",
        "tests/test_front_hygiene.py",
    ),
    (
        "README 回退：又把已下线的源写回去",
        "README.md",
        "、Knaben",
        "、Knaben、BTDigg",
        "tests/test_front_hygiene.py",
    ),
    (
        "BitSearch 回退：又在内置清单里被删掉",
        "app/config.py",
        '    {"key": "bitsearch", "label": "BitSearch", "type": "builtin",\n'
        '     "enabled": True, "timeout": 15, "base": "", "order": 6},\n',
        "",
        "tests/test_bitsearch_kept.py",
    ),
    (
        "死代码回退：return 之后又挂一句",
        "app/sources.py",
        "    return _search_mikan_rss(query, timeout, root, batch)\n"
        "\n"
        "def _search_mikan_rss",
        "    return _search_mikan_rss(query, timeout, root, batch)\n"
        "    return _search_mikan_rss(query, timeout, root, batch)\n"
        "\n"
        "def _search_mikan_rss",
        "tests/test_contract.py",
    ),
    (
        "静默降级回退：mikan 请求失败又只写 debug",
        "app/sources.py",
        'logger.warning("mikan 搜索页请求失败',
        'logger.debug("mikan 搜索页请求失败',
        "tests/test_new_sources.py",
    ),
    (
        "投递限流回退：批量上限抬到预算撑不住的量",
        "app/api.py",
        "MAGNET_CAP = 200",
        "MAGNET_CAP = 5000",
        "tests/test_delivery.py",
    ),
    (
        "投递限流回退：批量上限直接去掉",
        "app/api.py",
        "        if len(items) > MAGNET_CAP:\n"
        "            return {\"ok\": False,\n"
        "                    \"message\": f\"一次最多提交 {MAGNET_CAP} 条，本次 {len(items)} 条\"}\n",
        "",
        "tests/test_delivery.py",
    ),
    (
        "双击语义回退：已选中时不再重置选区",
        "web/js/views/search.js",
        '      var row = e.target.closest(".srow");\n'
        '      if (!row) return;\n'
        '      st.sel = {};\n'
        '      st.sel[row.dataset.hash] = true;\n'
        '      st.anchor = row.dataset.hash;\n'
        '      updateSelUI();\n'
        '      doCopy();',
        '      var row = e.target.closest(".srow");\n'
        '      if (!row) return;\n'
        '      if (!st.sel[row.dataset.hash]){\n'
        '        st.sel = {};\n'
        '        st.sel[row.dataset.hash] = true;\n'
        '        st.anchor = row.dataset.hash;\n'
        '        updateSelUI();\n'
        '      }\n'
        '      doCopy();',
        "tests/test_delivery.py",
    ),
    (
        "复制出口回退：发送下载绕过上限",
        "web/js/views/search.js",
        "    if (overCap(magnets.length)) return;\n"
        "    HC.api.deliver(magnets).then(function(r){",
        "    HC.api.deliver(magnets).then(function(r){",
        "tests/test_delivery.py",
    ),
    (
        "开始事件回退：提交任务时就发（排队被当成在跑）",
        "app/sources.py",
        "            jobs[pool.submit(_search_starting, s, query, page, timeout, batch,\n"
        "                             on_start)] = s.key",
        "            jobs[pool.submit(_search_starting, s, query, page, timeout, batch,\n"
        "                             None)] = s.key",
        "tests/test_front_hygiene.py",
    ),
    (
        "排队判定回退：只看 pending 不看 startedAt",
        "web/js/views/search.js",
        '      var busy = ss.state === "pending" && !!ss.startedAt;',
        '      var busy = ss.state === "pending";',
        "tests/test_front_hygiene.py",
    ),
    (
        "呼吸动画回退：排队态又开始呼吸",
        "web/styles/base.css",
        ".stile.pending .sdot{background:var(--ink-13)}",
        ".stile.pending .sdot{background:var(--ink-13); animation:breathe 1.4s var(--e) infinite}",
        "tests/test_front_hygiene.py",
    ),
    (
        "基线口径回退：中位数换成均值",
        "app/api.py",
        "        return times[len(times) // 2]",
        "        return sum(times) // len(times)",
        "tests/test_front_hygiene.py",
    ),
    (
        "mock 回退：又不推开始事件",
        "web/js/api.js",
        "          if (sHooks.start){\n"
        "            sHooks.start({token:token, key:key, typical_ms:typical});\n"
        "          }",
        "",
        "tests/test_front_hygiene.py",
    ),
    (
        "红块判定回退：又拿 err 非空当失败",
        "web/js/views/search.js",
        '        var segRed = d.state === "err" || (!d.state && d.err && d.outcome !== "empty");',
        '        var segRed = !!d.err;',
        "tests/test_front_hygiene.py",
    ),
    (
        "退场回退：又把红块排除在熄灭之外",
        "web/js/views/search.js",
        '        lit = [].slice.call(progEl.querySelectorAll(".seg.on, .seg.err")).reverse();',
        '        lit = [].slice.call(progEl.querySelectorAll(".seg.on")).reverse();',
        "tests/test_front_hygiene.py",
    ),
    (
        "mock 载荷回退：空结果又不带真实形状",
        "web/js/api.js",
        '                           err: err || (outcome === "empty" ? "无结果" : ""),\n'
        '                           outcome: outcome,',
        '                           err: err,',
        "tests/test_front_hygiene.py",
    ),
    (
        "CDATA 回退：hash 字段又不剥壳",
        "app/sources.py",
        "    h = _unescape(_text(info_hash)).strip().lower()",
        "    h = _text(info_hash).strip().lower()",
        "tests/test_regressions.py",
    ),
    (
        "暗色错误色回退：--err 又只留浅色一份",
        "web/styles/tokens.css",
        "  --err:#F87171;\n  --err-rgb:248,113,113;",
        "  --err-rgb:248,113,113;",
        "tests/test_front_hygiene.py",
    ),
    (
        "文字色回退：选中栏数字又拿描边色当文字",
        "web/styles/base.css",
        "body.dark .selbar .st b{color:var(--brand-active)}",
        "body.dark .selbar .st b{color:var(--brand-line)}",
        "tests/test_front_hygiene.py",
    ),
    (
        "外观参数回退：新参数又不落 CSS 变量",
        "web/index.html",
        'glow:["--prog-glow","px"], pulse:["--prog-pulse","ms"],',
        'pulse:["--prog-pulse","ms"],',
        "tests/test_front_hygiene.py",
    ),
    (
        "外观参数回退：越界值不再夹取",
        "web/index.html",
        "    return Math.max(r[0], Math.min(r[1], v));",
        "    return v;",
        "tests/test_front_smoke.py",
    ),
    (
        "预览收尾回退：又自己写死时长",
        "web/js/views/settings.js",
        "}, lit.length * step + (HC.PROG_TAIL_MS || 560)));",
        "}, lit.length * step + 260));",
        "tests/test_front_hygiene.py",
    ),
    (
        "预览收尾回退：真实条又写死字面量",
        "web/js/views/search.js",
        "      }, lit.length * 45 + PROG_TAIL_MS);",
        "      }, lit.length * 45 + 560);",
        "tests/test_front_hygiene.py",
    ),
]


def backup(paths):
    return {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in paths}


def restore(saved):
    for rel, text in saved.items():
        (ROOT / rel).write_text(text, encoding="utf-8")


def run(test_file):
    cmd = [PY, "-X", "utf8", "-m", "unittest"]
    if test_file:
        cmd.append(test_file.replace("/", ".").replace(".py", ""))
    else:
        cmd += ["discover", "-s", "tests", "-p", "test_*.py"]
    cmd.append("-q")
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def select(argv):
    """按 --case 关键字挑出要跑的 case。

    全量 38 条要 5 分钟，日常改一条护栏不该等 5 分钟。
    关键字匹配 case 名字 / 源文件 / 测试文件，任中其一即可。
    """
    if "--list" in argv:
        for i, (name, rel, _old, _new, test_file) in enumerate(CASES, 1):
            print(f"{i:>3}  {name}")
            print(f"      {rel}  ->  {test_file}")
        return None

    keyword = None
    for arg in argv:
        if arg.startswith("--case="):
            keyword = arg.split("=", 1)[1]
        elif arg == "--case" and argv.index(arg) + 1 < len(argv):
            keyword = argv[argv.index(arg) + 1]
    if not keyword:
        return CASES

    picked = [c for c in CASES
              if keyword in c[0] or keyword in c[1] or keyword in c[4]]
    if not picked:
        raise SystemExit(f"没有 case 匹配 {keyword!r}，用 --list 看全部名字")
    print(f"选中 {len(picked)}/{len(CASES)} 条（关键字 {keyword!r}）\n")
    return picked


def main():
    selected = select(sys.argv[1:])
    if selected is None:
        return 0
    saved = backup(sorted({c[1] for c in selected}))
    caught, missed = 0, []

    try:
        for name, rel, old, new, test_file in selected:
            path = ROOT / rel
            text = path.read_text(encoding="utf-8")
            if old not in text:
                print(f"[跳过] {name}\n        锚点找不到，脚本需更新")
                missed.append(name)
                continue
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            code, out = run(test_file)
            path.write_text(text, encoding="utf-8")
            if code != 0:
                caught += 1
                line = [l for l in out.splitlines()
                        if l.startswith("FAIL:") or l.startswith("ERROR:")]
                head = line[0][:74] if line else "非零退出"
                print(f"[拦住] {name}\n        {head}")
            else:
                missed.append(name)
                print(f"[漏过] {name}\n        改坏了但测试仍然全绿")
    finally:
        restore(saved)

    print()
    print(f"共 {len(selected)} 项 · 拦住 {caught} · 漏过 {len(missed)}")
    for m in missed:
        print("  漏过:", m)
    return 0 if not missed else 1


if __name__ == "__main__":
    sys.exit(main())
