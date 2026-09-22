import json
import re
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


class ApibayCategorySpanTest(unittest.TestCase):

    def test_first_request_is_uncategorised(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            return json.dumps([adult_row(1)])

        with mock.patch.object(sources, "http_get", fake_get):
            sources._search_apibay("demo", 1, timeout=5)
        self.assertNotIn("cat=", seen[0],
                         "先打一次不带分类的，用它判断关键词到底有没有命中")

    def test_relevant_query_also_pulls_every_category(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            n = len(seen)
            return json.dumps([adult_row(n), dict(adult_row(n), name="demo item")])

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_apibay("demo", 1, timeout=5)

        cats = sorted(int(m.group(1)) for m in
                      (re.search(r"cat=(\d+)", u) for u in seen) if m)
        self.assertEqual(cats, sorted(sources.APIBAY_CATS),
                         "关键词命中时要铺满所有顶层分类，否则单次 100 条上限"
                         "会把结果按分类切碎")
        self.assertEqual(len(sources.APIBAY_CATS), 6)
        self.assertEqual(sources.APIBAY_CATS,
                         (100, 200, 300, 400, 500, 600))
        self.assertGreater(len(items), 1)

    def test_fallback_query_is_not_expanded(self):
        seen = []
        payload = [{"id": "77", "name": "something unrelated",
                    "info_hash": "a" * 40, "leechers": "1", "seeders": "2",
                    "size": "10", "added": "1", "category": "207"}]

        def fake_get(url, **kw):
            seen.append(url)
            return json.dumps(payload)

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_apibay("完全无关的关键词", 1, timeout=5)

        self.assertEqual(len(seen), 1,
                         "关键词没命中时返回的是兜底列表，再铺六个分类只会"
                         "把噪声放大六倍")
        self.assertEqual(len(items), 1)

    def test_empty_answer_is_not_expanded(self):
        seen = []
        sentinel = json.dumps([{
            "id": "0", "name": "No results returned", "info_hash": "0" * 40,
            "leechers": "0", "seeders": "0", "size": "0", "added": "0",
            "category": "0"}])

        def fake_get(url, **kw):
            seen.append(url)
            return sentinel

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_apibay("demo", 1, timeout=5)
        self.assertEqual(items, [])
        self.assertEqual(len(seen), 1, "空结果没必要再铺分类")

    def test_merged_rows_are_deduped_and_tagged_apibay(self):
        counter = {"n": 0}

        def fake_get(url, **kw):
            counter["n"] += 1
            return json.dumps([adult_row(1), dict(adult_row(1), name="demo x")])

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_apibay("demo", 1, timeout=5)

        hashes = [i["info_hash"] for i in items]
        self.assertEqual(len(hashes), len(set(hashes)), "分类之间会有重复，必须去重")
        self.assertTrue(all(i["source"] == "apibay" for i in items),
                        "跨分类取回的行仍然属于海盗湾这一个源")

    def test_result_count_is_capped(self):
        def fake_get(url, **kw):
            return json.dumps([dict(adult_row(i), name=f"demo {i}")
                               for i in range(1, 200)])

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_apibay("demo", 1, timeout=5)
        self.assertLessEqual(len(items), sources.APIBAY_MAX_HITS)

    def test_a_failing_category_does_not_lose_the_rest(self):
        def fake_get(url, **kw):
            if "cat=300" in url:
                raise urllib.error.HTTPError(url, 500, "boom", {}, None)
            return json.dumps([dict(adult_row(9), name="demo nine")])

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_apibay("demo", 1, timeout=5)
        self.assertTrue(items, "个别分类失败时，其余分类的结果必须保留")

    def test_all_categories_failing_still_returns_the_first_page(self):
        def fake_get(url, **kw):
            if "cat=" in url:
                raise urllib.error.HTTPError(url, 500, "boom", {}, None)
            return json.dumps([dict(adult_row(9), name="demo nine")])

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_apibay("demo", 1, timeout=5)
        self.assertEqual(len(items), 1,
                         "分类全挂也要保住已经拿到的那一页")

    def test_adult_key_is_retired(self):
        from app import config
        self.assertIn("apibay_adult", config.RETIRED_SOURCES)
        self.assertNotIn("apibay_adult", sources.BUILTIN_KEYS)
        self.assertNotIn("apibay_adult",
                         [s["key"] for s in config.DEFAULT_SOURCES])

    def test_old_config_drops_the_retired_key(self):
        from app import config as cfgmod
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            old = {"version": 1, "sources": [
                {"key": "apibay", "label": "海盗湾", "type": "builtin",
                 "enabled": True, "timeout": 15, "base": "", "order": 0},
                {"key": "apibay_adult", "label": "海盗湾成人", "type": "builtin",
                 "enabled": True, "timeout": 15, "base": "", "order": 1},
            ]}
            path.write_text(json.dumps(old), encoding="utf-8")
            cfg = cfgmod.Config(str(path)).load()
            self.assertNotIn("apibay_adult", cfg.all_keys(),
                             "已经并入主源的旧配置项必须自动移除，否则界面上"
                             "会留下一个名字重复的源")


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


class KnabenRegistrationTest(unittest.TestCase):

    def test_knaben_is_builtin(self):
        self.assertIn("knaben", sources.BUILTIN_KEYS)

    def test_knaben_has_a_default_base(self):
        self.assertEqual(sources.DEFAULT_BASES["knaben"],
                         "https://api.knaben.org/v1")

    def test_knaben_supports_paging(self):
        self.assertNotIn("knaben", sources.PAGELESS_KEYS,
                         "knaben 支持通过 from 翻页")

    def test_adult_split_source_is_gone(self):
        self.assertNotIn("apibay_adult", sources.BUILTIN_KEYS)
        self.assertNotIn("apibay_adult", sources.DEFAULT_BASES)
        self.assertNotIn("apibay_adult", sources.PAGELESS_KEYS)

    def test_label_matches_config(self):
        want = {s["key"]: s["label"] for s in config.DEFAULT_SOURCES}
        self.assertEqual(sources._BUILTIN_ADAPTERS["knaben"][0],
                         want["knaben"])

    def test_builtin_label_is_clean_of_guidance(self):
        label = sources._BUILTIN_ADAPTERS["knaben"][0]
        self.assertLessEqual(len(label), 6, "源名是字段名，不是一句说明")

    def test_adapter_name_tracks_the_function(self):
        self.assertEqual(sources.BUILTIN_ADAPTER_NAMES["knaben"],
                         "_search_knaben")

    def test_base_override_is_honoured(self):
        self.assertEqual(sources.base_of("knaben", "https://mirror.example"),
                         "https://mirror.example")
        self.assertEqual(sources.base_of("knaben", ""),
                         "https://api.knaben.org/v1")

    def test_knaben_reaches_the_existing_config_file(self):
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
            self.assertIn("knaben", cfg.all_keys(),
                          "老配置启动时要自动补上新增的内置源")


class NewSourceParityTest(unittest.TestCase):

    def test_frontend_adapter_map_lists_knaben(self):
        js = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        block = js.split("function adapterName(key){", 1)[1].split("}", 1)[0]
        self.assertIn("knaben", block)
        self.assertNotIn("apibay_adult", block,
                         "已并入主源的键不该留在前端映射里")

    def test_frontend_mock_lists_knaben(self):
        js = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
        head = js.split("var MOCK = [", 1)[1].split("];", 1)[0]
        self.assertIn('key:"knaben"', head,
                      "浏览器直开时源列表要和后端一致")
        self.assertNotIn('key:"apibay_adult"', head)

    def test_committed_config_has_no_retired_key(self):
        raw = json.loads((ROOT / "data" / "sources.json").read_text(
            encoding="utf-8"))
        keys = [s["key"] for s in raw["sources"]]
        self.assertNotIn("apibay_adult", keys)
        self.assertIn("knaben", keys)


if __name__ == "__main__":
    unittest.main()
