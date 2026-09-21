import os
import sys
import json
import time
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot  # noqa: E402
import keyboards  # noqa: E402
import search  # noqa: E402
import storage  # noqa: E402
import telegram_api  # noqa: E402

TODAY = date(2026, 4, 20)
CHAT = "1001"

CANDIDATES = [
    {"name": "비토애 산청", "address": "경남 산청군 시천면 지리산대로 123",
     "url": "https://m.place.naver.com/accommodation/1259756405/room"},
    {"name": "비토애 산청 별관", "address": "경남 산청군 단성면 2-3", "url": ""},
]


def texts(replies):
    return "\n".join(item["text"] for item in replies)


def buttons(replies):
    data = []
    for item in replies:
        for row in item.get("keyboard") or []:
            data.extend(button["callback_data"] for button in row)
    return data


class FakeTelegram:
    """telegram_api 전송 함수를 가로채 보낸 메시지를 모아둔다."""

    def __init__(self):
        self.sent = []
        self.menus = []

    def __enter__(self):
        self._send = telegram_api.send_message
        self._edit = telegram_api.edit_message

        def send(chat_id, text, preview=False, keyboard=None, menu=None):
            self.sent.append((str(chat_id), text))
            self.menus.append(menu)
            return 42

        def edit(chat_id, message_id, text, keyboard=None):
            self.sent.append((str(chat_id), text))
            return True

        telegram_api.send_message = bot.telegram_api.send_message = send
        telegram_api.edit_message = bot.telegram_api.edit_message = edit
        return self

    def __exit__(self, *exc):
        telegram_api.send_message = bot.telegram_api.send_message = self._send
        telegram_api.edit_message = bot.telegram_api.edit_message = self._edit

    def text(self):
        return "\n".join(t for _, t in self.sent)


class FakeBrowser:
    """검색 결과를 미리 정해두는 가짜 브라우저."""

    def __init__(self, cards=None, page_text="", body=""):
        self.cards = cards or []
        self._page_text = page_text
        self.body = body
        self.visited = []
        self.quit_called = False

    def collect_cards(self, url, selectors, wait=6, scrolls=2, retry_wait=5, ready=None):
        self.visited.append(url)
        return self.cards

    def page_text(self, url, wait=7, scrolls=2):
        self.visited.append(url)
        return self._page_text

    def body_text(self, limit=2000):
        return self.body

    def quit(self):
        self.quit_called = True


class ConversationTest(unittest.TestCase):
    def setUp(self):
        self.db = storage.default_db()

    def say(self, text, lookup=None):
        return bot.handle_text(self.db, CHAT, text, today=TODAY, lookup=lookup)

    def tap(self, data):
        return bot.handle_callback(self.db, CHAT, data, today=TODAY)

    def state(self):
        return storage.get_chat(self.db, CHAT)["state"]

    def watches(self):
        return storage.get_chat(self.db, CHAT)["watches"]

    def register(self, line, address="건너뛰기", guests="2"):
        """네이버 후보 없이(수동 주소) 등록하는 지름길."""
        self.say(line)
        self.say(address)
        if self.state() and self.state()["step"] == "await_guests":
            self.say(guests)
        return self.say("예")

    # --- 네이버 후보 + 달력 -------------------------------------------------

    def test_full_flow_with_candidates_and_calendar(self):
        replies = self.say("비토애 산청", lookup=lambda q: CANDIDATES)
        self.assertIn("어느 숙소인가요", texts(replies))
        self.assertIn("경남 산청군 시천면 지리산대로 123", texts(replies))
        self.assertIn("place:pick:0", buttons(replies))
        self.assertEqual(self.state()["step"], "await_place_choice")

        replies = self.tap("place:pick:0")
        self.assertIn("체크인", texts(replies))
        self.assertIn("cal:in:2026-04-20", buttons(replies))   # 오늘부터 선택 가능
        self.assertNotIn("cal:in:2026-04-19", buttons(replies))  # 지난 날짜는 없음
        self.assertEqual(self.state()["step"], "await_checkin")
        self.assertEqual(self.state()["address"], CANDIDATES[0]["address"])

        replies = self.tap("cal:in:2026-05-02")
        self.assertIn("체크아웃", texts(replies))
        self.assertIn("cal:out:2026-05-03", buttons(replies))
        self.assertNotIn("cal:out:2026-05-02", buttons(replies))  # 체크인 당일은 불가

        replies = self.tap("cal:out:2026-05-04")
        self.assertIn("몇 분이 묵으시나요", texts(replies))
        self.assertIn("guests:pick:4", buttons(replies))

        replies = self.tap("guests:pick:4")
        self.assertIn("등록 완료", texts(replies))
        self.assertIsNone(self.state())

        watch = self.watches()[0]
        self.assertEqual(watch["query"], "비토애 산청")
        self.assertEqual(watch["guests"], 4)
        self.assertEqual(watch["address"], CANDIDATES[0]["address"])
        self.assertEqual(watch["url"], CANDIDATES[0]["url"])
        self.assertEqual((watch["checkin"], watch["checkout"]), ("2026-05-02", "2026-05-04"))
        self.assertTrue(watch["force"])

    def test_candidate_can_be_chosen_by_number(self):
        self.say("비토애 산청", lookup=lambda q: CANDIDATES)
        replies = self.say("2")
        self.assertIn("체크인", texts(replies))
        self.assertEqual(self.state()["address"], CANDIDATES[1]["address"])

    def test_calendar_month_navigation(self):
        self.say("비토애 산청", lookup=lambda q: CANDIDATES)
        self.tap("place:pick:0")
        replies = self.tap("cal:m:2026-05")
        self.assertIn("2026년 5월", str(replies))
        self.assertIn("cal:in:2026-05-31", buttons(replies))

    def test_dates_already_given_skip_calendar(self):
        replies = self.say("비토애 산청 5/2~5/3", lookup=lambda q: CANDIDATES)
        self.assertIn("어느 숙소인가요", texts(replies))
        replies = self.tap("place:pick:0")
        self.assertIn("몇 분이 묵으시나요", texts(replies))
        replies = self.tap("guests:pick:3")
        self.assertIn("등록 완료", texts(replies))
        self.assertEqual(self.watches()[0]["checkin"], "2026-05-02")
        self.assertEqual(self.watches()[0]["guests"], 3)

    def test_typed_dates_instead_of_calendar(self):
        self.say("비토애 산청", lookup=lambda q: CANDIDATES)
        self.tap("place:pick:0")
        replies = self.say("5/2~5/4 4명")   # 인원까지 적으면 인원 질문을 건너뛴다
        self.assertIn("등록 완료", texts(replies))
        watch = self.watches()[0]
        self.assertEqual(watch["checkout"], "2026-05-04")
        self.assertEqual(watch["guests"], 4)

    def test_checkout_must_be_after_checkin(self):
        self.say("비토애 산청", lookup=lambda q: CANDIDATES)
        self.tap("place:pick:0")
        self.tap("cal:in:2026-05-02")
        replies = self.tap("cal:out:2026-05-01")
        self.assertIn("다음 날부터", texts(replies))
        self.assertEqual(self.watches(), [])

    def test_place_none_falls_back_to_manual_address(self):
        self.say("비토애 산청", lookup=lambda q: CANDIDATES)
        replies = self.tap("place:none")
        self.assertIn("주소를 알려주세요", texts(replies))
        self.say("경남 산청군 시천면")
        self.tap("cal:in:2026-05-02")
        self.tap("cal:out:2026-05-03")
        replies = self.tap("guests:pick:2")
        self.assertIn("확인해 주세요", texts(replies))   # 직접 입력은 한 번 더 확인
        replies = self.tap("confirm:yes")
        self.assertIn("등록 완료", texts(replies))
        self.assertEqual(self.watches()[0]["address"], "경남 산청군 시천면")

    def test_place_skip_registers_without_address(self):
        self.say("비토애 산청 5/2~5/3", lookup=lambda q: CANDIDATES)
        self.tap("place:skip")
        replies = self.tap("guests:pick:2")
        self.assertIn("확인해 주세요", texts(replies))
        self.tap("confirm:yes")
        self.assertEqual(self.watches()[0]["address"], "")

    def test_cancel_button_clears_state(self):
        self.say("비토애 산청", lookup=lambda q: CANDIDATES)
        self.tap("place:pick:0")
        replies = self.tap("cal:cancel")
        self.assertIn("취소", texts(replies))
        self.assertIsNone(self.state())

    def test_noop_button_does_nothing(self):
        self.say("비토애 산청", lookup=lambda q: CANDIDATES)
        self.assertEqual(self.tap(keyboards.NOOP), [])

    def test_callback_without_state_is_guided(self):
        replies = self.tap("cal:in:2026-05-02")
        self.assertIn("진행 중인 등록이 없어요", texts(replies))

    def test_lookup_failure_falls_back_to_manual(self):
        def broken(_query):
            raise RuntimeError("크롬 실행 실패")

        replies = self.say("비토애 산청", lookup=broken)
        self.assertIn("주소를 알려주세요", texts(replies))
        self.assertEqual(self.state()["step"], "await_address")

    def test_no_candidates_message(self):
        replies = self.say("비토애 산청", lookup=lambda q: [])
        self.assertIn("찾지 못했어요", texts(replies))

    # --- 기본 명령 ---------------------------------------------------------

    def test_reject_confirmation_restarts(self):
        self.say("비토애 산청 5/2~5/3")
        self.say("경남 산청군")
        self.say("2")
        replies = self.say("아니오")
        self.assertIn("다시 알려주세요", texts(replies))
        self.assertEqual(self.watches(), [])

    def test_unclear_confirmation_keeps_asking(self):
        self.say("비토애 산청 5/2~5/3")
        self.say("경남 산청군")
        self.say("2")
        replies = self.say("음...")
        self.assertIn("'예' 또는 '아니오'", texts(replies))
        self.assertEqual(self.state()["step"], "await_confirm")

    def test_single_line_registration(self):
        self.register("소노벨 변산 5/2~5/4 4명", address="전북 부안군 변산면")
        watch = self.watches()[0]
        self.assertEqual(watch["query"], "소노벨 변산")
        self.assertEqual(watch["address"], "전북 부안군 변산면")
        self.assertEqual(watch["guests"], 4)

    def test_duplicate_registration_rejected(self):
        self.register("비토애 산청 5/2~5/3")
        replies = self.register("비토애 산청 5/2~5/3")
        self.assertIn("이미 등록", texts(replies))
        self.assertEqual(len(self.watches()), 1)

    def test_list_and_delete(self):
        self.register("비토애 산청 5/2~5/3", address="경남 산청군")
        self.register("소노벨 변산 6/1~6/2")
        listing = texts(self.say("목록"))
        self.assertIn("비토애 산청", listing)
        self.assertIn("📍 경남 산청군", listing)

        self.say("삭제 1")
        self.assertEqual(len(self.watches()), 1)
        self.say("삭제 전체")
        self.assertEqual(self.watches(), [])

    def test_delete_out_of_range(self):
        self.register("비토애 산청 5/2~5/3")
        self.assertIn("사이의 번호", texts(self.say("삭제 7")))

    def test_help_command(self):
        self.assertIn("숙소 빈방 알림봇", texts(self.say("/start")))

    def test_guests_question_and_change(self):
        """인원을 안 적으면 물어보고, 등록 후에도 바꿀 수 있다."""
        self.say("소노벨 변산 6/1~6/2")
        self.say("전북 부안군 변산면")
        replies = self.say("음...")
        self.assertIn("숫자로 알려주세요", texts(replies))
        self.say("6")
        self.say("예")
        self.assertEqual(self.watches()[0]["guests"], 6)

        self.watches()[0]["force"] = False
        replies = self.say("인원 1 4")
        self.assertIn("4명으로 바꿨어요", texts(replies))
        self.assertEqual(self.watches()[0]["guests"], 4)
        self.assertTrue(self.watches()[0]["force"])   # 바뀐 인원으로 바로 재검색

    def test_guests_out_of_range(self):
        self.register("소노벨 변산 6/1~6/2")
        self.assertIn("사이로 알려주세요", texts(self.say("인원 1 99")))
        self.assertEqual(self.watches()[0]["guests"], 2)

    def test_guests_change_needs_a_number(self):
        self.register("소노벨 변산 6/1~6/2")
        self.register("비토애 산청 6/1~6/2")
        self.assertIn("'인원 2 4' 처럼", texts(self.say("인원")))

    def test_naver_link_registers_directly(self):
        url = (
            "https://m.place.naver.com/accommodation/1259756405/room?entry=pll"
            "&bk_query=%EB%B9%84%ED%86%A0%EC%95%A0%20%EC%82%B0%EC%B2%AD"
            "&guest=4&checkin=20260502&checkout=20260503"
        )
        replies = self.say(url)   # 링크에 guest=4 가 들어 있어 인원을 묻지 않는다
        self.assertIn("등록 완료", texts(replies))
        watch = self.watches()[0]
        self.assertEqual(watch["query"], "비토애 산청")
        self.assertEqual(watch["guests"], 4)
        self.assertIn("accommodation/1259756405/room", watch["url"])

    def test_link_without_guests_asks(self):
        self.say("https://m.place.naver.com/accommodation/1/room?checkin=20260502&checkout=20260503")
        self.assertEqual(self.state()["step"], "await_guests")

    def test_link_without_dates_opens_calendar(self):
        replies = self.say("https://www.goodchoice.kr/product/123")
        self.assertIn("체크인", texts(replies))

    def test_force_search_command(self):
        self.register("비토애 산청 5/2~5/3")
        self.watches()[0]["force"] = False
        self.say("지금")
        self.assertTrue(self.watches()[0]["force"])

    def test_watch_limit(self):
        for i in range(bot.MAX_WATCHES):
            self.register(f"숙소{i} 5/2~5/3")
        replies = self.register("하나더 5/2~5/3")
        self.assertIn("최대", texts(replies))


class SearchRunTest(unittest.TestCase):
    def setUp(self):
        self.db = storage.default_db()
        for message in ("비토애 산청 5/2~5/3", "경남 산청군 시천면", "2", "예"):
            bot.handle_text(self.db, CHAT, message, today=TODAY)
        self.watch = storage.get_chat(self.db, CHAT)["watches"][0]

    def run_search(self, browser, now=1_000_000.0):
        bot.run_due_searches(self.db, now=now, today=TODAY, browser=browser)

    def test_available_sends_report(self):
        browser = FakeBrowser(cards=[
            {"text": "비토애 산청\n산청군 시천면\n디럭스 120,000원", "url": "https://x/1"}])
        with FakeTelegram() as fake:
            self.run_search(browser)
        self.assertIn("예약 가능", fake.text())
        self.assertIn("120,000원", fake.text())
        self.assertTrue(self.watch["was_available"])
        self.assertFalse(self.watch["force"])

    def test_no_repeat_notification_within_interval(self):
        cards = [{"text": "비토애 산청\n산청군 시천면\n120,000원", "url": "https://x/1"}]
        with FakeTelegram():
            self.run_search(FakeBrowser(cards=cards), now=1_000_000.0)
        self.watch["last_searched"] = 0
        with FakeTelegram() as second:
            self.run_search(FakeBrowser(cards=cards), now=1_000_100.0)
        self.assertEqual(second.sent, [])

    def test_price_change_alone_does_not_notify_again(self):
        # 빈방이 계속 열려 있는 동안에는 값이 달라져도 다시 알리지 않는다
        with FakeTelegram():
            self.run_search(FakeBrowser(cards=[
                {"text": "비토애 산청\n산청군 시천면\n120,000원"}]), now=1_000_000.0)
        self.watch["last_searched"] = 0
        with FakeTelegram() as second:
            self.run_search(FakeBrowser(cards=[
                {"text": "비토애 산청\n산청군 시천면\n99,000원"}]), now=1_000_100.0)
        self.assertEqual(second.sent, [])

    def test_notifies_again_after_the_interval(self):
        with FakeTelegram():
            self.run_search(FakeBrowser(cards=[
                {"text": "비토애 산청\n산청군 시천면\n120,000원"}]), now=1_000_000.0)
        self.watch["last_searched"] = 0
        later = 1_000_000.0 + bot.NOTIFY_INTERVAL + 1
        with FakeTelegram() as second:
            self.run_search(FakeBrowser(cards=[
                {"text": "비토애 산청\n산청군 시천면\n120,000원"}]), now=later)
        self.assertIn("120,000원", second.text())

    def test_reopening_notifies_right_away(self):
        # 마감됐다가 다시 열리면 간격과 상관없이 바로 알린다
        with FakeTelegram():
            self.run_search(FakeBrowser(cards=[
                {"text": "비토애 산청\n산청군 시천면\n120,000원"}]), now=1_000_000.0)
        self.watch["last_searched"] = 0
        with FakeTelegram():
            self.run_search(FakeBrowser(cards=[
                {"text": "비토애 산청\n산청군 시천면\n예약마감"}]), now=1_000_100.0)
        self.watch["last_searched"] = 0
        with FakeTelegram() as third:
            self.run_search(FakeBrowser(cards=[
                {"text": "비토애 산청\n산청군 시천면\n130,000원"}]), now=1_000_200.0)
        self.assertIn("130,000원", third.text())

    def test_sold_out_after_available_notifies_once(self):
        with FakeTelegram():
            self.run_search(FakeBrowser(cards=[
                {"text": "비토애 산청\n산청군 시천면\n120,000원"}]))
        self.watch["last_searched"] = 0
        with FakeTelegram() as second:
            self.run_search(FakeBrowser(cards=[
                {"text": "비토애 산청\n산청군 시천면\n예약마감"}]), now=1_000_100.0)
        self.assertIn("마감됐어요", second.text())

        self.watch["last_searched"] = 0
        with FakeTelegram() as third:
            self.run_search(FakeBrowser(cards=[
                {"text": "비토애 산청\n산청군 시천면\n예약마감"}]), now=1_000_200.0)
        self.assertEqual(third.sent, [])

    def test_address_mismatch_is_filtered_out(self):
        cards = [
            {"text": "비토애 산청\n제주시 애월읍\n120,000원", "url": "https://x/1"},
            {"text": "비토애 산청\n산청군 시천면\n150,000원", "url": "https://x/2"},
        ]
        with FakeTelegram() as fake:
            self.run_search(FakeBrowser(cards=cards))
        self.assertIn("150,000원", fake.text())
        self.assertNotIn("120,000원", fake.text())
        self.assertIn("주소 일치", fake.text())

    def test_card_without_address_is_flagged(self):
        with FakeTelegram() as fake:
            self.run_search(FakeBrowser(cards=[
                {"text": "비토애 산청\n디럭스\n120,000원", "url": "https://x/1"}]))
        self.assertIn("주소 미확인", fake.text())

    def test_not_due_is_skipped(self):
        self.watch["force"] = False
        self.watch["last_searched"] = 1_000_000
        browser = FakeBrowser()
        with FakeTelegram() as fake:
            self.run_search(browser, now=1_000_060.0)
        self.assertEqual(browser.visited, [])
        self.assertEqual(fake.sent, [])

    def test_manual_search_reports_even_when_unavailable(self):
        self.watch["force"] = True
        with FakeTelegram() as fake:
            self.run_search(FakeBrowser(cards=[{"text": "다른 숙소\n80,000원"}]))
        self.assertIn("검색 결과", fake.text())

    def test_expired_watch_is_removed(self):
        with FakeTelegram() as fake:
            bot.run_due_searches(self.db, now=1_000_000.0, today=date(2026, 6, 1),
                                 browser=FakeBrowser())
        self.assertEqual(storage.get_chat(self.db, CHAT)["watches"], [])
        self.assertIn("숙박일이 지나", fake.text())

    def test_site_that_does_not_list_the_place(self):
        """사이트가 '검색 결과가 없어요'라고 답하면 미취급으로 알린다."""
        browser = FakeBrowser(cards=[{"text": "다른 숙소\n80,000원"}],
                              body="'비토애 산청' 검색 결과가 없어요.")
        self.watch["force"] = True
        with FakeTelegram() as fake:
            self.run_search(browser)
        self.assertIn("미취급", fake.text())
        self.assertIn("이 사이트에는 없는 숙소예요", fake.text())

    def test_many_cards_are_not_called_not_listed(self):
        """결과가 잔뜩 떠 있으면 '결과 없음' 문구가 있어도 미취급으로 단정하지 않는다."""
        cards = [{"text": f"다른 숙소 {i}\n80,000원"} for i in range(10)]
        browser = FakeBrowser(cards=cards, body="조건에 맞는 숙소가 없어요 (필터 안내)")
        self.watch["force"] = True
        with FakeTelegram() as fake:
            self.run_search(browser)
        self.assertNotIn("미취급", fake.text())

    def test_unknown_status_explains_itself(self):
        """가격이 안 보이는 카드는 왜 판정을 못 했는지 알려준다."""
        self.watch["force"] = True
        with FakeTelegram() as fake:
            self.run_search(FakeBrowser(cards=[{"text": "비토애 산청\n산청군 시천면\n펜션"}]))
        self.assertIn("가격 표시가 없어", fake.text())

    def test_site_error_is_reported_not_raised(self):
        class BrokenBrowser(FakeBrowser):
            def collect_cards(self, *args, **kwargs):
                raise RuntimeError("chrome 실행 실패")

        with FakeTelegram() as fake:
            self.run_search(BrokenBrowser())
        self.assertIn("검색 실패", fake.text())

    def test_registered_naver_url_uses_detail_check(self):
        watch = self.watch
        watch["url"] = "https://m.place.naver.com/accommodation/1/room"
        watch["force"] = True
        page = ("네이버 예약 " + "객실 안내 " * 12 + "경남 산청군 시천면 "
                + "기준 최대 최소 예약마감 " * 2 + "기준 최대 최소 130,000원")
        with FakeTelegram() as fake:
            self.run_search(FakeBrowser(page_text=page))
        self.assertIn("네이버 예약(등록 링크)", fake.text())
        self.assertIn("빈 객실 있음", fake.text())


class ParticleTest(unittest.TestCase):
    def test_object_particle(self):
        self.assertEqual(bot._object_particle("부킹닷컴"), "을")   # 받침 있음
        self.assertEqual(bot._object_particle("여기어때"), "를")   # 받침 없음


class LogMaskTest(unittest.TestCase):
    def test_chat_id_is_masked(self):
        self.assertEqual(bot.mask("652517175"), "…7175")
        self.assertEqual(bot.mask(123), "…")


class StorageTest(unittest.TestCase):
    def test_legacy_migration(self):
        legacy = {
            "last_update_id": 5,
            "users": {
                CHAT: [{
                    "url": "https://m.place.naver.com/accommodation/1/room?"
                           "bk_query=%EB%B9%84%ED%86%A0%EC%95%A0&checkin=20260502"
                           "&checkout=20260503&guest=4",
                    "last_notified": 12,
                }],
            },
        }
        db = storage.migrate(legacy)
        watch = db["chats"][CHAT]["watches"][0]
        self.assertEqual(db["version"], storage.SCHEMA_VERSION)
        self.assertEqual(watch["query"], "비토애")
        self.assertEqual(watch["checkin"], "2026-05-02")
        self.assertEqual(watch["last_notified"], 12)

    def test_migration_is_idempotent(self):
        db = storage.migrate(storage.migrate({"users": {}}))
        self.assertEqual(db["chats"], {})

    def test_roundtrip(self):
        import tempfile

        db = storage.default_db()
        storage.get_chat(db, CHAT)["watches"].append(
            storage.new_watch("비토애 산청", "2026-05-02", "2026-05-03", 4,
                              address="경남 산청군")
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "users.json")
            storage.save_db(db, path)
            loaded = storage.load_db(path)
        self.assertEqual(loaded["chats"][CHAT]["watches"][0]["address"], "경남 산청군")


if __name__ == "__main__":
    unittest.main()


TRIPLE_URL = ("https://triple.guide/hotels/d0e0ae59-1ede-4062-baaf-ebc7af354718"
              "?regionId=41ef0101-2663-4f1f-a117-8c5490f4cf44&checkIn=2026-10-04"
              "&checkOut=2026-10-05&numberOfAdults=2")


class TripleLinkConversationTest(unittest.TestCase):
    def setUp(self):
        self.db = storage.default_db()

    def say(self, text):
        return bot.handle_text(self.db, CHAT, text, today=TODAY)

    def tap(self, data):
        return bot.handle_callback(self.db, CHAT, data, today=TODAY)

    def state(self):
        return storage.get_chat(self.db, CHAT)["state"]

    def watches(self):
        return storage.get_chat(self.db, CHAT)["watches"]

    def register(self, line):
        self.say(line)
        self.say("건너뛰기")
        if self.state() and self.state()["step"] == "await_guests":
            self.say("2")
        return self.say("예")

    def test_link_without_any_watch_asks_to_register_first(self):
        replies = self.say(TRIPLE_URL)
        self.assertIn("먼저 숙소 이름을", texts(replies))
        self.assertIsNone(self.state())

    def test_single_watch_gets_the_link_right_away(self):
        self.register("덴바스타 10/4~10/5")
        replies = self.say(TRIPLE_URL)
        self.assertIn("트리플", texts(replies))
        self.assertEqual(self.watches()[0]["triple"], TRIPLE_URL)
        self.assertTrue(self.watches()[0]["force"])
        self.assertIsNone(self.state())

    def test_several_watches_ask_which_one(self):
        self.register("덴바스타 10/4~10/5")
        self.register("쏠비치 남해 11/1~11/2")
        replies = self.say(f"이거요 {TRIPLE_URL}")
        self.assertIn("어느 숙소에 붙일까요", texts(replies))
        self.assertIn("triple:pick:1", buttons(replies))
        self.assertEqual(self.state()["step"], "await_triple_target")

        self.tap("triple:pick:1")
        self.assertIsNone(self.watches()[0]["triple"])
        self.assertEqual(self.watches()[1]["triple"], TRIPLE_URL)

    def test_number_works_instead_of_button(self):
        self.register("덴바스타 10/4~10/5")
        self.register("쏠비치 남해 11/1~11/2")
        self.say(TRIPLE_URL)
        self.say("1")
        self.assertEqual(self.watches()[0]["triple"], TRIPLE_URL)

    def test_cancel_leaves_watches_alone(self):
        self.register("덴바스타 10/4~10/5")
        self.register("쏠비치 남해 11/1~11/2")
        self.say(TRIPLE_URL)
        self.tap("triple:cancel")
        self.assertIsNone(self.watches()[0]["triple"])
        self.assertIsNone(self.state())

    def test_list_shows_the_connection(self):
        self.register("덴바스타 10/4~10/5")
        self.say(TRIPLE_URL)
        self.assertIn("인터파크 트리플 연결됨", texts(self.say("목록")))

    def test_naver_link_still_registers_a_new_watch(self):
        replies = self.say("https://m.place.naver.com/accommodation/1259756405/room")
        self.assertNotIn("어느 숙소에 붙일까요", texts(replies))


class StuckStateTest(unittest.TestCase):
    """등록을 하다 만 뒤에 다른 숙소를 못 넣던 문제."""

    def setUp(self):
        self.db = storage.default_db()

    def say(self, text, lookup=None):
        return bot.handle_text(self.db, CHAT, text, today=TODAY, lookup=lookup)

    def state(self):
        return storage.get_chat(self.db, CHAT)["state"]

    def stall_at_date_step(self):
        self.say("케이키즈풀빌라펜션")
        self.say("건너뛰기")
        self.assertEqual(self.state()["step"], "await_checkin")

    def test_new_name_at_date_step_starts_over(self):
        self.stall_at_date_step()
        replies = self.say("소노캄 경주")
        self.assertNotIn("날짜를 이해하지 못했어요", texts(replies))
        self.assertIn("소노캄 경주", texts(replies))
        self.assertEqual(self.state()["query"], "소노캄 경주")

    def test_real_date_still_works(self):
        self.stall_at_date_step()
        self.say("5/2~5/3")
        self.assertIn(self.state()["step"], ("await_guests", "await_confirm"))

    def test_gibberish_with_digits_explains_how_to_quit(self):
        self.stall_at_date_step()
        replies = self.say("13월 99일")
        self.assertIn("취소", texts(replies))
        self.assertEqual(self.state()["step"], "await_checkin")

    def test_forgotten_registration_expires(self):
        self.stall_at_date_step()
        # 30분 넘게 손을 놓았다
        self.state()["touched_at"] = int(time.time()) - bot.STATE_TTL - 1
        replies = self.say("소노캄 경주")
        self.assertNotIn("날짜를 이해하지 못했어요", texts(replies))
        self.assertEqual(self.state()["query"], "소노캄 경주")

    def test_a_live_registration_is_not_dropped(self):
        self.stall_at_date_step()
        self.say("5/2~5/3")
        self.assertIsNotNone(self.state())


class MenuButtonTest(unittest.TestCase):
    """입력창 아래 고정 메뉴 버튼."""

    def setUp(self):
        self.db = storage.default_db()

    def say(self, text, lookup=None):
        return bot.handle_text(self.db, CHAT, text, today=TODAY, lookup=lookup)

    def tap(self, data):
        return bot.handle_callback(self.db, CHAT, data, today=TODAY)

    def watches(self):
        return storage.get_chat(self.db, CHAT)["watches"]

    def register(self, line):
        self.say(line)
        self.tap("place:skip")
        self.say("5/2~5/3")
        if storage.get_chat(self.db, CHAT)["state"]["step"] == "await_guests":
            self.tap("guests:pick:2")
        return self.say("예")

    def test_button_text_becomes_a_command(self):
        self.assertIn("숙소 이름을 보내주세요", texts(self.say("➕ 숙소 추가")))
        self.assertIn("등록된 알림이 없어요", texts(self.say("📋 목록")))
        self.assertIn("삭제할 알림이 없어요", texts(self.say("➖ 삭제")))
        self.assertIn("등록된 알림이 없어요", texts(self.say("🔍 지금 검색")))
        self.assertIn("숙소 빈방 알림봇", texts(self.say("❓ 도움말")))

    def test_plain_words_still_work(self):
        self.assertIn("등록된 알림이 없어요", texts(self.say("목록")))

    def test_delete_button_asks_which_one(self):
        self.register("비토애 산청")
        replies = self.say("➖ 삭제")
        self.assertIn("어느 알림을 지울까요", texts(replies))
        self.assertIn("del:pick:0", buttons(replies))
        self.assertIn("del:all", buttons(replies))
        self.assertEqual(len(self.watches()), 1)   # 아직 안 지웠다

    def test_bare_delete_no_longer_wipes_everything(self):
        self.register("비토애 산청")
        self.say("삭제")
        self.assertEqual(len(self.watches()), 1)

    def test_delete_one_by_button(self):
        self.register("비토애 산청")
        self.say("➖ 삭제")
        self.tap("del:pick:0")
        self.assertEqual(self.watches(), [])

    def test_delete_all_by_button(self):
        self.register("비토애 산청")
        self.say("➖ 삭제")
        self.tap("del:all")
        self.assertEqual(self.watches(), [])

    def test_delete_cancel_keeps_them(self):
        self.register("비토애 산청")
        self.say("➖ 삭제")
        self.tap("del:cancel")
        self.assertEqual(len(self.watches()), 1)

    def test_delete_with_a_number_still_works(self):
        self.register("비토애 산청")
        self.say("삭제 1")
        self.assertEqual(self.watches(), [])

    def test_delete_all_by_word_still_works(self):
        self.register("비토애 산청")
        self.say("삭제 전체")
        self.assertEqual(self.watches(), [])


class NoTypingTest(unittest.TestCase):
    """숙소 이름 말고는 타이핑 없이 끝나는지."""

    def setUp(self):
        self.db = storage.default_db()

    def say(self, text, lookup=None):
        return bot.handle_text(self.db, CHAT, text, today=TODAY, lookup=lookup)

    def tap(self, data):
        return bot.handle_callback(self.db, CHAT, data, today=TODAY)

    def state(self):
        return storage.get_chat(self.db, CHAT)["state"]

    def test_address_step_has_buttons(self):
        replies = self.say("비토애 산청")
        self.assertEqual(self.state()["step"], "await_address")
        self.assertIn("place:skip", buttons(replies))
        self.assertIn("place:cancel", buttons(replies))

    def test_name_then_only_buttons(self):
        self.say("비토애 산청")            # 타이핑은 여기 한 번뿐
        self.tap("place:skip")            # 주소 건너뛰기
        self.tap("cal:in:2026-05-02")     # 체크인
        self.tap("cal:out:2026-05-03")    # 체크아웃
        self.tap("guests:pick:4")         # 인원
        self.tap("confirm:yes")
        watches = storage.get_chat(self.db, CHAT)["watches"]
        self.assertEqual(len(watches), 1)
        self.assertEqual(watches[0]["checkin"], "2026-05-02")
        self.assertEqual(watches[0]["checkout"], "2026-05-03")
        self.assertEqual(watches[0]["guests"], 4)


class MenuAttachedTest(unittest.TestCase):
    """보내는 메시지에 하단 메뉴가 실제로 붙는지."""

    def test_menu_rides_along(self):
        db = storage.default_db()
        with FakeTelegram() as fake:
            bot._send_replies(CHAT, [bot.reply("안녕하세요")])
        self.assertEqual(fake.menus[-1], keyboards.menu_keyboard())

    def test_telegram_builds_a_persistent_keyboard(self):
        import json
        import telegram_api as api
        markup = json.loads(api._menu_markup(keyboards.menu_keyboard()))
        self.assertTrue(markup["is_persistent"])
        self.assertTrue(markup["resize_keyboard"])
        self.assertIn("➕ 숙소 추가", markup["keyboard"][0])

    def test_inline_buttons_win_over_the_menu(self):
        # 한 메시지에 둘 다는 못 붙인다 — 달력 같은 버튼이 우선
        import json
        import telegram_api as api
        self.assertIsNone(api._menu_markup(None))
        self.assertIn("inline_keyboard", json.loads(api._markup([[{"text": "x", "callback_data": "y"}]])))


class SearchingNoticeTest(unittest.TestCase):
    """네이버를 훑는 동안 '찾는 중'이라고 먼저 알리는지."""

    class SlowBrowser:
        """후보를 돌려주기 전에 시간이 걸리는 척한다."""

        def collect_cards(self, url, selectors, wait=6, scrolls=2, retry_wait=5,
                          ready=None):
            return [{"text": "비토애 산청\n경남 산청군 시천면 지리산대로 123",
                     "url": "https://m.place.naver.com/accommodation/1/room"}]

        def body_text(self, limit=2000):
            return ""

        def quit(self):
            pass

    def test_notice_comes_before_the_candidates(self):
        db = storage.default_db()
        update = {"update_id": 1,
                  "message": {"text": "비토애 산청", "chat": {"id": int(CHAT)}}}

        with FakeTelegram() as fake:
            original = telegram_api.get_updates
            telegram_api.get_updates = bot.telegram_api.get_updates = (
                lambda offset, timeout=0, limit=50: [update])
            try:
                bot.process_updates(db, browser=self.SlowBrowser(), timeout=0)
            finally:
                telegram_api.get_updates = bot.telegram_api.get_updates = original

        sent = [text for _, text in fake.sent]
        self.assertTrue(sent, "아무 메시지도 안 갔다")
        self.assertIn("찾는 중", sent[0])          # 먼저 안내가 가고
        self.assertIn("비토애 산청", sent[0])
        self.assertIn("어느 숙소인가요", "\n".join(sent[1:]))   # 그 다음 후보


class StayAwakeDuringSearchTest(unittest.TestCase):
    """검색이 도는 동안에도 텔레그램 입력을 받는지."""

    class CountingBrowser:
        def collect_cards(self, url, selectors, wait=6, scrolls=2, retry_wait=5,
                          ready=None):
            return [{"text": "비토애 산청\n산청군 시천면\n120,000원", "url": "https://x/1"}]

        def body_text(self, limit=2000):
            return ""

        def quit(self):
            pass

    def setUp(self):
        self.db = storage.default_db()
        chat = storage.get_chat(self.db, CHAT)
        chat["watches"] = [storage.new_watch("비토애 산청", "2026-05-02", "2026-05-03",
                                             2, address="경남 산청군 시천면")]
        self.watch = chat["watches"][0]
        self.watch["force"] = True

    def test_called_between_sites(self):
        calls = []
        with FakeTelegram():
            bot.run_due_searches(self.db, browser=self.CountingBrowser(),
                                 today=TODAY, between=lambda: calls.append(1))
        sites = len(search.load_sites())
        self.assertEqual(len(calls), sites)   # 사이트마다 한 번씩

    def test_works_without_the_hook(self):
        with FakeTelegram() as fake:
            bot.run_due_searches(self.db, browser=self.CountingBrowser(),
                                 today=TODAY)
        self.assertIn("비토애 산청", fake.text())


class NewPersonNoticeTest(unittest.TestCase):
    """남이 봇을 쓰기 시작하면 주인에게 알리는지."""

    OTHER = "99887766"

    def setUp(self):
        self.db = storage.default_db()
        self.db["owner"] = CHAT
        storage.get_chat(self.db, CHAT)   # 주인은 이미 쓰고 있다

    def feed(self, chat_id, text="안녕"):
        update = {"update_id": 1,
                  "message": {"text": text, "chat": {"id": int(chat_id)}}}
        original = telegram_api.get_updates
        telegram_api.get_updates = bot.telegram_api.get_updates = (
            lambda offset, timeout=0, limit=50: [update])
        try:
            bot.process_updates(self.db, browser=None, timeout=0)
        finally:
            telegram_api.get_updates = bot.telegram_api.get_updates = original

    def test_owner_hears_about_a_stranger(self):
        with FakeTelegram() as fake:
            self.feed(self.OTHER)
        notices = [text for chat, text in fake.sent
                   if chat == CHAT and "새로운 사람" in text]
        self.assertEqual(len(notices), 1)
        self.assertIn("…7766", notices[0])          # 가린 채팅 ID
        self.assertNotIn(self.OTHER, notices[0])    # 전체 ID 는 안 보낸다

    def test_only_once_per_person(self):
        with FakeTelegram() as fake:
            self.feed(self.OTHER)
            self.feed(self.OTHER, "목록")
        notices = [t for c, t in fake.sent if c == CHAT and "새로운 사람" in t]
        self.assertEqual(len(notices), 1)

    def test_owner_is_not_announced(self):
        with FakeTelegram() as fake:
            self.feed(CHAT)
        self.assertEqual([t for c, t in fake.sent if "새로운 사람" in t], [])

    def test_first_person_becomes_the_owner(self):
        db = storage.default_db()
        self.db = db
        with FakeTelegram() as fake:
            self.feed(self.OTHER)
        self.assertEqual(db["owner"], self.OTHER)
        self.assertEqual([t for c, t in fake.sent if "새로운 사람" in t], [])


class OwnerGuessTest(unittest.TestCase):
    """이미 쓰고 있던 사람을 주인으로 이어받는지."""

    def test_picks_the_one_with_the_most_watches(self):
        db = storage.default_db()
        busy = storage.get_chat(db, "111")
        busy["watches"] = [storage.new_watch("가", "2026-05-02", "2026-05-03"),
                           storage.new_watch("나", "2026-05-02", "2026-05-03")]
        storage.get_chat(db, "222")
        self.assertEqual(storage.ensure_owner(db), "111")

    def test_keeps_an_owner_once_set(self):
        db = storage.default_db()
        db["owner"] = "333"
        storage.get_chat(db, "111")["watches"] = [
            storage.new_watch("가", "2026-05-02", "2026-05-03")]
        self.assertEqual(storage.ensure_owner(db), "333")

    def test_no_owner_when_nobody_has_used_it(self):
        self.assertEqual(storage.ensure_owner(storage.default_db()), "")


class OwnerNeverChangesTest(unittest.TestCase):
    """주인은 한 번 정해지면 바뀌지 않는다."""

    def test_someone_else_with_more_watches_does_not_take_over(self):
        db = storage.default_db()
        db["owner"] = "111"
        storage.get_chat(db, "111")            # 주인은 숙소가 하나도 없고
        greedy = storage.get_chat(db, "222")   # 남이 잔뜩 등록해도
        greedy["watches"] = [storage.new_watch(str(n), "2026-05-02", "2026-05-03")
                             for n in range(5)]
        self.assertEqual(storage.ensure_owner(db), "111")

    def test_owner_survives_losing_all_watches(self):
        db = storage.default_db()
        db["owner"] = "111"
        storage.get_chat(db, "111")["watches"] = []
        self.assertEqual(storage.ensure_owner(db), "111")

    def test_owner_survives_a_reload(self):
        db = storage.default_db()
        db["owner"] = "111"
        storage.get_chat(db, "222")["watches"] = [
            storage.new_watch("가", "2026-05-02", "2026-05-03")]
        again = storage.migrate(json.loads(json.dumps(db)))
        self.assertEqual(again["owner"], "111")

    def test_setting_wins_over_everything(self):
        original = storage.OWNER_CHAT_ID
        storage.OWNER_CHAT_ID = "999"
        try:
            db = storage.default_db()
            db["owner"] = "111"
            self.assertEqual(storage.ensure_owner(db), "999")
            self.assertEqual(db["owner"], "999")
        finally:
            storage.OWNER_CHAT_ID = original

    def test_a_stranger_cannot_become_owner_by_talking(self):
        db = storage.default_db()
        db["owner"] = CHAT
        storage.get_chat(db, CHAT)
        update = {"update_id": 1,
                  "message": {"text": "안녕", "chat": {"id": 55554444}}}
        original = telegram_api.get_updates
        telegram_api.get_updates = bot.telegram_api.get_updates = (
            lambda offset, timeout=0, limit=50: [update])
        try:
            with FakeTelegram():
                bot.process_updates(db, browser=None, timeout=0)
        finally:
            telegram_api.get_updates = bot.telegram_api.get_updates = original
        self.assertEqual(db["owner"], CHAT)
