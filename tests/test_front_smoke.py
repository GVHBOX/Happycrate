import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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


if __name__ == "__main__":
    unittest.main()


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
