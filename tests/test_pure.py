import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config, core, sources


def bencode(obj) -> bytes:
    if isinstance(obj, bool):
        return b"i%de" % int(obj)
    if isinstance(obj, int):
        return b"i%de" % obj
    if isinstance(obj, str):
        obj = obj.encode()
    if isinstance(obj, bytes):
        return b"%d:%s" % (len(obj), obj)
    if isinstance(obj, (list, tuple)):
        return b"l" + b"".join(bencode(x) for x in obj) + b"e"
    if isinstance(obj, dict):
        return b"d" + b"".join(bencode(k) + bencode(v) for k, v in obj.items()) + b"e"
    raise TypeError(obj)


class TextCoerceTest(unittest.TestCase):

    def test_string_passthrough(self):
        self.assertEqual(sources._text("标题"), "标题")

    def test_numbers_become_text(self):
        self.assertEqual(sources._text(5), "5")
        self.assertEqual(sources._text(1.5), "1.5")

    def test_none_and_containers_become_empty(self):
        self.assertEqual(sources._text(None), "")
        self.assertEqual(sources._text({"a": 1}), "")
        self.assertEqual(sources._text([1]), "")

    def test_bool_does_not_become_python_literal(self):
        self.assertEqual(sources._text(True), "",
                         "JSON 里 title:true 不该渲染成 'True'")
        self.assertEqual(sources._text(False), "",
                         "JSON 里 title:false 不该渲染成 'False'")


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

    def _import_one(self, payload):
        import json
        import tempfile
        path = tempfile.mktemp(suffix=".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"sources": [payload]}, fh)
        self.cfg.import_from(path)
        return self.cfg.get(payload["key"])

    def test_builtin_timeout_clamped(self):
        src = self._import_one({"key": "nyaa", "type": "builtin", "timeout": 99999})
        self.assertEqual(src["timeout"], 120)

    def test_builtin_timeout_low_clamped(self):
        src = self._import_one({"key": "nyaa", "type": "builtin", "timeout": 0})
        self.assertEqual(src["timeout"], 1)

    def test_builtin_timeout_garbage_falls_back(self):
        src = self._import_one({"key": "nyaa", "type": "builtin", "timeout": "abc"})
        self.assertEqual(src["timeout"], 15)

    def test_custom_timeout_clamped(self):
        self.cfg.sources.append({"key": "myrss", "label": "M", "type": "rss",
                                 "base": "https://example.org/?q={query}",
                                 "timeout": 15, "order": 9})
        src = self._import_one({"key": "myrss", "timeout": 99999})
        self.assertEqual(src["timeout"], 120)

    def test_new_source_timeout_still_rejected(self):
        result = self._import_one({"key": "myrss", "label": "M", "type": "rss",
                                   "base": "https://example.org/?q={query}",
                                   "timeout": 99999})
        self.assertIsNone(result)


class TorrentDecodeTest(unittest.TestCase):

    def test_single_file(self):
        blob = bencode({"info": {"length": 1024, "name": "a.mp4"}})
        self.assertEqual(sources.decode_torrent_files(blob),
                         [{"n": "a.mp4", "b": 1024}])

    def test_multi_file_paths_joined(self):
        blob = bencode({"info": {"files": [
            {"length": 1, "path": ["a", "b"]},
            {"length": 2, "path": ["c"]},
        ]}})
        self.assertEqual(sources.decode_torrent_files(blob),
                         [{"n": "a/b", "b": 1}, {"n": "c", "b": 2}])

    def test_garbage_returns_empty(self):
        self.assertEqual(sources.decode_torrent_files(b"not bencode at all"), [])
        self.assertEqual(sources.decode_torrent_files(b""), [])

    def test_missing_info_returns_empty(self):
        self.assertEqual(sources.decode_torrent_files(bencode({"x": 1})), [])

    def test_deep_nesting_rejected_without_recursion_error(self):
        blob = b"d4:infod5:files" + b"l" * 4000 + b"e" * 4000 + b"ee"
        self.assertEqual(sources.decode_torrent_files(blob), [])

    def test_declared_length_beyond_buffer_rejected(self):
        blob = b"d4:infod6:lengthi1e4:name999999:" + b"abce"
        self.assertEqual(sources.decode_torrent_files(blob), [])

    def test_negative_length_rejected(self):
        blob = b"d4:infod6:lengthi1e4:namei-5e:abce" + b"e"
        self.assertEqual(sources.decode_torrent_files(blob), [])


class TorrentCapTest(unittest.TestCase):

    def test_read_capped_rejects_oversize(self):
        class Resp:
            def __init__(self, blob):
                self.blob = blob
                self.pos = 0

            def read(self, n=-1):
                if n is None or n < 0:
                    n = len(self.blob) - self.pos
                chunk = self.blob[self.pos:self.pos + n]
                self.pos += len(chunk)
                return chunk

        resp = Resp(b"x" * 1000)
        self.assertEqual(len(sources._read_capped(resp, 5000)), 1000)
        with self.assertRaises(sources.TooLarge):
            sources._read_capped(Resp(b"x" * 1000), 100)

    def test_read_capped_unlimited_passes_through(self):
        class Resp:
            def read(self, n=-1):
                return b"y" * 10

        self.assertEqual(sources._read_capped(Resp(), None), b"y" * 10)

    def test_cap_is_sane(self):
        self.assertLessEqual(sources.MAX_TORRENT_BYTES, 32 * 1024 * 1024,
                             "上限太大就失去了意义")


class SslLaxMemoryTest(unittest.TestCase):

    def setUp(self):
        sources.reset_ssl_lax()

    def tearDown(self):
        sources.reset_ssl_lax()

    def test_unknown_host_is_strict(self):
        self.assertFalse(sources.ssl_known_lax("https://example.org/a/b"))

    def test_recorded_host_is_lax(self):
        sources.ssl_mark_lax("https://example.org/a/b")
        self.assertTrue(sources.ssl_known_lax("https://example.org/a/b"))
        self.assertFalse(sources.ssl_known_lax("https://other.org/x"))

    def test_port_and_path_ignored(self):
        sources.ssl_mark_lax("https://example.org/a/b")
        self.assertTrue(sources.ssl_known_lax("https://example.org:8443/x?y=1"))

    def test_lax_hosts_sorted(self):
        sources.ssl_mark_lax("https://b.org/")
        sources.ssl_mark_lax("https://a.org/")
        self.assertEqual(sources.ssl_lax_hosts(), ["a.org", "b.org"])

    def test_reset_clears(self):
        sources.ssl_mark_lax("https://example.org/")
        sources.reset_ssl_lax()
        self.assertEqual(sources.ssl_lax_hosts(), [])

    def test_downgrade_expires(self):
        sources.ssl_mark_lax("https://example.org/")
        self.assertTrue(sources.ssl_known_lax("https://example.org/x"))
        sources._LAX_HOSTS["example.org"] = 0.0
        self.assertFalse(sources.ssl_known_lax("https://example.org/x"),
                         "降级必须有有效期，不能整个进程生命周期永久记忆")
        self.assertEqual(sources.ssl_lax_hosts(), [])

    def test_lax_hosts_capped(self):
        for i in range(sources._LAX_LIMIT + 10):
            sources.ssl_mark_lax(f"https://h{i}.org/")
        self.assertLessEqual(len(sources.ssl_lax_hosts()), sources._LAX_LIMIT)


if __name__ == "__main__":
    unittest.main()
