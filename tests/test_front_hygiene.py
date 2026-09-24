import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JS = sorted((ROOT / "web" / "js").rglob("*.js"))
CSS = sorted((ROOT / "web" / "styles").rglob("*.css"))
HTML = ROOT / "web" / "index.html"

_BANNED_GUIDANCE = ("点击", "请选择", "您可以", "建议", "试试", "请注意",
                    "使用方法", "该字段", "点击这里")

_BANNED_GUIDANCE_EXTRA = ("请先", "请再", "请把", "请确认", "请检查", "请重新",
                          "填写代理", "打开系统代理", "换一个", "先启用",
                          "重新搜索", "需要换", "换成", "然后在", "即可",
                          "如果反复", "发给我", "粘贴到")

_NOT_USER_FACING = re.compile(
    r"logger\.|log\.|logging\.|#\s|re\.compile|_RE\b|PATTERN"
    r"|def test_|assert|self\.assert|docstring|\.md\b")


def _is_not_user_facing(line: str) -> bool:
    return bool(_NOT_USER_FACING.search(line))


class SharedEscTest(unittest.TestCase):

    def test_only_api_js_defines_esc(self):
        owners = []
        for p in JS:
            text = p.read_text(encoding="utf-8")
            if re.search(r"function\s+esc\s*\(", text):
                owners.append(str(p.relative_to(ROOT)))
        self.assertEqual(owners, ["web\\js\\api.js"] if owners else [],
                         "esc 只能有一份实现，实际分布：" + repr(owners))

    def test_api_exports_esc(self):
        text = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        self.assertRegex(text, r"HC\.esc\s*=\s*esc")

    def test_esc_covers_all_five_characters(self):
        text = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        i = text.find("function esc(")
        self.assertGreater(i, 0)
        body = text[i:i + 400]
        for ch in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
            self.assertIn(ch, body, f"esc 缺少 {ch} 转义")

    def test_consumers_alias_to_hc_esc(self):
        for rel in ("web/js/motion.js", "web/js/diagnostics.js",
                    "web/js/views/search.js", "web/js/views/settings.js"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("var esc = HC.esc;", text,
                          f"{rel} 应引用共享 esc 而非自带实现")


class ScriptOrderTest(unittest.TestCase):

    def html_scripts(self):
        text = HTML.read_text(encoding="utf-8")
        tags = re.findall(r'<script\s+src="([^"]+)"', text)
        return ["web/" + t.replace("./", "") for t in tags]

    def test_api_js_loads_first(self):
        order = self.html_scripts()
        self.assertEqual(order[0], "web/js/api.js",
                         "HC.esc / HC.api 由 api.js 提供，必须最先加载")

    def test_smoke_list_matches_html(self):
        smoke = (ROOT / "tests" / "front_smoke.cjs").read_text(encoding="utf-8")
        block = smoke.split("const FRONTEND = [", 1)[1].split("];", 1)[0]
        listed = re.findall(r'"([^"]+\.js)"', block)
        self.assertEqual(listed, self.html_scripts(),
                         "冒烟脚本的前端列表与 index.html 顺序不一致")


class CssHygieneTest(unittest.TestCase):

    def selectors_with_lines(self, path):
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"),
                      text, flags=re.S)
        out = {}
        depth = 0
        buf = []
        line = 1
        start = 1
        for ch in text:
            if ch == "\n":
                line += 1
                continue
            if ch == "{":
                if depth == 0:
                    sel = " ".join("".join(buf).split())
                    if sel and not sel.startswith("@"):
                        out.setdefault(sel, []).append(start)
                depth += 1
                buf = []
                start = line
                continue
            if ch == "}":
                if depth:
                    depth -= 1
                buf = []
                start = line
                continue
            if depth == 0:
                if not buf:
                    start = line
                buf.append(ch)
        return out

    def animation_names(self):
        text = "\n".join(p.read_text(encoding="utf-8") for p in CSS)
        text += "\n" + "\n".join(p.read_text(encoding="utf-8") for p in JS)
        used = set()
        for ref in re.findall(r"animation(?:-name)?\s*[:=]\s*[\"']?([^;}\"']+)", text):
            for token in re.split(r"[\s,]+", ref.strip()):
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", token):
                    used.add(token)
        return used

    def test_no_orphan_keyframes(self):
        dead = []
        for p in CSS:
            text = p.read_text(encoding="utf-8")
            for m in re.finditer(r"@keyframes\s+([A-Za-z_][A-Za-z0-9_-]*)", text):
                if m.group(1) not in self.animation_names():
                    dead.append(f"{p.name} :: {m.group(1)}")
        self.assertEqual(dead, [], "定义了却没人引用的关键帧：" + repr(dead))

    def test_no_duplicate_top_level_selectors(self):
        dupes = {}
        for p in CSS:
            for sel, lines in self.selectors_with_lines(p).items():
                if len(lines) > 1:
                    dupes[f"{p.name} :: {sel}"] = lines
        self.assertEqual(dupes, {}, f"CSS 存在重复选择器：{dupes}")

    def test_body_declared_once(self):
        base = ROOT / "web" / "styles" / "base.css"
        sels = self.selectors_with_lines(base)
        self.assertEqual(len(sels.get("body", [])), 1,
                         "body 只应有一个顶层规则块")

    def test_state_class_does_not_clash_with_layout_class(self):
        base = ROOT / "web" / "styles" / "base.css"
        sels = self.selectors_with_lines(base)
        for state in ("empty", "ok", "warn", "err", "na"):
            with self.subTest(state=state):
                owners = [s for s in sels if s == f".{state}"]
                self.assertEqual(
                    owners, [],
                    f".{state} 既是状态类又是布局类，会互相污染"
                    f"（健康度圆点曾被 .empty 的 padding 撑成椭圆）；"
                    f"布局样式请收窄作用域，例如 .rows > .{state}",
                )

    def css_blocks(self):
        out = []
        for p in CSS:
            text = p.read_text(encoding="utf-8")
            for m in re.finditer(r"([^{}@][^{}]*)\{([^{}]*)\}", text):
                out.append((p.name, " ".join(m.group(1).split()), m.group(2)))
        return out

    def test_no_hardcoded_white_surface(self):
        allow = {".sw::after"}
        bad = ["%s :: %s" % (f, s) for f, s, body in self.css_blocks()
               if re.search(r"background\s*:\s*#fff\b", body, re.I) and s not in allow]
        self.assertEqual(
            bad, [],
            "写死的白底不会跟着 body.dark 走，而前景也用 var(--t1)，"
            "暗色下文字会直接消失（输入框一聚焦就看不见）。改用 var(--surface-solid)")

    def test_z_index_comes_from_tokens(self):
        bad = ["%s :: %s" % (f, s) for f, s, body in self.css_blocks()
               if re.search(r"z-index\s*:\s*\d", body)]
        self.assertEqual(bad, [], "z-index 必须用 --z-* 令牌，散落的魔数会互相盖住")

    def test_every_css_variable_is_defined(self):
        text = "\n".join(p.read_text(encoding="utf-8") for p in CSS)
        defined = set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", text))
        used = set(re.findall(r"var\(\s*(--[A-Za-z0-9_-]+)", text))
        missing = sorted(used - defined - {"--sbw"})
        self.assertEqual(
            missing, [],
            "用了未定义的变量时整条声明失效，属性会静默回退（--line 就漏过一次）："
            + repr(missing))

    def test_no_orphan_css_variable(self):
        text = "\n".join(p.read_text(encoding="utf-8") for p in CSS)
        markup = HTML.read_text(encoding="utf-8") + "\n".join(
            p.read_text(encoding="utf-8") for p in JS)
        defined = set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", text))
        used = set(re.findall(r"var\(\s*(--[A-Za-z0-9_-]+)", text + markup))
        used |= set(re.findall(r"setProperty\(\s*[\"'](--[A-Za-z0-9_-]+)", markup))
        orphan = sorted(defined - used)
        self.assertEqual(orphan, [], "定义了但没人引用的变量：" + repr(orphan))

    def test_ripple_host_contract_is_complete(self):
        src = (ROOT / "web" / "js" / "motion.js").read_text(encoding="utf-8")
        m = re.search(r'el\.closest\(\s*"([^"]+)"\s*\)', src)
        self.assertIsNotNone(m, "找不到 ripple 宿主选择器串")
        hosts = set()
        for part in m.group(1).split(","):
            for cls in part.split():
                if cls.startswith("."):
                    hosts.add(cls[1:])
        need = {"btn", "op", "iconbtn", "mi", "cb", "gobtn", "chipbtn", "tb-btn",
                "sbtn", "sclose", "fchev", "srcdot"}
        missing = sorted(need - hosts)
        self.assertEqual(
            missing, [],
            "这些可点控件不在 ripple 白名单里，按下没有任何视觉回应："
            + repr(missing) + "（新增控件时记得同步这行与 base.css 的 :active）")

    def test_ripple_hosts_can_clip(self):
        need = {"sbtn", "sclose", "fchev", "srcdot"}
        ok = set()
        for _f, sel, body in self.css_blocks():
            parts = [x for x in re.split(r"[,\s]+", sel) if x.startswith(".")]
            for p in parts:
                if p[1:] in need and "overflow:hidden" in body:
                    ok.add(p[1:])
        missing = sorted(need - ok)
        self.assertEqual(
            missing, [],
            "波纹靠 overflow:hidden 裁切，缺了会溢出控件："
            + repr(missing) + "（.fchev 是 absolute 定位，不要加 position:relative）")

    def test_progress_not_fake(self):
        base = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        m = re.search(r"\.progress\s+\.fill\{([^}]*)\}", base)
        self.assertIsNotNone(m, "找不到 .progress .fill 规则")
        self.assertIn("var(--p", m.group(1),
                      "进度条必须跟真实进度走。一次填满后静止等于告诉用户"
                      "「已完成但仍无结果」，是用动效掩盖状态")
        self.assertRegex(base, r"\.progress\.on\.wait\s+\.fill\{[^}]*animation",
                         "总数未知时应切到不确定进度循环，而不是静止不动")

    def test_progress_fed_by_real_counts(self):
        src = (ROOT / "web" / "js" / "views" / "search.js").read_text(encoding="utf-8")
        self.assertIn('setProperty("--p"', src, "必须有代码把真实进度写进 --p")
        self.assertIn("st.done / st.total", src, "进度应来自已完成源数 / 总源数")
        self.assertIn('classList.add("on", "wait")', src,
                      "startSearch 返回前总数未知，应先进入不确定态")

    def test_issue_modal_has_no_internal_detail(self):
        src = (ROOT / "web" / "js" / "views" / "sources.js").read_text(encoding="utf-8")
        start = src.find("function showBadModal()")
        end = src.find("\n  }", start)
        body = src[start:end]
        self.assertNotIn("adapterLocation", body,
                         "代码路径不该出现在用户界面里")
        self.assertIn("issue", body, "应改用结构化的问题列表")
        detail = body.find("highlightJson")
        self.assertGreater(detail, -1, "诊断原文应只有一处渲染入口")
        wrapper = body[max(0, detail - 260):detail]
        self.assertIn("<details", wrapper,
                      "诊断原文（面向 AI 的排查数据）不能直接摊在用户面前，"
                      "必须收进可折叠块里")
        self.assertRegex(wrapper, r"<details(?![^>]*\sopen\b)",
                         "折叠块不能默认展开，否则等于直接摊出来")
        self.assertIn("logbox", wrapper,
                      "折叠块要带 logbox 类，否则 .logbox:not([open]) 的 "
                      "display:none 规则落不到 .term 上，面板会以 171px 漏出来")

    def test_user_facing_strings_carry_no_advice(self):
        banned = _BANNED_GUIDANCE + _BANNED_GUIDANCE_EXTRA
        targets = [ROOT / "web" / "js" / "views" / "sources.js",
                   ROOT / "web" / "js" / "views" / "search.js",
                   ROOT / "web" / "js" / "views" / "settings.js",
                   ROOT / "web" / "js" / "api.js",
                   ROOT / "web" / "js" / "motion.js",
                   ROOT / "web" / "js" / "diagnostics.js",
                   ROOT / "web" / "index.html",
                   ROOT / "app" / "api.py",
                   ROOT / "app" / "sources.py",
                   ROOT / "app" / "shell.py",
                   ROOT / "app" / "downloaders" / "thunder.py",
                   ROOT / "app" / "downloaders" / "base.py"]
        for p in targets:
            text = p.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                if not re.search(r"[\u4e00-\u9fff]", line):
                    continue
                if _is_not_user_facing(line):
                    continue
                for b in banned:
                    with self.subTest(file=p.name, line=lineno, banned=b):
                        self.assertNotIn(
                            b, line,
                            f"{p.name}:{lineno} 界面只写「是什么」和「出了什么问题」，"
                            f"不写「怎么用」")

    def test_banned_word_list_covers_the_synonyms(self):
        for word in ("请先", "请再", "换一个", "先启用", "重新搜索",
                     "需要换", "换成", "然后在", "即可"):
            with self.subTest(word=word):
                self.assertIn(
                    word, _BANNED_GUIDANCE_EXTRA,
                    "护栏的禁用词表要覆盖这类引导措辞，否则同义改写就绕过了")

    def test_guard_catches_a_real_violation(self):
        sample = "连接失败（需要换地址或查网络）"
        self.assertTrue(
            any(b in sample for b in _BANNED_GUIDANCE_EXTRA),
            "这条样本是 AGENTS.md 点名的违规形态，护栏必须能拦下来"),

    def test_health_dot_has_fixed_size(self):
        base = ROOT / "web" / "styles" / "base.css"
        text = base.read_text(encoding="utf-8")
        m = re.search(r"^\.hd\{([^}]*)\}", text, re.M)
        self.assertIsNotNone(m, "找不到 .hd 规则")
        rule = m.group(1)
        self.assertIn("width:", rule)
        self.assertIn("height:", rule)
        self.assertIn("flex:none", rule, "圆点必须在 flex 容器里禁止伸缩")

    def test_collapsed_logbox_hides_panel(self):
        base = ROOT / "web" / "styles" / "base.css"
        text = base.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"\.logbox:not\(\[open\]\)\s+\.term\s*\{[^}]*display\s*:\s*none",
            "折叠时必须显式 display:none —— 全局 .term 的 padding 会压过 "
            "details 的默认隐藏，面板会以 171px 高度漏出来",
        )


class DuplicateRequestTest(unittest.TestCase):

    def test_mount_asks_for_sources_once(self):
        src = (ROOT / "web" / "js" / "views" / "search.js").read_text(encoding="utf-8")
        self.assertNotIn(
            "onLive(refreshSources)", src,
            "onLive 在已 live 时立即回调，mount 里的直接调用会撞成两次请求")
        self.assertEqual(
            src.count("HC.api.onLive("), 1,
            "mount 只许挂一个 onLive——多一条就是 mock 模式下多一条轮询、"
            "live 后多一次重复请求")
        self.assertIn(
            "loadSourcesOnce();", src,
            "live 回调里仍要走 loadSourcesOnce 去重入口，不能直接调 refreshSources")


class A11yTest(unittest.TestCase):

    def test_toast_is_live_region(self):
        src = (ROOT / "web" / "js" / "motion.js").read_text(encoding="utf-8")
        self.assertIn('setAttribute("role", "status")', src,
                      "toast 必须带 role=status")
        self.assertIn('setAttribute("aria-live", "polite")', src,
                      "toast 必须是 polite live region，否则提示出现时不可感知")

    def test_modal_is_dialog(self):
        src = (ROOT / "web" / "js" / "motion.js").read_text(encoding="utf-8")
        self.assertRegex(src, r'class="modal[\s\S]{0,80}role="dialog" aria-modal="true"',
                         "模态必须声明 dialog 语义")

    def test_modal_manages_focus(self):
        src = (ROOT / "web" / "js" / "motion.js").read_text(encoding="utf-8")
        self.assertIn("function focusables(", src,
                      "必须有可聚焦元素收集器")
        self.assertIn("bd._opener", src,
                      "openModal 必须记录触发者，closeModal 才能归还焦点")
        self.assertIn("(target || modal).focus()", src,
                      "模态打开后初始焦点必须落在模态内")
        self.assertIn('e.key !== "Tab"', src,
                      "Tab 陷阱缺失时键盘焦点会掉到模态背后的页面")

    def test_modal_implementation_is_shared(self):
        for rel in ("web/js/views/sources.js", "web/js/diagnostics.js"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotRegex(text, r'className\s*=\s*"backdrop"',
                                f"{rel} 不得自建模态——两份 close() 会让 Esc 的"
                                "closing 守卫抢先，焦点归还永远轮空")
        diag = (ROOT / "web" / "js" / "diagnostics.js").read_text(encoding="utf-8")
        self.assertIn("HC.motion.openModal(", diag)
        self.assertIn("HC.motion.closeModal()", diag)

    def test_switch_buttons_carry_aria_pressed(self):
        src = (ROOT / "web" / "js" / "views" / "sources.js").read_text(encoding="utf-8")
        start = src.find("function rowHtml(")
        body = src[start:start + 900]
        self.assertRegex(body, r'class="sw [\s\S]{0,120}aria-pressed=',
                         "源启停开关缺状态语义")
        settings = (ROOT / "web" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
        self.assertRegex(settings, r'function setSw\([\s\S]{0,260}aria-pressed',
                         "setSw 必须同步 aria-pressed")
        for sid in ("s_selbar", "s_theme", "s_autofiles"):
            self.assertRegex(settings,
                             r'#' + sid + r'"\)\.onclick[\s\S]{0,220}(setSw\(|aria-pressed)',
                             f"设置页开关 {sid} 的点击处理必须同步 aria-pressed")


class MockSourceListTest(unittest.TestCase):

    def mock_builtins(self):
        text = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        block = text.split("var MOCK = [", 1)[1].split("var db = null;", 1)[0]
        return re.findall(r'key:"([a-z0-9_]+)"', block)

    def real_builtins(self):
        from app import config
        return [s["key"] for s in config.DEFAULT_SOURCES]

    def test_mock_matches_real_builtin_sources(self):
        self.assertEqual(sorted(self.mock_builtins()),
                         sorted(self.real_builtins()),
                         "mock 的内置源清单必须与后端一致，否则浏览器直开看到的"
                         "不是成品（双模机制靠同一份前端）")

    def test_mock_has_no_unknown_keys(self):
        known = set(self.real_builtins())
        extra = [k for k in self.mock_builtins() if k not in known]
        self.assertEqual(extra, [],
                         f"mock 里有后端不存在的内置源：{extra}")

    def test_no_retired_source_in_mock(self):
        from app import config
        for key in config.RETIRED_SOURCES:
            self.assertNotIn(key, self.mock_builtins(),
                             f"{key} 已下线，mock 里不该还留着")

    def test_mock_has_no_custom_source_left(self):
        text = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        block = text.split("var MOCK = [", 1)[1].split("var db = null;", 1)[0]
        for key in ("custom1", "custom2", "custom3"):
            self.assertNotIn(key, block,
                             "自定义源已移除，mock 里不该再有样例")


class MockSettingsTest(unittest.TestCase):

    def mock_keys(self):
        text = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        block = text.split("var mockSettings = {", 1)[1].split("};", 1)[0]
        return set(re.findall(r"(\w+)\s*:", block))

    def test_mock_settings_cover_backend_specs(self):
        from app import config
        missing = sorted(set(config.SETTING_SPECS) - self.mock_keys())
        self.assertEqual(
            missing, [],
            "浏览器直开时 mock 就是后端。这些设置项 mock 里没有，"
            "预览会读到 undefined，与真实模式行为分叉：" + repr(missing))

    def test_mock_settings_have_no_unknown_keys(self):
        from app import config
        extra = sorted(self.mock_keys() - set(config.SETTING_SPECS) - {"version"})
        self.assertEqual(
            extra, [],
            "mock 里有后端不认识的设置项，保存时会被静默丢弃：" + repr(extra))


class ReadmeDirTableTest(unittest.TestCase):

    def test_readme_lists_every_top_level_dir(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        block = readme.split("## 目录", 1)[1].split("## ", 1)[0]
        listed = set(re.findall(r"`([A-Za-z_.-]+)/`", block))
        actual = {p.name for p in ROOT.iterdir()
                  if p.is_dir() and not p.name.startswith(".")
                  and p.name not in {"build", "_internal"}}
        missing = sorted(actual - listed)
        self.assertEqual(
            missing, [],
            "README 目录表漏了这些一级目录，读者按表找会找不到：" + repr(missing))


class ReadmeSourceListTest(unittest.TestCase):

    def readme_sources_line(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for line in readme.splitlines():
            if line.startswith("- **内置源**"):
                return line
        self.fail("README 里找不到内置源那一行")

    def real_labels(self):
        from app import config
        return [s["label"] for s in config.DEFAULT_SOURCES]

    def test_readme_lists_every_builtin_source(self):
        line = self.readme_sources_line()
        missing = [label for label in self.real_labels() if label not in line]
        self.assertEqual(
            missing, [],
            "README 的内置源清单漏了这些源，读者按文档找会对不上：" + repr(missing))

    def test_readme_has_no_retired_source(self):
        from app import config
        from app import sources
        line = self.readme_sources_line().lower()
        retired_names = set()
        for key in config.RETIRED_SOURCES:
            retired_names.add(key.lower())
        for key in config.RETIRED_SOURCES:
            pair = sources._BUILTIN_ADAPTERS.get(key)
            if pair:
                retired_names.add(pair[0].lower())
        stale = sorted(n for n in retired_names if n and n in line)
        self.assertEqual(
            stale, [],
            "README 里还写着已经下线的源（比对不区分大小写，"
            "BitSearch / BTDigg 这类混合大小写的名字也算）：" + repr(stale))

    def test_readme_count_matches_the_list(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        m = re.search(r"同时检索 (\d+) 个公开磁力索引站", readme)
        self.assertIsNotNone(m, "README 首段的源数量写法变了，护栏要跟着改")
        self.assertEqual(
            int(m.group(1)), len(self.real_labels()),
            "README 首段的源数量与内置源清单对不上")


class ProgressLineWiringTest(unittest.TestCase):

    def build_prog_block(self):
        src = (ROOT / "web" / "js" / "views" / "search.js").read_text(encoding="utf-8")
        i = src.index("function buildProg(")
        return src[i:src.index("\n  }", i)]

    def test_build_prog_reads_live_state_not_startup_snapshot(self):
        block = self.build_prog_block()
        self.assertIn(
            "st.progLineOn", block,
            "警戒线开关要读实时状态。改读 HC.settings 那份启动快照后，"
            "在设置页关掉开关必须重启程序才生效")
        self.assertNotIn(
            "HC.settings", block,
            "buildProg 不能依赖 HC.settings 快照")

    def test_settings_save_refreshes_the_global_snapshot(self):
        src = (ROOT / "web" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
        marker = '#btnSave").onclick'
        i = src.index(marker)
        block = src[i:i + 900]
        self.assertIn(
            "HC.settings", block,
            "保存设置后要回填 HC.settings，否则全局快照永远是启动时那份")

    def test_warning_line_is_wired_end_to_end(self):
        settings = (ROOT / "web" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
        self.assertIn("s_progline", settings, "设置页要有警戒线开关")
        self.assertIn("progress_line", settings, "开关要读写 progress_line")
        api = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        self.assertIn("progress_line", api, "mock 设置里也要有这个键")
        backend = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
        self.assertIn("progress_line", backend, "后端要有默认值")


class CacheReplayStateTest(unittest.TestCase):

    def setUp(self):
        import tempfile
        from pathlib import Path
        from app import api as api_mod, config, sources
        self.api_mod = api_mod
        self.sources = sources
        self.tmpdir = tempfile.mkdtemp(prefix="hc-replay-")
        self.api = api_mod.Api()
        self.api._cfg = config.Config(path=Path(self.tmpdir) / "sources.json")
        self.api._cfg.load()
        self.api._settings = config.Settings(
            path=Path(self.tmpdir) / "settings.json")
        self.api._settings.load()
        self.api._health_store = config.HealthStore(
            path=Path(self.tmpdir) / "health.json")
        self.orig_all = sources.ALL_SOURCES
        self.orig_by = sources.BY_KEY
        self.pushed = []
        self.api._push = self.capture
        sources.reload_from_config(self.api._cfg)

    def tearDown(self):
        self.sources.ALL_SOURCES = self.orig_all
        self.sources.BY_KEY = self.orig_by

    def capture(self, js):
        if "__onSearchSource" in js:
            import json
            self.pushed.append(json.loads(
                js.split("__onSearchSource(", 1)[1].rsplit(")", 1)[0]))

    def wire(self, empty_key, full_key):
        def empty_fn(q, page=1, timeout=15, base="", batch=None):
            return []

        def full_fn(q, page=1, timeout=15, base="", batch=None):
            return [{"title": "t", "info_hash": "a" * 40, "source": full_key}]

        pair = [self.sources.Source(empty_key, empty_key, empty_fn),
                self.sources.Source(full_key, full_key, full_fn)]
        self.sources.ALL_SOURCES = pair
        self.sources.BY_KEY = {s.key: s for s in pair}
        return [s.key for s in pair]

    def test_replay_reports_empty_for_zero_result_sources(self):
        keys = self.wire("s_empty", "s_full")
        token = self.sources.start_batch()
        self.api._search_token = token
        self.api._search_worker(token, "ubuntu", keys)
        self.assertEqual(
            [r["state"] for r in self.pushed], ["empty", "ok"],
            "第一轮就应如实反映：0 条是 empty，有结果是 ok")

        self.pushed.clear()
        token = self.sources.start_batch()
        self.api._search_token = token
        self.api._search_worker(token, "ubuntu", keys)
        by_key = {r["key"]: r for r in self.pushed}
        self.assertEqual(
            by_key["s_empty"]["state"], "empty",
            "缓存回放时不能把 0 条的源写成 ok —— 界面会亮绿点，"
            "与源管理页的红/灰状态互相矛盾")
        self.assertTrue(by_key["s_empty"].get("cached"),
                        "回放要带 cached 标记，前端据此显示「缓存」")


class SearchThreadCleanupTest(unittest.TestCase):

    def callers(self):
        out = []
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if "start_search(" not in line or line.lstrip().startswith("#"):
                    continue
                if "MAX_QUERY_LEN" in line or "assertRaises" in line:
                    continue
                out.append((path, i, text))
        return out

    def test_start_search_callers_wait_for_the_worker(self):
        offenders = []
        for path, lineno, text in self.callers():
            window = "\n".join(text.splitlines()[lineno - 1:lineno + 14])
            if "self.await_search_threads(" not in window:
                offenders.append(f"{path.name}:{lineno}")
        self.assertEqual(
            offenders, [],
            "调 start_search 会起一个 _search_worker 后台线程。测试必须等它结束，"
            "否则 mock 窗口一关，它就拿着真 search_many 去打真实站点，"
            "并被后续测试的 http_get 替身记进它们的断言列表：" + repr(offenders))


class TestCollectionPositionTest(unittest.TestCase):

    FILES = ("test_front_hygiene.py", "test_front_smoke.py",
             "test_source_relevance.py", "test_xccl263.py",
             "test_adapter_contract.py", "test_contract.py",
             "test_regressions.py", "test_pure.py")

    def test_main_guard_is_the_last_thing_in_the_file(self):
        for name in self.FILES:
            path = ROOT / "tests" / name
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            marker = 'if __name__ == "__main__":'
            lines = text.splitlines()
            starts = [i for i, l in enumerate(lines) if l.strip() == marker]
            if not starts:
                continue
            with self.subTest(file=name):
                after = "\n".join(lines[starts[-1]:])
                self.assertNotIn(
                    "\nclass ", after,
                    f"{name} 的 unittest.main() 之后还有测试类，"
                    f"直接运行这个文件时它们不会被收集")

    def test_files_add_project_root_to_sys_path(self):
        for name in self.FILES:
            path = ROOT / "tests" / name
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            if "from app" not in text:
                continue
            with self.subTest(file=name):
                self.assertIn(
                    "sys.path.insert", text,
                    f"{name} 导入了 app 却没把项目根加进 sys.path，"
                    f"直接运行会 ModuleNotFoundError")


class JsonHighlightTest(unittest.TestCase):

    def semantic_map(self):
        src = (ROOT / "web" / "js" / "views" / "sources.js").read_text(encoding="utf-8")
        block = src.split("var SEMANTIC = {", 1)[1].split("};", 1)[0]
        return dict(re.findall(r"(\w+)\s*:\s*\"(\w+)\"", block))

    def test_every_outcome_maps_to_its_state_color(self):
        from app import api as api_mod
        m = self.semantic_map()
        missing = [o for o in api_mod.OUTCOME_STATE if o not in m]
        self.assertEqual(missing, [],
                         f"诊断里会出现这些 outcome，高亮表漏了：{missing}")
        for outcome, state in api_mod.OUTCOME_STATE.items():
            with self.subTest(outcome=outcome):
                self.assertEqual(m[outcome], state,
                                 f"{outcome} 的颜色必须与后端 OUTCOME_STATE 一致，"
                                 f"否则颜色就成了乱标")

    def test_every_state_has_a_highlight_rule(self):
        from app import api as api_mod
        base = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        states = set(api_mod.OUTCOME_STATE.values()) | {"na"}
        missing = sorted(s for s in states
                         if not re.search(r"\.js-" + re.escape(s) + r"\s*\{", base))
        self.assertEqual(
            missing, [],
            "诊断会把这些状态标成对应颜色，CSS 里却没有 .js-<状态> 规则，"
            "结果是标签没颜色：" + repr(missing))

    def test_kind_values_are_mapped(self):
        m = self.semantic_map()
        self.assertIn("fail", m)
        self.assertEqual(m["fail"], "err", "kind=fail 是故障，应与 err 同色")
        self.assertIn("empty", m)

    def test_colors_come_from_existing_tokens(self):
        base = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        for cls, tok in (("js-ok", "ok"), ("js-warn", "warn"),
                         ("js-empty", "empty"), ("js-err", "err")):
            with self.subTest(cls=cls):
                self.assertRegex(
                    base,
                    rf"\.{cls}\{{[^}}]*var\(--{tok}\)",
                    f".{cls} 必须用项目既有的 --{tok}，不要另造色值")


class MockHashTest(unittest.TestCase):

    def node(self):
        import shutil
        for cand in (shutil.which("node"), r"C:\Program Files\nodejs\node.exe"):
            if cand and Path(cand).exists():
                return cand
        return None

    def test_mock_hashes_are_valid_hex(self):
        node = self.node()
        if not node:
            self.skipTest("没有可用的 node")
        script = """
        const fs=require('fs');
        const t=fs.readFileSync('web/js/api.js','utf8');
        const i=t.indexOf('function mockHash(');
        const j=t.indexOf('\\n  }', i);
        eval(t.slice(i, j+4));
        let bad=[], seen={}, dup=[];
        for(let k=0;k<24;k++){
          const h=mockHash(k);
          if(!/^[0-9a-f]{40}$/.test(h)) bad.push(k+':'+h);
          if(seen[h]) dup.push(k); else seen[h]=1;
        }
        console.log(JSON.stringify({bad, dup, n:Object.keys(seen).length}));
        """
        proc = subprocess.run([node, "-e", script], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        import json
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(data["bad"], [], "mock hash 不是合法 40 位 hex")
        self.assertEqual(data["dup"], [], "mock hash 有重复")
        self.assertEqual(data["n"], 24)



class SourceStripWrapTest(unittest.TestCase):

    def strip_block(self):
        src = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        i = src.index(".srcstrip{")
        return src[i:src.index("}", i)]

    def test_strip_wraps_instead_of_scrolling(self):
        block = self.strip_block()
        self.assertIn("flex-wrap:wrap", block,
                      "逐源进度条要自动换行，不能横向滚动")

    def test_strip_has_no_horizontal_overflow(self):
        block = self.strip_block()
        self.assertNotIn("overflow-x", block,
                         "有 overflow-x 就会出横向滚动条，看不到的源要藏在滑块后面")

    def test_strip_updates_in_place_not_by_innerHTML(self):
        src = (ROOT / "web" / "js" / "views" / "search.js").read_text(encoding="utf-8")
        i = src.index("function paintStrip(")
        block = src[i:src.index("function headHtml(", i)]
        self.assertNotIn("stripEl.innerHTML =", block,
                         "整块重建会让每个标签的 CSS 过渡重启，状态切换会闪；"
                         "要按 key 原地更新")
        self.assertIn("dataset.key", block,
                      "原地更新要靠 key 找回已有节点")

    def test_no_strip_scrollbar_styling_remains(self):
        src = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        self.assertNotIn(".srcstrip::-webkit-scrollbar", src,
                         "换行后不该再留滚动条样式")

    def test_item_count_is_not_pushed_far_right(self):
        src = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        i = src.index(".scount{")
        block = src[i:src.index("}", i)]
        self.assertNotIn("margin-left:auto", block,
                         "换行后 margin-left:auto 会把完成数甩到最右，与上一行断开")

    def test_tiles_grow_to_fill_the_row(self):
        src = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        i = src.index(".stile{")
        block = src[i:src.index("}", i)]
        self.assertRegex(block, r"flex:1 1 ",
                         "标签要能伸展填满整行，否则末行会留缺口")

    def tile_block(self):
        src = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        i = src.index(".stile{")
        return src[i:src.index("}", i)]

    def test_tiles_have_a_max_width(self):
        self.assertIn("max-width", self.tile_block(),
                      "没有上限时，末行只剩一个标签会被拉成整行宽")

    def test_min_width_follows_the_name(self):
        self.assertIn("min-width:max-content", self.tile_block().replace(" ", ""),
                      "下限要用内容宽度：写死像素会把长名字裁掉")

    def test_max_width_is_a_plain_length(self):
        block = self.tile_block()
        i = block.index("max-width:")
        value = block[i + len("max-width:"):].split(";")[0].strip()
        self.assertNotIn("max-content", value,
                         "max-width 里混 max()/clamp() 与 max-content 会整条失效"
                         "（浏览器解析为 none，上限形同不存在）")
        self.assertRegex(value, r"^calc\(", f"上限应是普通长度，实际 {value!r}")

    def test_name_is_never_clipped(self):
        self.assertNotIn("text-overflow", self.tile_block(),
                         "不要用省略号藏起源名")
        src = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        i = src.index(".stile .stitle")
        self.assertIn("min-width:0", src[i:src.index("}", i)].replace(" ", ""),
                      "名字要能撑开标签（min-width:0 + max-content 下限），"
                      "否则会被父级的 overflow:hidden 裁掉")

    def test_tile_clips_only_the_track(self):
        src = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        block = self.tile_block().replace(" ", "")
        self.assertIn("overflow:hidden", block,
                      "标签要裁掉底部进度条超出圆角的部分")

    def test_track_bar_clips_its_own_overflow(self):
        src = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        i = src.index(".stile .track{")
        block = src[i:src.index("}", i)]
        self.assertIn("overflow:hidden", block.replace(" ", ""),
                      "进度条要自己裁溢出，别让父级替它裁")

    def test_track_is_static_not_looping(self):
        src = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        i = src.index(".stile .track{")
        block = src[i:src.index("}", i)]
        self.assertNotIn("animation", block,
                         "等待态底轨应是静态的，不循环")


class StripCompletionMotionTest(unittest.TestCase):

    def css(self):
        return (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")

    def rule(self, selector):
        src = self.css()
        i = src.index(selector)
        return src[i:src.index("}", i)]

    def paint_block(self):
        src = (ROOT / "web" / "js" / "views" / "search.js").read_text(encoding="utf-8")
        i = src.index("function paintStrip(")
        return src[i:src.index("function headHtml(", i)]

    def test_completion_flash_paints_each_state_in_its_own_color(self):
        want = {
            "ok": "var(--ok)",
            "empty": "var(--empty)",
            "warn": "var(--warn)",
            "err": "var(--err)",
        }
        for state, color in want.items():
            block = self.rule(".stile.flash." + state + " .wipe{")
            self.assertIn("background:" + color, block.replace(" ", ""),
                          f"{state} 完成时铺色要用它自己的颜色，实际 {block!r}")

    def test_zero_results_flashes_grey_not_red(self):
        block = self.rule(".stile.flash.empty .wipe{")
        self.assertNotIn("--err", block,
                         "返回 0 条不是故障，铺色不能是红的")

    def test_wipe_is_a_one_shot_animation(self):
        block = self.rule(".stile.flash .wipe{")
        self.assertRegex(block, r"animation:srcWipe \d+ms [^;]*both",
                         "铺色只播一次（both），不能 infinite 循环")

    def test_progress_slot_stays_visible(self):
        block = self.rule(".progress{")
        self.assertIn("background:var(--prog-gap)", block.replace(" ", ""),
                      "顶部进度条要有常驻深色进度槽，搜索结束后也能看总进度")
        tokens = (ROOT / "web" / "styles" / "tokens.css").read_text(encoding="utf-8")
        self.assertGreaterEqual(tokens.count("--prog-gap:"), 2,
                                "浅色与暗色都要定义进度槽色，槽是常驻的不能透明")

    def tile_block(self):
        src = self.css()
        i = src.index(".stile{")
        return src[i:src.index("}", i)]

    def test_tile_hover_lifts_like_the_brandmark(self):
        block = self.rule(".stile:hover{")
        self.assertIn("transform:translateY", block.replace(" ", ""),
                      "源标签悬停要有和大标题一样的抬升")

    def test_tile_hover_uses_project_motion_tokens(self):
        block = self.tile_block().replace(" ", "")
        self.assertIn("transformvar(--d-push)var(--spring)", block,
                      "抬升要跟大标题同一套令牌（--d-push / --spring），别自己写时长")

    def test_tile_hover_keeps_state_colors(self):
        block = self.rule(".stile:hover{").replace(" ", "")
        self.assertNotIn("color:var(", block,
                         "悬停不许改写状态色：绿/黄/红/灰是健康度语义")

    def test_repaint_does_not_move_tiles(self):
        block = self.paint_block()
        self.assertNotIn("stripEl.appendChild(el)", block,
                         "每次重绘都 appendChild 会把节点摘下重插，"
                         "CSS 动画从头重启，扫光相位会乱跳")
        self.assertIn("insertBefore", block,
                      "已就位的标签不要动，缺的才插入")


class SourceProgressVisibilityTest(unittest.TestCase):

    def search_js(self):
        return (ROOT / "web" / "js" / "views" / "search.js").read_text(encoding="utf-8")

    def api_js(self):
        return (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")

    def test_backend_emits_start_before_the_source_finishes(self):
        src = (ROOT / "app" / "sources.py").read_text(encoding="utf-8")
        self.assertIn("def _search_starting(", src,
                      "没有开始事件，前端就分不出「排队」和「进行中」，"
                      "两种完全不同的处境只能都显示成「等待」")
        self.assertIn("on_start(source.key)", src,
                      "开始事件要在任务真正拿到线程时发，不是在提交任务时发")

    def test_start_fires_inside_the_worker_not_at_submit(self):
        src = (ROOT / "app" / "sources.py").read_text(encoding="utf-8")
        i = src.index("def search_many(")
        tail = src[i + 10:]
        nxt = tail.find("\ndef ")
        block = tail if nxt < 0 else tail[:nxt]
        self.assertIn("pool.submit(_search_starting", block,
                      "提交时发开始事件的话，排队中的源会被当成正在跑")
        self.assertIn("on_start)] = s.key", block,
                      "回调必须真的传进 worker。传 None 的话事件永远不发，"
                      "界面上就只剩「排队」和「已完成」，进行中整段消失")

        wrap = src[src.index("def _search_starting("):]
        wrap = wrap[:wrap.index("def search_one(")]
        self.assertIn("on_start(source.key)", wrap,
                      "开始事件要在任务真正拿到线程时发")

    def test_typical_is_a_median_not_a_mean(self):
        from app import api as api_mod
        api = api_mod.Api()
        api._health_store.data["probe_src"] = {"events": [
            {"ms": 100, "outcome": "ok"},
            {"ms": 200, "outcome": "ok"},
            {"ms": 9000, "outcome": "ok"},
        ]}
        try:
            self.assertEqual(api._typical_ms("probe_src"), 200,
                             "「约」要用中位数：均值会被偶发的一次超时拉飞，"
                             "给用户一个没有参考价值的基线")
        finally:
            api._health_store.data.pop("probe_src", None)

    def test_typical_ignores_failures_and_unknown_keys(self):
        from app import api as api_mod
        api = api_mod.Api()
        self.assertEqual(api._typical_ms("no_such_source_at_all"), 0,
                         "没有历史时必须返回 0，前端才知道不要显示「约」")
        api._health_store.data["probe_src2"] = {"events": [
            {"ms": 9999, "outcome": "http429"},
            {"ms": 0, "outcome": "ok"},
        ]}
        try:
            self.assertEqual(api._typical_ms("probe_src2"), 0,
                             "失败请求的耗时不能进基线，否则错误地抬高预期")
        finally:
            api._health_store.data.pop("probe_src2", None)

    def test_frontend_has_the_start_hook(self):
        self.assertIn("window.__onSearchStart", self.api_js(),
                      "后端推的开始事件要有接收口，否则白推")
        self.assertIn("start: function(d)", self.search_js(),
                      "搜索视图要处理 start 事件")

    def test_running_needs_a_start_marker_not_just_pending(self):
        src = self.search_js()
        self.assertIn('ss.state === "pending" && !!ss.startedAt', src,
                      "排队与进行中共用 pending 状态，靠 startedAt 区分；"
                      "少了这个判断两者又会合并成一个样子")

    def test_elapsed_time_comes_from_the_start_event(self):
        src = self.search_js()
        self.assertIn("startedAt = performance.now()", src,
                      "已用时间要锚在开始事件上，不能用搜索开始时间冒充，"
                      "否则排队时间会被算进请求耗时")

    def test_eta_is_dropped_once_the_baseline_is_passed(self):
        src = self.search_js()
        self.assertIn("used < typ", src,
                      "超过基线后要撤掉「约」，否则会出现"
                      "「12.0s / 约 3.2s」这种自己打自己脸的读数")

    def test_running_style_is_defined_and_breathing_is_moved_off_pending(self):
        src = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        self.assertIn(".stile.running .sdot{", src,
                      "进行中要有自己的圆点样式")
        i = src.index(".stile.running .sdot{")
        block = src[i:src.index("}", i)]
        self.assertIn("breathe", block,
                      "呼吸动画是「在跑」的信号，要挂在 running 上")
        pending = src[src.index(".stile.pending .sdot{"):]
        pending = pending[:pending.index("}")]
        self.assertNotIn("animation", pending,
                         "排队态不该呼吸：不动的点才表示「还没轮到」，"
                         "排队和进行中都呼吸就又分不出来了")

    def test_mock_emits_start_so_both_modes_match(self):
        src = self.api_js()
        i = src.index("startSearch: function(query){")
        block = src[i:src.index("function mockItems(", i)]
        self.assertIn("sHooks.start(", block,
                      "直开网页与真机两种跑法要一致，mock 也要推开始事件")

    def test_concurrency_covers_the_builtin_sources(self):
        from app import config, sources
        self.assertGreaterEqual(
            sources.MAX_SEARCH_WORKERS, len(config.DEFAULT_SOURCES),
            f"默认并发 {sources.MAX_SEARCH_WORKERS} 小于内置源数量 "
            f"{len(config.DEFAULT_SOURCES)}，多出来的源要在队列里白等")

    def test_seg_red_requires_err_state_not_a_filled_err_field(self):
        js = self.search_js()
        self.assertNotIn('d.err ? " err" : " on"', js,
                         "后端把「无结果」装在 err 字段里（outcome_text 对 "
                         "OUTCOME_EMPTY 返回「无结果」），拿 err 非空当失败 "
                         "会把空结果涂成红色")
        self.assertIn('var segRed = d.state === "err"', js,
                      "红块判定要以后端 state 为准：只有真失败才上红")
        i = js.index("var segRed = d.state === \"err\"")
        body = js[i:i + 200]
        self.assertIn('d.outcome !== "empty"', body,
                      "旧载荷没有 state 时要用 outcome 排除空结果，"
                      "否则旧形状事件会把无结果涂红")

    def test_recede_does_not_exclude_err_segments(self):
        js = self.search_js()
        self.assertNotIn('.seg:not(.err)', js,
                         "退场排除红块的话，失败块就成了唯一不熄灭的残留")
        i = js.index("function recedeProg(")
        block = js[i:js.index("function paintClock(", i)]
        self.assertIn('.seg.on, .seg.err', block,
                      "逐块熄灭要把失败块也扫进去，全条一起退场")
        self.assertIn('querySelectorAll(".seg")', block,
                      "庆祝点亮要覆盖全部块，红块先转 on 才有得灭")

    def test_mock_empty_result_carries_the_real_payload_shape(self):
        src = self.api_js()
        i = src.index("startSearch: function(query){")
        block = src[i:src.index("function mockItems(", i)]
        self.assertIn('err: err || (outcome === "empty" ? "无结果" : "")', block,
                      "真实后端对空结果在 err 字段里填「无结果」，"
                      "mock 缺这个形状的话这类缺陷在 E2E 里永远测不出")
        self.assertIn('outcome: outcome', block,
                      "mock 载荷要带 outcome，与真实 on_source 一致")

    def test_backend_empty_text_still_travels_in_err_field(self):
        from app import api
        self.assertEqual(api.OUTCOME_TEXT[api.OUTCOME_EMPTY], "无结果",
                         "后端契约：空结果的说明文字放在 err 字段里下发，"
                         "前端 segRed 依赖 outcome/state 来区分它与真失败")


_PREVIEW_ONLY_LOOK_KEYS = frozenset({"hold", "step"})

_TEXT_CONTRAST_EXEMPT = frozenset({"t4", "t5", "t-disabled"})
_TEXT_CONTRAST_PENDING = frozenset({"brand", "brand-active", "ok", "warn", "danger"})
_PENDING_REASON = ("这几项都是「按填充调出来的饱和度」被拿去当文字用："
                   "ok / warn / danger 的浅色值对白底只有 2.94~3.76，"
                   "brand / brand-active 的暗色值对浮层底只有 3.24~4.08。"
                   "要修得重新选色（或让文字用法改走 -strong 变体），属取舍，等拍板。")

_LIGHT_SURFACE = "#FFFFFF"
_DARK_SURFACE = "#2A2C36"
_AA_TEXT = 4.5


def _token_blocks(path):
    text = Path(path).read_text(encoding="utf-8")
    blocks = {}
    i = 0
    while True:
        brace = text.find("{", i)
        if brace < 0:
            break
        head = [l.strip() for l in text[i:brace].split("\n") if l.strip()]
        depth = 0
        j = brace
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blocks[" ".join(head)] = {
            m.group(1): m.group(2).strip()
            for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", text[brace + 1:j])
        }
        i = j + 1
    return blocks


def _resolved(layer, root, name):
    value = layer.get(name, root.get(name, ""))
    m = re.match(r"var\(\s*(--[\w-]+)\s*\)$", value)
    if m:
        return layer.get(m.group(1), root.get(m.group(1), value))
    return value


def _luminance(hex_value):
    h = str(hex_value).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if not re.match(r"^[0-9a-fA-F]{6}$", h):
        return None
    channels = [int(h[k:k + 2], 16) / 255 for k in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(fg, bg):
    a, b = _luminance(fg), _luminance(bg)
    if a is None or b is None:
        return None
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


class LookParamWiringTest(unittest.TestCase):

    def html(self):
        return HTML.read_text(encoding="utf-8")

    def object_keys(self, name):
        src = self.html()
        i = src.index("var " + name + " = {")
        block = src[i:src.index("\n  };", i)]
        return block

    def test_every_numeric_look_param_reaches_a_css_var(self):
        defaults = self.object_keys("LOOK_DEFAULTS")
        numeric = {m.group(1) for m in re.finditer(r"(\w+)\s*:\s*\d", defaults)}
        wired = set(re.findall(r"(\w+)\s*:\s*\[", self.object_keys("LOOK_VARS")))
        orphan = sorted(numeric - wired - _PREVIEW_ONLY_LOOK_KEYS)
        self.assertEqual(
            orphan, [],
            "这些外观参数既没落到 CSS 变量、也没登记为预览专用，" + repr(orphan)
            + "：用户在设置页拖了它不会有任何效果")

    def test_preview_only_params_are_really_consumed(self):
        settings = (ROOT / "web" / "js" / "views" / "settings.js").read_text(
            encoding="utf-8")
        for key in sorted(_PREVIEW_ONLY_LOOK_KEYS):
            self.assertIn("look." + key, settings,
                          key + " 被登记为预览专用，但预览里也没人读它")

    def test_preview_tail_uses_the_real_bar_constant(self):
        search = (ROOT / "web" / "js" / "views" / "search.js").read_text(
            encoding="utf-8")
        settings = (ROOT / "web" / "js" / "views" / "settings.js").read_text(
            encoding="utf-8")
        self.assertIn("HC.PROG_TAIL_MS = PROG_TAIL_MS", search,
                      "真实进度条的收尾时长要有单一来源并导出，别在函数里写死数字")
        self.assertIn("lit.length * 45 + PROG_TAIL_MS", search,
                      "真实进度条自己也要用这个常量，不能导出却另写一个字面量")
        self.assertIn("HC.PROG_TAIL_MS", settings,
                      "面板预览要用真实进度条的收尾时长；各写一份会让预览比真实条短一截")


class TextContrastTest(unittest.TestCase):

    def audit(self):
        blocks = _token_blocks(ROOT / "web" / "styles" / "tokens.css")
        root, dark = blocks[":root"], blocks["body.dark"]
        css = (ROOT / "web" / "styles" / "base.css").read_text(encoding="utf-8")
        used = {m.group(1) for m in
                re.finditer(r"(?<![\w-])color\s*:\s*var\(\s*(--[\w-]+)\s*\)", css)}
        rows = []
        for name in sorted(used):
            key = name[2:]
            if key.startswith("inv-") or key in _TEXT_CONTRAST_EXEMPT:
                continue
            light = _contrast(_resolved(root, root, name), _LIGHT_SURFACE)
            darkc = _contrast(_resolved(dark, root, name), _DARK_SURFACE)
            rows.append((key, light, darkc))
        return rows

    def test_text_tokens_clear_aa_in_both_themes(self):
        bad = []
        for key, light, dark in self.audit():
            if key in _TEXT_CONTRAST_PENDING:
                continue
            if light is not None and light < _AA_TEXT:
                bad.append(key + " 浅色 " + str(round(light, 2)))
            if dark is not None and dark < _AA_TEXT:
                bad.append(key + " 暗色 " + str(round(dark, 2)))
        self.assertEqual(bad, [], "文字色对比度不达 AA：" + repr(bad))

    def test_pending_tokens_are_reported_until_they_pass(self):
        failing = set()
        for key, light, dark in self.audit():
            if key not in _TEXT_CONTRAST_PENDING:
                continue
            if light is not None and light < _AA_TEXT:
                failing.add(key)
            elif dark is not None and dark < _AA_TEXT:
                failing.add(key)
        self.assertEqual(
            sorted(failing), sorted(_TEXT_CONTRAST_PENDING),
            "待定表与实际不符（待定项已达标，或达标判定失效）：" + _PENDING_REASON)


class ToolRootPathTest(unittest.TestCase):

    def tools(self):
        return sorted((ROOT / "tools").rglob("*.py"))

    def test_tool_roots_resolve_to_the_project_root(self):
        for path in self.tools():
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(
                    r"Path\(__file__\)\.resolve\(\)\.parents\[(\d+)\]", text):
                got = path.resolve().parents[int(m.group(1))]
                self.assertEqual(
                    got, ROOT,
                    path.relative_to(ROOT).as_posix() + " 的 __file__ 层级算到了 "
                    + str(got) + "，不是项目根。工具搬目录后这个数字必须跟着改")

    def test_no_tool_hardcodes_an_absolute_project_path(self):
        for path in self.tools():
            text = path.read_text(encoding="utf-8")
            for needle in (str(ROOT), ROOT.as_posix()):
                self.assertNotIn(
                    needle, text,
                    path.relative_to(ROOT).as_posix()
                    + " 里写死了本机绝对路径，换个 clone 就跑不了")


if __name__ == "__main__":
    unittest.main()
