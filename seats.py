"""네이버 예약 공연 좌석 화면에서 붙어 있는 빈자리를 찾는다.

좌석 선택 화면(m.booking.naver.com/booking/…/bizes/…/items/…/seats/…)은 서버가
보내는 HTML 안(window.__APOLLO_STATE__)에 좌석마다 이름('A구역 8열 1번')과
상태('sold' 등)를 담아 둔다. 그래서 크롬을 띄우지 않고 주소 하나만 받아 읽는다.

    python seats.py <좌석 화면 링크> [붙은 자리 수] [몇 열까지]
"""

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

KST = timezone(timedelta(hours=9))
WEEKDAYS = "월화수목금토일"

# 좌석 화면(…/items/공연/seats/회차) 또는 회차를 고른 공연 화면(…/items/공연?slotId=회차).
# 텔레그램 공유로는 뒤의 모양이 온다.
LINK_RE = re.compile(
    r"https?://(?:m\.)?booking\.naver\.com/booking/\d+/bizes/\d+/items/\d+[^\s]*")
# 회차를 아직 안 고른 공연 화면. 좌석 화면으로 바꿀 수 없어 회차를 골라 달라고 한다.
PERFORMANCE_RE = re.compile(r"https?://(?:m\.)?booking\.naver\.com/booking/12/bizes/\d+/items/\d+")
# 'A구역 8열 1번', '1층 B구역 12열 3번', 'C열 7번'
SEAT_NAME_RE = re.compile(r"^(.*?)\s*(\S+?)\s*열\s*(\d+)\s*번")
# 좌석 그림(seattle) 상태: normal · selected · sold · hidden · notForSale.
# 값이 비어 있으면 normal 이다. 이 둘만 살 수 있는 자리로 본다.
OPEN_STATES = (None, "", "normal")

USER_AGENT = ("Mozilla/5.0 (Linux; Android 13; SM-S918N) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")
TIMEOUT = 20


class SeatPageError(RuntimeError):
    """좌석 화면을 열지 못했거나, 열었는데 좌석 정보가 없을 때."""


@dataclass
class Seat:
    name: str
    zone: str
    row: str
    number: int
    available: bool

    def row_number(self):
        return int(self.row) if self.row.isdigit() else None


@dataclass
class SeatPage:
    title: str = ""
    starts_at: datetime = None
    sale_end: datetime = None
    on_sale: bool = True
    seats: list = field(default_factory=list)

    def free_count(self, max_row=None):
        return sum(1 for seat in self.seats
                   if seat.available and within_rows(seat, max_row))


def find_link(text):
    """메시지에서 좌석 화면 링크를 찾는다. (좌석 화면 주소, 회차 번호) 또는 None."""
    match = LINK_RE.search(text or "")
    if not match:
        return None
    link = match.group(0).rstrip(".,)>]")
    parts = urlsplit(link)
    seat = re.search(r"/seats/(\d+)", parts.path)
    if seat:
        return link, seat.group(1)
    query = parse_qsl(parts.query)
    slot = next((value for key, value in query if key == "slotId" and value.isdigit()), None)
    if not slot:
        return None
    rest = urlencode([(key, value) for key, value in query if key != "slotId"])
    path = f"{parts.path.rstrip('/')}/seats/{slot}"
    return urlunsplit((parts.scheme, parts.netloc, path, rest, "")), slot


def apollo_state(html):
    """HTML 에 박힌 window.__APOLLO_STATE__ 를 읽는다."""
    marker = "window.__APOLLO_STATE__="
    start = (html or "").find(marker)
    if start < 0:
        raise SeatPageError("좌석 정보가 들어 있지 않은 화면이에요")
    try:
        state, _ = json.JSONDecoder().raw_decode(html, start + len(marker))
    except ValueError as exc:
        raise SeatPageError(f"좌석 정보를 읽지 못했어요 ({exc})") from exc
    return state


def _first(state, prefix):
    return next((value for key, value in state.items() if key.startswith(prefix)), {})


def _time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(KST)
    except ValueError:
        return None


def parse_seat(name, available):
    match = SEAT_NAME_RE.match(name or "")
    if not match:
        return None
    zone, row, number = match.groups()
    return Seat(name=name, zone=zone.strip(), row=row, number=int(number),
                available=available)


def _drawn_seats(state):
    """좌석 그림(SeattleSeatMap)의 자리들. 상태가 가장 자세하다."""
    seats = []
    for group in _first(state, "SeattleSeatMap:").get("seats") or []:
        for shapes in group.values():
            if not isinstance(shapes, list):
                continue
            for shape in shapes:
                if isinstance(shape, dict) and shape.get("name"):
                    seats.append(parse_seat(shape["name"],
                                            shape.get("state") in OPEN_STATES))
    return [seat for seat in seats if seat]


def _group_seats(state):
    """좌석 그림이 없을 때 쓰는 판매 목록(SeatGroup). sold 가 '0' 이면 빈자리."""
    seats = []
    for key, group in state.items():
        if not key.startswith("SeatGroup:"):
            continue
        items = group.get("seats") or []
        if isinstance(items, str):
            items = json.loads(items)
        for item in items:
            seats.append(parse_seat(item.get("name"), str(item.get("sold")) == "0"))
    return [seat for seat in seats if seat]


def parse_page(html):
    state = apollo_state(html)
    schedule = _first(state, "Slot:").get("hourlySchedule") or {}
    seats = _drawn_seats(state) or _group_seats(state)
    if not seats:
        raise SeatPageError("좌석 목록이 비어 있어요")
    seat_map = _first(state, "SeatMap:")
    return SeatPage(
        title=_first(state, "BizItem:").get("name") or "",
        starts_at=_time(schedule.get("unitStartDateTime")),
        sale_end=_time(schedule.get("saleEndDateTime")),
        on_sale=seat_map.get("sale") is not False,
        seats=seats,
    )


def fetch(url, timeout=TIMEOUT):
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SeatPageError(f"좌석 화면을 열지 못했어요 ({str(exc)[:80]})") from exc
    return response.text


def check(url):
    return parse_page(fetch(url))


def within_rows(seat, max_row):
    """max_row 열 이내인가. 열이 숫자가 아니면(A열 등) 판단할 근거가 없어 거르지 않는다."""
    row = seat.row_number()
    return not max_row or row is None or row <= max_row


def find_runs(seats, count, max_row=None):
    """같은 구역·같은 열에서 번호가 이어진 빈자리가 count 석 이상인 묶음들."""
    rows = {}
    for seat in seats:
        if seat.available and within_rows(seat, max_row):
            rows.setdefault((seat.zone, seat.row), []).append(seat)
    runs = []
    for row_seats in rows.values():
        row_seats.sort(key=lambda seat: seat.number)
        run = []
        for seat in row_seats:
            if run and seat.number != run[-1].number + 1:
                if len(run) >= count:
                    runs.append(run)
                run = []
            run.append(seat)
        if len(run) >= count:
            runs.append(run)
    runs.sort(key=lambda run: (run[0].row_number() or 0, run[0].zone, run[0].number))
    return runs


def describe_run(run):
    """'A구역 6열 1~5번 (5석)'"""
    first, last = run[0], run[-1]
    place = f"{first.zone} {first.row}열".strip()
    numbers = (f"{first.number}번" if first is last
               else f"{first.number}~{last.number}번")
    return f"{place} {numbers} ({len(run)}석)"


def describe_time(moment):
    """'2026-11-08(일) 16:00'"""
    if not moment:
        return ""
    return f"{moment:%Y-%m-%d}({WEEKDAYS[moment.weekday()]}) {moment:%H:%M}"


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    found = find_link(argv[0])
    if not found:
        print("좌석 화면 링크가 아니에요.")
        return 1
    count = int(argv[1]) if len(argv) > 1 else 2
    max_row = int(argv[2]) if len(argv) > 2 else None
    page = check(found[0])
    print(f"🎭 {page.title} · {describe_time(page.starts_at)} · 판매 {'중' if page.on_sale else '안 함'}")
    print(f"   예매 마감: {describe_time(page.sale_end) or '(모름)'}")
    print(f"   좌석 {len(page.seats)}석 · 빈자리 {page.free_count()}석")
    if max_row:
        print(f"   {max_row}열 이내 빈자리 {page.free_count(max_row)}석")
    runs = find_runs(page.seats, count, max_row)
    print(f"   {count}석 이상 붙은 자리: {len(runs)}곳")
    for run in runs:
        print(f"   • {describe_run(run)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
