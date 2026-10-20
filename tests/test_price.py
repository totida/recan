"""1박 가격대 — 입력 해석과 검색 결과 거르기."""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dateparse  # noqa: E402
import price  # noqa: E402
import search  # noqa: E402

TODAY = date(2026, 4, 20)

# 2026-10-20 점검(check-sites.yml)에서 실제로 읽은 카드. 줄마다 끊어 저장한다.
# 여기어때 1박: 쿠폰 적용가와 회원가 두 값이 붙어 나온다.
YEOGI_ONE_NIGHT = ("블랙\n5성급\n호텔\n라한셀렉트 경주\n경주시경주보문관광단지 내\n"
                   "9.4\n3,022명 평가\n미리예약특가\n2% 쿠폰 적용가\n250,000원\n"
                   "회원가\n245,000\n원")
# 여기어때 3박: 값 뒤에 '/1박' 이 붙어 1박 값임을 알려준다.
YEOGI_PER_NIGHT = ("호텔\n소노벨 경주 감포\n경주시나정고운모래해변 차량 4분\n9.1\n"
                   "2,316명 평가\n87,686\n원\n/1박")
# 야놀자 1박 목록 카드
YANOLJA_ONE_NIGHT = ("숙박페스타\n숙박페스타\n5성급 호텔\n라한셀렉트 경주\n보문관광단지 내\n"
                     "4.7\n(2,459)\n숙박 15:00~\n239,700\n원~\n"
                     "NOL 머니 결제 시 최대 3,596P 적립")


class ParseRangeTest(unittest.TestCase):
    def check(self, text, expected, bare=False):
        found = price.parse_range(text, bare=bare)
        self.assertIsNotNone(found, text)
        self.assertEqual(found[:2], expected, text)

    def test_range_forms(self):
        self.check("10~15만", (100000, 150000))
        self.check("10만~15만원", (100000, 150000))
        self.check("10 - 15만 원", (100000, 150000))
        self.check("100,000~150,000원", (100000, 150000))
        self.check("12.5~20만", (125000, 200000))
        self.check("15~10만", (100000, 150000))   # 거꾸로 적어도

    def test_upper_and_lower_only(self):
        self.check("15만 이하", (None, 150000))
        self.check("~15만", (None, 150000))
        self.check("최대 15만원", (None, 150000))
        self.check("10만 이상", (100000, None))
        self.check("10만~", (100000, None))
        self.check("최소 10만", (100000, None))

    def test_bare_numbers_are_manwon_only_when_asked_for_a_price(self):
        self.check("10~15", (100000, 150000), bare=True)
        self.check("15 이하", (None, 150000), bare=True)
        self.check("100000~150000", (100000, 150000), bare=True)
        self.assertIsNone(price.parse_range("10~15"))

    def test_dates_and_guests_are_not_prices(self):
        for text in ("5/2~5/3 4명", "2026.5.2~2026.5.4", "20260502-20260503",
                     "12/30~1/2", "내일 2박"):
            self.assertIsNone(price.parse_range(text), text)
            self.assertIsNone(price.parse_range(text, bare=True), text)

    def test_a_single_amount_is_the_maximum_when_asked_for_a_price(self):
        # '최대 얼마까지 괜찮으세요?' 에 대한 답
        self.check("28만", (None, 280000), bare=True)
        self.check("28", (None, 280000), bare=True)
        self.check("280,000원", (None, 280000), bare=True)
        # 숙소 이름과 함께 적은 줄에서는 금액 하나를 가격대로 보지 않는다
        self.assertIsNone(price.parse_range("15만"))
        self.assertIsNone(price.parse_range("비토애 산청 28만", bare=True))
        self.assertIsNone(price.parse_range("20260502", bare=True))

    def test_describe(self):
        self.assertEqual(price.describe(100000, 150000), "10~15만원")
        self.assertEqual(price.describe(None, 150000), "15만원 이하")
        self.assertEqual(price.describe(500000, None), "50만원 이상")
        self.assertEqual(price.describe(None, None), "상관없음")
        self.assertEqual(price.short_label(None, 100000), "10만 이하")
        self.assertEqual(price.short_label(500000, None), "50만 이상")
        self.assertEqual(price.short_label(100000, 150000), "10~15만")

    def test_one_line_request_keeps_the_name_clean(self):
        parsed = dateparse.parse_request("비토애 산청 5/2~5/3 4명 10~15만", today=TODAY)
        self.assertEqual(parsed["name"], "비토애 산청")
        self.assertEqual(parsed["guests"], 4)
        self.assertEqual(parsed["price"], (100000, 150000))

        parsed = dateparse.parse_request("비토애 산청 15만 이하", today=TODAY)
        self.assertEqual(parsed["name"], "비토애 산청")
        self.assertEqual(parsed["price"], (None, 150000))

        self.assertIsNone(dateparse.parse_request("비토애 산청 5/2~5/3", today=TODAY)["price"])


class FitsBudgetTest(unittest.TestCase):
    def test_one_night(self):
        self.assertTrue(search.fits_budget(120000, (100000, 150000, 1)))
        self.assertFalse(search.fits_budget(180000, (100000, 150000, 1)))
        self.assertTrue(search.fits_budget(80000, (None, 100000, 1)))
        self.assertFalse(search.fits_budget(80000, (100000, None, 1)))

    def test_total_or_per_night_when_unmarked(self):
        # 3박 총액 360,000원 = 1박 120,000원. 어느 쪽인지 모르면 거르지 않는다.
        self.assertTrue(search.fits_budget(360000, (100000, 150000, 3)))
        self.assertTrue(search.fits_budget(120000, (100000, 150000, 3)))
        self.assertFalse(search.fits_budget(600000, (100000, 150000, 3)))

    def test_marked_per_night_is_not_divided(self):
        self.assertFalse(search.fits_budget(87686, (None, 30000, 3), per_night=True))


class BudgetCardTest(unittest.TestCase):
    def analyze(self, card, budget, query="라한셀렉트 경주"):
        return search.analyze_cards(query, [{"text": card, "url": "https://x/1"}],
                                    budget=budget)

    def test_without_budget_nothing_changes(self):
        status, offers = self.analyze(YEOGI_ONE_NIGHT, None)
        self.assertEqual(status, search.STATUS_AVAILABLE)
        self.assertEqual(offers[0].price, "250,000원")

    def test_room_above_budget_is_not_an_alert(self):
        status, offers = self.analyze(YEOGI_ONE_NIGHT, (None, 150000, 1))
        self.assertEqual(status, search.STATUS_OVER_BUDGET)
        self.assertEqual(offers, [])

    def test_member_price_inside_budget_is_used(self):
        # 쿠폰 적용가 250,000원은 넘지만 회원가 245,000원은 가격대 안이다
        status, offers = self.analyze(YEOGI_ONE_NIGHT, (200000, 248000, 1))
        self.assertEqual(status, search.STATUS_AVAILABLE)
        self.assertEqual(offers[0].price, "245,000원")

    def test_per_night_mark_is_read(self):
        query = "소노벨 경주 감포"
        status, _ = self.analyze(YEOGI_PER_NIGHT, (None, 100000, 3), query)
        self.assertEqual(status, search.STATUS_AVAILABLE)
        # '/1박' 이 있으니 3으로 나누지 않는다 (나누면 29,228원이라 통과해 버린다)
        status, _ = self.analyze(YEOGI_PER_NIGHT, (None, 30000, 3), query)
        self.assertEqual(status, search.STATUS_OVER_BUDGET)

    def test_yanolja_list_card(self):
        self.assertEqual(self.analyze(YANOLJA_ONE_NIGHT, (None, 200000, 1))[0],
                         search.STATUS_OVER_BUDGET)
        status, offers = self.analyze(YANOLJA_ONE_NIGHT, (200000, 300000, 1))
        self.assertEqual(status, search.STATUS_AVAILABLE)
        self.assertEqual(offers[0].price, "239,700원")

    def test_sold_out_stays_sold_out(self):
        card = YANOLJA_ONE_NIGHT.replace("239,700\n원~", "예약마감")
        self.assertEqual(self.analyze(card, (None, 100000, 1))[0], search.STATUS_SOLDOUT)

    def test_card_without_price_is_not_filtered(self):
        card = "라한셀렉트 경주\n보문관광단지 내"
        self.assertEqual(self.analyze(card, (None, 100000, 1))[0], search.STATUS_UNKNOWN)


class BudgetDetailTest(unittest.TestCase):
    # 야놀자 상세: '객실 선택' 아래 방 목록. 숙소 안내의 요금은 방 값이 아니다.
    PAGE = ("라한셀렉트 경주\n" * 5 + "객실 선택\n11.10~11.11, 1박\n성인 2, 아동 0\n"
            "디럭스 더블\n기준 2인 / 최대 3인\n239,700원\n"
            "위치/교통\n경상북도 경주시\n숙소 이용 정보\n조식 1인 35,000원\n")

    def test_room_inside_budget(self):
        status, _ = search.analyze_stay_detail(self.PAGE, 2, (200000, 300000, 1))
        self.assertEqual(status, search.STATUS_AVAILABLE)

    def test_room_above_budget(self):
        status, _ = search.analyze_stay_detail(self.PAGE, 2, (None, 100000, 1))
        self.assertEqual(status, search.STATUS_OVER_BUDGET)

    def test_fee_below_room_list_does_not_count(self):
        # 조식 35,000원은 '~10만' 안이지만 방 목록 밖이다
        status, _ = search.analyze_stay_detail(self.PAGE, 2, (None, 100000, 1))
        self.assertNotEqual(status, search.STATUS_AVAILABLE)

    def test_watch_budget(self):
        watch = {"checkin": "2026-11-10", "checkout": "2026-11-13",
                 "price_min": 100000, "price_max": None}
        self.assertEqual(search.watch_budget(watch), (100000, None, 3))
        watch.update(price_min=None)
        self.assertIsNone(search.watch_budget(watch))


if __name__ == "__main__":
    unittest.main()
