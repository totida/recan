import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import keyboards  # noqa: E402

TODAY = date(2026, 4, 20)


def all_data(rows):
    return [button["callback_data"] for row in rows for button in row]


def all_labels(rows):
    return [button["text"] for row in rows for button in row]


class CalendarTest(unittest.TestCase):
    def test_today_is_marked_and_selectable(self):
        rows = keyboards.month_calendar(2026, 4, TODAY)
        self.assertIn("[20]", all_labels(rows))
        self.assertIn("cal:in:2026-04-20", all_data(rows))

    def test_past_days_are_disabled(self):
        rows = keyboards.month_calendar(2026, 4, TODAY)
        self.assertNotIn("cal:in:2026-04-19", all_data(rows))
        self.assertNotIn("cal:in:2026-04-01", all_data(rows))

    def test_previous_month_button_hidden_at_current_month(self):
        rows = keyboards.month_calendar(2026, 4, TODAY)
        self.assertNotIn("cal:m:2026-03", all_data(rows))
        self.assertIn("cal:m:2026-05", all_data(rows))

    def test_previous_month_available_later(self):
        rows = keyboards.month_calendar(2026, 6, TODAY)
        self.assertIn("cal:m:2026-05", all_data(rows))

    def test_one_year_ahead_limit(self):
        rows = keyboards.month_calendar(2027, 4, TODAY)
        self.assertNotIn("cal:m:2027-05", all_data(rows))

    def test_checkout_mode_starts_after_checkin(self):
        rows = keyboards.month_calendar(2026, 5, TODAY,
                                        min_date=date(2026, 5, 3), mode="out")
        data = all_data(rows)
        self.assertIn("cal:out:2026-05-03", data)
        self.assertNotIn("cal:out:2026-05-02", data)

    def test_has_manual_input_and_cancel(self):
        data = all_data(keyboards.month_calendar(2026, 4, TODAY))
        self.assertIn("cal:type", data)
        self.assertIn("cal:cancel", data)

    def test_default_month_follows_today(self):
        self.assertEqual(keyboards.default_month(TODAY), (2026, 4))
        self.assertEqual(keyboards.default_month(TODAY, date(2026, 12, 1)), (2026, 12))

    def test_next_day(self):
        self.assertEqual(keyboards.next_day("2026-05-02"), date(2026, 5, 3))


class PlaceKeyboardTest(unittest.TestCase):
    CANDIDATES = [
        {"name": "비토애 산청", "address": "경남 산청군 시천면 지리산대로 123"},
        {"name": "비토애 별관", "address": "경남 산청군 단성면"},
    ]

    def test_one_button_per_candidate(self):
        data = all_data(keyboards.place_keyboard(self.CANDIDATES))
        self.assertIn("place:pick:0", data)
        self.assertIn("place:pick:1", data)
        self.assertIn("place:none", data)
        self.assertIn("place:skip", data)

    def test_message_lists_addresses(self):
        message = keyboards.place_message("비토애 산청", self.CANDIDATES)
        self.assertIn("1. 비토애 산청", message)
        self.assertIn("경남 산청군 시천면 지리산대로 123", message)


if __name__ == "__main__":
    unittest.main()
