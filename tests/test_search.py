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


class RealCardTest(unittest.TestCase):
    """실제 점검 로그에서 가져온 카드 모양으로 회귀 확인."""

    NAVER_CARD = ("예약\n비토애 럭셔리 글램핑 산청점펜션\n주소보기\n"
                  "경상남도 산청군 신안면 둔철산로 575-26 비토애 럭셔리글램핑 산청점\n"
                  "1공유\n네이버페이\n지도 전화 길찾기 내비게이션")
    YANOLJA_CARD = "펜션\n산청 비토애럭셔리글램핑\n산청군 신안면\n5.0\n(55)\n숙박\n예약마감"

    def test_naver_card_address_and_title(self):
        self.assertTrue(search.address_line(self.NAVER_CARD).startswith("경상남도 산청군"))
        self.assertEqual(search.card_title(self.NAVER_CARD, query="비토애 산청"),
                         "비토애 럭셔리 글램핑 산청점펜션")

    def test_yanolja_card_address_and_title(self):
        self.assertEqual(search.address_line(self.YANOLJA_CARD), "산청군 신안면")
        self.assertEqual(search.card_title(self.YANOLJA_CARD, query="비토애 산청"),
                         "산청 비토애럭셔리글램핑")

    def test_yanolja_card_is_soldout(self):
        status, _ = search.analyze_cards("비토애 산청", [{"text": self.YANOLJA_CARD}],
                                         address="경남 산청군 신안면")
        self.assertEqual(status, search.STATUS_SOLDOUT)

    def test_name_line_is_not_mistaken_for_address(self):
        self.assertEqual(search.address_line("비토애 럭셔리 글램핑 산청점펜션"), "")
        self.assertFalse(search.looks_like_address("리뷰 152"))
        self.assertFalse(search.looks_like_address("1박 120,000원"))

    def test_category_line_is_not_a_title(self):
        self.assertEqual(search.card_title("펜션\n소노벨 변산\n120,000원"), "소노벨 변산")

    def test_place_link_is_followed(self):
        cards = [
            {"text": "지도보기", "url": "https://m.place.naver.com/place/list?query=x"},
            {"text": "비토애 럭셔리 글램핑 산청점\n펜션",
             "url": "https://m.place.naver.com/place/1259756405?entry=pll"},
        ]
        link = search.first_place_link("비토애 산청", cards)
        self.assertEqual(link, "https://m.place.naver.com/accommodation/1259756405/room")

    def test_place_link_ignores_other_places(self):
        cards = [{"text": "제주 카페\n카페", "url": "https://m.place.naver.com/place/999999"}]
        self.assertEqual(search.first_place_link("비토애 산청", cards), "")


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


class PlaceLookupTest(unittest.TestCase):
    CARDS = [
        {"text": "비토애 산청\n펜션\n경남 산청군 시천면 지리산대로 123\n리뷰 12",
         "url": "https://m.place.naver.com/place/1259756405/home"},
        {"text": "비토애 산청 별관\n경남 산청군 단성면 2-3", "url": ""},
        {"text": "전혀 다른 카페\n서울시 강남구", "url": ""},
        {"text": "주소 없는 카드\n리뷰 3", "url": ""},
    ]

    def test_parse_place_cards(self):
        candidates = search.parse_place_cards("비토애 산청", self.CARDS)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["name"], "비토애 산청")
        self.assertEqual(candidates[0]["address"], "경남 산청군 시천면 지리산대로 123")
        self.assertIn("accommodation/1259756405/room", candidates[0]["url"])

    def test_limit(self):
        cards = [{"text": f"비토애 산청 {i}\n경남 산청군 시천면", "url": ""} for i in range(9)]
        self.assertEqual(len(search.parse_place_cards("비토애 산청", cards, limit=3)), 3)

    def test_naver_room_url_variants(self):
        self.assertIn("accommodation/1259756405/room",
                      search.naver_room_url("https://m.place.naver.com/place/1259756405/home"))
        self.assertIn("accommodation/1259756405/room",
                      search.naver_room_url("https://m.map.naver.com/x?code=1259756405"))
        self.assertEqual(search.naver_room_url("https://www.goodchoice.kr/product/1"),
                         "https://www.goodchoice.kr/product/1")
        self.assertEqual(search.naver_room_url(""), "")

    def test_lookup_tries_next_url_when_empty(self):
        class Browser:
            def __init__(self):
                self.visited = []

            def collect_cards(self, url, selectors, wait=5, scrolls=1):
                self.visited.append(url)
                return [] if len(self.visited) == 1 else PlaceLookupTest.CARDS

        browser = Browser()
        config = {"urls": ["https://a/?q={query}", "https://b/?q={query}"],
                  "card_selectors": [], "max_candidates": 5}
        candidates = search.lookup_places(browser, "비토애 산청", config)
        self.assertEqual(len(browser.visited), 2)
        self.assertEqual(candidates[0]["name"], "비토애 산청")

    def test_lookup_survives_browser_error(self):
        class Broken:
            def collect_cards(self, *args, **kwargs):
                raise RuntimeError("크롬 없음")

        config = {"urls": ["https://a/?q={query}"], "card_selectors": []}
        self.assertEqual(search.lookup_places(Broken(), "비토애", config), [])

    def test_config_file_has_lookup_urls(self):
        self.assertTrue(search.load_place_lookup().get("urls"))


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
            candidates = search.site_urls(site)
            self.assertTrue(candidates, site["key"])
            for template in candidates:
                url = search.build_url(template, "비토애 산청", "2026-05-02",
                                       "2026-05-03", 2)
                self.assertTrue(url.startswith("https://"), site["key"])

    def test_site_urls_accepts_single_url(self):
        self.assertEqual(search.site_urls({"url": "https://a"}), ["https://a"])
        self.assertEqual(search.site_urls({"urls": ["https://a", "https://b"]}),
                         ["https://a", "https://b"])
        self.assertEqual(search.site_urls({}), [])

    def test_naver_detail_url_replaces_dates(self):
        original = "https://m.place.naver.com/accommodation/123/room?entry=pll&checkin=20260101&checkout=20260102&guest=2"
        url = search._naver_detail_url(original, "2026-05-02", "2026-05-03", 4)
        self.assertIn("checkin=20260502", url)
        self.assertIn("checkout=20260503", url)
        self.assertNotIn("20260101", url)
        self.assertIn("guest=4", url)


if __name__ == "__main__":
    unittest.main()
