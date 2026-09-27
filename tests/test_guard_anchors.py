import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "guard_regression", ROOT / "tools" / "guard-regression.py")
_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_guard)


class GuardAnchorTest(unittest.TestCase):

    def test_every_old_string_still_exists(self):
        stale = []
        for name, rel, old, _new, _tf in _guard.CASES:
            text = (ROOT / rel).read_text(encoding="utf-8")
            if old not in text:
                stale.append(f"{name} -> {rel}")
        self.assertEqual(stale, [], "这些护栏从没被验过，去更新脚本里的旧串：\n"
                         + "\n".join(stale))

    def test_every_injection_actually_changes_the_file(self):
        noop = [name for name, _rel, old, new, _tf in _guard.CASES
                if old == new]
        self.assertEqual(noop, [], "新旧串相同的注入等于没注入：\n" + "\n".join(noop))

    def test_every_case_points_at_a_real_test_file(self):
        missing = []
        for name, _rel, _old, _new, tf in _guard.CASES:
            if tf and not (ROOT / tf).exists():
                missing.append(f"{name} -> {tf}")
        self.assertEqual(missing, [], "\n".join(missing))

    def test_case_names_are_unique(self):
        names = [name for name, *_ in _guard.CASES]
        dup = sorted({n for n in names if names.count(n) > 1})
        self.assertEqual(dup, [], "--case 关键字会同时命中重名条目：" + repr(dup))


if __name__ == "__main__":
    unittest.main()
