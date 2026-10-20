"""네이버 호텔 가격비교 (hotels.naver.com)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import search  # noqa: E402


def lines(text):
    """점검 로그는 줄바꿈을 ' / ' 로 찍는다. 원래 화면 글자로 되돌린다."""
    return text.replace(" / ", "\n")


# 2026-10-20 check-url.yml 실측 — 토요코인 서울강남 (숙소 번호 1745414542), 성인 2
# 12/09~12/10: 방이 있다. 아래 '함께 찾는 호텔' 에 다른 토요코인 지점 값이 붙는다.
RATES_OPEN = lines(
    "Naver / 여행상품 / 여행정보 / 로그인 / 마이페이지 / 여행핫딜 / 항공 / 호텔 / 패키지 / For U / "
    "이전으로 이동 / 토요코인 서울강남 / 변경 / 더보기 / 서울특별시서초구서초동 / "
    "토요코인 서울강남3급 / 12.09.-12.10. (1박) / 111,216원 / 전체 가격 비교하기 / 111,216원~ / "
    "12.09.수-12.10.목, 1박2명 / 전체 가격 비교하기 / 공유 / 무료 조식 서비스가 제공되는 가성비 좋은 호텔 / "
    "서울 서초구 강남대로 323  위치길찾기거리뷰 / 체크인 15:00체크아웃 10:00 / "
    "요약 / 가격비교 / 사진 / 관련글 / 리뷰 / 지도 / 시설정보 / 5/9 / 12.09. 수 - 12.10. 목, 1박 / "
    "성인2 / 조건 / 객실유형 / 여행사 / 전체 / 무료예약취소 / 조식포함 / 1박 최저가 추이 / "
    "평균 가격보다 3% / 높음 / 가격 낮은순 / 1박 세금 포함 / "
    "판매 사이트에서 숙소명, 위치, 가격 등을 재확인하세요. / 111,216원~ / 더보기 / 네이버페이 / "
    "123,200원~ / 더보기 / 제공 / 트립어드바이저 / 광고 / 더블룸, 금연 / 무료예약취소조식 / "
    "무료취소 26.12.08.(화) 14:59 전까지 / 111,216원 / 더블룸 / 무료예약취소조식 / "
    "무료취소 26.12.08.(화) 14:59 전까지 / 123,200원 / 네이버페이 / 최대 6,160원 적립 / "
    "항공+호텔 둘 다 예약하면 5% 추가적립 / 트윈룸 / 무료예약취소조식 / "
    "무료취소 26.12.08.(화) 14:59 전까지 / 126,500원 / 네이버페이 / 최대 6,325원 적립 / "
    "이 호텔을 본 다른 사람이  / 함께 찾는 호텔이에요! / 위브스위트 선유 파크사이드 / 8.5 / "
    "99,956원~ / 케이브 료칸 호텔 바이 아늑 성신여대점 / 6.5 / 109,608원~ / "
    "토요코인 서울동대문1 / 8.7 / 90,651원~ / 추천 호텔 더보기 / 실제 예약이 많은 호텔  / "
    "확인 해보세요! / 에이든 바이 베스트웨스턴 청담 / 8.6 / 149,827원~ / NAVER")

# 10/20~10/21: 방이 없을 때의 짧은 화면 (숙소 이름도 안 나온다)
RATES_EMPTY_SHORT = lines(
    "Naver / 여행상품 / 여행정보 / 로그인 / 마이페이지 / 여행핫딜 / 항공 / 호텔 / 패키지 / For U / "
    "이전으로 이동 / 변경 / 더보기 / 요약 / 지도 / 10.20. 화 - 10.21. 수, 1박 / 성인2 / "
    "선택하신 일정에 예약 가능한 객실이 없습니다. / 일정을 변경하거나 목적지를 변경해주세요. / "
    "일정 변경 / 목적지 변경 / 로그인 / 전체서비스 / 공유하기 / NAVER")

# 12/31~01/01: 방이 없는데 아래 '함께 찾는 호텔' 에 다른 숙소 값(118,260원~)이 있다.
# 페이지 전체에서 값을 찾으면 마감된 날을 예약 가능으로 읽는다.
RATES_EMPTY_WITH_OTHERS = lines(
    "Naver / 여행상품 / 여행정보 / 로그인 / 마이페이지 / 여행핫딜 / 항공 / 호텔 / 패키지 / For U / "
    "이전으로 이동 / 토요코인 서울강남 / 변경 / 더보기 / 서울특별시서초구서초동 / 토요코인 서울강남3급 / "
    "예약 가능한 객실 없음 / 일정 변경하기 / 예약 가능한 객실 없음 / 12.31.목-01.01.금, 1박2명 / "
    "일정 변경하기 / 공유 / 무료 조식 서비스가 제공되는 가성비 좋은 호텔 / "
    "서울 서초구 강남대로 323  위치길찾기거리뷰 / 요약 / 가격비교 / 사진 / 관련글 / 리뷰 / 지도 / "
    "시설정보 / 4/9 / 12.31. 목 - 01.01. 금, 1박 / 성인2 / "
    "선택하신 일정에 예약 가능한 객실이 없습니다. / 일정을 변경하거나 목적지를 변경해주세요. / "
    "일정 변경 / 목적지 변경 / 이 호텔을 본 다른 사람이  / 함께 찾는 호텔이에요! / "
    "로컬스티치 크리에이터 타운 서교 / 8 / 118,260원~ / 호텔더디자이너스 리즈스윗 역삼 / 8.8 / "
    "237,492원~ / 88호텔 / 8.2 / 59,870원~ / 추천 호텔 더보기 / NAVER")

SITE = {"key": "naver_hotels", "name": "네이버 호텔 가격비교",
        "rates_url": "https://hotels.naver.com/accommodation/search/detail/domestic/"
                     "{place_id}/rates?rateTab=&dCheckIn={checkin}&dCheckOut={checkout}"
                     "&dAdultCnt={guests}"}


def watch(checkin="2026-12-09", checkout="2026-12-10", **extra):
    base = {"query": "토요코인 서울강남", "keyword": "토요코인 서울강남",
            "address": "서울특별시 서초구 강남대로 323", "checkin": checkin,
            "checkout": checkout, "guests": 2}
    base.update(extra)
    return base


class PageBrowser:
    """주소에 따라 미리 정해둔 화면을 돌려주는 가짜 브라우저."""

    def __init__(self, pages=None, cards=None):
        self.pages = pages or {}
        self.cards = cards or {}
        self.visited = []

    def page_text(self, url, wait=10, scrolls=3):
        self.visited.append(url)
        return next((page for key, page in self.pages.items() if key in url), "")

    def collect_cards(self, url, selectors, wait=6, scrolls=2, retry_wait=5, ready=None):
        self.visited.append(url)
        return next((cards for key, cards in self.cards.items() if key in url), [])

    def body_text(self, limit=2000):
        return ""


class AnalyzeRatesTest(unittest.TestCase):
    def test_rooms_are_found(self):
        status, _ = search.analyze_naver_rates(RATES_OPEN, "2026-12-09", "2026-12-10")
        self.assertEqual(status, search.STATUS_AVAILABLE)

    def test_other_hotels_below_are_not_this_hotel(self):
        section = search.naver_rates_section(RATES_OPEN)
        self.assertIn("111,216원", section)
        self.assertNotIn("토요코인 서울동대문1", section)
        self.assertNotIn("90,651원", section)

    def test_short_empty_page_is_soldout(self):
        status, note = search.analyze_naver_rates(RATES_EMPTY_SHORT, "2026-10-20", "2026-10-21")
        self.assertEqual(status, search.STATUS_SOLDOUT)
        self.assertIn("객실이 없어요", note)

    def test_empty_page_with_other_hotels_prices_is_soldout(self):
        # 이전 방식(페이지 전체에서 값 찾기)이었다면 118,260원을 이 숙소 값으로 읽었다
        self.assertEqual(search.find_price(RATES_EMPTY_WITH_OTHERS), "118,260원")
        status, _ = search.analyze_naver_rates(RATES_EMPTY_WITH_OTHERS,
                                               "2026-12-31", "2027-01-01")
        self.assertEqual(status, search.STATUS_SOLDOUT)

    def test_dates_must_match(self):
        status, note = search.analyze_naver_rates(RATES_OPEN, "2026-12-10", "2026-12-11")
        self.assertEqual(status, search.STATUS_UNKNOWN)
        self.assertIn("날짜", note)

    def test_place_id(self):
        self.assertEqual(search.naver_place_id(
            "https://m.place.naver.com/accommodation/1745414542/room"), "1745414542")
        self.assertEqual(search.naver_place_id(
            "https://hotels.naver.com/accommodation/search/detail/domestic/1745414542/rates"),
            "1745414542")
        self.assertEqual(search.naver_place_id("https://example.com/1"), "")


class RatesResultTest(unittest.TestCase):
    def browser(self):
        return PageBrowser(pages={"hotels.naver.com": RATES_OPEN})

    def test_offer_and_link(self):
        result = search.naver_rates_result(self.browser(), watch(), SITE, "1745414542")
        self.assertEqual(result.status, search.STATUS_AVAILABLE)
        self.assertEqual(result.offers[0].price, "111,216원")
        self.assertIn("domestic/1745414542/rates", result.url)
        self.assertIn("dCheckIn=2026-12-09", result.url)
        self.assertTrue(result.offers[0].verified)     # '서초구 강남대로 323' 일치

    def test_price_range(self):
        over = search.naver_rates_result(
            self.browser(), watch(price_min=None, price_max=100000), SITE, "1745414542")
        self.assertEqual(over.status, search.STATUS_OVER_BUDGET)
        fits = search.naver_rates_result(
            self.browser(), watch(price_min=120000, price_max=130000), SITE, "1745414542")
        self.assertEqual(fits.status, search.STATUS_AVAILABLE)
        self.assertEqual(fits.offers[0].price, "123,200원")

    def test_without_place_id(self):
        result = search.naver_rates_result(self.browser(), watch(), SITE, "")
        self.assertEqual(result.status, search.STATUS_NONE)
        self.assertIn("찾지 못해", result.note)


class RatesOrderTest(unittest.TestCase):
    """가격비교 결과는 맨 위에 보인다."""

    SITES = [{"key": "yanolja", "name": "야놀자", "url": "https://yanolja/?q={query}"},
             {"key": "naver", "name": "네이버 예약", "follow_place": True,
              "url": "https://m.search.naver.com/?q={query}"},
             SITE,
             {"key": "booking", "name": "부킹닷컴", "url": "https://booking/?ss={query}"}]

    def test_place_found_by_naver_search_goes_first(self):
        naver_cards = [{"text": "토요코인 서울강남",
                        "url": "https://m.place.naver.com/accommodation/1745414542/home"}]
        booking_cards = [{"text": "Toyoko Inn Seoul Gangnam\nUnavailable\n"
                                  "Too late – no availability for your selected dates "
                                  "at this property!"}]
        browser = PageBrowser(pages={"hotels.naver.com": RATES_OPEN},
                              cards={"m.search.naver.com": naver_cards,
                                     "booking": booking_cards})
        item = watch()
        results = search.search_watch(browser, item, self.SITES)
        self.assertEqual([r.key for r in results][0], "naver_hotels")
        self.assertEqual(results[0].status, search.STATUS_AVAILABLE)
        self.assertEqual(item["naver_place_id"], "1745414542")
        booking = next(r for r in results if r.key == "booking")
        self.assertEqual(booking.status, search.STATUS_SOLDOUT)   # 부킹닷컴은 그대로 마감

    def test_registered_naver_link_gives_the_place(self):
        browser = PageBrowser(pages={"hotels.naver.com": RATES_OPEN})
        item = watch(url="https://m.place.naver.com/accommodation/1745414542/room")
        results = search.search_watch(browser, item, self.SITES)
        self.assertEqual(results[0].key, "naver_hotels")
        self.assertEqual(results[0].status, search.STATUS_AVAILABLE)

    def test_unknown_place_goes_last(self):
        results = search.search_watch(PageBrowser(), watch(), self.SITES)
        self.assertEqual(results[-1].key, "naver_hotels")
        self.assertEqual(results[-1].status, search.STATUS_NONE)


if __name__ == "__main__":
    unittest.main()
