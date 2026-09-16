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


class ForeignPriceTest(unittest.TestCase):
    """아고다·부킹닷컴 등 해외 사이트의 원화 표기."""

    def test_won_symbol(self):
        self.assertEqual(search.find_price("1박 ₩150,000"), "150,000원")

    def test_krw_prefix(self):
        self.assertEqual(search.find_price("KRW 98,000"), "98,000원")

    def test_prefers_korean_won_suffix(self):
        self.assertEqual(search.find_price("120,000원 · ₩999,999"), "120,000원")

    def test_english_soldout(self):
        self.assertTrue(search.is_soldout("Sold out"))
        self.assertTrue(search.is_soldout("No rooms available for your dates"))

    def test_foreign_card_becomes_offer(self):
        card = {"text": "라한셀렉트 경주\n경주시 보문로\n8.7 훌륭해요\n₩210,000", "url": "https://a/1"}
        status, offers = search.analyze_cards("라한셀렉트 경주", [card],
                                              address="경상북도 경주시 보문로")
        self.assertEqual(status, search.STATUS_AVAILABLE)
        self.assertEqual(offers[0].price, "210,000원")


class PriceTest(unittest.TestCase):
    def test_comma_price(self):
        self.assertEqual(search.find_price("1박 120,000원"), "120,000원")

    def test_plain_price(self):
        self.assertEqual(search.find_price("98000원부터"), "98,000원")

    def test_no_price(self):
        self.assertEqual(search.find_price("리뷰 152"), "")


class YeogiSoldOutTest(unittest.TestCase):
    """여기어때는 그 날짜에 안 파는 숙소에 가격 대신 '다른 날짜 확인' 을 띄운다."""

    CARD = ("5성급\n리조트\n쏠비치 남해\n남해군 미조면\n9.5\n1,204명 평가\n다른 날짜 확인")

    def test_other_date_notice_is_soldout(self):
        self.assertTrue(search.is_soldout("다른 날짜 확인"))
        status, offers = search.analyze_cards("쏠비치 남해", [{"text": self.CARD}])
        self.assertEqual(status, search.STATUS_SOLDOUT)
        self.assertEqual(offers, [])

    def test_priced_card_still_available(self):
        card = "5성급\n리조트\n쏠비치 남해\n남해군 미조면\n250,000원"
        status, _ = search.analyze_cards("쏠비치 남해", [{"text": card}])
        self.assertEqual(status, search.STATUS_AVAILABLE)


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


class FuzzyMatchTest(unittest.TestCase):
    """이름 표기가 사이트마다 달라도 같은 숙소로 보는지."""

    YANOLJA_SACHEON = ("펜션\n사천 비토애풀빌라펜션&글램핑\n사천시 서포면\n4.2\n(125)\n"
                       "숙박 15:00~\n8%\n500,000\n460,000\n원~")
    NAVER_SACHEON = "비토애 풀빌라펜션N럭셔리글램핑\n네이버페이\n톡톡\n펜션"
    YANOLJA_SANCHEONG = "펜션\n산청 비토애럭셔리글램핑\n산청군 신안면\n5.0\n(55)\n예약마감"

    def test_word_inserted_in_the_middle(self):
        # '비토애풀빌라&글램핑' vs '비토애풀빌라펜션&글램핑'
        self.assertTrue(search.card_matches("사천 비토애풀빌라&글램핑", self.YANOLJA_SACHEON))

    def test_different_spelling_on_naver(self):
        self.assertTrue(search.card_matches("사천 비토애풀빌라&글램핑", self.NAVER_SACHEON))

    def test_official_name_matches_short_listing(self):
        self.assertTrue(search.card_matches("비토애 럭셔리 글램핑 산청점",
                                            self.YANOLJA_SANCHEONG))

    def test_similar_but_different_place_is_rejected(self):
        self.assertFalse(search.card_matches("사천 비토애풀빌라&글램핑",
                                             "스테이빛토 풀빌라\n네이버페이\n펜션"))

    def test_unrelated_hotels_are_rejected(self):
        for card in ("9.2\n블랙 · 특급 · 호텔\n세인트존스 호텔\n강릉시강릉 강문해변 앞\n210,936\n원",
                     "4성급\n호텔\n나인트리 바이 파르나스 서울 판교\n305,500\n원",
                     "9.3\n블랙 · 리조트 · 호텔\n포레스트 리솜 & 레스트리\n제천시봉양역 차량 11분"):
            self.assertFalse(search.card_matches("사천 비토애풀빌라&글램핑", card), card[:20])

    def test_available_offer_is_read_from_real_card(self):
        status, offers = search.analyze_cards(
            "사천 비토애풀빌라&글램핑", [{"text": self.YANOLJA_SACHEON, "url": "https://y/1"}],
            address="경남 사천시 서포면",
        )
        self.assertEqual(status, search.STATUS_AVAILABLE)
        self.assertEqual(offers[0].price, "460,000원")  # 할인가가 표시된다
        self.assertTrue(offers[0].verified)

    def test_search_term_prefers_keyword(self):
        self.assertEqual(search.search_term({"query": "비토애 럭셔리 글램핑 산청점",
                                             "keyword": "비토애 산청"}), "비토애 산청")
        self.assertEqual(search.search_term({"query": "소노벨 변산"}), "소노벨 변산")


class PlaceCandidateTest(unittest.TestCase):
    """네이버 후보 목록 정리 (실제 점검 로그 기준)."""

    CARDS = [
        {"text": "한우산별천지기타숙박업\n경상남도 의령군 궁류면 한우산길 688", "url": ""},
        {"text": "라한셀렉트 경주호텔\n경상북도 경주시 보문로 338", "url": ""},
        {"text": "라한셀렉트 경주지하주차장주차장\n경상북도 경주시 보문로 338", "url": ""},
        {"text": "라한셀렉트 경주 마켓338양식\n경상북도 경주시 보문로 338", "url": ""},
    ]

    def test_business_category_suffix_removed(self):
        self.assertEqual(search.clean_place_name("한우산별천지기타숙박업"), "한우산별천지")
        self.assertEqual(search.clean_place_name("비토애 산청점부속시설"), "비토애 산청점")

    def test_real_name_is_kept(self):
        self.assertEqual(search.clean_place_name("라한셀렉트 경주호텔"), "라한셀렉트 경주호텔")

    def test_parking_and_restaurants_are_dropped(self):
        names = [c["name"] for c in search.parse_place_cards("라한셀렉트 경주", self.CARDS)]
        self.assertEqual(names, ["라한셀렉트 경주호텔"])

    def test_lodging_candidate_is_kept(self):
        names = [c["name"] for c in search.parse_place_cards("한우산 별천지", self.CARDS[:1])]
        self.assertEqual(names, ["한우산별천지"])


class RomanizedMatchTest(unittest.TestCase):
    """해외 사이트가 영문으로 적은 숙소를 한글 이름과 대조."""

    BOOKING_TARGET = ("Lahan Select Gyeongju\nUnavailable\n"
                      "Too late – no availability for your selected dates at this property!")
    BOOKING_OTHER = ("Benikea Hotel Pohang\nScored 8.2\n"
                     "Pohang • 13.1 miles from Lahan Select Gyeongju\nPer night ₩84,000")

    def test_romanize(self):
        self.assertEqual(search.romanize("경주"), "gyeongju")
        self.assertEqual(search.romanize("서울"), "seoul")

    def test_english_listing_matches(self):
        self.assertTrue(search.card_matches("라한셀렉트 경주", self.BOOKING_TARGET))
        self.assertTrue(search.card_matches("롯데호텔 서울", "Lotte Hotel Seoul\n₩300,000"))
        self.assertTrue(search.card_matches("신라스테이 서대문",
                                            "Shilla Stay Seodaemun\n₩120,000"))

    def test_distance_line_is_not_a_match(self):
        """'15.4 miles from Lahan Select Gyeongju' 가 적힌 다른 숙소 카드."""
        card = ("노을이 아름다운 호미곶 캠핑카\nSup'sil • 15.4 miles from Lahan Select "
                "Gyeongju\nPer night ₩84,000")
        self.assertFalse(search.card_matches("라한셀렉트 경주", card))

    def test_nearby_reference_is_not_a_match(self):
        # 다른 숙소 카드에 '13.1 miles from Lahan Select Gyeongju' 가 적혀 있어도
        # 그 숙소로 보면 안 된다.
        self.assertFalse(search.card_matches("라한셀렉트 경주", self.BOOKING_OTHER))

    def test_different_hotel_in_same_city_is_rejected(self):
        self.assertFalse(search.card_matches("라한셀렉트 경주",
                                             "Hanwha Resort Gyeongju\n8.5\n₩150,000"))
        self.assertFalse(search.card_matches("비토애 산청", "Jeju Shilla Stay\n₩98,000"))

    def test_english_soldout_listing_reads_as_soldout(self):
        status, _ = search.analyze_cards("라한셀렉트 경주",
                                         [{"text": self.BOOKING_TARGET}])
        self.assertEqual(status, search.STATUS_SOLDOUT)


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

    def test_empty_room_phrase_means_soldout(self):
        text = ("네이버 예약 " + "객실 안내 " * 12 + "기준 최대 최소 "
                "예약 가능한 객실이 없습니다 120,000원")
        status, _, _ = search.analyze_naver_detail(text)
        self.assertEqual(status, search.STATUS_SOLDOUT)

    def test_available_requires_a_price(self):
        text = "네이버 예약 페이지 " + "객실 안내 " * 20 + "기준 최대 최소 객실 소개"
        status, _, _ = search.analyze_naver_detail(text)
        self.assertEqual(status, search.STATUS_SOLDOUT)

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

    def test_disabled_sites_are_excluded_by_default(self):
        enabled = {s["key"] for s in search.load_sites()}
        every = {s["key"] for s in search.load_sites(include_disabled=True)}
        self.assertTrue(enabled < every)          # 꺼진 사이트가 존재한다
        self.assertNotIn("hanatour", enabled)     # 동작하지 않아 꺼둔 사이트

    def test_probe_sites_are_marked(self):
        probes = [s["key"] for s in search.load_sites(include_disabled=True)
                  if s.get("probe")]
        for key in probes:
            self.assertFalse(
                next(s for s in search.load_sites(include_disabled=True)
                     if s["key"] == key).get("enabled", True),
                f"{key} 는 점검 중이므로 꺼져 있어야 한다")

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


TRIPLE_LINK = ("https://triple.guide/hotels/d0e0ae59-1ede-4062-baaf-ebc7af354718"
               "?regionId=41ef0101-2663-4f1f-a117-8c5490f4cf44&cityId=KM2144459757"
               "&checkIn=2026-10-04&checkOut=2026-10-05&numberOfAdults=2")

TRIPLE_AVAILABLE = (
    "김해시 숙소 모두 보기\n김해 덴바스타 테마 키즈호텔 펜션\n펜션\n"
    "최저가 예약\n11.20(금) - 11.21(토)\n성인 2\n500,000원\n1박, 세금포함\n"
    "객실 목록\n1박, 세금포함\n룸필터\n"
    "아이스크림룸 - 미온수 무료\n56.2 m²\n최대 5인\n4인 기준\n1개 남음!\n280,000원\n선택\n"
    "기차여행룸 - 미온수 무료\n56.2 m²\n최대 5인\n4인 기준\n1개 남음!\n280,000원\n선택\n"
    "기본정보\n주소\n(50802) 경상남도 김해시 생림면 인제로 545-20\n전화\n+050350528947\n"
)

TRIPLE_SOLDOUT = (
    "김해시 숙소 모두 보기\n김해 덴바스타 테마 키즈호텔 펜션\n펜션\n"
    "최저가 예약\n11.20(금) - 11.21(토)\n성인 2\n판매 완료\n일정 변경\n"
    "객실 목록\n1박, 세금포함\n룸필터\n예약 가능한 객실이 없습니다\n"
    "기본정보\n주소\n(50802) 경상남도 김해시 생림면 인제로 545-20\n전화\n+050350528947\n"
)


class TripleLinkTest(unittest.TestCase):
    def test_finds_link_in_message(self):
        self.assertEqual(search.triple_link(f"이거 봐줘 {TRIPLE_LINK} 고마워"),
                         TRIPLE_LINK)

    def test_ignores_other_links(self):
        self.assertEqual(search.triple_link("https://triple.guide/articles/123"), "")
        self.assertEqual(search.triple_link("https://m.place.naver.com/1234"), "")

    def test_puts_our_dates_and_guests_in(self):
        url = search.triple_detail_url(TRIPLE_LINK, "2026-11-20", "2026-11-21", 4)
        self.assertIn("checkIn=2026-11-20", url)
        self.assertIn("checkOut=2026-11-21", url)
        self.assertIn("numberOfAdults=4", url)
        # 원래 날짜는 남아 있으면 안 된다
        self.assertNotIn("checkIn=2026-10-04", url)
        self.assertNotIn("numberOfAdults=2", url)
        # 지역 정보는 그대로 둔다
        self.assertIn("cityId=KM2144459757", url)

    def test_forces_fresh_render(self):
        # 이 값이 없으면 트리플이 캐시된 기본 날짜 화면을 준다
        url = search.triple_detail_url(TRIPLE_LINK, "2026-11-20", "2026-11-21", 2)
        self.assertIn("skipInitialCache=true", url)
        again = search.triple_detail_url(url, "2026-12-01", "2026-12-02", 2)
        self.assertEqual(again.count("skipInitialCache=true"), 1)

    def test_link_without_query(self):
        url = search.triple_detail_url("https://triple.guide/hotels/abc",
                                       "2026-11-20", "2026-11-21", 2)
        self.assertTrue(url.startswith("https://triple.guide/hotels/abc?"))


class TripleDetailTest(unittest.TestCase):
    def test_rooms_on_sale(self):
        status, rooms = search.analyze_triple_detail(TRIPLE_AVAILABLE)
        self.assertEqual(status, search.STATUS_AVAILABLE)
        self.assertEqual(rooms, 2)

    def test_sold_out(self):
        status, rooms = search.analyze_triple_detail(TRIPLE_SOLDOUT)
        self.assertEqual(status, search.STATUS_SOLDOUT)
        self.assertEqual(rooms, 0)

    def test_preview_price_alone_is_not_available(self):
        # '최저가 예약' 미리보기에만 값이 있고 객실 목록은 마감인 경우
        self.assertEqual(search.analyze_triple_detail(TRIPLE_SOLDOUT)[0],
                         search.STATUS_SOLDOUT)

    def test_empty_page_is_unknown(self):
        self.assertEqual(search.analyze_triple_detail("잠시만요")[0],
                         search.STATUS_UNKNOWN)


class TripleSearchWatchTest(unittest.TestCase):
    class FakeBrowser:
        def __init__(self, text):
            self.text = text
            self.opened = []

        def page_text(self, url, **kwargs):
            self.opened.append(url)
            return self.text

        def collect_cards(self, *args, **kwargs):
            return []

        def body_text(self, limit=2000):
            return ""

    def test_registered_link_is_checked(self):
        watch = {"query": "덴바스타", "keyword": "덴바스타", "checkin": "2026-11-20",
                 "checkout": "2026-11-21", "guests": 2, "triple": TRIPLE_LINK,
                 "address": "경상남도 김해시 생림면 인제로 545-20"}
        browser = self.FakeBrowser(TRIPLE_AVAILABLE)
        results = search.search_watch(browser, watch, sites=[])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].key, "triple")
        self.assertTrue(results[0].available)
        self.assertIn("checkIn=2026-11-20", browser.opened[0])

    def test_no_link_means_no_triple_result(self):
        watch = {"query": "덴바스타", "keyword": "덴바스타", "checkin": "2026-11-20",
                 "checkout": "2026-11-21", "guests": 2}
        results = search.search_watch(self.FakeBrowser(""), watch, sites=[])
        self.assertEqual(results, [])


class WrongPlaceTest(unittest.TestCase):
    """이름이 살짝 겹치는 다른 숙소를 걸러내는지 (실제로 겪은 오탐)."""

    ADDRESS = "경상북도 경주시 천북면 천북남로 558-27 스테이루나"

    def test_one_letter_coincidence_is_not_a_match(self):
        # '사우나'의 '나' 한 글자 때문에 '스테이루나'로 통했었다
        for text in ("향남 스테이13 호텔\n사우나\n150,000원",
                     "향남 스테이13 호텔\n루프탑\n150,000원",
                     "향남 스테이13 호텔\n150,000원\n스파,사우나 이용 가능"):
            self.assertFalse(search.card_matches("스테이루나", text), text)

    def test_real_place_still_matches(self):
        self.assertTrue(search.card_matches(
            "스테이루나", "스테이루나 펜션\n경주시 천북면\n250,000원"))

    def test_name_inserted_in_the_middle_still_matches(self):
        # 이름 중간에 단어가 끼어드는 경우는 계속 통해야 한다
        self.assertTrue(search.card_matches(
            "비토애 산청", "사천 비토애풀빌라펜션&글램핑\n460,000원"))

    def test_other_city_is_dropped(self):
        cards = [{"text": "스테이루나 호텔\n경기 화성시 향남읍\n150,000원",
                  "url": "https://example.com/1"}]
        status, offers = search.analyze_cards("스테이루나", cards,
                                              address=self.ADDRESS)
        self.assertEqual(status, search.STATUS_NONE)
        self.assertEqual(offers, [])

    def test_same_city_is_kept(self):
        cards = [{"text": "스테이루나 펜션\n경상북도 경주시 천북면\n250,000원",
                  "url": "https://example.com/2"}]
        status, offers = search.analyze_cards("스테이루나", cards,
                                              address=self.ADDRESS)
        self.assertEqual(status, search.STATUS_AVAILABLE)
        self.assertTrue(offers[0].verified)

    def test_card_without_a_region_is_not_judged(self):
        # 지역이 안 적힌 카드는 '모르는 것'이지 '다른 것'이 아니다
        cards = [{"text": "스테이루나 펜션\n250,000원", "url": "https://example.com/3"}]
        status, offers = search.analyze_cards("스테이루나", cards,
                                              address=self.ADDRESS)
        self.assertEqual(status, search.STATUS_AVAILABLE)

    def test_region_in_the_name_is_not_mistaken_for_a_conflict(self):
        # '라한셀렉트 경주' 처럼 이름에 지역이 든 경우
        self.assertFalse(search.address_conflicts(
            "경상북도 경주시 신평동", "라한셀렉트 경주\n210,000원",
            ignore="라한셀렉트 경주"))


class RealCardTest(unittest.TestCase):
    """실제로 사이트에서 읽어온 카드 원문으로 확인 (스테이루나 오탐 건)."""

    WRONG = ("모텔\n향남 스테이13 호텔\n화성시 만세구\n9.5\n260명 평가\n대실\n"
             "5시간\n150,000\n원\n이 가격으로 남은 객실 1개\n감성 루프탑, 최대 12")
    RIGHT = "풀빌라\n펜션\n경주 스테이 루나\n경주시MCY파크 차량 9분\n10\n3명 평가\n다른 날짜 확인"
    BOOKING_FAR = ("청라 스테이 22층 뷰 공항 송도 검단 김포\n"
                   "Kojan • 15.3 miles from 스테이루헤 Stayruhe in Hongdae\nHot tub")

    def test_wrong_hotel_is_rejected(self):
        self.assertFalse(search.card_matches("스테이루나", self.WRONG))

    def test_right_place_is_accepted(self):
        self.assertTrue(search.card_matches("스테이루나", self.RIGHT))

    def test_distance_line_does_not_drag_other_places_in(self):
        # 부킹닷컴은 카드마다 '15.3 miles from OO' 로 기준 숙소를 적어둔다
        self.assertFalse(search.card_matches("스테이루나", self.BOOKING_FAR))


class PlacePickTest(unittest.TestCase):
    """이름이 같은 네이버 장소가 여럿일 때 제대로 고르는지."""

    CARDS = [
        {"text": "스테이 루나\n네이버페이\n톡톡\n민박",
         "url": "https://m.place.naver.com/place/2070273740?entry=pll"},
        {"text": "스테이루나\n네이버페이\n톡톡\n쿠폰\n게스트하우스",
         "url": "https://m.place.naver.com/place/2004105147?entry=pll"},
        {"text": "스테이루나\n네이버페이\n펜션",
         "url": "https://m.place.naver.com/place/1735150004?entry=pll"},
    ]

    def test_picks_the_one_matching_the_registered_name(self):
        url = search.first_place_link("스테이루나", self.CARDS,
                                      prefer="스테이루나펜션")
        self.assertIn("1735150004", url)   # 민박도 게스트하우스도 아닌 펜션

    def test_falls_back_to_the_search_word(self):
        url = search.first_place_link("스테이루나", self.CARDS)
        self.assertIn("accommodation", url)

    def test_no_place_cards(self):
        self.assertEqual(search.first_place_link("스테이루나", [
            {"text": "광고", "url": "https://example.com"}]), "")
