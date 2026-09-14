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

    def test_dead_aria_pressed_rule_removed(self):
        text = "\n".join(p.read_text(encoding="utf-8") for p in CSS)
        self.assertNotIn("aria-pressed", text,
                         "aria-pressed 全项目无人设置，是死样式")

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
