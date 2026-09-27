import io
import re
import sys
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config, sources

JAVBUS_ROW = """
<tr onmouseover="this.style.backgroundColor='#F4F9FD';this.style.cursor='pointer';" onmouseout="this.style.backgroundColor='#FFFFFF'" height="35px" style=" border-top:#DDDDDD solid 1px">
    <td width="70%" onclick="window.open('magnet:?xt=urn:btih:{h}&dn=x','_self')">
        <a style="color:#333" rel="nofollow" title="滑鼠右鍵點擊並選擇【複製連結網址】" href="magnet:?xt=urn:btih:{h}&dn=x">
        {title}{badge}                	</a>
    </td>
    <td style="text-align:center;white-space:nowrap" onclick="window.open('magnet:?xt=urn:btih:{h}&dn=x','_self')">
        <a style="color:#333" rel="nofollow" title="滑鼠右鍵點擊並選擇【複製連結網址】" href="magnet:?xt=urn:btih:{h}&dn=x">
        {size}                	</a>
    </td>
    <td style="text-align:center;white-space:nowrap" onclick="window.open('magnet:?xt=urn:btih:{h}&dn=x','_self')">
        <a style="color:#333" rel="nofollow" title="滑鼠右鍵點擊並選擇【複製連結網址】" href="magnet:?xt=urn:btih:{h}&dn=x">
        {date}                	</a>
    </td>
</tr>
"""

JAVBUS_BADGE = (' <a class="btn btn-mini-new btn-primary disabled" '
                'title="包含高清HD的磁力連結">高清</a>')

JAVBUS_DETAIL = """
<script>var gid = {gid}; var uc = {uc}; var img = '{img}';</script>
<div class="row movie"><div class="col-md-3 info">
<p><span class="header">識別碼:</span> <span style="color:#CC0000;">{code}</span> </p>
</div></div>
"""

JAVDB_ITEM = """
<div class="item {odd}"
     data-rank="{rank}"
     data-size="{mb}"
     data-files="1"
     data-date="{date}">
  <div class="magnet-name">
    <a href="magnet:?xt=urn:btih:{h}&amp;dn=[javdb.com]{title}" title="右鍵點擊並選擇「複製鏈接地址」">
      <span class="name">{title}</span>
      <div class="tags">
        <span class="tag is-primary is-small is-light">高清</span>
      </div>
      <span class="meta"> {human}, 1個文件 </span>
    </a>
  </div>
  <div class="date"><span class="time">{iso}</span></div>
  <div class="buttons">
    <button class="button is-info is-small copy-to-clipboard" data-clipboard-text="magnet:?xt=urn:btih:{h}" type="button">&nbsp;複製&nbsp;</button>
  </div>
</div>
"""


def magnet_page(*rows) -> str:
    return "<html><body><table>" + "".join(rows) + "</table></body></html>"


def search_page(*boxes) -> str:
    return "<html><body>" + "".join(boxes) + "</body></html>"


def bus_box(code: str) -> str:
    return (f'<a class="movie-box" href="https://www.javbus.com/{code}">'
            f'<div class="photo-info"><span>{code}</span>'
            f'<date>{code}</date></div></a>')


def db_entry(token: str) -> str:
    return (f'<div class="movie-list h cols-4"><div class="item">'
            f'<a href="/v/{token}" class="box" title="{token}">'
            f'<div class="video-title"><strong>{token}</strong></div>'
            f'</a></div></div>')


class JavbusParseTest(unittest.TestCase):

    def test_reads_hash_size_date_title(self):
        html = magnet_page(JAVBUS_ROW.format(
            h="A" * 40, title="SSIS-001", size="2.02GB",
            date="2025-10-28", badge=""))
        items = sources._parse_javbus_magnets(html)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["info_hash"], "a" * 40)
        self.assertEqual(it["title"], "SSIS-001")
        self.assertEqual(it["size"], sources.parse_size("2.02GB"))
        self.assertEqual(it["source"], "javbus")
        self.assertTrue(it["magnet"].startswith("magnet:?xt=urn:btih:" + "a" * 40))

    def test_lowercases_uppercase_hash(self):
        html = magnet_page(JAVBUS_ROW.format(
            h="ABCDEF" * 6 + "ABCD", title="x", size="1GB",
            date="2024-01-01", badge=""))
        self.assertEqual(sources._parse_javbus_magnets(html)[0]["info_hash"],
                         ("abcdef" * 6 + "abcd").lower())

    def test_badge_text_is_not_part_of_the_title(self):
        html = magnet_page(JAVBUS_ROW.format(
            h="b" * 40, title="SSIS-960_60FPS_FHD_CH", size="1.32GB",
            date="2024-10-20", badge=JAVBUS_BADGE))
        title = sources._parse_javbus_magnets(html)[0]["title"]
        self.assertNotIn("高清", title)
        self.assertEqual(title, "SSIS-960_60FPS_FHD_CH")

    def test_date_is_china_time(self):
        html = magnet_page(JAVBUS_ROW.format(
            h="c" * 40, title="x", size="1GB", date="2024-01-01", badge=""))
        expect = sources._ts_from_iso("2024-01-01T00:00:00+08:00")
        self.assertAlmostEqual(sources._parse_javbus_magnets(html)[0]["added"],
                               expect, places=3)

    def test_dedups_repeated_hash(self):
        row = JAVBUS_ROW.format(h="d" * 40, title="same", size="1GB",
                                date="2024-01-01", badge="")
        self.assertEqual(len(sources._parse_javbus_magnets(magnet_page(row, row))), 1)

    def test_rows_without_hash_are_skipped(self):
        html = magnet_page("<tr><td>no hash here</td><td>1GB</td></tr>")
        self.assertEqual(sources._parse_javbus_magnets(html), [])

    def test_empty_body_is_empty(self):
        self.assertEqual(sources._parse_javbus_magnets(""), [])

    def test_bad_date_leaves_added_none(self):
        html = magnet_page(JAVBUS_ROW.format(
            h="e" * 40, title="x", size="1GB", date="日期未知", badge=""))
        self.assertIsNone(sources._parse_javbus_magnets(html)[0]["added"])


class JavdbParseTest(unittest.TestCase):

    def test_reads_hash_title_size_date(self):
        html = JAVDB_ITEM.format(
            odd="odd", rank=0, mb=6480, date="20231118", h="A" * 40,
            title="SSIS-001-UC", human="6.33GB", iso="2023-11-18")
        items = sources._parse_javdb_magnets(html)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["info_hash"], "a" * 40)
        self.assertEqual(it["title"], "SSIS-001-UC")
        self.assertEqual(it["size"], sources.parse_size("6.33GB"))
        self.assertEqual(it["source"], "javdb")

    def test_size_falls_back_to_data_attribute(self):
        html = JAVDB_ITEM.format(
            odd="odd", rank=0, mb=5310, date="20231214", h="b" * 40,
            title="x", human="4個文件", iso="2023-12-14")
        self.assertEqual(sources._parse_javdb_magnets(html)[0]["size"],
                         5310 * 1024 * 1024)

    def test_zero_data_size_stays_zero(self):
        html = JAVDB_ITEM.format(
            odd="", rank=7, mb=0, date="20240527", h="c" * 40,
            title="SSIS-997", human="3個文件", iso="2024-05-27")
        self.assertEqual(sources._parse_javdb_magnets(html)[0]["size"], 0)

    def test_date_comes_from_the_attribute(self):
        html = JAVDB_ITEM.format(
            odd="", rank=0, mb=100, date="20231118", h="d" * 40,
            title="x", human="100MB", iso="1999-01-01")
        expect = sources._ts_from_iso("2023-11-18T00:00:00+08:00")
        self.assertAlmostEqual(sources._parse_javdb_magnets(html)[0]["added"],
                               expect, places=3)

    def test_multiple_items_are_split_at_item_boundaries(self):
        one = JAVDB_ITEM.format(odd="odd", rank=0, mb=100, date="20231118",
                                h="e" * 40, title="first", human="100MB",
                                iso="2023-11-18")
        two = JAVDB_ITEM.format(odd="", rank=1, mb=200, date="20231119",
                                h="f" * 40, title="second", human="200MB",
                                iso="2023-11-19")
        items = sources._parse_javdb_magnets(one + two)
        self.assertEqual([i["title"] for i in items], ["first", "second"])

    def test_dedups_repeated_hash(self):
        one = JAVDB_ITEM.format(odd="odd", rank=0, mb=100, date="20231118",
                                h="a" * 40, title="same", human="100MB",
                                iso="2023-11-18")
        two = JAVDB_ITEM.format(odd="", rank=1, mb=200, date="20231119",
                                h="a" * 40, title="same again", human="200MB",
                                iso="2023-11-19")
        self.assertEqual(len(sources._parse_javdb_magnets(one + two)), 1)

    def test_page_without_items_is_empty(self):
        self.assertEqual(sources._parse_javdb_magnets("<html></html>"), [])


class SearchFlowTest(unittest.TestCase):

    def test_javbus_walks_search_then_detail_then_ajax(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            if "/search/" in url:
                return search_page(bus_box("SSIS-001"))
            if "/ajax/" in url:
                return magnet_page(JAVBUS_ROW.format(
                    h="a" * 40, title="SSIS-001", size="2.02GB",
                    date="2025-10-28", badge=""))
            return JAVBUS_DETAIL.format(gid=45622863524, uc=0,
                                        img="/pics/cover/83ie_b.jpg",
                                        code="SSIS-001")

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_javbus("SSIS", 1, timeout=5)

        self.assertEqual(len(items), 1)
        self.assertTrue(any("/search/" in u for u in seen), "要先查搜索页")
        self.assertTrue(any("/ajax/uncledatoolsbyajax.php" in u for u in seen),
                        "磁力藏在未破解 AJAX 接口里，必须去取")
        ajax = [u for u in seen if "/ajax/" in u][0]
        self.assertIn("gid=45622863524", ajax)

    def test_javbus_search_url_encodes_the_query(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            return search_page()

        with mock.patch.object(sources, "http_get", fake_get):
            sources._search_javbus("hello world", 1, timeout=5)
        self.assertTrue(seen)
        self.assertIn("hello%20world", seen[0])

    def test_javbus_page_number_is_in_the_path(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            return search_page()

        with mock.patch.object(sources, "http_get", fake_get):
            sources._search_javbus("SSIS", 3, timeout=5)
        self.assertIn("/search/SSIS/3", seen[0],
                      "第 1 页不带后缀，其后是 /search/<q>/<p>")

    def test_javbus_skips_detail_when_search_is_empty(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            return search_page()

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_javbus("nothing", 1, timeout=5)
        self.assertEqual(items, [])
        self.assertEqual(len(seen), 1, "搜索页空结果时不该再去抓详情")

    def test_javbus_partial_detail_failure_keeps_the_rest(self):
        def fake_get(url, **kw):
            if "/search/" in url:
                return search_page(bus_box("SSIS-001"), bus_box("SSIS-002"))
            if "/ajax/" in url:
                return magnet_page(JAVBUS_ROW.format(
                    h="a" * 40, title="ok", size="1GB",
                    date="2024-01-01", badge=""))
            if url.endswith("SSIS-002"):
                raise OSError("detail down")
            return JAVBUS_DETAIL.format(gid=1, uc=0, img="i", code="SSIS-001")

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_javbus("SSIS", 1, timeout=5)
        self.assertEqual(len(items), 1)

    def test_javbus_raises_when_every_detail_fails(self):
        def fake_get(url, **kw):
            if "/search/" in url:
                return search_page(bus_box("SSIS-001"))
            raise OSError("network down")

        with mock.patch.object(sources, "http_get", fake_get):
            with self.assertRaises(OSError):
                sources._search_javbus("SSIS", 1, timeout=5)

    def test_javbus_empty_result_is_not_an_error(self):
        def fake_get(url, **kw):
            raise urllib.error.HTTPError(
                url, 404, "Not Found", {}, io.BytesIO(
                    "<html><head><title>沒有您要的結果！ - JavBus</title>"
                    "</head></html>".encode("utf-8")))

        with mock.patch.object(sources, "http_get", fake_get):
            self.assertEqual(sources._search_javbus("无码", 1, timeout=5), [],
                             "该站用 404 + 「沒有您要的結果」表示搜不到，"
                             "当成失败会把空结果涂成红色")

    def test_javbus_real_404_still_raises(self):
        def fake_get(url, **kw):
            raise urllib.error.HTTPError(
                url, 404, "Not Found", {}, io.BytesIO(b"<html>gone</html>"))

        with mock.patch.object(sources, "http_get", fake_get):
            with self.assertRaises(urllib.error.HTTPError):
                sources._search_javbus("SSIS", 1, timeout=5)

    def test_javbus_other_status_codes_are_never_swallowed(self):
        for code in (403, 429, 503):
            with self.subTest(code=code):
                def fake_get(url, **kw):
                    raise urllib.error.HTTPError(
                        url, code, "x", {}, io.BytesIO(
                            "沒有您要的結果".encode("utf-8")))

                with mock.patch.object(sources, "http_get", fake_get):
                    with self.assertRaises(urllib.error.HTTPError):
                        sources._search_javbus("SSIS", 1, timeout=5)

    def test_javdb_walks_search_then_detail(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            if "/search?" in url:
                return search_page(db_entry("ZY5eq"))
            return JAVDB_ITEM.format(
                odd="odd", rank=0, mb=6480, date="20231118", h="b" * 40,
                title="SSIS-001-UC", human="6.33GB", iso="2023-11-18")

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_javdb("SSIS", 1, timeout=5)

        self.assertEqual(len(items), 1)
        self.assertIn("/search?f=all", seen[0])
        self.assertIn("locale=zh", seen[0])
        self.assertTrue(any(u.endswith("/v/ZY5eq") for u in seen),
                        "磁力在详情页里，必须跟进去")

    def test_javdb_page_number_is_a_query_param(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            return search_page()

        with mock.patch.object(sources, "http_get", fake_get):
            sources._search_javdb("SSIS", 4, timeout=5)
        self.assertIn("page=4", seen[0])

    def test_javdb_skips_detail_when_search_is_empty(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            return search_page()

        with mock.patch.object(sources, "http_get", fake_get):
            self.assertEqual(sources._search_javdb("nothing", 1, timeout=5), [])
        self.assertEqual(len(seen), 1)

    def test_javdb_partial_failure_keeps_the_rest(self):
        def fake_get(url, **kw):
            if "/search?" in url:
                return search_page(db_entry("AAA"), db_entry("BBB"))
            if url.endswith("/v/BBB"):
                raise OSError("detail down")
            return JAVDB_ITEM.format(
                odd="odd", rank=0, mb=100, date="20231118", h="c" * 40,
                title="ok", human="100MB", iso="2023-11-18")

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_javdb("SSIS", 1, timeout=5)
        self.assertEqual(len(items), 1)

    def test_javdb_raises_when_every_detail_fails(self):
        def fake_get(url, **kw):
            if "/search?" in url:
                return search_page(db_entry("AAA"))
            raise OSError("network down")

        with mock.patch.object(sources, "http_get", fake_get):
            with self.assertRaises(OSError):
                sources._search_javdb("SSIS", 1, timeout=5)


JAVDB_LOGIN_PAGE = ("<html><head><title> 登入 | JavDB 成人影片數據庫"
                    "</title></head><body>"
                    "<input type=password></body></html>")

JAVDB_EMPTY_PAGE = ("<html><head><title>SSIS-999 | JavDB</title></head>"
                    "<body>no magnet here</body></html>")


class LoginWallTest(unittest.TestCase):

    def test_detects_the_login_page(self):
        self.assertTrue(sources._javdb_login_wall(JAVDB_LOGIN_PAGE))
        self.assertTrue(sources._javdb_login_wall(
            "<title>\n  登錄 | JavDB</title>"))
        self.assertFalse(sources._javdb_login_wall(JAVDB_EMPTY_PAGE))
        self.assertFalse(sources._javdb_login_wall(""))

    def test_all_walled_details_raise_instead_of_returning_zero(self):
        def fake_get(url, **kw):
            if "/search?" in url:
                return search_page(db_entry("AAA"), db_entry("BBB"))
            return JAVDB_LOGIN_PAGE

        with mock.patch.object(sources, "http_get", fake_get):
            with self.assertRaises(sources.Blocked) as caught:
                sources._search_javdb("SSIS", 1, timeout=5)
        self.assertEqual(str(caught.exception), sources.JAVDB_LOGIN_TEXT)

    def test_walled_pages_without_magnets_raise_even_if_a_page_returned(self):
        def fake_get(url, **kw):
            if "/search?" in url:
                return search_page(db_entry("AAA"), db_entry("BBB"))
            if url.endswith("/v/AAA"):
                return JAVDB_EMPTY_PAGE
            return JAVDB_LOGIN_PAGE

        with mock.patch.object(sources, "http_get", fake_get):
            with self.assertRaises(sources.Blocked) as caught:
                sources._search_javdb("SSIS", 1, timeout=5)
        self.assertEqual(str(caught.exception), sources.JAVDB_LOGIN_TEXT)

    def test_a_page_with_magnets_does_not_raise(self):
        def fake_get(url, **kw):
            if "/search?" in url:
                return search_page(db_entry("AAA"), db_entry("BBB"))
            if url.endswith("/v/BBB"):
                return JAVDB_LOGIN_PAGE
            return JAVDB_ITEM.format(
                odd="odd", rank=0, mb=100, date="20231118", h="e" * 40,
                title="ok", human="100MB", iso="2023-11-18")

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_javdb("SSIS", 1, timeout=5)
        self.assertEqual(len(items), 1,
                         "有磁力就不算撞墙，别把结果一起丢掉")

    def test_partial_wall_keeps_the_pages_that_worked(self):
        def fake_get(url, **kw):
            if "/search?" in url:
                return search_page(db_entry("AAA"), db_entry("BBB"))
            if url.endswith("/v/BBB"):
                return JAVDB_LOGIN_PAGE
            return JAVDB_ITEM.format(
                odd="odd", rank=0, mb=100, date="20231118", h="d" * 40,
                title="ok", human="100MB", iso="2023-11-18")

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_javdb("SSIS", 1, timeout=5)
        self.assertEqual(len(items), 1,
                         "有一部要登入不该把已经拿到的结果一起丢掉")

    def test_wall_classifies_as_login_not_as_captcha(self):
        from app import api
        outcome, code = api.classify(False, 0, sources.JAVDB_LOGIN_TEXT)
        self.assertEqual(outcome, api.OUTCOME_LOGIN)
        self.assertNotEqual(outcome, api.OUTCOME_BLOCKED,
                            "登入墙不是人机验证，报错文案会误导用户去刷新重试")
        self.assertEqual(api.outcome_text(outcome, code),
                         sources.JAVDB_LOGIN_TEXT)

    def test_captcha_still_classifies_as_blocked(self):
        from app import api
        outcome, _code = api.classify(False, 0, sources.BLOCKED_TEXT)
        self.assertEqual(outcome, api.OUTCOME_BLOCKED)


class MultiWordFallbackTest(unittest.TestCase):

    def test_split_words_ignores_extra_spaces(self):
        self.assertEqual(sources._split_words("  a  b "), ["a", "b"])
        self.assertEqual(sources._split_words(""), [])
        self.assertEqual(sources._split_words("   "), [])

    def test_merge_word_results_unions_and_dedups(self):
        rows = {
            "a": [{"info_hash": "1" * 40}, {"info_hash": "2" * 40}],
            "b": [{"info_hash": "2" * 40}, {"info_hash": "3" * 40}],
        }
        out = sources._merge_word_results(rows.__getitem__, ["a", "b"], 99, "t")
        self.assertEqual([i["info_hash"][0] for i in out], ["1", "2", "3"])

    def test_merge_word_results_respects_the_cap(self):
        rows = {w: [{"info_hash": f"{i:040x}"} for i in range(10)]
                for w in ("a", "b")}
        out = sources._merge_word_results(rows.__getitem__, ["a", "b"], 4, "t")
        self.assertEqual(len(out), 4)

    def test_merge_word_results_keeps_going_when_one_word_fails(self):
        def gather(word):
            if word == "bad":
                raise OSError("boom")
            return [{"info_hash": "9" * 40}]

        out = sources._merge_word_results(gather, ["bad", "good"], 99, "t")
        self.assertEqual(len(out), 1)

    def test_merge_word_results_raises_when_every_word_fails(self):
        def gather(word):
            raise OSError("boom")

        with self.assertRaises(OSError):
            sources._merge_word_results(gather, ["a", "b"], 99, "t")

    def test_xccl263_two_words_fall_back_to_per_word(self):
        seen = []
        xccl = ("<html><body>"
                '<div class="search-item detail-width">'
                '<a title="{t}" href="/hash/{h}.html">{t}</a>'
                "文件大小:<b>1GB</b> 创建时间:<b>2024-01-01</b> "
                "下载热度:<b>1</b></div></body></html>")

        def fake_get(url, **kw):
            seen.append(url)
            word = urllib.parse.unquote(
                url.split("/search/kw-")[1].rsplit("-1.html", 1)[0])
            if " " in word:
                return "<html><body>找到0条结果</body></html>"
            n = 1 if word == "羽山典子" else 2
            return xccl.format(t=f"row{n}", h=f"{n * 20:040x}")

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_xccl263("羽山典子 岡田純菜", 1, timeout=5)

        self.assertEqual(len(items), 2, "两个词的结果都要合进来")
        self.assertTrue(any("%20" in u for u in seen), "先按原样试一次多词")
        self.assertTrue(any("%20" not in u for u in seen), "失败后要退化成逐词")

    def test_xccl263_single_word_does_not_fall_back(self):
        calls = []
        xccl = ("<html><body>"
                '<div class="search-item detail-width">'
                '<a title="one" href="/hash/{h}.html">one</a>'
                "文件大小:<b>1GB</b> 创建时间:<b>2024-01-01</b> "
                "下载热度:<b>1</b></div></body></html>")

        def fake_get(url, **kw):
            calls.append(url)
            p = url.rsplit("-", 1)[-1].split(".html")[0]
            return xccl.format(h=f"{int(p):040x}")

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_xccl263("羽山典子", 1, timeout=5)
        self.assertEqual(len(items), sources.XCCL_PAGES)
        self.assertEqual(len(calls), sources.XCCL_PAGES,
                         "单词命中时不该再打一轮逐词")

    def test_javbus_multiword_403_falls_back_to_per_word(self):
        def fake_get(url, **kw):
            if "/search/" in url and "%20" in url:
                raise urllib.error.HTTPError(url, 403, "Forbidden", {},
                                             io.BytesIO(b""))
            if "/search/" in url:
                word = urllib.parse.unquote(url.rsplit("/search/", 1)[1])
                word = word.split("/")[0]
                code = "AAA-001" if word == "AAA" else "BBB-002"
                return search_page(bus_box(code))
            if "/ajax/" in url:
                gid = re.search(r"gid=(\d+)", url).group(1)
                return magnet_page(JAVBUS_ROW.format(
                    h=f"{int(gid):040x}", title="t", size="1GB",
                    date="2024-01-01", badge=""))
            code = url.rsplit("/", 1)[-1]
            gid = 1 if code.startswith("AAA") else 2
            return JAVBUS_DETAIL.format(gid=gid, uc=0, img="i", code=code)

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_javbus("AAA BBB", 1, timeout=5)
        self.assertEqual(len(items), 2, "403 之后要逐词取回两份结果")

    def test_javbus_single_word_403_is_not_swallowed(self):
        def fake_get(url, **kw):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {},
                                         io.BytesIO(b""))

        with mock.patch.object(sources, "http_get", fake_get):
            with self.assertRaises(urllib.error.HTTPError):
                sources._search_javbus("AAA", 1, timeout=5)


class AdultSourceContractTest(unittest.TestCase):

    def test_both_keys_are_registered(self):
        for key, label in (("javbus", "JavBus"), ("javdb", "JavDB")):
            with self.subTest(key=key):
                self.assertIn(key, sources.BUILTIN_KEYS)
                self.assertEqual(sources._BUILTIN_ADAPTERS[key][0], label)
                self.assertEqual(sources.BUILTIN_ADAPTER_NAMES[key],
                                 f"_search_{key}")

    def test_default_bases_have_hosts(self):
        self.assertEqual(sources.DEFAULT_BASES["javbus"],
                         "https://www.javbus.com")
        self.assertEqual(sources.DEFAULT_BASES["javdb"],
                         "https://javdb.com")

    def test_base_override_wins(self):
        self.assertEqual(sources.base_of("javbus", "https://mirror.example"),
                         "https://mirror.example")
        self.assertEqual(sources.base_of("javdb", "https://mirror.example"),
                         "https://mirror.example")

    def test_both_are_in_default_sources(self):
        keys = [s["key"] for s in config.DEFAULT_SOURCES]
        self.assertIn("javbus", keys)
        self.assertIn("javdb", keys)

    def test_labels_match_config(self):
        want = {s["key"]: s["label"] for s in config.DEFAULT_SOURCES}
        for key in ("javbus", "javdb"):
            with self.subTest(key=key):
                self.assertEqual(sources._BUILTIN_ADAPTERS[key][0], want[key])

    def test_labels_are_short_enough_to_be_field_names(self):
        for key in ("javbus", "javdb"):
            with self.subTest(key=key):
                self.assertLessEqual(len(sources._BUILTIN_ADAPTERS[key][0]), 6,
                                     "源名是字段名，不是一句说明")

    def test_both_stay_paginated(self):
        for key in ("javbus", "javdb"):
            with self.subTest(key=key):
                self.assertNotIn(key, sources.PAGELESS_KEYS)

    def test_both_are_overseas_so_a_timeout_names_the_proxy(self):
        for key in ("javbus", "javdb"):
            with self.subTest(key=key):
                self.assertIn(key, sources._OVERSEAS_KEYS,
                              "这两站直连不通，只能走代理；不进这个集合，"
                              "超时提示会误导用户去查本地网络")

    def test_detail_worker_count_is_conservative(self):
        self.assertLessEqual(sources.JAVBUS_WORKERS, 4,
                             "详情页是逐部抓的，并发再高容易触发风控")
        self.assertLessEqual(sources.JAVDB_WORKERS, 4)

    def test_detail_batches_are_bounded(self):
        for key, cap in (("JAVBUS_DETAILS", 20), ("JAVDB_DETAILS", 20)):
            with self.subTest(key=key):
                self.assertLessEqual(
                    getattr(sources, key), cap,
                    f"{key} 是每轮跟进的详情页数，放大会把一次搜索拖成几十个请求")
        for key, cap in (("JAVBUS_MAX_HITS", 400), ("JAVDB_MAX_HITS", 400)):
            with self.subTest(key=key):
                self.assertLessEqual(getattr(sources, key), cap)

    def test_max_hits_actually_caps_the_merge(self):
        def fake_get(url, **kw):
            if "/search/" in url:
                return search_page(*[bus_box(f"SSIS-{i:03d}")
                                     for i in range(sources.JAVBUS_DETAILS)])
            if "/ajax/" in url:
                gid = int(re.search(r"gid=(\d+)", url).group(1))
                return magnet_page(*[
                    JAVBUS_ROW.format(h=f"{gid * 100 + i:040x}", title=f"t{i}",
                                      size="1GB", date="2024-01-01", badge="")
                    for i in range(60)])
            code = url.rsplit("/", 1)[-1]
            gid = int(code.rsplit("-", 1)[-1])
            return JAVBUS_DETAIL.format(gid=gid, uc=0, img="i", code=code)

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_javbus("SSIS", 1, timeout=5)
        self.assertEqual(len(items), sources.JAVBUS_MAX_HITS,
                         "上限要在合并时就截断，不能任由详情页把结果堆爆")
        self.assertEqual(len({i["info_hash"] for i in items}), len(items),
                         "截断之后也不许有重复 hash")


if __name__ == "__main__":
    unittest.main()
