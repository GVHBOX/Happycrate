import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import sources


def mikan_rss_xml(rows):
    items = []
    for h, title, size, pub in rows:
        items.append(
            f"<item><title>{title}</title>"
            f"<link>https://mikanani.me/Home/Episode/{h}</link>"
            f"<contentLength>{size}</contentLength>"
            f"<pubDate>{pub}</pubDate></item>")
    return ("<?xml version=\"1.0\"?><rss version=\"2.0\"><channel>"
            + "".join(items) + "</channel></rss>")


def dmhy_rss_xml(rows):
    items = []
    for h, title, size, pub, guid in rows:
        items.append(
            f"<item><title>{title}</title>"
            f"<enclosure url=\"magnet:?xt=urn:btih:{h}\" "
            f"length=\"1\" type=\"application/x-bittorrent\"/>"
            f"<contentLength>{size}</contentLength>"
            f"<guid>{guid}</guid>"
            f"<pubDate>{pub}</pubDate></item>")
    return ("<?xml version=\"1.0\"?><rss version=\"2.0\"><channel>"
            + "".join(items) + "</channel></rss>")


class MikanRssTest(unittest.TestCase):

    def _run(self, xml):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            return xml

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_mikan_rss("秘密", 5, "https://mikanani.me", None)
        return seen, items

    def test_request_carries_the_query(self):
        seen, _items = self._run(mikan_rss_xml([]))
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].startswith("https://mikanani.me/RSS/Search?searchstr="))
        self.assertIn("%E7%A7%98%E5%AF%86", seen[0])

    def test_reads_hash_title_size_and_date(self):
        h = "a" * 40
        _seen, items = self._run(mikan_rss_xml(
            [(h, "[VCB] 番组 01", "1.5 GiB", "2026-09-20 06:16")]))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["info_hash"], h)
        self.assertEqual(items[0]["title"], "[VCB] 番组 01")
        self.assertEqual(items[0]["size"], int(1.5 * 1024 ** 3))
        self.assertEqual(items[0]["source"], "mikan")
        self.assertIsNotNone(items[0]["added"])

    def test_iso_pubdate_is_accepted(self):
        h = "b" * 40
        _seen, items = self._run(mikan_rss_xml(
            [(h, "番组", "1.0 GiB", "2026-09-20T06:16:00")]))
        self.assertEqual(len(items), 1)
        self.assertIsNotNone(items[0]["added"])

    def test_items_without_hash_are_skipped(self):
        xml = ("<?xml version=\"1.0\"?><rss version=\"2.0\"><channel>"
               "<item><title>没有种子的条目</title>"
               "<link>https://mikanani.me/Home/Bangumi/1</link>"
               "<pubDate>2026-09-20 06:16</pubDate></item></channel></rss>")
        _seen, items = self._run(xml)
        self.assertEqual(items, [])

    def test_hash_is_taken_from_the_episode_link(self):
        h = "c" * 40
        xml = ("<?xml version=\"1.0\"?><rss version=\"2.0\"><channel><item>"
               "<title>只有链接里有 hash</title>"
               f"<description>https://mikanani.me/Home/Episode/{h}</description>"
               "<pubDate>2026-09-20 06:16</pubDate></item></channel></rss>")
        _seen, items = self._run(xml)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["info_hash"], h)


class DmhyRssTest(unittest.TestCase):

    def _run(self, xml):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            return xml

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_dmhy_rss("秘密", 5, "https://share.dmhy.org", None)
        return seen, items

    def test_request_carries_the_keyword(self):
        seen, _items = self._run(dmhy_rss_xml([]))
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].startswith(
            "https://share.dmhy.org/topics/rss/rss.xml?keyword="))
        self.assertIn("%E7%A7%98%E5%AF%86", seen[0])

    def test_reads_hash_size_and_fetch_link(self):
        h = "d" * 40
        _seen, items = self._run(dmhy_rss_xml([(
            h, "[字幕组] 番组 01", "800 MiB",
            "Sat, 20 Sep 2026 06:16:00 +0800",
            "https://share.dmhy.org/topics/view/1.html")]))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["info_hash"], h)
        self.assertEqual(items[0]["title"], "[字幕组] 番组 01")
        self.assertEqual(items[0]["size"], int(800 * 1024 ** 2))
        self.assertEqual(items[0]["source"], "dmhy")
        self.assertEqual(items[0]["fetch"]["url"],
                         "https://share.dmhy.org/topics/view/1.html")
        self.assertIsNotNone(items[0]["added"])

    def test_size_falls_back_to_the_title(self):
        h = "e" * 40
        _seen, items = self._run(dmhy_rss_xml([(
            h, "[字幕组] 番组 [720P][2.4GB]", "",
            "Sat, 20 Sep 2026 06:16:00 +0800", "not-a-url")]))
        self.assertEqual(len(items), 1)
        self.assertGreater(items[0]["size"], 0)
        self.assertNotIn("fetch", items[0])

    def test_items_without_hash_are_skipped(self):
        xml = ("<?xml version=\"1.0\"?><rss version=\"2.0\"><channel>"
               "<item><title>没有种子的条目</title>"
               "<guid>https://share.dmhy.org/topics/view/2.html</guid>"
               "<pubDate>Sat, 20 Sep 2026 06:16:00 +0800</pubDate>"
               "</item></channel></rss>")
        _seen, items = self._run(xml)
        self.assertEqual(items, [])
