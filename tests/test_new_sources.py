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


def sukebei_html(rows):
    body = []
    for i, (h, title, size, date, se, le, dl) in enumerate(rows):
        body.append(
            f'<tr class="default">'
            f'<td class="category-icon"><a href="/?c=2_2" title="Real Life">'
            f'<img src="/i.png" alt="cat"></a></td>'
            f'<td colspan="2"><a href="/view/{1000 + i}" title="{title}">'
            f'{title}</a></td>'
            f'<td class="text-center"><a href="/download/{1000 + i}.torrent">'
            f'<i class="fa fa-download"></i></a>'
            f'<a href="magnet:?xt=urn:btih:{h}&amp;dn=x">M</a></td>'
            f'<td class="text-center">{size}</td>'
            f'<td class="text-center" data-timestamp="1789884998">{date}</td>'
            f'<td class="text-center">{se}</td>'
            f'<td class="text-center">{le}</td>'
            f'<td class="text-center">{dl}</td>'
            f'</tr>')
    return ("<html><body><table id=\"torrentList\"><thead><tr>"
            "<th>Category</th><th>Name</th><th></th><th>Link</th>"
            "<th>Size</th><th>Date</th><th></th><th></th><th></th>"
            "</tr></thead><tbody>" + "".join(body)
            + "</tbody></table></body></html>")


SUK_ROWS = [
    ("a" * 40, "[无码破解] SSIS-321 title", "6.5 GiB", "2026-09-20 06:16", "23", "16", "83"),
    ("b" * 40, "[HD 720p] SSIS-068 title", "1.6 GiB", "2026-09-19 11:02", "20", "7", "61"),
    ("c" * 40, "[中文字幕] SSIS-100 title", "7.4 GiB", "2026-09-18 03:40", "18", "2", "44"),
]


def sukebei_rss_xml(rows):
    items = []
    for h, title, size, date, se, le, dl in rows:
        items.append(
            f"<item><title>{title}</title>"
            f"<nyaa:infoHash>{h}</nyaa:infoHash>"
            f"<nyaa:size>{size}</nyaa:size>"
            f"<nyaa:seeders>{se}</nyaa:seeders>"
            f"<nyaa:leechers>{le}</nyaa:leechers>"
            f"<nyaa:downloads>{dl}</nyaa:downloads>"
            f"<guid>https://sukebei.nyaa.si/view/1000</guid></item>")
    return ("<?xml version=\"1.0\"?><rss version=\"2.0\"><channel>"
            + "".join(items) + "</channel></rss>")


class SukebeiHtmlPageTest(unittest.TestCase):

    def test_parses_every_row_field(self):
        items = sources._parse_sukebei_html(sukebei_html(SUK_ROWS[:2]), "")
        self.assertEqual(len(items), 2)
        it = items[0]
        self.assertEqual(it["info_hash"], "a" * 40)
        self.assertEqual(it["title"], "[无码破解] SSIS-321 title")
        self.assertEqual(it["size"], int(6.5 * 1024 ** 3))
        self.assertEqual(it["seeders"], 23)
        self.assertEqual(it["leechers"], 16)
        self.assertEqual(it["source"], "sukebei")
        self.assertIsNotNone(it["added"])
        self.assertTrue(it["magnet"].startswith("magnet:?xt=urn:btih:"))

    def test_row_columns_match_the_rss_semantics(self):
        html_rows = sources._parse_sukebei_html(sukebei_html(SUK_ROWS[:1]), "")
        rss_rows = sources._parse_nyaa_rss(
            sukebei_rss_xml(SUK_ROWS[:1]), "sukebei", "")
        for field in ("seeders", "leechers", "size", "title"):
            with self.subTest(field=field):
                self.assertEqual(html_rows[0][field], rss_rows[0][field],
                                 "HTML 的列顺序取自实测：第 6/7 列是做种/下载"
                                 "之外，与 RSS 逐条一致")

    def test_rows_without_a_magnet_are_skipped(self):
        html = sukebei_html(SUK_ROWS[:1]).replace("magnet:?xt=urn:btih:" + "a" * 40, "")
        self.assertEqual(sources._parse_sukebei_html(html, ""), [])

    def test_short_rows_are_skipped(self):
        html = ('<html><table><tr><td><a href="magnet:?xt=urn:btih:'
                + "d" * 40 + '</a></td></tr></table></html>')
        self.assertEqual(sources._parse_sukebei_html(html, ""), [])

    def test_torrent_download_link_is_kept(self):
        items = sources._parse_sukebei_html(
            sukebei_html(SUK_ROWS[:1]), "https://sukebei.nyaa.si")
        self.assertEqual(items[0]["fetch"]["url"],
                         "https://sukebei.nyaa.si/download/1000.torrent")


class SukebeiSearchTest(unittest.TestCase):

    def _full_rss(self):
        return [(f"{i:040x}", f"rss{i}", "1.0 GiB", "2026-09-20 06:16",
                 "5", "1", "1") for i in range(sources.SUKEBEI_RSS_PAGE)]

    def _run(self, page=1, rss_rows=None):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            if "page=rss" in url:
                return sukebei_rss_xml(rss_rows or self._full_rss())
            n = len([u for u in seen if "page=rss" not in u])
            return sukebei_html([
                (f"{'f' * 8}{n:032x}", f"[page{n}] SSIS title", "1.0 GiB",
                 "2026-09-20 06:16", "9", "1", "2")])

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_sukebei("SSIS", page, timeout=5)
        return seen, items

    def test_rss_is_the_first_request(self):
        seen, _items = self._run()
        self.assertIn("page=rss", seen[0],
                      "RSS 是最快的保底路径，要先请求它")

    def test_also_spans_html_pages(self):
        seen, _items = self._run()
        pages = [re.search(r"[?&]p=(\d+)", u) for u in seen if "page=rss" not in u]
        got = sorted(int(m.group(1)) for m in pages if m)
        self.assertEqual(got, list(range(1, sources.SUKEBEI_PAGES + 1)),
                         "RSS 硬上限 75 条，必须靠 HTML 翻页补齐")
        self.assertGreater(sources.SUKEBEI_PAGES, 1)

    def test_html_pages_are_sorted_by_seeders(self):
        seen, _items = self._run()
        for u in seen:
            if "page=rss" in u:
                continue
            self.assertIn("s=seeders", u,
                          "按做种降序取页，拿到的是最热的那批而不是随机切片")
            self.assertIn("o=desc", u)

    def test_results_merge_and_dedupe(self):
        seen, items = self._run()
        hashes = [i["info_hash"] for i in items]
        self.assertEqual(len(hashes), len(set(hashes)))
        self.assertEqual(len(items),
                         sources.SUKEBEI_RSS_PAGE + sources.SUKEBEI_PAGES)
        self.assertTrue(all(i["source"] == "sukebei" for i in items))

    def test_rss_result_survives_when_every_html_page_fails(self):
        def fake_get(url, **kw):
            if "page=rss" in url:
                return sukebei_rss_xml(SUK_ROWS[:1])
            raise urllib.error.HTTPError(url, 500, "boom", {}, None)

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_sukebei("SSIS", 1, timeout=5)
        self.assertEqual(len(items), 1,
                         "HTML 全挂也要保住 RSS 已经拿到的那一批")

    def test_rss_failure_still_lets_html_answer(self):
        def fake_get(url, **kw):
            if "page=rss" in url:
                raise urllib.error.HTTPError(url, 500, "boom", {}, None)
            return sukebei_html(SUK_ROWS[:1])

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_sukebei("SSIS", 1, timeout=5)
        self.assertEqual(len(items), 1,
                         "RSS 挂掉不该让整个源失败，HTML 页还能出结果")

    def test_everything_failing_raises(self):
        def boom(url, **kw):
            raise urllib.error.HTTPError(url, 500, "boom", {}, None)

        with mock.patch.object(sources, "http_get", boom):
            with self.assertRaises(urllib.error.HTTPError):
                sources._search_sukebei("SSIS", 1, timeout=5)

    def test_short_page_skips_html_entirely(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            short = [(f"{i:040x}", f"t{i}", "1.0 GiB", "2026-09-20 06:16",
                      "5", "1", "1") for i in range(3)]
            if "page=rss" in url:
                return sukebei_rss_xml(short)
            self.fail("RSS 只有 3 条（未满一页）时不该再翻 HTML，"
                      "那是每次搜索白等约 4 秒")

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_sukebei("SSIS", 1, timeout=5)
        self.assertEqual(len(items), 3)
        self.assertEqual(len(seen), 1, "只应发一次 RSS 请求")

    def test_full_page_still_triggers_html_paging(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            if "page=rss" in url:
                rows = [(f"{i:040x}", f"t{i}", "1.0 GiB", "2026-09-20 06:16",
                         "5", "1", "1")
                        for i in range(sources.SUKEBEI_RSS_PAGE)]
                return sukebei_rss_xml(rows)
            return sukebei_html([(f"{'e' * 8}{i:032x}", f"p{i}", "1.0 GiB",
                                  "2026-09-20 06:16", "5", "1", "1")
                                 for i in range(2)])

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_sukebei("SSIS", 1, timeout=5)
        html_calls = [u for u in seen if "page=rss" not in u]
        self.assertEqual(len(html_calls), sources.SUKEBEI_PAGES,
                         "RSS 满页说明还有更多，必须继续翻 HTML")
        self.assertGreater(len(items), sources.SUKEBEI_RSS_PAGE)

    def test_page_budget_is_pinned_to_the_site_ceiling(self):
        self.assertEqual(sources.SUKEBEI_PAGES, 14,
                         "Sukebei 站点分页上限就是 14 页（实测分页条到 13/14），"
                         "自报总量约 1000 条；翻少了会漏掉后面的大多数")
        self.assertGreaterEqual(sources.SUKEBEI_MAX_HITS, 1000,
                                "上限要容得下站点能给的全部条目")

    def test_short_result_still_skips_all_pages(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            if "page=rss" in url:
                return sukebei_rss_xml(
                    [(f"{i:040x}", f"t{i}", "1.0 GiB", "2026-09-20 06:16",
                      "5", "1", "1") for i in range(4)])
            self.fail("结果未满一页时不该翻 14 页，那是每次搜索白等十几秒")

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_sukebei("rare", 1, timeout=5)
        self.assertEqual(len(items), 4)
        self.assertEqual(len(seen), 1)

    def test_rss_page_size_is_pinned_to_the_measured_value(self):
        self.assertEqual(sources.SUKEBEI_RSS_PAGE, 75,
                         "RSS 接口的每页条数；这个数变了短路口就会误判，"
                         "必须与实测一致")

    def test_html_failure_after_full_page_still_keeps_rss(self):
        def fake_get(url, **kw):
            if "page=rss" in url:
                rows = [(f"{i:040x}", f"t{i}", "1.0 GiB", "2026-09-20 06:16",
                         "5", "1", "1")
                        for i in range(sources.SUKEBEI_RSS_PAGE)]
                return sukebei_rss_xml(rows)
            raise urllib.error.HTTPError(url, 500, "boom", {}, None)

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_sukebei("SSIS", 1, timeout=5)
        self.assertEqual(len(items), sources.SUKEBEI_RSS_PAGE)

    def test_result_count_is_capped(self):
        def fake_get(url, **kw):
            if "page=rss" in url:
                return sukebei_rss_xml(self._full_rss())
            rows = [(f"{'c' * 8}{i:032x}", f"t{i}", "1.0 GiB",
                     "2026-09-20 06:16", "5", "1", "1")
                    for i in range(sources.SUKEBEI_MAX_HITS + 50)]
            return sukebei_html(rows)

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_sukebei("SSIS", 1, timeout=5)
        self.assertEqual(len(items), sources.SUKEBEI_MAX_HITS)


class NyaaFamilyTest(unittest.TestCase):

    def test_nyaa_and_sukebei_share_the_html_parser(self):
        html = sukebei_html(SUK_ROWS[:1])
        a = sources._parse_sukebei_html(html, "", "nyaa")
        b = sources._parse_sukebei_html(html, "", "sukebei")
        self.assertEqual(a[0]["info_hash"], b[0]["info_hash"])
        self.assertEqual(a[0]["source"], "nyaa",
                         "同一套 HTML 标记，靠参数区分来源")
        self.assertEqual(b[0]["source"], "sukebei")

    def test_nyaa_pages_are_pinned_to_the_site_ceiling(self):
        self.assertEqual(sources.NYAA_PAGES, 14,
                         "nyaa.si 与 sukebei 同款，站点分页上限 14 页、"
                         "自报约 1000 条；只取一页会漏掉九成以上")
        self.assertGreaterEqual(sources.NYAA_MAX_HITS, 1000)

    def test_nyaa_short_result_skips_paging(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            if "page=rss" in url:
                return sukebei_rss_xml(
                    [(f"{i:040x}", f"t{i}", "1.0 GiB", "2026-09-20 06:16",
                      "5", "1", "1") for i in range(5)])
            self.fail("结果未满一页时不该翻 14 页")

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_nyaa("rare", 1, timeout=5)
        self.assertEqual(len(items), 5)
        self.assertEqual(len(seen), 1)

    def test_nyaa_full_page_triggers_html_paging(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            if "page=rss" in url:
                rows = [(f"{i:040x}", f"t{i}", "1.0 GiB", "2026-09-20 06:16",
                         "5", "1", "1")
                        for i in range(sources.SUKEBEI_RSS_PAGE)]
                return sukebei_rss_xml(rows)
            return sukebei_html([(f"{'d' * 8}{i:032x}", f"p{i}", "1.0 GiB",
                                  "2026-09-20 06:16", "5", "1", "1")
                                 for i in range(2)])

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_nyaa("demo", 1, timeout=5)
        html_calls = [u for u in seen if "page=rss" not in u]
        self.assertEqual(len(html_calls), sources.NYAA_PAGES)
        self.assertTrue(all(i["source"] == "nyaa" for i in items))
        self.assertGreater(len(items), sources.SUKEBEI_RSS_PAGE)

    def test_nyaa_html_failure_keeps_rss(self):
        def fake_get(url, **kw):
            if "page=rss" in url:
                rows = [(f"{i:040x}", f"t{i}", "1.0 GiB", "2026-09-20 06:16",
                         "5", "1", "1")
                        for i in range(sources.SUKEBEI_RSS_PAGE)]
                return sukebei_rss_xml(rows)
            raise urllib.error.HTTPError(url, 500, "boom", {}, None)

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_nyaa("demo", 1, timeout=5)
        self.assertEqual(len(items), sources.SUKEBEI_RSS_PAGE)


class KnabenRequestTest(unittest.TestCase):

    def _bodies(self, page=1):
        seen = []

        def fake_get(url, **kw):
            body = json.loads(kw["data"].decode("utf-8"))
            seen.append({"body": body, "url": url,
                         "headers": kw.get("headers") or {}})
            return knaben_payload([knaben_hit(len(seen))])

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_knaben("ubuntu", page, timeout=5)
        return seen, items

    def test_posts_the_documented_query_field(self):
        seen, _items = self._bodies()
        body = seen[0]["body"]
        self.assertIn("query", body,
                      "knaben 只认 query 字段；写成 search_query 会静默返回"
                      "与关键词无关的榜单结果")
        self.assertNotIn("search_query", body)
        for s in seen:
            self.assertIn("application/json",
                          str(s["headers"].get("Content-Type", "")).lower())

    def test_orders_by_seeders(self):
        seen, _items = self._bodies()
        for s in seen:
            self.assertEqual(s["body"]["order_by"], "seeders")
            self.assertEqual(s["body"]["order_by"], sources.KNABEN_ORDER)

    def test_offset_uses_from_not_page(self):
        seen, _items = self._bodies()
        for s in seen:
            self.assertIn("from", s["body"],
                          "knaben 的偏移量参数是 from；page/offset 会被忽略并"
                          "重复返回第一页")
            self.assertNotIn("page", s["body"])
            self.assertNotIn("offset", s["body"])

    def test_first_page_starts_at_zero(self):
        seen, _items = self._bodies(1)
        self.assertIn(0, [s["body"]["from"] for s in seen],
                      "第一页必须含 from=0")

    def test_fetches_several_pages_concurrently(self):
        seen, _items = self._bodies(1)
        self.assertEqual(len(seen), sources.KNABEN_PAGES,
                         "只取一页会漏掉接口自报总数里的大部分结果")
        offsets = sorted(s["body"]["from"] for s in seen)
        self.assertEqual(offsets,
                         [i * sources.KNABEN_PAGE_SIZE
                          for i in range(sources.KNABEN_PAGES)])
        self.assertGreater(sources.KNABEN_PAGES, 1)

    def test_later_app_pages_move_the_window(self):
        seen, _items = self._bodies(2)
        step = sources.KNABEN_PAGE_SIZE * sources.KNABEN_PAGES
        self.assertEqual(sorted(s["body"]["from"] for s in seen),
                         [step + i * sources.KNABEN_PAGE_SIZE
                          for i in range(sources.KNABEN_PAGES)])

    def test_requests_the_server_max_page_size(self):
        seen, _items = self._bodies()
        for s in seen:
            self.assertEqual(s["body"]["size"], sources.KNABEN_PAGE_SIZE)
        self.assertEqual(sources.KNABEN_PAGE_SIZE, 300,
                         "实测接口的 size 上限就是 300，写更大也只会返回 300")

    def test_all_pages_failing_raises(self):
        def boom(url, **kw):
            raise urllib.error.HTTPError(url, 500, "boom", {}, None)

        with mock.patch.object(sources, "http_get", boom):
            with self.assertRaises(urllib.error.HTTPError):
                sources._search_knaben("demo", 1, timeout=5)

    def test_one_failing_page_keeps_the_others(self):
        calls = {"n": 0}

        def flaky(url, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise urllib.error.HTTPError(url, 500, "boom", {}, None)
            return knaben_payload([knaben_hit(calls["n"])])

        with mock.patch.object(sources, "http_get", flaky):
            items = sources._search_knaben("demo", 1, timeout=5)
        self.assertEqual(len(items), sources.KNABEN_PAGES - 1,
                         "个别页失败不该丢掉其余页的结果")


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
