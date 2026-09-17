import json
import socket
import sys
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import api as api_mod
from app import sources

DMHY_LIST_ROW = """
<tr class="">
\t<td width="98">今天 15:32<span style="display: none;">2026/09/16 15:32</span></td>
\t<td width="6%"><a href="/topics/list/sort_id/2">動畫</a></td>
\t<td class="title"><a href="/topics/view/727163_LoliHouse_Demo.html">
\t[LoliHouse] Demo Title [WebRip 1080p]</a></td>
\t<td><a class="download-arrow" href="magnet:?xt=urn:btih:{h}&dn=&tr=udp%3A%2F%2Ft.io%3A80">
\t</a></td>
\t<td>991.7MB</td>
\t<td>42</td>
\t<td>7</td>
\t<td>3</td>
\t<td>LoliHouse</td>
</tr>
"""

DMHY_PAGE = (
    '<html><div class="clear"><table class="tablesorter" id="topic_list">'
    "<thead><tr><th>日期</th></tr></thead><tbody>"
    + DMHY_LIST_ROW.format(h="a" * 40)
    + DMHY_LIST_ROW.format(h="b" * 40)
    + "</tbody></table></div></html>"
)

TPB_ROW = """
<tr>
<td class="vertTh"><a href="/browse/207">Video &gt; HD - Movies</a></td>
<td><a href="/torrent/83970962/Some_Title" title="Details">Some Title 1080p</a></td>
<td>09-14&nbsp;03:20</td>
<td><nobr><a href="magnet:?xt=urn:btih:{h}" title="Download">m</a></nobr></td>
<td align="right">1.96&nbsp;GiB</td>
<td align="right">5724</td>
<td align="right">1354</td>
<td><a href="/user/jajaja/">jajaja</a></td>
</tr>
"""

TPB_PAGE = (
    "<html><div id=\"searchResult\"><table>"
    "<tr class='header'><th>Type</th></tr>"
    + TPB_ROW.format(h="C" * 40)
    + "</table></div></html>"
)


class TimeoutBudgetTest(unittest.TestCase):

    def test_timeout_is_not_retried(self):
        calls = []

        class Opener:
            def open(self, req, timeout=None):
                calls.append(timeout)
                raise urllib.error.URLError(socket.timeout("timed out"))

        with mock.patch.object(sources, "_opener", lambda url, lax=False: Opener()):
            with self.assertRaises(Exception):
                sources.http_get("https://example.com/x", timeout=3)
        self.assertEqual(len(calls), 1,
                         "超时已经把源级预算花光，重试只会让用户白等一倍")

    def test_other_transport_error_still_retries(self):
        calls = []

        class Opener:
            def open(self, req, timeout=None):
                calls.append(timeout)
                raise urllib.error.URLError("connection reset by peer")

        with mock.patch.object(sources, "_opener", lambda url, lax=False: Opener()):
            with mock.patch.object(sources, "_retries", lambda: 1):
                with self.assertRaises(Exception):
                    sources.http_get("https://example.com/x", timeout=3)
        self.assertEqual(len(calls), 2, "非超时故障仍应重试")

    def test_is_timeout_detects_wrapped_and_plain(self):
        self.assertTrue(sources._is_timeout(TimeoutError("x")))
        self.assertTrue(sources._is_timeout(
            urllib.error.URLError(socket.timeout("x"))))
        self.assertTrue(sources._is_timeout(
            urllib.error.URLError("handshake operation timed out")))
        self.assertFalse(sources._is_timeout(
            urllib.error.URLError("connection refused")))


class CaptchaWallTest(unittest.TestCase):

    def error(self, code, body):
        return urllib.error.HTTPError(
            "https://example.com/search", code, "err", {}, _Reader(body))

    def test_cloudflare_challenge_is_blocked_not_throttled(self):
        exc = self.error(429, b"<html>One more step Please complete the "
                              b"security check to access")
        self.assertTrue(sources._captcha_wall(exc))

    def test_plain_429_is_still_throttling(self):
        self.assertFalse(sources._captcha_wall(
            self.error(429, b'{"error":"slow down"}')))

    def test_blocked_maps_to_rejection_not_self_healing_rate_limit(self):
        outcome, code = api_mod.classify(
            False, 0, sources.BLOCKED_TEXT, 1200)
        self.assertEqual(outcome, api_mod.OUTCOME_BLOCKED,
                         "验证码墙不会自愈，不该报成 429 限流")
        self.assertEqual(api_mod.OUTCOME_STATE[outcome], "err")
        self.assertEqual(api_mod.OUTCOME_TEXT[outcome], "人机验证拦截")
        self.assertIn(outcome, api_mod.FATAL_OUTCOMES)

    def test_real_429_stays_self_healing(self):
        outcome, _code = api_mod.classify(False, 0, "HTTP 429", 900)
        self.assertEqual(outcome, api_mod.OUTCOME_429)
        self.assertNotIn(outcome, api_mod.FATAL_OUTCOMES)

    def test_blocked_reaches_user_as_its_own_fact(self):
        err = str(sources.Blocked(sources.BLOCKED_TEXT))
        outcome, code = api_mod.classify(False, 0, err, 900)
        self.assertEqual(api_mod.outcome_text(outcome, code), "人机验证拦截",
                         "用户要看到真实原因，不是被翻译成 403")

    def test_captcha_text_detects_returned_challenge_body(self):
        self.assertTrue(sources._captcha_text(
            "<!DOCTYPE html><html><title>Just a moment...</title>"))
        self.assertFalse(sources._captcha_text('{"results":[]}'))
        self.assertFalse(sources._captcha_text(""))


class _Reader:

    def __init__(self, body):
        self._body = body

    def read(self, size=-1):
        if size is None or size < 0:
            body, self._body = self._body, b""
            return body
        body, self._body = self._body[:size], self._body[size:]
        return body

    def close(self):
        pass


class DmhyListTest(unittest.TestCase):

    def parse(self, page=DMHY_PAGE):
        with mock.patch.object(sources, "http_get", lambda url, **kw: page):
            return sources._search_dmhy("demo", timeout=5)

    def test_reads_size_from_list_page(self):
        items = self.parse()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["size"], sources.parse_size("991.7MB"),
                         "RSS 没有体积字段，必须从列表页取")
        self.assertTrue(all(i["size"] for i in items))

    def test_reads_seeders_and_fetch_link(self):
        item = self.parse()[0]
        self.assertEqual(item["seeders"], 42)
        self.assertTrue(item["fetch"]["url"].startswith(
            "https://share.dmhy.org/topics/view/"))

    def test_pub_date_uses_beijing_time(self):
        item = self.parse()[0]
        self.assertAlmostEqual(item["added"], sources._ts_from_naive_cn(
            "2026-09-16T15:32:00"), places=0)

    def test_bad_rows_do_not_shorten_later_pages(self):
        rows = 80
        good = "".join(
            DMHY_LIST_ROW.format(h=f"{i:040x}") for i in range(rows - 1))
        body = (f'<table id="topic_list"><tbody>{good}'
                "<tr><td>junk</td></tr></tbody></table>")
        items, total_rows, ok = sources._parse_dmhy_list(
            body, "https://share.dmhy.org")
        self.assertTrue(ok)
        self.assertEqual(total_rows, rows,
                         "分页判断要按原始行数，否则丢一行就误判成最后一页")
        self.assertEqual(len(items), rows - 1)

    def test_missing_table_is_reported_unparsable(self):
        _items, _rows, ok = sources._parse_dmhy_list(
            "<html>nothing here</html>", "https://share.dmhy.org")
        self.assertFalse(ok, "页面结构变了要能识别，好去回落 RSS")

    def test_real_empty_table_is_not_a_parse_failure(self):
        body = '<table id="topic_list"><tbody></tbody></table>'
        _items, rows, ok = sources._parse_dmhy_list(body, "")
        self.assertTrue(ok)
        self.assertEqual(rows, 0)

    def test_empty_list_falls_back_to_rss(self):
        rss = ("<rss><item><title>Fallback</title>"
               f"<guid>magnet:?xt=urn:btih:{'d' * 40}</guid>"
               "<pubDate>Wed, 16 Sep 2026 15:32:48 +0800</pubDate></item></rss>")
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            return rss if "rss" in url else "<html>no table here</html>"

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_dmhy("demo", timeout=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Fallback")
        self.assertTrue(any("rss.xml" in u for u in calls), "列表页空了必须回落 RSS")

    def test_empty_result_does_not_retry_rss(self):
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            return '<table id="topic_list"><tbody></tbody></table>'

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_dmhy("nothing", timeout=5)
        self.assertEqual(items, [])
        self.assertFalse(any("rss" in u for u in calls),
                         "真是 0 条就别再打 RSS，那是正常结果不是解析失败")


class TpbCellTest(unittest.TestCase):

    def parse(self, page=TPB_PAGE):
        with mock.patch.object(sources, "http_get", lambda url, **kw: page):
            return sources._search_tpb_mirror("1080p", timeout=5)

    def test_size_seeders_leechers_are_filled(self):
        items = self.parse()
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["size"], sources.parse_size("1.96 GiB"))
        self.assertEqual(it["seeders"], 5724)
        self.assertEqual(it["leechers"], 1354)

    def test_added_parsed_from_month_day_cell(self):
        it = self.parse()[0]
        self.assertIsNotNone(it["added"], "TPB 的 09-14 03:20 要能解析")
        self.assertLess(it["added"], time.time())

    def test_today_and_yesterday_are_relative(self):
        now = time.time()
        self.assertLess(abs(sources._tpb_added("Today 03:55") - now), 86400)
        self.assertLess(abs(sources._tpb_added("Y-day 21:00") - now), 2 * 86400)

    def test_unparsable_date_returns_none(self):
        self.assertIsNone(sources._tpb_added(""))
        self.assertIsNone(sources._tpb_added("not a date"))

    def test_base_override_disables_failover(self):
        urls = []

        def fake_get(url, **kw):
            urls.append(url)
            return TPB_PAGE

        with mock.patch.object(sources, "http_get", fake_get):
            sources._search_tpb_mirror("q", 1, 5, "https://my.mirror")
        self.assertEqual(len(urls), 1)
        self.assertTrue(urls[0].startswith("https://my.mirror/"),
                        "配了自定义镜像就只用它，不要去试别的")

    def test_failover_on_transport_error(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            if len(seen) == 1:
                raise OSError("first mirror down")
            return TPB_PAGE

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_tpb_mirror("q", 1, 5)
        self.assertEqual(len(items), 1)
        self.assertGreater(len(seen), 1)

    def test_failover_when_landing_page_returned(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            if len(seen) == 1:
                return "<html><body>mirror landing page</body></html>"
            return TPB_PAGE

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_tpb_mirror("q", 1, 5)
        self.assertEqual(len(items), 1, "镜像返回落地页说明它坏了，要换下一个")

    def test_no_hits_returns_empty_without_trying_others(self):
        seen = []

        def fake_get(url, **kw):
            seen.append(url)
            return ('<html><div id="searchResult">No hits</div></html>')

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_tpb_mirror("q", 1, 5)
        self.assertEqual(items, [])
        self.assertEqual(len(seen), 1,
                         "真是 0 条就别再试其他镜像，那是正常结果")

    def test_raises_when_all_mirrors_fail(self):
        def boom(url, **kw):
            raise OSError("down")

        with mock.patch.object(sources, "http_get", boom):
            with self.assertRaises(OSError):
                sources._search_tpb_mirror("q", 1, 5)

    def test_mirror_list_has_several_entries(self):
        self.assertGreaterEqual(len(sources.TPB_MIRRORS), 2)
        self.assertEqual(sources.TPB_MIRRORS[0],
                         sources.DEFAULT_BASES["tpb"],
                         "列表第一个要与默认地址一致")

    def test_failover_stays_within_source_budget(self):
        def slow_fail(url, **kw):
            time.sleep(1.2)
            raise OSError("hangs then fails")

        t0 = time.monotonic()
        with mock.patch.object(sources, "http_get", slow_fail):
            with self.assertRaises(OSError):
                sources._search_tpb_mirror("q", 1, 3)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 3 + 2.5,
                        "一个挂起的镜像不该吃光预算，否则后面的镜像没机会")


class MikanTimeTest(unittest.TestCase):

    def test_naive_iso_uses_china_time(self):
        got = sources._ts_from_naive_cn("2026-09-16T21:00:45.453639")
        expect = sources._ts_from_iso("2026-09-16T21:00:45.453639+08:00")
        self.assertAlmostEqual(got, expect, places=3)

    def test_zoned_timestamps_are_left_to_iso_parser(self):
        self.assertIsNone(sources._ts_from_naive_cn("2026-09-16T14:30:11.397Z"))
        self.assertIsNone(sources._ts_from_naive_cn("2026-09-16T14:30:11+00:00"))

    def test_mikan_item_is_not_in_the_future(self):
        page = ("<rss><item><title>Show</title>"
                "<link>https://mikanani.me/Home/Episode/" + "a" * 40 + "</link>"
                "<contentLength>1024</contentLength>"
                "<pubDate>2026-09-16T21:00:45.453639</pubDate></item></rss>")
        with mock.patch.object(sources, "http_get", lambda url, **kw: page):
            items = sources._search_mikan("show", timeout=5)
        self.assertEqual(len(items), 1)
        self.assertLess(items[0]["added"], time.time() + 60,
                        "无时区标注的 pubDate 按 UTC 解析会落到未来")


class ConcurrentPageTest(unittest.TestCase):

    def test_dmhy_fetches_pages_concurrently(self):
        starts = []

        def slow_get(url, **kw):
            starts.append(time.monotonic())
            time.sleep(0.25)
            return DMHY_PAGE

        t0 = time.monotonic()
        with mock.patch.object(sources, "http_get", slow_get):
            sources._search_dmhy("demo", timeout=5)
        elapsed = time.monotonic() - t0
        self.assertEqual(len(starts), sources.DMHY_PAGES)
        self.assertLess(elapsed, 0.25 * sources.DMHY_PAGES * 0.7,
                        "翻页要并发，否则源级预算内拿不到足够页数")

    def test_eztv_skips_extra_pages_when_first_is_short(self):
        calls = []

        def fake_get(url, **kw):
            page = int(str(url).rsplit("page=", 1)[-1])
            calls.append(page)
            if page == 1:
                return json.dumps({"torrents": [
                    {"title": "only one", "hash": "a" * 40}]})
            return json.dumps({"torrents": [
                {"title": "x", "hash": "b" * 40}]})

        with mock.patch.object(sources, "http_get", fake_get):
            sources._search_eztv("only", timeout=5)
        self.assertEqual(calls, [1],
                         "首页不满即到底，不该再多打请求")

    def test_bitsearch_reads_full_pages(self):
        def fake_get(url, **kw):
            page = int(str(url).split("page=", 1)[1].split("&", 1)[0])
            return json.dumps({"results": [
                {"infohash": f"{page:02x}{i:04x}" + "a" * 34,
                 "title": f"row {page}.{i}", "size": 10,
                 "seeders": 1, "leechers": 1,
                 "updatedAt": "2026-09-16T14:30:11.397Z"}
                for i in range(sources.BITSEARCH_PAGE_SIZE)]})

        with mock.patch.object(sources, "http_get", fake_get):
            items = sources._search_bitsearch("demo", 1, timeout=5)
        self.assertEqual(len(items), sources.BITSEARCH_MAX_HITS)
        self.assertEqual(sources.BITSEARCH_PAGE_SIZE, 100,
                         "官方接口默认只给 20 条，必须显式传 limit")

    def test_bitsearch_raises_when_every_page_fails(self):
        def boom(url, **kw):
            raise urllib.error.HTTPError(url, 500, "boom", {}, _Reader(b""))

        with mock.patch.object(sources, "http_get", boom):
            with self.assertRaises(urllib.error.HTTPError):
                sources._search_bitsearch("demo", 1, timeout=5)


if __name__ == "__main__":
    unittest.main()
