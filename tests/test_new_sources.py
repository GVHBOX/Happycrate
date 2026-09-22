import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config, sources


def adult_row(i, h=None):
    row_i = i if i else 1
    return {
        "id": str(80000000 + row_i),
        "name": f"Adult Release {row_i} XXX 1080p",
        "info_hash": (h or f"{row_i:040x}"),
        "leechers": str(row_i),
        "seeders": str(1000 - row_i),
        "num_files": "1",
        "size": str(1073741824 * (row_i + 1)),
        "added": str(1789379266 + row_i),
        "category": "505",
    }


def knaben_hit(i, h="auto", **over):
    row_i = i if i else 1
    if h == "auto":
        h = f"{row_i:040x}"
    hit = {
        "bytes": 1073741824 * (row_i + 1),
        "category": "Movies",
        "categoryId": [2000000],
        "date": "2026-09-20T12:00:00+00:00",
        "grabs": 10 + row_i,
        "hash": h,
        "id": f"{row_i:040x}",
        "lastSeen": "2026-09-22T12:00:00+00:00",
        "magnetUrl": f"magnet:?xt=urn:btih:{row_i:040x}",
        "peers": row_i,
        "seeders": 500 - row_i,
        "title": f"Knaben Result {row_i} 1080p",
        "tracker": "The Pirate Bay",
    }
    hit.update(over)
    return hit


def knaben_payload(hits):
    return json.dumps({"hits": hits, "max_score": 1.0,
                       "total": {"relation": "eq", "value": len(hits)}})


class ApibayAdultTest(unittest.TestCase):

    def test_request_carries_the_adult_category(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            return json.dumps([adult_row(1)])

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_apibay_adult("demo", 1, timeout=5)

        self.assertEqual(len(items), 1)
        self.assertIn(f"cat={sources.APIBAY_CAT_PORN}", seen[0],
                      "成人源必须带上分类参数，否则拿到的是全站混排结果")
        self.assertEqual(sources.APIBAY_CAT_PORN, 500)

    def test_plain_apibay_does_not_send_a_category(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            return json.dumps([adult_row(1)])

        with mock.patch.object(sources, "http_get", fake_get):
            sources._search_apibay("demo", 1, timeout=5)

        self.assertNotIn("cat=", seen[0],
                         "普通海盗湾源不该带分类，那会改变它的结果集")

    def test_items_tag_the_adult_source_key(self):
        with mock.patch.object(sources, "http_get",
                               lambda url, **kw: json.dumps([adult_row(3)])):
            items = sources._search_apibay_adult("demo", 1, timeout=5)
        self.assertEqual(items[0]["source"], "apibay_adult",
                         "来源标识要能和普通海盗湾区分开")
        self.assertTrue(items[0]["magnet"].startswith("magnet:?xt=urn:btih:"))

    def test_empty_sentinel_row_is_dropped(self):
        sentinel = json.dumps([{
            "id": "0", "name": "No results returned",
            "info_hash": "0" * 40, "leechers": "0", "seeders": "0",
            "size": "0", "added": "0", "category": "0",
        }])
        with mock.patch.object(sources, "http_get", lambda url, **kw: sentinel):
            items = sources._search_apibay_adult("nothing", 1, timeout=5)
        self.assertEqual(items, [],
                         "空结果是哨兵行，不能当成一条真结果展示")

    def test_rows_without_a_valid_hash_are_skipped(self):
        rows = [
            adult_row(1),
            {"name": "no hash at all", "info_hash": "", "seeders": "1",
             "leechers": "0", "size": "10", "added": "1", "category": "505"},
            {"name": "short hash", "info_hash": "abc", "seeders": "1",
             "leechers": "0", "size": "10", "added": "1", "category": "505"},
        ]
        with mock.patch.object(sources, "http_get",
                               lambda url, **kw: json.dumps(rows)):
            items = sources._search_apibay_adult("demo", 1, timeout=5)
        self.assertEqual(len(items), 1, "哈希不合格的行必须丢掉")

    def test_network_error_propagates(self):
        def boom(url, **kw):
            raise urllib.error.HTTPError(url, 500, "boom", {}, None)

        with mock.patch.object(sources, "http_get", boom):
            with self.assertRaises(urllib.error.HTTPError):
                sources._search_apibay_adult("demo", 1, timeout=5)

    def test_relevance_guard_is_not_applied_to_the_adult_source(self):
        rows = [adult_row(i) for i in range(1, 4)]
        with mock.patch.object(sources, "http_get",
                               lambda url, **kw: json.dumps(rows)):
            items = sources._search_apibay_adult("完全无关的词", 1, timeout=5)
        self.assertEqual(len(items), 3,
                         "成人词表与通用词表不同，不该套用通用相关性判断丢弃结果")

    def test_shared_row_parser_is_reused(self):
        src = (ROOT / "app" / "sources.py").read_text(encoding="utf-8")
        self.assertIn("def _apibay_rows", src)
        self.assertEqual(src.count("def _apibay_rows"), 1,
                         "两个海盗湾源必须共用同一个行解析器，避免规则漂移")


class KnabenRequestTest(unittest.TestCase):

    def test_posts_the_documented_query_field(self):
        seen = {}

        def fake_get(url, **kw):
            seen["url"] = url
            seen["data"] = kw.get("data")
            seen["headers"] = kw.get("headers") or {}
            return knaben_payload([knaben_hit(1)])

        with mock.patch.object(sources, "http_get", fake_get):
            sources._search_knaben("ubuntu", 1, timeout=5)

        body = json.loads(seen["data"].decode("utf-8"))
        self.assertIn("query", body,
                      "knaben 只认 query 字段；写成 search_query 会静默返回"
                      "与关键词无关的榜单结果")
        self.assertNotIn("search_query", body)
        self.assertIn("application/json",
                      str(seen["headers"].get("Content-Type", "")).lower())

    def test_orders_by_seeders(self):
        seen = {}

        def fake_get(url, **kw):
            seen["body"] = json.loads(kw["data"].decode("utf-8"))
            return knaben_payload([knaben_hit(1)])

        with mock.patch.object(sources, "http_get", fake_get):
            sources._search_knaben("ubuntu", 1, timeout=5)

        self.assertEqual(seen["body"]["order_by"], "seeders")
        self.assertEqual(seen["body"]["order_by"],
                         sources.KNABEN_ORDER)

    def test_offset_uses_from_not_page(self):
        seen = {}

        def fake_get(url, **kw):
            seen["body"] = json.loads(kw["data"].decode("utf-8"))
            return knaben_payload([knaben_hit(1)])

        with mock.patch.object(sources, "http_get", fake_get):
            sources._search_knaben("ubuntu", 3, timeout=5)

        self.assertIn("from", seen["body"],
                      "knaben 的偏移量参数是 from；page/offset 会被忽略并"
                      "重复返回第一页")
        self.assertNotIn("page", seen["body"])
        self.assertEqual(seen["body"]["from"],
                         (3 - 1) * sources.KNABEN_PAGE_SIZE)

    def test_first_page_offsets_to_zero(self):
        seen = {}

        def fake_get(url, **kw):
            seen["body"] = json.loads(kw["data"].decode("utf-8"))
            return knaben_payload([knaben_hit(1)])

        with mock.patch.object(sources, "http_get", fake_get):
            sources._search_knaben("ubuntu", 1, timeout=5)
        self.assertEqual(seen["body"]["from"], 0)

    def test_requests_a_full_page_size(self):
        seen = {}

        def fake_get(url, **kw):
            seen["body"] = json.loads(kw["data"].decode("utf-8"))
            return knaben_payload([knaben_hit(1)])

        with mock.patch.object(sources, "http_get", fake_get):
            sources._search_knaben("ubuntu", 1, timeout=5)
        self.assertEqual(seen["body"]["size"], sources.KNABEN_PAGE_SIZE)
        self.assertEqual(sources.KNABEN_PAGE_SIZE, 100)


class KnabenParseTest(unittest.TestCase):

    def test_maps_documented_fields(self):
        hit = knaben_hit(2, seeders=321, peers=45, bytes=987654321)
        with mock.patch.object(sources, "http_get",
                               lambda url, **kw: knaben_payload([hit])):
            items = sources._search_knaben("demo", 1, timeout=5)

        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["title"], hit["title"])
        self.assertEqual(it["info_hash"], hit["hash"].lower())
        self.assertEqual(it["size"], 987654321)
        self.assertEqual(it["seeders"], 321)
        self.assertEqual(it["leechers"], 45,
                         "knaben 的 peers 字段就是做种以外的连接数")
        self.assertEqual(it["source"], "knaben")
        self.assertIsNotNone(it["added"])
        self.assertTrue(it["magnet"].startswith("magnet:?xt=urn:btih:"))

    def test_uppercase_hashes_are_lowercased(self):
        hit = knaben_hit(1, h="AB" * 20)
        with mock.patch.object(sources, "http_get",
                               lambda url, **kw: knaben_payload([hit])):
            items = sources._search_knaben("demo", 1, timeout=5)
        self.assertEqual(items[0]["info_hash"], "ab" * 20)

    def test_hits_without_a_usable_hash_are_skipped(self):
        hits = [
            knaben_hit(1),
            knaben_hit(2, h=None),
            knaben_hit(3, h=""),
            knaben_hit(4, h="xyz"),
        ]
        with mock.patch.object(sources, "http_get",
                               lambda url, **kw: knaben_payload(hits)):
            items = sources._search_knaben("demo", 1, timeout=5)
        self.assertEqual(len(items), 1,
                         "没有哈希的条目无法构成磁力，必须丢掉"
                         "（knaben 实测约 6% 的条目 hash 为 null）")

    def test_duplicate_hashes_collapse(self):
        hits = [knaben_hit(1, h="aa" * 20), knaben_hit(2, h="aa" * 20)]
        with mock.patch.object(sources, "http_get",
                               lambda url, **kw: knaben_payload(hits)):
            items = sources._search_knaben("demo", 1, timeout=5)
        self.assertEqual(len(items), 1)

    def test_result_count_is_capped(self):
        hits = [knaben_hit(i) for i in range(sources.KNABEN_MAX_HITS + 40)]
        with mock.patch.object(sources, "http_get",
                               lambda url, **kw: knaben_payload(hits)):
            items = sources._search_knaben("demo", 1, timeout=5)
        self.assertEqual(len(items), sources.KNABEN_MAX_HITS)

    def test_empty_hits_is_not_an_error(self):
        with mock.patch.object(sources, "http_get",
                               lambda url, **kw: knaben_payload([])):
            items = sources._search_knaben("nothing", 1, timeout=5)
        self.assertEqual(items, [])

    def test_missing_hits_key_raises_shape_error(self):
        payload = json.dumps({"total": {"relation": "eq", "value": 0}})
        with mock.patch.object(sources, "http_get",
                               lambda url, **kw: payload):
            with self.assertRaises(sources.ShapeError):
                sources._search_knaben("demo", 1, timeout=5)

    def test_non_object_payload_raises_shape_error(self):
        with mock.patch.object(sources, "http_get",
                               lambda url, **kw: json.dumps(["not", "an", "object"])):
            with self.assertRaises(sources.ShapeError):
                sources._search_knaben("demo", 1, timeout=5)

    def test_shape_error_maps_to_the_structure_outcome(self):
        from app import api
        outcome, _code = api.classify(False, 0, "ShapeError: knaben 响应缺少 hits 列表")
        self.assertEqual(outcome, api.OUTCOME_SHAPE,
                         "结构不符要报成结构问题，而不是笼统的请求失败")

    def test_network_error_propagates(self):
        def boom(url, **kw):
            raise urllib.error.HTTPError(url, 429, "limited", {}, None)

        with mock.patch.object(sources, "http_get", boom):
            with self.assertRaises(urllib.error.HTTPError):
                sources._search_knaben("demo", 1, timeout=5)


class NewSourceRegistrationTest(unittest.TestCase):

    def test_both_keys_are_builtin(self):
        self.assertIn("apibay_adult", sources.BUILTIN_KEYS)
        self.assertIn("knaben", sources.BUILTIN_KEYS)

    def test_both_have_default_bases(self):
        self.assertEqual(sources.DEFAULT_BASES["apibay_adult"],
                         "https://apibay.org")
        self.assertEqual(sources.DEFAULT_BASES["knaben"],
                         "https://api.knaben.org/v1")

    def test_adult_shares_the_apibay_host(self):
        self.assertEqual(sources.DEFAULT_BASES["apibay_adult"],
                         sources.DEFAULT_BASES["apibay"],
                         "两个源同站不同分类，地址必须一致")

    def test_adult_is_pageless_and_knaben_is_not(self):
        self.assertIn("apibay_adult", sources.PAGELESS_KEYS,
                      "官方接口不收页码参数")
        self.assertNotIn("knaben", sources.PAGELESS_KEYS,
                         "knaben 支持通过 from 翻页")

    def test_labels_match_config(self):
        want = {s["key"]: s["label"] for s in config.DEFAULT_SOURCES}
        for key in ("apibay_adult", "knaben"):
            with self.subTest(key=key):
                self.assertEqual(sources._BUILTIN_ADAPTERS[key][0], want[key])

    def test_builtin_labels_are_clean_of_guidance(self):
        for key in ("apibay_adult", "knaben"):
            with self.subTest(key=key):
                label = sources._BUILTIN_ADAPTERS[key][0]
                self.assertLessEqual(len(label), 6,
                                     "源名是字段名，不是一句说明")

    def test_adapter_names_track_the_functions(self):
        self.assertEqual(sources.BUILTIN_ADAPTER_NAMES["apibay_adult"],
                         "_search_apibay_adult")
        self.assertEqual(sources.BUILTIN_ADAPTER_NAMES["knaben"],
                         "_search_knaben")

    def test_base_override_is_honoured(self):
        self.assertEqual(sources.base_of("knaben", "https://mirror.example"),
                         "https://mirror.example")
        self.assertEqual(sources.base_of("apibay_adult", ""),
                         "https://apibay.org")

    def test_new_sources_reach_the_existing_config_file(self):
        from app import config as cfgmod
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            old = {"version": 1, "sources": [
                {"key": "nyaa", "label": "Nyaa", "type": "builtin",
                 "enabled": True, "timeout": 15, "base": "", "order": 0},
            ]}
            path.write_text(json.dumps(old), encoding="utf-8")
            cfg = cfgmod.Config(str(path)).load()
            keys = cfg.all_keys()
            self.assertIn("apibay_adult", keys,
                          "老配置启动时要自动补上新增的内置源")
            self.assertIn("knaben", keys)


class NewSourceParityTest(unittest.TestCase):

    def test_frontend_adapter_map_lists_both(self):
        js = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        block = js.split("function adapterName(key){", 1)[1].split("}", 1)[0]
        self.assertIn("apibay_adult", block)
        self.assertIn("knaben", block)

    def test_frontend_mock_lists_both_sources(self):
        js = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        head = js.split("var MOCK = [", 1)[1].split("];", 1)[0]
        self.assertIn('key:"apibay_adult"', head,
                      "浏览器直开时源列表要和后端一致")
        self.assertIn('key:"knaben"', head)

    def test_adult_label_is_not_explicit_vulgar(self):
        label = sources._BUILTIN_ADAPTERS["apibay_adult"][0]
        self.assertIn("成人", label)


if __name__ == "__main__":
    unittest.main()
