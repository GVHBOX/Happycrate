import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

JS = sorted((ROOT / "web" / "js").rglob("*.js"))
CSS = sorted((ROOT / "web" / "styles").rglob("*.css"))
HTML = ROOT / "web" / "index.html"


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
        text = re.sub(r"@(media|supports)[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}",
                      lambda m: "\n" * m.group(0).count("\n"), text)
        out = {}
        for m in re.finditer(r"^([^{@/\n][^{]*?)\{", text, re.M):
            sel = " ".join(m.group(1).split())
            out.setdefault(sel, []).append(text[:m.start()].count("\n") + 1)
        return out

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
        m = re.search(r"\.progress\.on\s+\.fill\{([^}]*)\}", base)
        self.assertIsNotNone(m, "找不到 .progress.on .fill 规则")
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
        self.assertNotIn('class="term"', body,
                         "异常详情是给用户看的，不能直接把面向 AI 的诊断原文摊出来")
        self.assertNotIn("adapterLocation", body,
                         "代码路径不该出现在用户界面里")
        self.assertIn("issue", body, "应改用结构化的问题列表")

    def test_user_facing_strings_carry_no_advice(self):
        banned = ("点击", "请选择", "您可以", "建议", "试试", "请注意",
                  "使用方法", "该字段", "点击这里")
        targets = [ROOT / "web" / "js" / "views" / "sources.js",
                   ROOT / "web" / "js" / "views" / "search.js",
                   ROOT / "web" / "js" / "views" / "settings.js",
                   ROOT / "app" / "api.py"]
        for p in targets:
            text = p.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                if not re.search(r"[\u4e00-\u9fff]", line):
                    continue
                for b in banned:
                    with self.subTest(file=p.name, line=lineno, banned=b):
                        self.assertNotIn(
                            b, line,
                            f"{p.name}:{lineno} 界面只写「是什么」和「出了什么问题」，"
                            f"不写「怎么用」"),

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
        self.assertRegex(body, r'class="cb [\s\S]{0,120}aria-pressed=',
                         "批量复选按钮缺状态语义")
        self.assertRegex(body, r'class="sw [\s\S]{0,120}aria-pressed=',
                         "源启停开关缺状态语义")
        settings = (ROOT / "web" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
        self.assertRegex(settings, r'function setSw\([\s\S]{0,260}aria-pressed',
                         "setSw 必须同步 aria-pressed")
        for sid in ("s_selbar", "s_theme", "s_autofiles"):
            self.assertRegex(settings,
                             r'#' + sid + r'"\)\.onclick[\s\S]{0,220}(setSw\(|aria-pressed)',
                             f"设置页开关 {sid} 的点击处理必须同步 aria-pressed")


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
        for p in Path.home().glob(".workbuddy/binaries/node/versions/*/node.exe"):
            return str(p)
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


if __name__ == "__main__":
    unittest.main()
