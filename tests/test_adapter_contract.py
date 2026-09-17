import ast
import inspect
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import sources


def reads_page(fn) -> bool:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    fn_def = tree.body[0]
    if "page" not in [a.arg for a in fn_def.args.args]:
        return False
    for node in ast.walk(fn_def):
        if isinstance(node, ast.Name) and node.id == "page" \
                and isinstance(node.ctx, ast.Load):
            return True
    return False


class AdapterPageContractTest(unittest.TestCase):

    def test_pageless_keys_are_real_builtin_sources(self):
        unknown = sorted(sources.PAGELESS_KEYS - sources.BUILTIN_KEYS)
        self.assertEqual(unknown, [],
                         "PAGELESS_KEYS 里有不存在的内置源：" + repr(unknown))

    def test_pageless_adapters_really_ignore_page(self):
        wrong = []
        for key in sorted(sources.PAGELESS_KEYS):
            _label, fn = sources._BUILTIN_ADAPTERS[key]
            if reads_page(fn):
                wrong.append(key)
        self.assertEqual(
            wrong, [],
            "这些源标了不分页，函数体却读了 page，翻页参数会被静默丢掉："
            + repr(wrong))

    def test_paginated_adapters_really_use_page(self):
        unused = []
        for key, (_label, fn) in sources._BUILTIN_ADAPTERS.items():
            if key in sources.PAGELESS_KEYS:
                continue
            if not reads_page(fn):
                unused.append(key)
        self.assertEqual(
            unused, [],
            "这些源收了 page 却从不读，加翻页时会返回和第一页一样的东西："
            + repr(unused) + "（确实不支持分页就放进 PAGELESS_KEYS）")

    def test_pageless_sources_always_start_at_page_one(self):
        for key in sorted(sources.PAGELESS_KEYS):
            with self.subTest(key=key):
                seen = []
                src = sources.Source(key, key, lambda q, p, t, b, batch=None: (
                    seen.append(p) or []))
                src.search("x", 4)
                self.assertEqual(seen, [1],
                                 f"{key} 不支持分页，传进来的页码必须被归一成 1")

    def test_paginated_sources_keep_the_requested_page(self):
        seen = []
        src = sources.Source("nyaa", "nyaa", lambda q, p, t, b, batch=None: (
            seen.append(p) or []))
        src.search("x", 4)
        self.assertEqual(seen, [4], "支持分页的源必须把页码原样传下去")


if __name__ == "__main__":
    unittest.main()
