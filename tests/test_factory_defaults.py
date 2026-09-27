import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config, sources


def mock_builtins() -> list[tuple[str, bool]]:
    text = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
    block = text.split("var MOCK = [", 1)[1].split("];", 1)[0]
    out = []
    for m in re.finditer(r'key:"([a-z0-9_]+)"', block):
        tail = block[m.start():]
        on = re.search(r"enabled:(true|false)", tail)
        out.append((m.group(1), on.group(1) == "true" if on else True))
    return out


def mock_settings() -> dict:
    text = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
    block = text.split("var mockSettings = {", 1)[1].split("};", 1)[0]
    out: dict = {}
    for line in block.splitlines():
        for m in re.finditer(r"(\w+)\s*:\s*(\"([^\"]*)\"|true|false|-?\d+)", line):
            raw = m.group(2)
            if raw.startswith('"'):
                out[m.group(1)] = m.group(3)
            elif raw in ("true", "false"):
                out[m.group(1)] = raw == "true"
            else:
                out[m.group(1)] = int(raw)
    return out


class SourceDefaultsTest(unittest.TestCase):

    def test_bitsearch_and_javdb_ship_disabled(self):
        want = {s["key"]: s["enabled"] for s in config.DEFAULT_SOURCES}
        self.assertFalse(want["bitsearch"],
                         "BitSearch 长期 429，出厂默认关")
        self.assertFalse(want["javdb"],
                         "JavDB 多数影片要登入才给磁力，出厂默认关")

    def test_the_other_ten_ship_enabled(self):
        want = {s["key"]: s["enabled"] for s in config.DEFAULT_SOURCES}
        off = sorted(k for k, on in want.items() if not on)
        self.assertEqual(off, ["bitsearch", "javdb"],
                         "出厂默认只关这两个，其它源被动关掉会是回归")

    def test_disabled_sources_still_have_adapters(self):
        for key in ("bitsearch", "javdb"):
            with self.subTest(key=key):
                self.assertIn(key, sources.BUILTIN_KEYS,
                              "默认关不等于下线：适配器必须还在，"
                              "用户打开开关就能用")
                self.assertNotIn(key, config.RETIRED_SOURCES,
                                 "进了 RETIRED_SOURCES 会被自动删除，"
                                 "用户再也找不回来")

    def test_default_order_matches_declaration(self):
        orders = [s["order"] for s in config.DEFAULT_SOURCES]
        self.assertEqual(orders, list(range(len(orders))),
                         "出厂顺序要连续，否则配置页拖动时会跳号")

    def test_disabled_sources_sort_last(self):
        keys = [s["key"] for s in config.DEFAULT_SOURCES]
        self.assertLess(keys.index("javbus"), keys.index("bitsearch"))
        self.assertLess(keys.index("javbus"), keys.index("javdb"),
                        "默认关的源排在末尾，用户不用越过它们找可用源")

    def test_tracked_sources_json_matches_defaults(self):
        raw = json.loads((ROOT / "data" / "sources.json").read_text(
            encoding="utf-8"))
        want = [(s["key"], bool(s["enabled"]), int(s["order"]), int(s["timeout"]))
                for s in config.DEFAULT_SOURCES]
        have = [(s["key"], bool(s.get("enabled", True)), int(s.get("order", 0)),
                 int(s.get("timeout", 15))) for s in raw["sources"]]
        self.assertEqual(have, want,
                         "版本库里的 sources.json 与出厂默认漂移了；"
                         "它是新人拿到的第一份配置")

    def test_frontend_mock_matches_default_switches(self):
        want = {s["key"]: bool(s["enabled"]) for s in config.DEFAULT_SOURCES}
        got = dict(mock_builtins())
        self.assertEqual(got, want,
                         "浏览器直开时 mock 就是后端，开关状态必须一致")


class SettingsDefaultsTest(unittest.TestCase):

    def test_brand_ships_as_lilac(self):
        self.assertEqual(config.DEFAULT_SETTINGS["brand"], "lilac",
                         "出厂主题色是薰衣草；改成空串会让首屏配色与设计稿不符")

    def test_fail_sound_ships_off(self):
        self.assertFalse(config.DEFAULT_SETTINGS["sound_fail"],
                         "失败提示音出厂默认关（搜索出错时不该再响一声）")

    def test_other_sounds_ship_unchanged(self):
        want = {"sound": True, "sound_start": True, "sound_done": True,
                "sound_select": False, "sound_copy": True, "sound_deliver": True}
        got = {k: config.DEFAULT_SETTINGS[k] for k in want}
        self.assertEqual(got, want)

    def test_sound_volume_ships_at_eighty(self):
        self.assertEqual(config.DEFAULT_SETTINGS["sound_volume"], 80)

    def test_frontend_mock_settings_match_backend(self):
        got = mock_settings()
        for key in ("sound_fail", "brand", "sound_volume", "sound",
                    "sound_start", "sound_done", "sound_select", "sound_copy",
                    "sound_deliver"):
            with self.subTest(key=key):
                self.assertEqual(
                    got.get(key), config.DEFAULT_SETTINGS.get(key),
                    f"mockSettings.{key} 与后端 DEFAULT_SETTINGS 不一致，"
                    "浏览器直开会看到另一套默认值")


if __name__ == "__main__":
    unittest.main()
