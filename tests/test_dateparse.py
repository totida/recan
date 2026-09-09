import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dateparse  # noqa: E402

TODAY = date(2026, 4, 20)  # 월요일


class ParseStayTest(unittest.TestCase):
    def parse(self, text):
        return dateparse.parse_stay(text, today=TODAY)

    def test_full_iso_range(self):
        ci, co, _ = self.parse("2026-05-02~2026-05-03")
        self.assertEqual((ci, co), (date(2026, 5, 2), date(2026, 5, 3)))

    def test_dotted_range(self):
        ci, co, _ = self.parse("2026.5.2 ~ 2026.5.4")
        self.assertEqual((ci, co), (date(2026, 5, 2), date(2026, 5, 4)))

    def test_compact_range(self):
        ci, co, _ = self.parse("20260502-20260503")
        self.assertEqual((ci, co), (date(2026, 5, 2), date(2026, 5, 3)))

    def test_slash_month_day(self):
        ci, co, _ = self.parse("5/2~5/3")
        self.assertEqual((ci, co), (date(2026, 5, 2), date(2026, 5, 3)))

    def test_korean_words(self):
        ci, co, _ = self.parse("5월 2일부터 5월 3일까지")
        self.assertEqual((ci, co), (date(2026, 5, 2), date(2026, 5, 3)))

    def test_single_date_defaults_to_one_night(self):
        ci, co, _ = self.parse("5/2")
        self.assertEqual((ci, co), (date(2026, 5, 2), date(2026, 5, 3)))

    def test_nights_suffix(self):
        ci, co, _ = self.parse("5/2 2박")
        self.assertEqual((ci, co), (date(2026, 5, 2), date(2026, 5, 4)))

    def test_relative_tomorrow(self):
        ci, co, _ = self.parse("내일 1박")
        self.assertEqual((ci, co), (date(2026, 4, 21), date(2026, 4, 22)))

    def test_this_weekend(self):
        ci, co, _ = self.parse("이번주말")
        self.assertEqual((ci, co), (date(2026, 4, 25), date(2026, 4, 26)))

    def test_next_weekend(self):
        ci, co, _ = self.parse("다음 주말")
        self.assertEqual((ci, co), (date(2026, 5, 2), date(2026, 5, 3)))

    def test_year_rolls_forward_for_past_month_day(self):
        ci, co, _ = self.parse("1/2~1/3")
        self.assertEqual((ci, co), (date(2027, 1, 2), date(2027, 1, 3)))

    def test_year_boundary_range(self):
        ci, co, _ = self.parse("12/30~1/2")
        self.assertEqual((ci, co), (date(2026, 12, 30), date(2027, 1, 2)))

    def test_no_date_returns_none(self):
        self.assertIsNone(self.parse("비토애 산청"))

    def test_reversed_full_dates_rejected(self):
        with self.assertRaises(dateparse.DateParseError):
            self.parse("2026-05-05~2026-05-02")

    def test_too_long_stay_rejected(self):
        with self.assertRaises(dateparse.DateParseError):
            self.parse("2026-05-02~2026-08-02")


class ParseRequestTest(unittest.TestCase):
    def test_single_line_request(self):
        parsed = dateparse.parse_request("비토애 산청 5/2~5/3 4명", today=TODAY)
        self.assertEqual(parsed["name"], "비토애 산청")
        self.assertEqual(parsed["checkin"], date(2026, 5, 2))
        self.assertEqual(parsed["checkout"], date(2026, 5, 3))
        self.assertEqual(parsed["guests"], 4)

    def test_name_only(self):
        parsed = dateparse.parse_request("소노벨 변산", today=TODAY)
        self.assertEqual(parsed["name"], "소노벨 변산")
        self.assertIsNone(parsed["checkin"])

    def test_name_with_number_is_kept(self):
        parsed = dateparse.parse_request("호텔365 내일 2박", today=TODAY)
        self.assertEqual(parsed["name"], "호텔365")
        self.assertEqual(parsed["checkout"], date(2026, 4, 23))


if __name__ == "__main__":
    unittest.main()
