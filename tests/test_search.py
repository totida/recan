import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import search  # noqa: E402


class MatchingTest(unittest.TestCase):
    def test_matches_ignoring_spaces(self):
        self.assertTrue(search.card_matches("비토애 산청", "산청 비토애펜션\n120,000원"))

    def test_partial_token_match(self):
        self.assertTrue(search.card_matches("소노벨 변산", "소노벨 변산 오션뷰\n210,000원"))

    def test_unrelated_card_is_rejected(self):
        self.assertFalse(search.card_matches("비토애 산청", "제주 신라스테이\n98,000원"))


class PriceTest(unittest.TestCase):
    def test_comma_price(self):
        self.assertEqual(search.find_price("1박 120,000원"), "120,000원")

    def test_plain_price(self):
        self.assertEqual(search.find_price("98000원부터"), "98,000원")

    def test_no_price(self):
        self.assertEqual(search.find_price("리뷰 152"), "")


class AnalyzeCardsTest(unittest.TestCase):
    def test_available_card(self):
        cards = [
            {"text": "비토애 산청\n디럭스 더블\n120,000원", "url": "https://x/1"},
            {"text": "다른 펜션\n90,000원", "url": "https://x/2"},
        ]
        status, offers = search.analyze_cards("비토애 산청", cards, "https://search")
        self.assertEqual(status, search.STATUS_AVAILABLE)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].price, "120,000원")
        self.assertEqual(offers[0].url, "https://x/1")

    def test_soldout_card(self):
        cards = [{"text": "비토애 산청\n예약마감", "url": "https://x/1"}]
        status, offers = search.analyze_cards("비토애 산청", cards, "https://search")
        self.assertEqual(status, search.STATUS_SOLDOUT)
        self.assertEqual(offers, [])

    def test_no_matching_card(self):
        cards = [{"text": "전혀 다른 숙소\n80,000원", "url": ""}]
        status, offers = search.analyze_cards("비토애 산청", cards, "https://search")
        self.assertEqual(status, search.STATUS_NONE)

    def test_matched_without_price_is_unknown(self):
        cards = [{"text": "비토애 산청\n펜션 · 산청군", "url": ""}]
        status, _ = search.analyze_cards("비토애 산청", cards, "https://search")
        self.assertEqual(status, search.STATUS_UNKNOWN)

    def test_duplicate_cards_collapse(self):
        cards = [
            {"text": "비토애 산청\n디럭스\n120,000원", "url": "https://x/1"},
            {"text": "비토애 산청\n디럭스\n120,000원", "url": "https://x/1"},
        ]
        _, offers = search.analyze_cards("비토애 산청", cards, "")
        self.assertEqual(len(offers), 1)

    def test_offer_limit(self):
        cards = [
            {"text": f"비토애 산청\n객실{i}\n{100 + i},000원", "url": ""} for i in range(6)
        ]
        _, offers = search.analyze_cards("비토애 산청", cards, "", limit=3)
        self.assertEqual(len(offers), 3)


class AddressTest(unittest.TestCase):
    ADDRESS = "경상남도 산청군 시천면 지리산대로 123"

    def test_tokens_drop_numbers(self):
        groups = search.address_tokens("경남 산청군 123-4")
        self.assertEqual(len(groups), 2)

    def test_matching_region_scores(self):
        score = search.address_match_score(
            self.ADDRESS, "비토애 산청\n산청군 시천면\n120,000원", ignore="비토애 산청"
        )
        self.assertTrue(search.address_verified(score))

    def test_other_region_fails(self):
        score = search.address_match_score(
            self.ADDRESS, "비토애 산청\n제주시 애월읍\n120,000원", ignore="비토애 산청"
        )
        self.assertFalse(search.address_verified(score))

    def test_no_registered_address_skips_check(self):
        self.assertIsNone(search.address_match_score("", "아무 텍스트"))
        self.assertTrue(search.address_verified(None))

    def test_address_line_extraction(self):
        line = search.address_line("비토애 산청\n경남 산청군 시천면 123\n120,000원")
        self.assertEqual(line, "경남 산청군 시천면 123")

    def test_analyze_prefers_address_match(self):
        cards = [
            {"text": "비토애 산청\n제주시 애월읍\n120,000원", "url": "https://x/1"},
            {"text": "비토애 산청\n산청군 시천면\n150,000원", "url": "https://x/2"},
        ]
        status, offers = search.analyze_cards(
            "비토애 산청", cards, "https://search", address=self.ADDRESS
        )
        self.assertEqual(status, search.STATUS_AVAILABLE)
        self.assertEqual([o.price for o in offers], ["150,000원"])
        self.assertTrue(offers[0].verified)

    def test_analyze_flags_unverified_when_no_card_has_address(self):
        cards = [{"text": "비토애 산청\n디럭스\n120,000원", "url": ""}]
        status, offers = search.analyze_cards(
            "비토애 산청", cards, "", address=self.ADDRESS
        )
        self.assertEqual(status, search.STATUS_AVAILABLE)
        self.assertFalse(offers[0].verified)

    def test_verified_none_without_address(self):
        cards = [{"text": "비토애 산청\n디럭스\n120,000원", "url": ""}]
        _, offers = search.analyze_cards("비토애 산청", cards, "")
        self.assertIsNone(offers[0].verified)


class NaverDetailTest(unittest.TestCase):
    def test_vacancy_found(self):
        text = "네이버 예약 페이지 " + ("객실 안내 " * 12) + ("기준 최대 최소 예약마감 " * 2) + "기준 최대 최소 120,000원"
        status, rooms, closed = search.analyze_naver_detail(text)
        self.assertEqual(status, search.STATUS_AVAILABLE)
        self.assertEqual((rooms, closed), (3, 2))

    def test_all_closed(self):
        text = "네이버 예약 페이지 " + ("객실 안내 " * 12) + ("기준 최대 최소 예약마감 " * 3)
        status, rooms, closed = search.analyze_naver_detail(text)
        self.assertEqual(status, search.STATUS_SOLDOUT)
        self.assertEqual((rooms, closed), (3, 3))

    def test_short_page_is_unknown(self):
        status, _, _ = search.analyze_naver_detail("로딩중")
        self.assertEqual(status, search.STATUS_UNKNOWN)


class UrlTest(unittest.TestCase):
    def test_all_placeholders(self):
        template = "https://s/?q={query}&a={checkin}&b={checkout}&c={checkin_compact}&d={checkout_dot}&g={guests}&n={nights}"
        url = search.build_url(template, "비토애 산청", "2026-05-02", "2026-05-04", 4)
        self.assertIn("q=%EB%B9%84%ED%86%A0%EC%95%A0%20%EC%82%B0%EC%B2%AD", url)
        self.assertIn("a=2026-05-02", url)
        self.assertIn("c=20260502", url)
        self.assertIn("d=2026.05.04", url)
        self.assertIn("g=4", url)
        self.assertIn("n=2", url)

    def test_configured_sites_build(self):
        for site in search.load_sites():
            url = search.build_url(site["url"], "비토애 산청", "2026-05-02", "2026-05-03", 2)
            self.assertTrue(url.startswith("https://"), site["key"])

    def test_naver_detail_url_replaces_dates(self):
        original = "https://m.place.naver.com/accommodation/123/room?entry=pll&checkin=20260101&checkout=20260102&guest=2"
        url = search._naver_detail_url(original, "2026-05-02", "2026-05-03", 4)
        self.assertIn("checkin=20260502", url)
        self.assertIn("checkout=20260503", url)
        self.assertNotIn("20260101", url)
        self.assertIn("guest=4", url)


if __name__ == "__main__":
    unittest.main()
