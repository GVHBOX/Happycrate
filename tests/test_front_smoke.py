import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPT = ROOT / "tests" / "front_smoke.cjs"


def find_node() -> str | None:
    for name in ("node", "node.exe"):
        hit = shutil.which(name)
        if hit:
            return hit
    for cand in (
        r"C:\Program Files\nodejs\node.exe",
        os.path.expanduser(r"~\AppData\Roaming\npm\node.exe"),
    ):
        if os.path.isfile(cand):
            return cand
    import glob
    hits = sorted(glob.glob(
        os.path.expanduser(
            r"~\.workbuddy\binaries\node\versions\*\node.exe")))
    return hits[-1] if hits else None


class FrontEndSmokeTest(unittest.TestCase):

    def setUp(self):
        self.node = find_node()
        if not self.node:
            self.skipTest("本机没有 node，跳过前端冒烟")
        if not SCRIPT.is_file():
            self.fail(f"冒烟脚本缺失：{SCRIPT}")

    def run_script(self, script):
        proc = subprocess.run(
            [self.node, str(script)],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def test_window_tone_follows_theme_and_modal(self):
        script = ROOT / "tests" / "tone_smoke.cjs"
        self.assertTrue(script.is_file(), f"缺失：{script}")
        code, out = self.run_script(script)
        self.assertEqual(code, 0,
                         "窗口留白底色未跟随主题/弹窗状态，会出现边缘白框：\n" + out)
        self.assertIn("RESULT: PASS", out)

    def test_all_views_mount_without_throwing(self):
        proc = subprocess.run(
            [self.node, str(SCRIPT)],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        self.assertEqual(
            proc.returncode, 0,
            "前端冒烟未通过 —— 视图 mount 抛异常，通常是作用域或初始化回归：\n" + out,
        )
        self.assertIn("RESULT: PASS", out)

    def test_smoke_script_covers_every_view(self):
        body = SCRIPT.read_text(encoding="utf-8")
        for view in ("search", "sources", "settings"):
            with self.subTest(view=view):
                self.assertIn(view, body)
        self.assertIn("mount", body)



class FileRevealsTest(unittest.TestCase):

    def setUp(self):
        self.node = find_node()
        if not self.node:
            self.skipTest("本机没有 node，跳过前端校验")
        self.script = ROOT / "tests" / "file_reveals_check.cjs"

    def test_only_revealing_tokens_trigger_auto_expand(self):
        self.assertTrue(self.script.is_file(), f"校验脚本缺失：{self.script}")
        proc = subprocess.run(
            [self.node, str(self.script)],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        self.assertEqual(proc.returncode, 0,
                         "自动展开的条件只能是「标题里没有、文件里有」：\n"
                         + (proc.stdout or "") + (proc.stderr or ""))


class HighlightCheckTest(unittest.TestCase):

    def setUp(self):
        self.node = find_node()
        if not self.node:
            self.skipTest("本机没有 node，跳过高亮校验")
        self.script = ROOT / "tests" / "highlight_check.cjs"

    def test_highlight_never_corrupts_titles(self):
        self.assertTrue(self.script.is_file(), f"校验脚本缺失：{self.script}")
        proc = subprocess.run(
            [self.node, str(self.script)],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        self.assertEqual(
            proc.returncode, 0,
            "高亮把标题改坏了。高亮必须在原文上定位、逐段转义，"
            "不能在转义后的串上匹配——否则 & 会被拆成实体碎片，"
            "页面上多出 amp; 字样：\n" + out)

    def test_check_covers_enough_cases(self):
        import json
        proc = subprocess.run(
            [self.node, str(self.script)],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        line = [l for l in (proc.stdout or "").splitlines()
                if l.strip().startswith("{")]
        self.assertTrue(line, "校验脚本没输出 JSON：" + (proc.stdout or ""))
        data = json.loads(line[-1])
        self.assertGreaterEqual(data.get("total", 0), 50,
                                "用例太少，护栏覆盖不足")


class RelevanceCheckTest(unittest.TestCase):

    def setUp(self):
        self.node = find_node()
        if not self.node:
            self.skipTest("本机没有 node，跳过相关性校验")
        self.script = ROOT / "tests" / "relevance_check.cjs"

    def test_relevance_ranks_by_query_fit(self):
        self.assertTrue(self.script.is_file(), f"校验脚本缺失：{self.script}")
        proc = subprocess.run(
            [self.node, str(self.script)],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        self.assertEqual(
            proc.returncode, 0,
            "相关性排序未通过 —— 排序权重或匹配规则被改动：\n"
            + (proc.stdout or "") + (proc.stderr or ""))

    def test_script_reports_no_bad_cases(self):
        import json
        proc = subprocess.run(
            [self.node, str(self.script)],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        line = [l for l in (proc.stdout or "").splitlines() if l.strip().startswith("{")]
        self.assertTrue(line, "校验脚本没输出 JSON 结果：" + (proc.stdout or ""))
        data = json.loads(line[-1])
        self.assertGreater(data.get("total", 0), 0, "校验用例数为 0，护栏失效了")
        self.assertEqual(data.get("bad"), 0,
                         f"有 {data.get('bad')} 个排序用例不达标：{data}")


if __name__ == "__main__":
    unittest.main()
