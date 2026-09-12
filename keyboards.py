"""텔레그램 인라인 키보드 (달력 · 숙소 후보 선택)."""

import calendar as _calendar
from datetime import date, timedelta

WEEK_HEADERS = ("월", "화", "수", "목", "금", "토", "일")
MAX_MONTHS_AHEAD = 12
NOOP = "cal:x"


def _button(text, data):
    return {"text": text, "callback_data": data}


def _shift_month(year, month, delta):
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


def month_calendar(year, month, today, min_date=None, mode="in"):
    """달력 키보드를 만든다.

    mode: "in"=체크인 선택, "out"=체크아웃 선택
    min_date 이전 날짜는 누를 수 없다.
    """
    min_date = min_date or today
    rows = []

    prev_year, prev_month = _shift_month(year, month, -1)
    next_year, next_month = _shift_month(year, month, 1)
    last_allowed = _shift_month(today.year, today.month, MAX_MONTHS_AHEAD)

    can_prev = (prev_year, prev_month) >= (min_date.year, min_date.month)
    can_next = (next_year, next_month) <= last_allowed
    rows.append([
        _button("◀", f"cal:m:{prev_year}-{prev_month:02d}") if can_prev else _button(" ", NOOP),
        _button(f"{year}년 {month}월", NOOP),
        _button("▶", f"cal:m:{next_year}-{next_month:02d}") if can_next else _button(" ", NOOP),
    ])
    rows.append([_button(header, NOOP) for header in WEEK_HEADERS])

    weeks = _calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    for week in weeks:
        row = []
        for day in week:
            if day.month != month:
                row.append(_button(" ", NOOP))
            elif day < min_date:
                row.append(_button("·", NOOP))
            else:
                label = str(day.day)
                if day == today:
                    label = f"[{day.day}]"
                row.append(_button(label, f"cal:{mode}:{day.isoformat()}"))
        rows.append(row)

    rows.append([_button("✍️ 직접 입력", "cal:type"), _button("✖️ 취소", "cal:cancel")])
    return rows


def calendar_message(query, mode, checkin=None):
    if mode == "out":
        return (
            f"🏨 {query}\n"
            f"✅ 체크인: {checkin}\n\n"
            "📆 체크아웃(퇴실) 날짜를 선택해 주세요."
        )
    return f"🏨 {query}\n\n📆 체크인(입실) 날짜를 선택해 주세요."


def place_keyboard(candidates):
    """네이버에서 찾은 숙소 후보 선택 버튼."""
    rows = []
    for index, candidate in enumerate(candidates):
        label = candidate.get("name", "")
        region = candidate.get("address", "")
        if region:
            label = f"{label} · {region[:20]}"
        rows.append([_button(f"{index + 1}. {label[:55]}", f"place:pick:{index}")])
    rows.append([_button("🔎 목록에 없어요 (주소 직접 입력)", "place:none")])
    rows.append([_button("⏭️ 주소 없이 진행", "place:skip")])
    rows.append([_button("✖️ 취소", "place:cancel")])
    return rows


def place_message(query, candidates):
    lines = [f"📍 '{query}'을(를) 네이버에서 찾아봤어요. 어느 숙소인가요?", ""]
    for index, candidate in enumerate(candidates, start=1):
        lines.append(f"{index}. {candidate.get('name', '')}")
        if candidate.get("address"):
            lines.append(f"   {candidate['address']}")
    lines.append("")
    lines.append("아래 버튼을 누르거나 번호를 보내주세요.")
    return "\n".join(lines)


def confirm_keyboard():
    return [[_button("✅ 예, 등록할게요", "confirm:yes"),
             _button("↩️ 아니오", "confirm:no")]]


def default_month(today, min_date=None):
    """처음 보여줄 달(오늘 기준)."""
    base = min_date or today
    return base.year, base.month


def next_day(value):
    return date.fromisoformat(value) + timedelta(days=1)
