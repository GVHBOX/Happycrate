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

CASES = [
    (
        "未保存回退：告警文字又用回 --warn 本体",
        "web/styles/base.css",
        ".status.dirty{color:var(--warn-strong)}",
        ".status.dirty{color:var(--warn)}",
        "tests/test_front_hygiene.py",
    ),
    (
        "丢弃回退：放弃改动时又不还原实时预览",
        "web/js/views/settings.js",
        "          revertApplied();\n          goSearch();",
        "          goSearch();",
        "tests/test_front_hygiene.py",
    ),
    (
        "复制按钮回退：又拿品牌色当实底上的文字",
        "web/styles/base.css",
        ".prow .cp{border:0; background:transparent; color:var(--t1);",
        ".prow .cp{border:0; background:transparent; color:var(--brand);",
        "tests/test_front_hygiene.py",
    ),
    (
        "选中态回退：brand-soft 底上又用品牌色当文字",
        "web/styles/base.css",
        ".chipbtn.on{background:var(--brand-soft); color:var(--t1)}",
        ".chipbtn.on{background:var(--brand-soft); color:var(--brand)}",
        "tests/test_front_hygiene.py",
    ),
    (
        "分段回退：选中项又拿品牌色当文字",
        "web/styles/base.css",
        "  background:var(--surface-solid); color:var(--t1);\n  font-weight:600; box-shadow:var(--sh-seg);",
        "  background:var(--surface-solid); color:var(--brand);\n  font-weight:600; box-shadow:var(--sh-seg);",
        "tests/test_front_hygiene.py",
    ),
    (
        "开关语义回退：setSw 又写 aria-pressed",
        "web/js/views/settings.js",
        'el.setAttribute("aria-checked", String(on));',
        'el.setAttribute("aria-pressed", String(on));',
        "tests/test_front_hygiene.py",
    ),
    (
        "选中态回退：侧栏选中又拿品牌色当 brand-soft 上的文字",
        "web/styles/base.css",
        ".snav-i.on{background:var(--brand-soft); color:var(--t1); font-weight:600}",
        ".snav-i.on{background:var(--brand-soft); color:var(--brand); font-weight:600}",
        "tests/test_front_hygiene.py",
    ),
    (
        "字段名回退：后端标签又和界面不同名",
        "app/config.py",
        '"timeout": "投递/清单超时",',
        '"timeout": "超时",',
        "tests/test_front_hygiene.py",
    ),
    (
        "滑块方向回退：off 修饰符又被拿去表示开态",
        "web/styles/base.css",
        ".sw:not(.off)::after{transform:translateX(var(--sw-move))}",
        ".sw.off::after{transform:translateX(var(--sw-move))}",
        "tests/test_front_hygiene.py",
    ),
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
        "JavBus 回退：又把徽章文字混进标题",
        "app/sources.py",
        '            title=_javbus_text(cells[0]) if cells else "",',
        '            title=_cell_text(cells[0]) if cells else "",',
        "tests/test_adult_sources.py",
    ),
    (
        "JavDB 回退：又只认 meta 里的可读体积、不看 data-size",
        "app/sources.py",
        "            mb = _JAVDB_SIZE_ATTR_RE.search(block)\n"
        "            size = (int(mb.group(1)) * 1024 * 1024) if mb else 0",
        "            size = 0",
        "tests/test_adult_sources.py",
    ),
    (
        "成人源回退：又挪出 _OVERSEAS_KEYS（超时提示会误导）",
        "app/sources.py",
        '    "javbus", "javdb",\n})',
        "})",
        "tests/test_adult_sources.py",
    ),
    (
        "搜索页回退：JavBus 分页参数又丢了（第 2 页起返回同一批）",
        "app/sources.py",
        '    url = f"{root}/search/{q}" if p <= 1 else f"{root}/search/{q}/{p}"',
        '    url = f"{root}/search/{q}"',
        "tests/test_adult_sources.py",
    ),
    (
        "搜索页回退：JavDB 页码参数又丢了",
        "app/sources.py",
        '        "f": "all", "q": q, "locale": "zh", "page": max(1, p)})',
        '        "f": "all", "q": q, "locale": "zh"})',
        "tests/test_adult_sources.py",
    ),
    (
        "空结果回退：JavBus 又把「沒有您要的結果」当失败",
        "app/sources.py",
        "    body = _http_error_body(exc).decode(\"utf-8\", \"replace\")\n"
        "    return any(sign in body for sign in _JAVBUS_EMPTY_SIGNS)",
        "    return False",
        "tests/test_adult_sources.py",
    ),
    (
        "登入墙回退：JavDB 又把「要登入」当成 0 条",
        "app/sources.py",
        "    if _javdb_login_wall(text):\n"
        "        raise Blocked(JAVDB_LOGIN_TEXT)",
        "    if False:\n"
        "        raise Blocked(JAVDB_LOGIN_TEXT)",
        "tests/test_adult_sources.py",
    ),
    (
        "登入墙回退：全部撞墙时又不报错（静默成空结果）",
        "app/sources.py",
        "    got_magnets = any(items for items in found.values())\n"
        "    if walled and not got_magnets:\n"
        "        raise Blocked(JAVDB_LOGIN_TEXT)",
        "    if False:\n"
        "        raise Blocked(JAVDB_LOGIN_TEXT)",
        "tests/test_adult_sources.py",
    ),
    (
        "登入墙回退：被当成验证码拦截（文案误导）",
        "app/api.py",
        "    if sources.JAVDB_LOGIN_TEXT in (err or \"\"):\n"
        "        return OUTCOME_LOGIN, 0",
        "    if False:\n"
        "        return OUTCOME_LOGIN, 0",
        "tests/test_adult_sources.py",
    ),
    (
        "多词回退：小草又对多词直接返回空",
        "app/sources.py",
        "    items = _xccl263_words(root, query, page, timeout, batch)\n"
        "    if items or len(words) < 2:\n"
        "        return items",
        "    items = _xccl263_words(root, query, page, timeout, batch)\n"
        "    if True:\n"
        "        return items",
        "tests/test_adult_sources.py",
    ),
    (
        "多词回退：JavBus 多词 403 又整个抛出去",
        "app/sources.py",
        "        if len(words) < 2 or exc.code not in (403, 404):\n"
        "            raise",
        "        if True:\n"
        "            raise",
        "tests/test_adult_sources.py",
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
        "| `assets/` | 图标与截图 |\n",
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
        '     "enabled": False, "timeout": 15, "base": "", "order": 10},\n',
        "",
        "tests/test_bitsearch_kept.py",
    ),
    (
        "出厂源开关回退：BitSearch 又默认启用",
        "app/config.py",
        '     "enabled": False, "timeout": 15, "base": "", "order": 10},\n'
        '    {"key": "javdb", "label": "JavDB", "type": "builtin",\n'
        '     "enabled": False, "timeout": 20, "base": "", "order": 11},',
        '     "enabled": True, "timeout": 15, "base": "", "order": 10},\n'
        '    {"key": "javdb", "label": "JavDB", "type": "builtin",\n'
        '     "enabled": False, "timeout": 20, "base": "", "order": 11},',
        "tests/test_factory_defaults.py",
    ),
    (
        "出厂源开关回退：JavDB 又默认启用",
        "app/config.py",
        '     "enabled": False, "timeout": 20, "base": "", "order": 11},\n]',
        '     "enabled": True, "timeout": 20, "base": "", "order": 11},\n]',
        "tests/test_factory_defaults.py",
    ),
    (
        "出厂主题色回退：brand 又变回空串",
        "app/config.py",
        '    "brand": "lilac",',
        '    "brand": "",',
        "tests/test_factory_defaults.py",
    ),
    (
        "出厂提示音回退：失败音又默认打开",
        "app/config.py",
        '    "sound_fail": False,',
        '    "sound_fail": True,',
        "tests/test_factory_defaults.py",
    ),
    (
        "mock 默认值回退：前端开关状态与后端脱钩",
        "web/js/api.js",
        '    {key:"bitsearch", label:"BitSearch", enabled:false,',
        '    {key:"bitsearch", label:"BitSearch", enabled:true,',
        "tests/test_factory_defaults.py",
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
        '          lit: ".pseg.on, .pseg.err",',
        '          lit: ".pseg.on",',
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
        "      defer(rest, u.count * u.step + u.tail);",
        "      defer(rest, 260);",
        "tests/test_front_hygiene.py",
    ),
    (
        "预览收尾回退：真实条又写死字面量",
        "web/js/views/search.js",
        "      var tail = PROG_TAIL_MS;",
        "      var tail = 560;",
        "tests/test_front_hygiene.py",
    ),
    (
        "预览回退：播放按钮又从 #lookCtl 里找",
        "web/js/views/settings.js",
        'var play = root.querySelector("#btnLookPlay");',
        'var play = box.querySelector("#btnLookPlay");',
        "tests/test_front_hygiene.py",
    ),
    (
        "预览回退：斜纹类名又写成 flow",
        "web/js/views/settings.js",
        'bar.classList.toggle("style-flow", progStyleKey === "flow");',
        'bar.classList.toggle("flow", progStyleKey === "flow");',
        "tests/test_front_hygiene.py",
    ),
    (
        "预览回退：斜纹模式又不驱动填充宽度",
        "web/js/views/settings.js",
        '        bar.style.setProperty("--p", '
        'String(Math.min(1, el / lookTimes[8])));\n',
        "",
        "tests/test_front_hygiene.py",
    ),
    (
        "预览回退：警戒线又无条件显示",
        "web/js/views/settings.js",
        'dl.classList.toggle("show", progLineOn);',
        'dl.classList.add("show");',
        "tests/test_front_hygiene.py",
    ),
    (
        "预设回退：进页面又硬清高亮",
        "web/js/views/settings.js",
        "    syncLookPreset();\n    lookApply();\n  }",
        '    lookPreset = "";\n    lookApply();\n  }',
        "tests/test_front_hygiene.py",
    ),
    (
        "重置回退：又不回填全局快照",
        "web/js/views/settings.js",
        "          HC.settings = Object.assign({}, res[0] || {});\n"
        "          fill(res[0] || {}, res[1] || []);",
        "          fill(res[0] || {}, res[1] || []);",
        "tests/test_front_hygiene.py",
    ),
    (
        "返回按钮回退：设置页又没有可见的返回入口",
        "web/js/views/settings.js",
        'id="btnSettingsBack" title="返回搜索"',
        'id="btnSettingsBackGone" title=" gone"',
        "tests/test_front_hygiene.py",
    ),
    (
        "样式回退：又留没人用的类名",
        "web/styles/base.css",
        ".status.dirty{color:var(--warn-strong)}",
        ".status.dirty{color:var(--warn-strong)}\n.field.inline{display:flex}",
        "tests/test_front_hygiene.py",
    ),
    (
        "滑杆回退：又交回浏览器原生（系统深色会变黑轨）",
        "web/styles/base.css",
        ".rng{-webkit-appearance:none; appearance:none;",
        ".rng{",
        "tests/test_front_hygiene.py",
    ),
    (
        "滑杆回退：轨道色又写死",
        "web/styles/base.css",
        ".rng::-webkit-slider-runnable-track{height:calc(4px*var(--frs)); "
        "border-radius:999px; background:var(--track-off)}",
        ".rng::-webkit-slider-runnable-track{height:calc(4px*var(--frs)); "
        "border-radius:999px; background:#D3D7E0}",
        "tests/test_front_hygiene.py",
    ),
    (
        "外观行回退：又排成三段竖排",
        "web/js/views/settings.js",
        'return \'<div class="prow" data-lookn="\' + n.key + \'">\' +',
        'return \'<div class="lookn" data-lookn="\' + n.key + \'">\' +',
        "tests/test_front_hygiene.py",
    ),
    (
        "外观小节回退：标题又另起一套",
        "web/js/views/settings.js",
        'return sectHtml("配色") +',
        'return \'<div class="looksub">配色</div>\' +',
        "tests/test_front_hygiene.py",
    ),
    (
        "滑杆回退：又有滑杆漏了 .rng",
        "web/js/views/settings.js",
        '\'<div class="rngpair"><input type="range" class="rng" '
        'id="sldVolume" min="0" max="100" step="1">\' +',
        '\'<div class="rngpair"><input type="range" '
        'id="sldVolume" min="0" max="100" step="1">\' +',
        "tests/test_front_hygiene.py",
    ),
    (
        "命中判定回退：后端又只拿 subject 判未使用关键词",
        "app/api.py",
        "            fuzzy = bool(items) and bool(needs) and \\\n"
        "                sources.keyword_hit_rate(items, needs) < sources.FUZZY_RATE\n",
        "            fuzzy = bool(items) and subject and \\\n"
        "                sources.keyword_hit_rate(items, subject) < sources.FUZZY_RATE\n",
        "tests/test_regressions.py",
    ),
    (
        "needles 回退：又不收 soft 的同义词形式",
        "app/query.py",
        '    for item in parsed.get("soft") or []:\n'
        '        if isinstance(item, dict):\n'
        '            groups.append(item.get("forms") or [])\n',
        "",
        "tests/test_query.py",
    ),
    (
        "排序回退：相关度排序又不给零命中行分层",
        "web/js/views/search.js",
        "      scored.sort(function(a, b){\n"
        "        return a.m !== b.m ? a.m - b.m : b.r - a.r;\n"
        "      });\n",
        "      scored.sort(function(a, b){ return b.r - a.r; });\n",
        "tests/test_front_smoke.py",
    ),
    (
        "排序回退：数值排序又不给零命中行分层",
        "web/js/views/search.js",
        "    rows.sort(function(a, b){\n"
        "      if (a.m !== b.m) return a.m - b.m;\n",
        "    rows.sort(function(a, b){\n"
        "      if (false) return a.m - b.m;\n",
        "tests/test_front_smoke.py",
    ),
]


def backup(paths):
    """按字节备份。

    不能用 read_text/write_text：文本模式读会把 \\r\\n 规范化成 \\n，
    写回时又按 os.linesep 换成 \\r\\n —— 结果就是每跑一次，
    被注入过的文件行尾都被悄悄改一遍，git status 常年挂着一堆假 modified，
    dist 同步检查也会误报「与源码不一致」。
    """
    return {rel: (ROOT / rel).read_bytes() for rel in paths}


def restore(saved):
    for rel, raw in saved.items():
        (ROOT / rel).write_bytes(raw)


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
    caught, missed, stale = 0, [], []

    try:
        for name, rel, old, new, test_file in selected:
            path = ROOT / rel
            text = path.read_text(encoding="utf-8")
            if old not in text:
                print(f"[锚点失效] {name}\n        {rel} 里找不到要改的那段，脚本该更新旧串了")
                stale.append(name)
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
    print(f"共 {len(selected)} 项 · 拦住 {caught} · 漏过 {len(missed)}"
          f" · 锚点失效 {len(stale)}")
    for m in missed:
        print("  漏过（护栏有洞，去查测试）:", m)
    for s in stale:
        print("  锚点失效（护栏没验过，去查脚本的旧串）:", s)
    return 0 if not missed and not stale else 1


if __name__ == "__main__":
    sys.exit(main())
