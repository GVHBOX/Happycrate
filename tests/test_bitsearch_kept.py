import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config, sources


class BitSearchKeptTest(unittest.TestCase):

    def test_stays_a_builtin_source(self):
        self.assertIn("bitsearch", sources.BUILTIN_KEYS,
                      "BitSearch 目前只回 429，但保留着等它恢复；"
                      "真要下线必须同时改这条测试并说明原因")
        self.assertNotIn("bitsearch", config.RETIRED_SOURCES,
                         "不该进 RETIRED_SOURCES——那会让老配置启动时"
                         "自动删掉它，源站恢复后用户也找不回来")

    def test_has_a_default_base(self):
        self.assertEqual(sources.DEFAULT_BASES["bitsearch"],
                         "https://bitsearch.to")

    def test_adapter_is_intact(self):
        self.assertEqual(sources.BUILTIN_ADAPTER_NAMES["bitsearch"],
                         "_search_bitsearch")
        self.assertEqual(sources.BITSEARCH_PAGES, 2)
        self.assertEqual(sources.BITSEARCH_PAGE_SIZE, 100)

    def test_not_pageless(self):
        self.assertNotIn("bitsearch", sources.PAGELESS_KEYS,
                         "bitsearch 支持 page 参数，不该标成分页无关")

    def test_label_matches_config(self):
        want = {s["key"]: s["label"] for s in config.DEFAULT_SOURCES}
        self.assertEqual(sources._BUILTIN_ADAPTERS["bitsearch"][0],
                         want["bitsearch"])
        self.assertEqual(want["bitsearch"], "BitSearch")

    def test_reaches_the_existing_config_file(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            old = {"version": 1, "sources": [
                {"key": "nyaa", "label": "Nyaa", "type": "builtin",
                 "enabled": True, "timeout": 15, "base": "", "order": 0},
            ]}
            path.write_text(json.dumps(old), encoding="utf-8")
            cfg = config.Config(str(path)).load()
            self.assertIn("bitsearch", cfg.all_keys(),
                          "老配置启动时要自动补上它，用户不用手动添加")

    def test_frontend_mock_keeps_it(self):
        js = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        head = js.split("var MOCK = [", 1)[1].split("];", 1)[0]
        self.assertIn('key:"bitsearch"', head,
                      "浏览器直开时源列表要和后端一致")


if __name__ == "__main__":
    unittest.main()
