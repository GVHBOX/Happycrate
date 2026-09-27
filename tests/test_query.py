import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import query


class NormalizeTest(unittest.TestCase):

    def test_fullwidth_to_halfwidth(self):
        self.assertEqual(query.normalize("４Ｋ"), "4k")

    def test_folds_separators(self):
        self.assertEqual(query.normalize("a_b+c,d"), "a b c d")

    def test_keeps_version_dots(self):
        self.assertEqual(query.normalize("Ubuntu 22.04"), "ubuntu 22.04")

    def test_collapses_spaces(self):
        self.assertEqual(query.normalize("  电影   4K  "), "电影 4k")


class RoleTest(unittest.TestCase):

    def test_browse_query_has_no_subject(self):
        r = query.parse("电影 4K")
        self.assertEqual(r["subject"], [])
        self.assertEqual([m["role"] for m in r["mods"]], ["QUALITY"])
        self.assertIn("2160p", r["mods"][0]["forms"])

    def test_browse_query_with_genre_only(self):
        r = query.parse("射击游戏 3D 第三人称")
        self.assertEqual(r["subject"], [])

    def test_subject_is_separated(self):
        r = query.parse("流浪地球 2160p 中字")
        self.assertEqual(r["subject"], ["流浪地球"])
        self.assertEqual([m["role"] for m in r["mods"]], ["QUALITY"])
        self.assertEqual([s["kind"] for s in r["soft"]], ["LANG"])

    def test_season_is_exact(self):
        r = query.parse("进击的巨人 第12话")
        season = [m for m in r["mods"] if m["role"] == "SEASON"]
        self.assertEqual(len(season), 1)
        self.assertEqual((season[0]["s"], season[0]["e"]), (0, 12))
        self.assertEqual(r["subject"], ["进击的巨人"])

    def test_season_episode_pair(self):
        r = query.parse("沙丘 2024 S01E05")
        season = [m for m in r["mods"] if m["role"] == "SEASON"]
        year = [m for m in r["mods"] if m["role"] == "YEAR"]
        self.assertEqual((season[0]["s"], season[0]["e"]), (1, 5))
        self.assertEqual(year[0]["text"], "2024")
        self.assertEqual(r["subject"], ["沙丘"])

    def test_season_does_not_swallow_compound_token(self):
        r = query.parse("沙丘.S01E05")
        self.assertEqual([m for m in r["mods"] if m["role"] == "SEASON"], [])

    def test_year_is_soft_not_subject(self):
        r = query.parse("沙丘 2024")
        self.assertEqual(r["subject"], ["沙丘"])
        self.assertEqual([m["role"] for m in r["mods"]], ["YEAR"])

    def test_unknown_token_stays_subject(self):
        r = query.parse("阿凡达 4K")
        self.assertEqual(r["subject"], ["阿凡达"])
        self.assertEqual([m["role"] for m in r["mods"]], ["QUALITY"])


class VariantTest(unittest.TestCase):

    def test_quality_synonyms(self):
        r = query.parse("xxx 4k")
        forms = r["mods"][0]["forms"]
        for word in ("2160p", "uhd", "2160"):
            self.assertIn(word, forms)

    def test_codec_synonyms(self):
        r = query.parse("xxx x265")
        self.assertIn("hevc", r["mods"][0]["forms"])

    def test_lang_synonyms(self):
        r = query.parse("xxx 中字")
        self.assertIn("chs", r["soft"][0]["forms"])

    def test_third_person_synonyms(self):
        r = query.parse("第三人称")
        forms = r["soft"][0]["forms"]
        for word in ("third person", "third-person", "tps"):
            self.assertIn(word, forms)


class NeedlesTest(unittest.TestCase):

    def test_browse_query_has_needles(self):
        got = query.needles(query.parse("电影"))
        self.assertEqual(got, ["电影", "影片", "movie", "film"],
                         "浏览型查询 subject 为空，只用 subject 判会漏掉整类查询")

    def test_subject_comes_first(self):
        got = query.needles(query.parse("流浪地球 中字"))
        self.assertEqual(got[0], "流浪地球")
        self.assertIn("中字", got)

    def test_quality_token_is_not_a_needle(self):
        got = query.needles(query.parse("沙丘 4K"))
        self.assertEqual(got, ["沙丘"],
                         "画质词不参与命中判定：源站只匹配到 2160p 不算用了关键词")

    def test_duplicates_are_dropped(self):
        got = query.needles(query.parse("电影 movie"))
        self.assertEqual(got.count("电影"), 1)
        self.assertEqual(got.count("movie"), 1)

    def test_all_lowercase(self):
        for n in query.needles(query.parse("流浪地球 MOVIE 中字")):
            self.assertEqual(n, n.lower())

    def test_junk_input_is_empty(self):
        for bad in (None, "", {}, [], 0):
            with self.subTest(bad=bad):
                self.assertEqual(query.needles(bad), [])

    def test_missing_groups_are_tolerated(self):
        self.assertEqual(query.needles({"subject": ["a"], "soft": [None, 7]}), ["a"])

    def test_backend_fuzzy_uses_them(self):
        src = (ROOT / "app" / "api.py").read_text(encoding="utf-8")
        self.assertIn("needs = query.needles(parsed)", src,
                      "api 必须用 needles 判定，只看 subject 就是本次修的漏洞")
        self.assertNotIn("bool(items) and subject and", src,
                         "旧写法对浏览型查询恒不成立")


class ContractTest(unittest.TestCase):

    def test_parse_returns_expected_keys(self):
        r = query.parse("anything")
        for key in ("text", "tokens", "subject", "mods", "soft"):
            self.assertIn(key, r)
        for gone in ("raw", "bigrams", "season", "year", "browse"):
            self.assertNotIn(gone, r,
                             f"载荷已瘦身，query.{gone} 不应再出现")

    def test_empty_query(self):
        r = query.parse("")
        self.assertEqual(r["subject"], [])
        self.assertEqual(r["mods"], [])

    def test_none_query(self):
        r = query.parse(None)
        self.assertEqual(r["text"], "")


if __name__ == "__main__":
    unittest.main()
