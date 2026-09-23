"""야놀자 상세 페이지 판정 — 방 목록 구간을 어디까지 볼지."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import search  # noqa: E402


# 실제로 겪은 오탐: '경주 맘편한집키즈풀빌라' 7명. 상세 페이지에는
# '선택한 날짜에는 모든 객실이 예약되었어요' 가 떠 있고 유일한 방(독채)도
# 예약마감인데, 방 목록 아래 숙소 안내의 요금까지 읽어 예약 가능으로 알렸다.
YANOLJA_ALL_BOOKED = """경주 맘편한집키즈풀빌라
숙소 위치보기
후기 (1)
펜션 최대 8% 쿠폰 받기
결제 혜택
카카오페이로 결제 시 10% 즉시 할인 (최대 1만원, ...
객실 선택
10.04~10.05, 1박
성인 7, 아동 0
선택한 날짜에는 모든 객실이 예약되었어요.
로그인하고 더 많은 혜택을 받아보세요
로그인
독채
수영장 미온수 24시간 무료 제공
기준 4인 / 최대 10인
숙박 · 체크인 15:00 ~ 체크아웃 11:00
상세보기
예약마감
(판매가 690,000원)
위치/교통
경상북도 경주시
숙소 이용 정보
기준 인원 초과 시 1인 20,000원
바비큐 이용 30,000원
"""


class AllBookedDetailTest(unittest.TestCase):
    def test_all_booked_notice_is_soldout(self):
        status, note = search.analyze_stay_detail(YANOLJA_ALL_BOOKED, 7)
        self.assertEqual(status, search.STATUS_SOLDOUT)
        self.assertEqual(note, "모든 객실 예약 마감")

    def test_fees_below_the_room_list_are_not_rooms(self):
        # 안내 문구가 없어도 '위치/교통' 아래 요금은 방 값이 아니다
        page = YANOLJA_ALL_BOOKED.replace("선택한 날짜에는 모든 객실이 예약되었어요.\n", "")
        self.assertEqual(search.analyze_stay_detail(page, 7)[0],
                         search.STATUS_SOLDOUT)

    def test_room_list_stops_at_next_heading(self):
        section = search.fitting_rooms_section(YANOLJA_ALL_BOOKED)
        self.assertIn("독채", section)
        self.assertNotIn("바비큐", section)

    def test_heading_word_inside_a_room_description_does_not_cut(self):
        # 사장님이 객실 설명에 '편의시설' 을 적어도 목록이 거기서 끊기면 안 된다
        page = ("경주 맘편한집키즈풀빌라\n" * 5 + "객실 선택\n성인 7, 아동 0\n독채\n"
                "편의시설 이용 가능, 수영장 미온수 무료\n기준 4인 / 최대 10인\n"
                "690,000원\n위치/교통\n경상북도 경주시\n")
        self.assertEqual(search.analyze_stay_detail(page, 7)[0],
                         search.STATUS_AVAILABLE)

    def test_opened_room_is_still_found(self):
        page = (YANOLJA_ALL_BOOKED
                .replace("선택한 날짜에는 모든 객실이 예약되었어요.\n", "")
                .replace("예약마감\n(판매가 690,000원)", "690,000원"))
        self.assertEqual(search.analyze_stay_detail(page, 7)[0],
                         search.STATUS_AVAILABLE)
