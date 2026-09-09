import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot  # noqa: E402
import search  # noqa: E402
import storage  # noqa: E402
import telegram_api  # noqa: E402

TODAY = date(2026, 4, 20)
CHAT = "1001"


class FakeTelegram:
    """telegram_api.send_message 를 가로채 보낸 메시지를 모아둔다."""

    def __init__(self):
        self.sent = []
        self._original = telegram_api.send_message

    def __enter__(self):
        def _send(chat_id, text, preview=False):
            self.sent.append((str(chat_id), text))
            return True

        telegram_api.send_message = _send
        bot.telegram_api.send_message = _send
        return self

    def __exit__(self, *exc):
        telegram_api.send_message = self._original
        bot.telegram_api.send_message = self._original

    def text(self):
        return "\n".join(t for _, t in self.sent)


class FakeBrowser:
    """검색 결과를 미리 정해두는 가짜 브라우저."""

    def __init__(self, cards=None, page_text=""):
        self.cards = cards or []
        self._page_text = page_text
        self.visited = []
        self.quit_called = False

    def collect_cards(self, url, selectors, wait=6, scrolls=2):
        self.visited.append(url)
        return self.cards

    def page_text(self, url, wait=7, scrolls=2):
        self.visited.append(url)
        return self._page_text

    def quit(self):
        self.quit_called = True


class ConversationTest(unittest.TestCase):
    def setUp(self):
        self.db = storage.default_db()

    def say(self, text):
        return bot.handle_text(self.db, CHAT, text, today=TODAY)

    def watches(self):
        return storage.get_chat(self.db, CHAT)["watches"]

    def register(self, line, address="건너뛰기", approve="예"):
        """이름+날짜 → 주소 → 승인까지 한 번에."""
        self.say(line)
        self.say(address)
        return self.say(approve)

    def state(self):
        return storage.get_chat(self.db, CHAT)["state"]

    def test_full_flow_name_dates_address_confirm(self):
        replies = self.say("비토애 산청")
        self.assertIn("언제 묵으실 건가요", replies[0])
        self.assertEqual(self.state()["step"], "await_dates")

        replies = self.say("5/2~5/3")
        self.assertIn("주소를 알려주세요", replies[0])
        self.assertEqual(self.state()["step"], "await_address")

        replies = self.say("경남 산청군 시천면 지리산대로 123")
        self.assertIn("맞는지 확인해 주세요", replies[0])
        self.assertIn("경남 산청군 시천면", replies[0])
        self.assertEqual(self.state()["step"], "await_confirm")
        self.assertEqual(self.watches(), [])  # 승인 전에는 등록되지 않는다

        replies = self.say("예")
        self.assertIn("등록 완료", replies[0])
        self.assertIsNone(self.state())

        watch = self.watches()[0]
        self.assertEqual(watch["query"], "비토애 산청")
        self.assertEqual(watch["address"], "경남 산청군 시천면 지리산대로 123")
        self.assertEqual(watch["checkin"], "2026-05-02")
        self.assertEqual(watch["checkout"], "2026-05-03")
        self.assertTrue(watch["force"])  # 등록 직후 즉시 검색

    def test_reject_confirmation_restarts(self):
        self.say("비토애 산청")
        self.say("5/2~5/3")
        self.say("경남 산청군")
        replies = self.say("아니오")
        self.assertIn("다시 알려주세요", replies[0])
        self.assertIsNone(self.state())
        self.assertEqual(self.watches(), [])

    def test_unclear_confirmation_keeps_asking(self):
        self.say("비토애 산청 5/2~5/3")
        self.say("경남 산청군")
        replies = self.say("음...")
        self.assertIn("'예' 또는 '아니오'", replies[0])
        self.assertEqual(self.state()["step"], "await_confirm")

    def test_address_can_be_skipped(self):
        self.say("비토애 산청 5/2~5/3")
        replies = self.say("건너뛰기")
        self.assertIn("(입력 안 함)", replies[0])
        self.say("예")
        self.assertEqual(self.watches()[0]["address"], "")

    def test_single_line_registration(self):
        replies = self.say("소노벨 변산 5/2~5/4 4명")
        self.assertIn("주소를 알려주세요", replies[0])
        self.say("전북 부안군 변산면")
        self.say("네")
        watch = self.watches()[0]
        self.assertEqual(watch["query"], "소노벨 변산")
        self.assertEqual(watch["address"], "전북 부안군 변산면")
        self.assertEqual(watch["guests"], 4)
        self.assertEqual(watch["checkout"], "2026-05-04")

    def test_bad_date_keeps_waiting(self):
        self.say("비토애 산청")
        replies = self.say("아무때나")
        self.assertIn("이해하지 못했어요", replies[0])
        self.assertEqual(
            storage.get_chat(self.db, CHAT)["state"]["step"], "await_dates"
        )
        self.assertEqual(self.watches(), [])

    def test_cancel_pending(self):
        self.say("비토애 산청")
        replies = self.say("취소")
        self.assertIn("취소", replies[0])
        self.assertIsNone(storage.get_chat(self.db, CHAT)["state"])

    def test_duplicate_registration_rejected(self):
        self.register("비토애 산청 5/2~5/3")
        replies = self.register("비토애 산청 5/2~5/3")
        self.assertIn("이미 등록", replies[0])
        self.assertEqual(len(self.watches()), 1)

    def test_list_and_delete(self):
        self.register("비토애 산청 5/2~5/3", address="경남 산청군")
        self.register("소노벨 변산 6/1~6/2")
        listing = self.say("목록")[0]
        self.assertIn("비토애 산청", listing)
        self.assertIn("📍 경남 산청군", listing)

        self.say("삭제 1")
        self.assertEqual(len(self.watches()), 1)
        self.assertEqual(self.watches()[0]["query"], "소노벨 변산")

        self.say("삭제 전체")
        self.assertEqual(self.watches(), [])

    def test_delete_out_of_range(self):
        self.register("비토애 산청 5/2~5/3")
        self.assertIn("사이의 번호", self.say("삭제 7")[0])

    def test_help_command(self):
        self.assertIn("숙소 빈방 알림봇", self.say("/start")[0])

    def test_naver_link_asks_address_then_registers(self):
        url = (
            "https://m.place.naver.com/accommodation/1259756405/room?entry=pll"
            "&bk_query=%EB%B9%84%ED%86%A0%EC%95%A0%20%EC%82%B0%EC%B2%AD"
            "&guest=4&checkin=20260502&checkout=20260503"
        )
        replies = self.say(url)
        self.assertIn("주소를 알려주세요", replies[0])
        self.say("경남 산청군 시천면")
        self.say("예")
        watch = self.watches()[0]
        self.assertEqual(watch["query"], "비토애 산청")
        self.assertEqual(watch["url"], url)
        self.assertEqual(watch["guests"], 4)

    def test_link_without_dates_asks_for_dates(self):
        replies = self.say("https://www.goodchoice.kr/product/123")
        self.assertIn("언제 묵으실", replies[0])

    def test_force_search_command(self):
        self.register("비토애 산청 5/2~5/3")
        self.watches()[0]["force"] = False
        self.say("지금")
        self.assertTrue(self.watches()[0]["force"])

    def test_watch_limit(self):
        for i in range(bot.MAX_WATCHES):
            self.register(f"숙소{i} 5/2~5/3")
        replies = self.register("하나더 5/2~5/3")
        self.assertIn("최대", replies[0])


class SearchRunTest(unittest.TestCase):
    def setUp(self):
        self.db = storage.default_db()
        for message in ("비토애 산청 5/2~5/3", "경남 산청군 시천면", "예"):
            bot.handle_text(self.db, CHAT, message, today=TODAY)
        self.watch = storage.get_chat(self.db, CHAT)["watches"][0]

    def run_search(self, browser, now=1_000_000.0):
        original = search.Browser
        search.Browser = lambda: browser
        try:
            bot.run_due_searches(self.db, now=now, today=TODAY)
        finally:
            search.Browser = original

    def test_available_sends_report_and_records_state(self):
        browser = FakeBrowser(cards=[{"text": "비토애 산청\n디럭스\n120,000원", "url": "https://x/1"}])
        with FakeTelegram() as fake:
            self.run_search(browser)
        self.assertIn("예약 가능", fake.text())
        self.assertIn("120,000원", fake.text())
        self.assertTrue(self.watch["was_available"])
        self.assertFalse(self.watch["force"])
        self.assertTrue(browser.quit_called)

    def test_no_repeat_notification_within_interval(self):
        cards = [{"text": "비토애 산청\n디럭스\n120,000원", "url": "https://x/1"}]
        with FakeTelegram():
            self.run_search(FakeBrowser(cards=cards), now=1_000_000.0)
        with FakeTelegram() as second:
            self.watch["last_searched"] = 0  # 검색 주기는 지났지만 결과는 동일
            self.run_search(FakeBrowser(cards=cards), now=1_000_100.0)
        self.assertEqual(second.sent, [])

    def test_price_change_triggers_new_notification(self):
        with FakeTelegram():
            self.run_search(FakeBrowser(cards=[{"text": "비토애 산청\n디럭스\n120,000원"}]))
        self.watch["last_searched"] = 0
        with FakeTelegram() as second:
            self.run_search(
                FakeBrowser(cards=[{"text": "비토애 산청\n디럭스\n99,000원"}]),
                now=1_000_100.0,
            )
        self.assertIn("99,000원", second.text())

    def test_sold_out_after_available_notifies_once(self):
        with FakeTelegram():
            self.run_search(FakeBrowser(cards=[{"text": "비토애 산청\n디럭스\n120,000원"}]))
        self.watch["last_searched"] = 0
        with FakeTelegram() as second:
            self.run_search(
                FakeBrowser(cards=[{"text": "비토애 산청\n예약마감"}]), now=1_000_100.0
            )
        self.assertIn("마감됐어요", second.text())
        self.assertFalse(self.watch["was_available"])

        self.watch["last_searched"] = 0
        with FakeTelegram() as third:
            self.run_search(
                FakeBrowser(cards=[{"text": "비토애 산청\n예약마감"}]), now=1_000_200.0
            )
        self.assertEqual(third.sent, [])

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
            bot.run_due_searches(self.db, now=1_000_000.0, today=date(2026, 6, 1))
        self.assertEqual(storage.get_chat(self.db, CHAT)["watches"], [])
        self.assertIn("숙박일이 지나", fake.text())

    def test_address_mismatch_is_filtered_out(self):
        """이름은 같지만 주소가 다른 숙소만 나오면 알리지 않는다."""
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
        cards = [{"text": "비토애 산청\n디럭스\n120,000원", "url": "https://x/1"}]
        with FakeTelegram() as fake:
            self.run_search(FakeBrowser(cards=cards))
        self.assertIn("주소 미확인", fake.text())

    def test_site_error_is_reported_not_raised(self):
        class BrokenBrowser(FakeBrowser):
            def collect_cards(self, *args, **kwargs):
                raise RuntimeError("chrome 실행 실패")

        with FakeTelegram() as fake:
            self.run_search(BrokenBrowser())
        self.assertIn("검색 실패", fake.text())


class StorageTest(unittest.TestCase):
    def test_legacy_migration(self):
        legacy = {
            "last_update_id": 5,
            "users": {
                CHAT: [
                    {
                        "url": "https://m.place.naver.com/accommodation/1/room?bk_query=%EB%B9%84%ED%86%A0%EC%95%A0&checkin=20260502&checkout=20260503&guest=4",
                        "last_notified": 12,
                    }
                ]
            },
        }
        db = storage.migrate(legacy)
        self.assertEqual(db["version"], storage.SCHEMA_VERSION)
        self.assertEqual(db["last_update_id"], 5)
        watch = db["chats"][CHAT]["watches"][0]
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
            storage.new_watch("비토애 산청", "2026-05-02", "2026-05-03", 4)
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "users.json")
            storage.save_db(db, path)
            loaded = storage.load_db(path)
        self.assertEqual(loaded["chats"][CHAT]["watches"][0]["query"], "비토애 산청")


if __name__ == "__main__":
    unittest.main()
