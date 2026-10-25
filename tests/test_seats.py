import json
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot  # noqa: E402
import keyboards  # noqa: E402
import seats  # noqa: E402
import storage  # noqa: E402
from test_bot import CHAT, FakeTelegram, buttons, texts  # noqa: E402

LINK = ("https://m.booking.naver.com/booking/12/bizes/1688834/items/7826615/seats/1310178633"
        "?area=pll&lang=ko&startDateTime=2026-11-08T00%3A00%3A00%2B09%3A00&theme=place")

# 2026-10-25 사용자가 텔레그램에 실제로 보낸 링크. 좌석 화면이 아니라 공연 화면에 회차(slotId)가 붙은 모양이다.
USER_ITEM_LINK = ("https://m.booking.naver.com/booking/12/bizes/1688834/items/7826615"
                  "?area=pll&lang=ko&slotId=1310178633"
                  "&startDateTime=2026-11-08T00%3A00%3A00%2B09%3A00&theme=place")

# 2026-10-23 사용자가 보낸 공연(누가 내 머리에 똥 쌌어 - 부산 낙동, 11-08 16:00)의
# 실제 좌석 상태. 열마다 1번부터 X=팔림, .=빈자리. (B구역 11열만 5번부터 있다)
REAL_ROWS = {
    "A": {2: "XXXXX", 3: "XXXXX", 4: "XXXXX", 6: ".XXXX", 7: "..XXX", 8: "XXXXX",
          9: "..XXX", 10: "XXXXX", 11: "...XX", 12: "XXXXX", 13: "XX.XX", 14: ".....",
          15: "....."},
    "B": {2: "XXXXXXXXXX", 3: "XXXXXX.XXX", 4: "XXXXXXXXXX", 6: "XXXXXXXXXX",
          7: "XXXXXX.XXX", 9: "XXXXXXXXXX", 10: "XXXXXXXXXX", 11: (5, "XXXXX."),
          12: "XXXXXXXXXX", 13: "XXXXXXXXXX", 14: "...XXXX...", 15: ".........."},
    "C": {2: "XXXXX", 3: "XXXXX", 4: "XXXXX", 6: "XXXXX", 7: "XXXXX", 9: "XXXXX",
          10: "XXXXX", 11: "XX...", 12: "XXXX.", 13: "XXXXX", 14: ".....", 15: "....."},
}
ZONE_X = {"A": 137, "B": 236, "C": 405}


def rectangles(rows, overrides=None):
    """좌석 그림(SeattleRectangle)을 실제 화면과 같은 모양으로 만든다."""
    overrides = overrides or {}
    shapes = []
    for zone, zone_rows in rows.items():
        for row, line in zone_rows.items():
            first, line = line if isinstance(line, tuple) else (1, line)
            for offset, mark in enumerate(line):
                number = first + offset
                name = f"{zone}구역 {row}열 {number}번"
                shapes.append({
                    "__typename": "SeattleRectangle", "name": name,
                    "udid": f"{zone}{row}-{number}",
                    "state": overrides.get(name, "sold" if mark == "X" else None),
                    "stockId": None, "rotation": None,
                    "lefttop": {"__typename": "Point", "x": ZONE_X[zone] + 14 * (number - 1),
                                "y": 233 + 14 * row},
                    "size": {"__typename": "Size", "width": 10, "height": 10},
                })
    return shapes


def page_html(rows=REAL_ROWS, overrides=None, sale=True, drawn=True,
              sale_end="2026-11-07T08:00:00Z"):
    state = {
        "Business:1688834": {"__typename": "Business", "name": "엔에이치엔링크"},
        'BizItem:7826615_{"bizItemId":"7826615","businessId":"1688834"}': {
            "__typename": "BizItem", "bizItemId": "7826615",
            "name": "누가 내 머리에 똥 쌌어 - 부산 낙동"},
        "Slot:1310178633": {
            "__typename": "Slot", "slotId": "1310178633",
            "hourlySchedule": {"__typename": "HourlySchedule", "maxBookingCount": 10,
                               "unitStartDateTime": "2026-11-08T07:00:00Z",
                               "saleEndDateTime": sale_end}},
        "SeatMap:1310178633": {"__typename": "SeatMap", "sale": sale,
                               "seatGroups": [{"__ref": "SeatGroup:6a45"}]},
    }
    shapes = rectangles(rows, overrides)
    if drawn:
        state["SeattleSeatMap:1310178633"] = {
            "__typename": "SeattleSeatMap",
            "seats": [{"__typename": "SeattleSeat", "color": "#f56257", "rectangles": shapes}],
            "map": {"__typename": "SeattleMap", "background": "https://x/image.png"},
        }
    else:
        state["SeatGroup:6a45"] = {
            "__typename": "SeatGroup", "typeName": "전석",
            "seats": [{"__typename": "Seat", "name": shape["name"],
                       "sold": "1" if shape["state"] == "sold" else "0", "op": "11"}
                      for shape in shapes]}
    return ('<script>window.__BOOKING_BUILD__="261017-1455"</script>\n'
            f"  <script>window.__APOLLO_STATE__={json.dumps(state, ensure_ascii=False)}"
            "</script>\n  <script>window.__PLACE_STATE__={}</script>")


def runs_text(runs):
    return [seats.describe_run(run) for run in runs]


class SeatPageTest(unittest.TestCase):
    def test_real_page_parsed(self):
        page = seats.parse_page(page_html())
        self.assertEqual(page.title, "누가 내 머리에 똥 쌌어 - 부산 낙동")
        self.assertEqual(seats.describe_time(page.starts_at), "2026-11-08(일) 16:00")
        self.assertEqual(seats.describe_time(page.sale_end), "2026-11-07(토) 17:00")
        self.assertTrue(page.on_sale)
        self.assertEqual(len(page.seats), 241)
        self.assertEqual(page.free_count(), 52)
        self.assertEqual(page.free_count(10), 7)

    def test_real_page_has_no_four_together_within_ten_rows(self):
        page = seats.parse_page(page_html())
        self.assertEqual(seats.find_runs(page.seats, 4, 10), [])

    def test_pairs_within_ten_rows(self):
        page = seats.parse_page(page_html())
        self.assertEqual(runs_text(seats.find_runs(page.seats, 2, 10)),
                         ["A구역 7열 1~2번 (2석)", "A구역 9열 1~2번 (2석)"])

    def test_back_rows_without_row_limit(self):
        page = seats.parse_page(page_html())
        self.assertEqual(runs_text(seats.find_runs(page.seats, 4)), [
            "A구역 14열 1~5번 (5석)", "C구역 14열 1~5번 (5석)", "A구역 15열 1~5번 (5석)",
            "B구역 15열 1~10번 (10석)", "C구역 15열 1~5번 (5석)"])

    def test_cancellation_within_ten_rows_found(self):
        cancelled = {f"A구역 7열 {n}번": None for n in (3, 4)}
        page = seats.parse_page(page_html(overrides=cancelled))
        self.assertEqual(runs_text(seats.find_runs(page.seats, 4, 10)),
                         ["A구역 7열 1~4번 (4석)"])

    def test_seats_in_other_zones_are_not_together(self):
        # A구역 5번과 B구역 1번은 통로를 사이에 두고 있다.
        rows = {"A": {6: "XXX.."}, "B": {6: "..XXXXXXXX"}}
        page = seats.parse_page(page_html(rows=rows))
        self.assertEqual(seats.find_runs(page.seats, 4, 10), [])

    def test_only_normal_state_is_free(self):
        rows = {"B": {3: "......XXXX"}}
        for state in ("notForSale", "hidden", "selected"):
            page = seats.parse_page(page_html(rows=rows, overrides={"B구역 3열 3번": state}))
            self.assertEqual(seats.find_runs(page.seats, 4, 10), [], state)
        page = seats.parse_page(page_html(rows=rows, overrides={"B구역 3열 3번": "normal"}))
        self.assertEqual(runs_text(seats.find_runs(page.seats, 4, 10)),
                         ["B구역 3열 1~6번 (6석)"])

    def test_seat_group_used_when_drawing_missing(self):
        page = seats.parse_page(page_html(drawn=False))
        self.assertEqual(page.free_count(), 52)
        self.assertEqual(runs_text(seats.find_runs(page.seats, 2, 10)),
                         ["A구역 7열 1~2번 (2석)", "A구역 9열 1~2번 (2석)"])

    def test_letter_rows_are_not_filtered_by_row_limit(self):
        free = [seats.parse_seat(f"1층 C열 {n}번", True) for n in range(1, 5)]
        self.assertEqual(runs_text(seats.find_runs(free, 4, 10)), ["1층 C열 1~4번 (4석)"])

    def test_page_without_state_is_error(self):
        with self.assertRaises(seats.SeatPageError):
            seats.parse_page("<html>점검 중</html>")

    def test_page_without_seats_is_error(self):
        with self.assertRaises(seats.SeatPageError):
            seats.parse_page(page_html(rows={}))

    def test_find_link(self):
        url, slot = seats.find_link(f"이 공연 {LINK} 10열 4명")
        self.assertEqual(url, LINK)
        self.assertEqual(slot, "1310178633")
        self.assertIsNone(seats.find_link(
            "https://m.booking.naver.com/booking/3/bizes/1/items/2?startDate=2026-11-08"))
        self.assertIsNone(seats.find_link("비토애 산청 5/2~5/3"))

    def test_item_link_with_slot_becomes_seat_link(self):
        self.assertEqual(seats.find_link(USER_ITEM_LINK), (LINK, "1310178633"))

    def test_item_link_without_slot_is_not_seat_link(self):
        self.assertIsNone(seats.find_link(
            "https://m.booking.naver.com/booking/12/bizes/1688834/items/7826615"
            "?startDateTime=2026-11-08T00%3A00%3A00%2B09%3A00"))


class FakeSeats:
    """seats.check 를 가로채 정해둔 화면을 돌려준다."""

    def __init__(self, html=None, error=None):
        self.html = html or page_html()
        self.error = error
        self.calls = 0
        self.urls = []

    def __enter__(self):
        self._check = seats.check

        def check(url):
            self.calls += 1
            self.urls.append(url)
            if self.error:
                raise seats.SeatPageError(self.error)
            return seats.parse_page(self.html)

        seats.check = bot.seats.check = check
        return self

    def __exit__(self, *exc):
        seats.check = bot.seats.check = self._check


NOW = datetime(2026, 10, 23, 13, 0, tzinfo=seats.KST).timestamp()


def new_db():
    db = storage.default_db()
    db["owner"] = CHAT
    return db


def registered_db(count=4, max_row=10):
    db = new_db()
    with FakeSeats():
        bot.handle_text(db, CHAT, f"{LINK} {count}명 {max_row}열")
    return db, db["chats"][CHAT]["seats"][0]


class SeatRegistrationTest(unittest.TestCase):
    def test_link_with_conditions_registers_directly(self):
        db = new_db()
        with FakeSeats():
            replies = bot.handle_text(db, CHAT, f"{LINK} 4명 10열")
        self.assertIn("등록 완료", texts(replies))
        self.assertIn("2026-11-08(일) 16:00", texts(replies))
        watch = db["chats"][CHAT]["seats"][0]
        self.assertEqual((watch["count"], watch["max_row"], watch["force"]), (4, 10, True))
        self.assertEqual(watch["title"], "누가 내 머리에 똥 쌌어 - 부산 낙동")
        self.assertIsNone(db["chats"][CHAT]["state"])

    def test_user_item_link_asks_count_not_calendar(self):
        db = new_db()
        with FakeSeats() as fake:
            replies = bot.handle_text(db, CHAT, USER_ITEM_LINK)
        self.assertEqual(fake.urls, [LINK])
        self.assertIn("몇 명", texts(replies))
        self.assertNotIn("체크인", texts(replies))
        self.assertEqual(db["chats"][CHAT]["state"]["url"], LINK)

    def test_performance_link_without_slot_asks_for_time(self):
        db = new_db()
        with FakeSeats() as fake:
            replies = bot.handle_text(
                db, CHAT, "https://m.booking.naver.com/booking/12/bizes/1688834/items/7826615")
        self.assertEqual(fake.urls, [])
        self.assertIn("회차", texts(replies))
        self.assertNotIn("체크인", texts(replies))
        self.assertIsNone(db["chats"][CHAT]["state"])

    def test_link_only_asks_count_then_rows(self):
        db = new_db()
        with FakeSeats():
            replies = bot.handle_text(db, CHAT, LINK)
        self.assertIn("몇 명", texts(replies))
        self.assertIn("seat:count:4", buttons(replies))
        replies = bot.handle_callback(db, CHAT, "seat:count:4")
        self.assertIn("몇 열까지", texts(replies))
        self.assertIn("seat:row:10", buttons(replies))
        replies = bot.handle_callback(db, CHAT, "seat:row:10")
        self.assertIn("10열 이내 · 4명 붙은 자리", texts(replies))
        self.assertEqual(db["chats"][CHAT]["seats"][0]["max_row"], 10)

    def test_typed_answers_and_any_row(self):
        db = new_db()
        with FakeSeats():
            bot.handle_text(db, CHAT, LINK)
        bot.handle_text(db, CHAT, "4명")
        replies = bot.handle_text(db, CHAT, "상관없음")
        self.assertIn("전체 열 · 4명 붙은 자리", texts(replies))
        self.assertIsNone(db["chats"][CHAT]["seats"][0]["max_row"])

    def test_cancel_button(self):
        db = new_db()
        with FakeSeats():
            bot.handle_text(db, CHAT, LINK)
        bot.handle_callback(db, CHAT, "seat:cancel")
        self.assertEqual(db["chats"][CHAT]["seats"], [])
        self.assertIsNone(db["chats"][CHAT]["state"])

    def test_unreadable_page_not_registered(self):
        db = new_db()
        with FakeSeats(error="좌석 화면을 열지 못했어요"):
            replies = bot.handle_text(db, CHAT, f"{LINK} 4명 10열")
        self.assertIn("읽지 못했어요", texts(replies))
        self.assertEqual(db["chats"][CHAT]["seats"], [])

    def test_sale_already_over(self):
        db = new_db()
        with FakeSeats(page_html(sale_end="2026-01-01T00:00:00Z")):
            replies = bot.handle_text(db, CHAT, f"{LINK} 4명 10열")
        self.assertIn("예매가 끝난", texts(replies))
        self.assertEqual(db["chats"][CHAT]["seats"], [])

    def test_duplicate_rejected(self):
        db, _ = registered_db()
        with FakeSeats():
            replies = bot.handle_text(db, CHAT, f"{LINK} 4명 10열")
        self.assertIn("이미 등록된", texts(replies))
        self.assertEqual(len(db["chats"][CHAT]["seats"]), 1)

    def test_list_and_delete_number_after_stays(self):
        db, _ = registered_db()
        chat = db["chats"][CHAT]
        chat["watches"].append(storage.new_watch("비토애 산청", "2026-11-01", "2026-11-02"))
        listing = texts(bot.handle_text(db, CHAT, "목록"))
        self.assertIn("1. 비토애 산청", listing)
        self.assertIn("2. 누가 내 머리에 똥 쌌어 - 부산 낙동", listing)
        self.assertIn("del:pick:1", buttons(bot.handle_text(db, CHAT, "삭제")))
        replies = bot.handle_text(db, CHAT, "삭제 2")
        self.assertIn("누가 내 머리에", texts(replies))
        self.assertEqual(chat["seats"], [])
        self.assertEqual(len(chat["watches"]), 1)

    def test_delete_button_and_delete_all(self):
        db, _ = registered_db()
        bot.handle_callback(db, CHAT, "del:pick:0")
        self.assertEqual(db["chats"][CHAT]["seats"], [])
        db, _ = registered_db()
        bot.handle_callback(db, CHAT, "del:all")
        self.assertEqual(db["chats"][CHAT]["seats"], [])

    def test_now_command_with_only_seats(self):
        db, watch = registered_db()
        watch["force"] = False
        replies = bot.handle_text(db, CHAT, "지금")
        self.assertIn("좌석을 확인", texts(replies))
        self.assertTrue(watch["force"])

    def test_old_chat_without_seats_migrates(self):
        raw = {"version": storage.SCHEMA_VERSION, "owner": CHAT,
               "chats": {CHAT: {"state": None, "watches": []}}}
        self.assertEqual(storage.migrate(raw)["chats"][CHAT]["seats"], [])

    def test_seat_keyboards(self):
        self.assertIn("seat:row:any",
                      [b["callback_data"] for row in keyboards.seat_row_keyboard() for b in row])


class SeatCheckTest(unittest.TestCase):
    def check(self, db, html=None, now=NOW, error=None):
        with FakeTelegram() as telegram, FakeSeats(html, error=error):
            bot.run_due_seat_checks(db, now=now)
        return telegram

    def test_first_check_reports_nothing_yet(self):
        db, watch = registered_db()
        sent = self.check(db).text()
        self.assertIn("요청하신 좌석 확인 결과", sent)
        self.assertIn("조건에 맞는 자리가 없어요", sent)
        self.assertIn("빈자리 52석 · 그중 10열 이내 7석", sent)
        self.assertFalse(watch["force"])
        self.assertEqual(watch["last_checked"], int(NOW))

    def test_not_due_is_skipped(self):
        db, watch = registered_db()
        self.check(db)
        telegram = self.check(db, now=NOW + 60)
        self.assertEqual(telegram.sent, [])

    def test_cancellation_notifies_once(self):
        db, watch = registered_db()
        self.check(db)
        opened = page_html(overrides={"A구역 7열 3번": None, "A구역 7열 4번": None})
        later = NOW + bot.SEAT_INTERVAL
        sent = self.check(db, opened, now=later).text()
        self.assertIn("🚨", sent)
        self.assertIn("A구역 7열 1~4번 (4석)", sent)
        self.assertIn(LINK, sent)
        # 같은 자리가 계속 남아 있으면 다시 알리지 않는다
        self.assertEqual(self.check(db, opened, now=later + bot.SEAT_INTERVAL).sent, [])

    def test_another_opening_notifies_again(self):
        db, watch = registered_db()
        self.check(db)
        first = {"A구역 7열 3번": None, "A구역 7열 4번": None}
        later = NOW + bot.SEAT_INTERVAL
        self.check(db, page_html(overrides=first), now=later)
        both = dict(first, **{f"B구역 9열 {n}번": None for n in range(1, 5)})
        sent = self.check(db, page_html(overrides=both), now=later + bot.SEAT_INTERVAL).text()
        self.assertIn("B구역 9열 1~4번 (4석)", sent)

    def test_seats_gone_again(self):
        db, watch = registered_db()
        self.check(db)
        later = NOW + bot.SEAT_INTERVAL
        self.check(db, page_html(overrides={"A구역 7열 3번": None, "A구역 7열 4번": None}),
                   now=later)
        sent = self.check(db, now=later + bot.SEAT_INTERVAL).text()
        self.assertIn("다시 나갔어요", sent)
        self.assertEqual(watch["open_seats"], [])

    def test_not_on_sale(self):
        db, watch = registered_db()
        opened = page_html(sale=False, overrides={"A구역 7열 3번": None, "A구역 7열 4번": None})
        sent = self.check(db, opened).text()
        self.assertIn("팔고 있지 않아요", sent)
        self.assertNotIn("🚨", sent)

    def test_failures_alert_once(self):
        db, watch = registered_db()
        watch["force"] = False
        sent = []
        for step in range(bot.SEAT_FAIL_ALERT + 2):
            now = NOW + step * bot.SEAT_INTERVAL
            sent.extend(self.check(db, now=now, error="시간 초과").sent)
        self.assertEqual(len(sent), 1)
        self.assertIn("읽지 못했어요", sent[0][1])
        self.check(db, now=NOW + 99 * bot.SEAT_INTERVAL)
        self.assertEqual(watch["fails"], 0)

    def test_forced_failure_is_answered(self):
        db, watch = registered_db()
        self.assertIn("읽지 못했어요", self.check(db, error="시간 초과").text())

    def test_removed_after_sale_end(self):
        db, watch = registered_db()
        sale_end = datetime(2026, 11, 7, 17, 0, tzinfo=seats.KST).timestamp()
        self.assertEqual(watch["sale_end"], int(sale_end))
        sent = self.check(db, now=sale_end).text()
        self.assertIn("예매가 끝나 목록에서 삭제", sent)
        self.assertEqual(db["chats"][CHAT]["seats"], [])


if __name__ == "__main__":
    unittest.main()
