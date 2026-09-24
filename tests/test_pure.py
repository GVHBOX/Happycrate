import sys
import unittest
from pathlib import Path
from unittest import mock

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

    def test_keeps_poorer_side_extra_fields(self):
        rich = {"info_hash": "e" * 40, "title": "x" * 20, "size": 1024,
                "seeders": 5, "added": 111, "source": "nyaa"}
        poor = {"info_hash": "e" * 40, "title": "short", "source": "xccl263",
                "files": [{"n": "a.mp4", "s": "1 MB"}],
                "fetch": {"url": "https://x/a.torrent"}}
        for order in ([rich, poor], [poor, rich]):
            out = core.dedupe([dict(i) for i in order])
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["files"], [{"n": "a.mp4", "s": "1 MB"}])
            self.assertEqual(out[0]["fetch"], {"url": "https://x/a.torrent"})
            self.assertIn("nyaa", out[0]["sources"])
            self.assertIn("xccl263", out[0]["sources"])

    def test_fills_empty_field_from_other_side(self):
        dense = {"info_hash": "f" * 40, "title": "x" * 20, "seeders": 5,
                 "added": 10, "size": 0, "source": "nyaa"}
        sparse = {"info_hash": "f" * 40, "title": "y", "size": 2048,
                  "source": "dmhy"}
        out = core.dedupe([dense, sparse])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["size"], 2048)

    def test_richer_side_wins_on_conflict(self):
        rich = {"info_hash": "1" * 40, "title": "长标题占位内容足够长", "size": 4096,
                "seeders": 99, "added": 100, "source": "nyaa"}
        poor = {"info_hash": "1" * 40, "title": "短", "size": 8,
                "seeders": 1, "source": "dmhy"}
        out = core.dedupe([poor, rich])
        self.assertEqual(out[0]["size"], 4096)
        self.assertEqual(out[0]["seeders"], 99)
        self.assertEqual(out[0]["title"], "长标题占位内容足够长")

    def test_seeders_take_observed_max(self):
        low = {"info_hash": "2" * 40, "title": "a", "seeders": 3, "source": "nyaa"}
        high = {"info_hash": "2" * 40, "title": "b", "seeders": 41, "source": "dmhy"}
        for order in ([low, high], [high, low]):
            out = core.dedupe([dict(i) for i in order])
            self.assertEqual(out[0]["seeders"], 41)
            self.assertEqual(out[0]["leechers"], None)

    def test_unknown_seeders_stay_unknown(self):
        items = [
            {"info_hash": "3" * 40, "title": "a", "seeders": None, "source": "mikan"},
            {"info_hash": "3" * 40, "title": "b", "seeders": 7, "source": "nyaa"},
        ]
        out = core.dedupe(items)
        self.assertEqual(out[0]["seeders"], 7)

        items = [
            {"info_hash": "4" * 40, "title": "a", "seeders": 0, "source": "nyaa"},
            {"info_hash": "4" * 40, "title": "b", "seeders": None, "source": "mikan"},
        ]
        out = core.dedupe(items)
        self.assertEqual(out[0]["seeders"], 0)

    def test_added_takes_earliest(self):
        late = {"info_hash": "5" * 40, "title": "a", "added": 900, "source": "nyaa"}
        early = {"info_hash": "5" * 40, "title": "b", "added": 400, "source": "dmhy"}
        out = core.dedupe([late, early])
        self.assertEqual(out[0]["added"], 400)

    def test_alt_titles_keep_every_side(self):
        items = [
            {"info_hash": "6" * 40, "title": "Ubuntu 简繁字幕", "source": "poor"},
            {"info_hash": "6" * 40, "title": "Ubuntu 1080p WEB-DL", "source": "rich"},
        ]
        out = core.dedupe(items)
        self.assertEqual(out[0]["title"], "Ubuntu 1080p WEB-DL")
        self.assertIn("Ubuntu 简繁字幕", out[0]["altTitles"])
        self.assertIn("Ubuntu 1080p WEB-DL", out[0]["altTitles"])

    def test_alt_titles_dedup_and_cap(self):
        items = [{"info_hash": "7" * 40, "title": "same", "source": "s%d" % i}
                 for i in range(20)]
        items += [{"info_hash": "7" * 40, "title": "other", "source": "z"}]
        out = core.dedupe(items)
        self.assertEqual(out[0]["altTitles"], ["same", "other"])

        many = [{"info_hash": "8" * 40, "title": "t%d" % i, "source": "s%d" % i}
                for i in range(20)]
        out = core.dedupe(many)
        self.assertEqual(len(out[0]["altTitles"]), core._MAX_ALT_TITLES)

    def test_merge_does_not_overwrite_with_later_side(self):
        first = {"info_hash": "9" * 40, "title": "a", "size": 500,
                 "files": [{"n": "a.mp4", "s": "1 MB"}], "source": "nyaa"}
        second = {"info_hash": "9" * 40, "title": "b", "size": 100, "source": "dmhy"}
        out = core.dedupe([first, second])
        self.assertEqual(out[0]["size"], 500)
        self.assertEqual(out[0]["files"], [{"n": "a.mp4", "s": "1 MB"}])


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


class ProbePortTest(unittest.TestCase):

    def probe_with(self, addr):
        seen = []

        class FakeSock:
            def __init__(self):
                pass

            def settimeout(self, t):
                pass

            def connect_ex(self, addr):
                seen.append(addr)
                return 0

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(sources.socket, "socket", FakeSock):
            ok = sources._probe_port(addr)
        return ok, seen

    def test_omitted_port_falls_back_to_scheme_default(self):
        ok, seen = self.probe_with("http://proxy.lan")
        self.assertTrue(ok)
        self.assertEqual(seen, [("proxy.lan", 80)],
                         "代理地址省略端口时按协议默认端口探测，而不是直接报不可用")

    def test_https_defaults_to_443(self):
        ok, seen = self.probe_with("https://proxy.lan")
        self.assertTrue(ok)
        self.assertEqual(seen, [("proxy.lan", 443)])


class SingleInstanceTest(unittest.TestCase):

    def test_mutex_is_session_local(self):
        from app import single
        self.assertTrue(single.MUTEX_NAME.startswith("Local\\"),
                        "Global 互斥会跨用户会话拦人，别的会话双击会无提示退出")


class EztvApiTest(unittest.TestCase):

    def run_pages(self, payload):
        import json
        calls = []

        def fake_get(url, **kwargs):
            page = int(str(url).rsplit("page=", 1)[-1])
            calls.append(page)
            return json.dumps(payload.get(page, {"torrents": []}))

        from unittest import mock
        with mock.patch.object(sources, "http_get", fake_get):
            return sources._search_eztv("123", timeout=5), calls

    def test_matches_title_keyword_only(self):
        payload = {1: {"torrents": [
            {"title": "Foo 123 Bar", "hash": "a" * 40, "seeds": 3, "peers": 1,
             "size_bytes": "1024", "date_released_unix": 1700000000},
            {"title": "Nothing relevant", "hash": "b" * 40},
        ]}}
        items, _calls = self.run_pages(payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["info_hash"], "a" * 40)
        self.assertEqual(items[0]["title"], "Foo 123 Bar")

    def test_stops_when_page_not_full(self):
        payload = {1: {"torrents": [{"title": "123", "hash": "c" * 40}]}}
        _items, calls = self.run_pages(payload)
        self.assertEqual(calls, [1], "页没满就说明到底了，不该继续翻")

    def test_dedups_by_hash_across_pages(self):
        row = {"title": "123 dup", "hash": "d" * 40}
        payload = {1: {"torrents": [row] * 100},
                   2: {"torrents": [row] * 3}}
        items, _calls = self.run_pages(payload)
        self.assertEqual(len(items), 1)

    def test_cap_holds_across_pages(self):
        payload = {p: {"torrents": [
            {"title": f"123 p{p} n{n}", "hash": f"{p:02d}{n:038x}"}
            for n in range(100)]} for p in range(1, 6)}
        items, _calls = self.run_pages(payload)
        self.assertEqual(len(items), sources.EZTV_MAX_HITS,
                         "上限截断必须同时跳出内外两层循环，不能让后续页继续追加")

    def test_non_json_returns_empty_without_raising(self):
        from unittest import mock
        with mock.patch.object(sources, "http_get", lambda url, **kw: "<html>nope</html>"):
            self.assertEqual(sources._search_eztv("123", timeout=5), [])

    def test_empty_query_short_circuits(self):
        self.assertEqual(sources._search_eztv("", timeout=1), [])
        self.assertEqual(sources._search_eztv("   ", timeout=1), [])

    def test_page_constants_within_api_limits(self):
        self.assertLessEqual(sources.EZTV_PAGE_SIZE, 100,
                             "官方文档：limit 上限 100")
        self.assertLessEqual(sources.EZTV_PAGES, 100,
                             "官方文档：page 上限 100")


TORRENT_PAGE_URL = "https://mikanani.me/Home/Episode/xyz"


class TorrentMetaLinkTest(unittest.TestCase):

    def calls_for(self, page):
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            if url == TORRENT_PAGE_URL:
                return page
            return b"not bencode"

        with mock.patch.object(sources, "http_get", side_effect=fake_get):
            sources.torrent_meta(TORRENT_PAGE_URL)
        return calls

    def test_root_relative_download_link_resolved(self):
        calls = self.calls_for(b'<a href="/Download/202301/x.torrent">dl</a>')
        self.assertEqual(calls[-1], "https://mikanani.me/Download/202301/x.torrent",
                         "mikan 的下载链是根相对路径，认不出就永远拿不到文件清单")

    def test_protocol_relative_link_kept(self):
        calls = self.calls_for(b'<a href="//mirror.example.org/x.torrent">dl</a>')
        self.assertEqual(calls[-1], "https://mirror.example.org/x.torrent")

    def test_absolute_link_kept(self):
        calls = self.calls_for(b'<a href="https://share.dmhy.org/download/x.torrent">dl</a>')
        self.assertEqual(calls[-1], "https://share.dmhy.org/download/x.torrent")

    def test_no_link_makes_single_request(self):
        calls = self.calls_for(b"<html><body>empty</body></html>")
        self.assertEqual(len(calls), 1)


class SettingsTwoPhaseTest(unittest.TestCase):

    def test_partial_rejection_applies_nothing(self):
        s = config.Settings()
        before = dict(s.data)
        rejected = s.update(timeout=9999, retries=2)
        self.assertTrue(rejected)
        self.assertEqual(s.data["retries"], before["retries"],
                         "两个字段一好一坏时，好字段也不能进内存——"
                         "否则之后任意一次保存都会把被拒绝的修改带进盘")
        self.assertEqual(s.data["timeout"], before["timeout"])

    def test_all_valid_applies_everything(self):
        s = config.Settings()
        rejected = s.update(timeout=30, retries=2)
        self.assertEqual(rejected, [])
        self.assertEqual(s.data["timeout"], 30)
        self.assertEqual(s.data["retries"], 2)

    def test_unknown_key_is_rejected(self):
        s = config.Settings()
        self.assertEqual(len(s.update(no_such_key=1)), 1)


if __name__ == "__main__":
    unittest.main()
