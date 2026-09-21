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


class BigramsTest(unittest.TestCase):

    def test_splits_cjk(self):
        self.assertEqual(query.bigrams("流浪地球"), ["流浪", "浪地", "地球"])

    def test_single_char(self):
        self.assertEqual(query.bigrams("片"), ["片"])

    def test_dedupes(self):
        self.assertEqual(query.bigrams("球球球"), ["球球"])


class RoleTest(unittest.TestCase):

    def test_browse_query_has_no_subject(self):
        r = query.parse("电影 4K")
        self.assertEqual(r["subject"], [])
        self.assertTrue(r["browse"])
        self.assertEqual([m["role"] for m in r["mods"]], ["QUALITY"])
        self.assertIn("2160p", r["mods"][0]["forms"])

    def test_browse_query_with_genre_only(self):
        r = query.parse("射击游戏 3D 第三人称")
        self.assertEqual(r["subject"], [])
        self.assertTrue(r["browse"])

    def test_subject_is_separated(self):
        r = query.parse("流浪地球 2160p 中字")
        self.assertEqual(r["subject"], ["流浪地球"])
        self.assertFalse(r["browse"])
        self.assertEqual([m["role"] for m in r["mods"]], ["QUALITY"])
        self.assertEqual([s["kind"] for s in r["soft"]], ["LANG"])

    def test_season_is_exact(self):
        r = query.parse("进击的巨人 第12话")
        self.assertEqual(r["season"], {"s": 0, "e": 12})
        self.assertEqual(r["subject"], ["进击的巨人"])

    def test_season_episode_pair(self):
        r = query.parse("沙丘 2024 S01E05")
        self.assertEqual(r["season"], {"s": 1, "e": 5})
        self.assertEqual(r["year"], 2024)
        self.assertEqual(r["subject"], ["沙丘"])

    def test_season_does_not_swallow_compound_token(self):
        r = query.parse("沙丘.S01E05")
        self.assertIsNone(r["season"])

    def test_year_is_soft_not_subject(self):
        r = query.parse("沙丘 2024")
        self.assertEqual(r["subject"], ["沙丘"])
        self.assertEqual(r["year"], 2024)

    def test_unknown_token_stays_subject(self):
        r = query.parse("阿凡达 4K")
        self.assertEqual(r["subject"], ["阿凡达"])
        self.assertFalse(r["browse"])


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


class ContractTest(unittest.TestCase):

    def test_parse_returns_expected_keys(self):
        r = query.parse("anything")
        for key in ("raw", "text", "subject", "bigrams", "mods", "soft",
                    "season", "year", "browse"):
            self.assertIn(key, r)

    def test_empty_query(self):
        r = query.parse("")
        self.assertEqual(r["subject"], [])
        self.assertTrue(r["browse"])
        self.assertEqual(r["bigrams"], [])

    def test_none_query(self):
        r = query.parse(None)
        self.assertEqual(r["text"], "")


if __name__ == "__main__":
    unittest.main()
