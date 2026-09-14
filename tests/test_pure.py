import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config, core, sources


class ParseSizeTest(unittest.TestCase):

    def test_gigabyte(self):
        self.assertEqual(sources.parse_size("1.5 GB"), 1610612736)

    def test_megabyte_without_space(self):
        self.assertEqual(sources.parse_size("500MB"), 524288000)

    def test_binary_unit(self):
        self.assertEqual(sources.parse_size("1 GiB"), 1073741824)

    def test_plain_bytes(self):
        self.assertEqual(sources.parse_size("2048 B"), 2048)

    def test_empty_string(self):
        self.assertEqual(sources.parse_size(""), 0)

    def test_none(self):
        self.assertEqual(sources.parse_size(None), 0)

    def test_numeric_passthrough(self):
        self.assertEqual(sources.parse_size(12345), 12345)

    def test_no_size_in_text(self):
        self.assertEqual(sources.parse_size("no size here"), 0)

    def test_negative_rejected(self):
        self.assertEqual(sources.parse_size("abc -12 MB"), 0)


class HashFromMagnetTest(unittest.TestCase):

    def test_hex_hash(self):
        magnet = "magnet:?xt=urn:btih:" + "a" * 40
        self.assertEqual(sources.hash_from_magnet(magnet), "a" * 40)

    def test_uppercase_normalized(self):
        magnet = "magnet:?xt=urn:btih:" + "A" * 40
        self.assertEqual(sources.hash_from_magnet(magnet), "a" * 40)

    def test_with_extra_params(self):
        magnet = "magnet:?xt=urn:btih:" + "b" * 40 + "&dn=name&tr=udp://t"
        self.assertEqual(sources.hash_from_magnet(magnet), "b" * 40)

    def test_plain_hash(self):
        self.assertEqual(sources.hash_from_magnet("c" * 40), "c" * 40)

    def test_empty(self):
        self.assertEqual(sources.hash_from_magnet(""), "")

    def test_garbage(self):
        self.assertEqual(sources.hash_from_magnet("not a magnet"), "")


class DecodeTorrentFilesTest(unittest.TestCase):

    def test_empty_bytes(self):
        self.assertEqual(sources.decode_torrent_files(b""), [])

    def test_garbage_does_not_raise(self):
        self.assertEqual(sources.decode_torrent_files(b"not a torrent"), [])

    def test_truncated_bencode(self):
        self.assertEqual(sources.decode_torrent_files(b"d8:announce"), [])


class ValidateSourceTest(unittest.TestCase):

    def test_empty_dict_rejected(self):
        self.assertTrue(config.validate_source({}))

    def test_builtin_unknown_key(self):
        errs = config.validate_source({"key": "ghost", "label": "G",
                                       "type": "builtin", "timeout": 15})
        self.assertTrue(any("未知内置源" in e for e in errs))

    def test_builtin_known_key(self):
        self.assertEqual(config.validate_source({"key": "nyaa", "label": "N",
                                                 "type": "builtin", "timeout": 15}), [])

    def test_builtin_bad_base(self):
        errs = config.validate_source({"key": "nyaa", "label": "N",
                                       "type": "builtin", "base": "ftp://x"})
        self.assertTrue(any("http" in e for e in errs))

    def test_custom_missing_query_placeholder(self):
        errs = config.validate_source({"key": "c1", "label": "C", "type": "json",
                                       "url": "https://a.example/s?p={page}"})
        self.assertTrue(any("{query}" in e for e in errs))

    def test_custom_unknown_placeholder(self):
        errs = config.validate_source({"key": "c1", "label": "C", "type": "json",
                                       "url": "https://a.example/s?q={query}&k={key}"})
        self.assertTrue(any("未知占位符" in e for e in errs))

    def test_json_without_list_path(self):
        errs = config.validate_source({"key": "c1", "label": "C", "type": "json",
                                       "url": "https://a.example/s?q={query}"})
        self.assertTrue(any("列表路径" in e for e in errs))

    def test_html_without_map_allowed(self):
        self.assertEqual(config.validate_source({
            "key": "c1", "label": "C", "type": "html",
            "url": "https://a.example/s?q={query}"}), [])

    def test_invalid_regex(self):
        errs = config.validate_source({"key": "c1", "label": "C", "type": "html",
                                       "url": "https://a.example/s?q={query}",
                                       "hash_pattern": "([unclosed"})
        self.assertTrue(any("正则无效" in e for e in errs))

    def test_bad_timeout(self):
        errs = config.validate_source({"key": "nyaa", "label": "N",
                                       "type": "builtin", "timeout": 999})
        self.assertTrue(any("超时" in e for e in errs))


class DedupeTest(unittest.TestCase):

    def test_merges_same_hash(self):
        items = [
            {"info_hash": "a" * 40, "title": "same", "source": "nyaa"},
            {"info_hash": "a" * 40, "title": "same", "source": "apibay"},
        ]
        out = core.dedupe(items)
        self.assertEqual(len(out), 1)
        self.assertIn("nyaa", out[0]["sources"])
        self.assertIn("apibay", out[0]["sources"])

    def test_keeps_hashless_items(self):
        items = [{"title": "x"}, {"title": "y"}]
        self.assertEqual(len(core.dedupe(items)), 2)

    def test_preserves_first_seen_order(self):
        items = [
            {"info_hash": "b" * 40, "title": "first"},
            {"info_hash": "c" * 40, "title": "second"},
        ]
        self.assertEqual([i["title"] for i in core.dedupe(items)], ["first", "second"])

    def test_does_not_mutate_input(self):
        items = [{"info_hash": "d" * 40, "title": "t", "source": "nyaa"}]
        snapshot = [dict(i) for i in items]
        core.dedupe(items)
        self.assertEqual(items, snapshot)


class ImportFromTest(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.cfg = config.Config(path=tempfile.mktemp(suffix=".json"))
        self.cfg.load()

    def test_returns_four_tuple_on_bad_path(self):
        result = self.cfg.import_from("/nonexistent/path/xyz.json")
        self.assertEqual(len(result), 4)

    def test_returns_four_tuple_on_empty_list(self):
        import json
        import tempfile
        path = tempfile.mktemp(suffix=".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"sources": []}, fh)
        result = self.cfg.import_from(path)
        self.assertEqual(len(result), 4)

    def test_returns_four_tuple_on_success(self):
        import json
        import tempfile
        path = tempfile.mktemp(suffix=".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"sources": [{"key": "nyaa", "label": "N",
                                    "type": "builtin", "enabled": False}]}, fh)
        result = self.cfg.import_from(path)
        self.assertEqual(len(result), 4)


class SslLaxMemoryTest(unittest.TestCase):

    def setUp(self):
        sources.reset_ssl_lax()

    def tearDown(self):
        sources.reset_ssl_lax()

    def test_unknown_host_is_strict(self):
        self.assertFalse(sources.ssl_known_lax("https://example.org/a/b"))

    def test_recorded_host_is_lax(self):
        sources._LAX_HOSTS.add("example.org")
        self.assertTrue(sources.ssl_known_lax("https://example.org/a/b"))
        self.assertFalse(sources.ssl_known_lax("https://other.org/x"))

    def test_port_and_path_ignored(self):
        sources._LAX_HOSTS.add("example.org")
        self.assertTrue(sources.ssl_known_lax("https://example.org:8443/x?y=1"))

    def test_lax_hosts_sorted(self):
        sources._LAX_HOSTS.update(["b.org", "a.org"])
        self.assertEqual(sources.ssl_lax_hosts(), ["a.org", "b.org"])

    def test_reset_clears(self):
        sources._LAX_HOSTS.add("example.org")
        sources.reset_ssl_lax()
        self.assertEqual(sources.ssl_lax_hosts(), [])


if __name__ == "__main__":
    unittest.main()
