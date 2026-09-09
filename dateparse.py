"""숙박 날짜 파싱 (한국어 자연어 입력 지원).

지원 예시
    2026-05-02 ~ 2026-05-03
    2026.5.2~2026.5.3
    20260502-20260503
    5/2~5/3
    5월 2일부터 5월 3일까지
    5/2 2박
    내일 1박
    이번주말 / 다음주말
"""

import re
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

MAX_NIGHTS = 30

RELATIVE_DAYS = {
    "오늘": 0,
    "낼": 1,
    "내일": 1,
    "모레": 2,
    "내일모레": 2,
    "글피": 3,
}

# 전체 날짜 → 8자리 숫자 → 월/일 순서로 우선 매칭한다.
_DATE_RE = re.compile(
    r"(?P<y1>\d{4})\s*[.\-/년]\s*(?P<m1>\d{1,2})\s*[.\-/월]\s*(?P<d1>\d{1,2})\s*일?"
    r"|(?<!\d)(?P<ymd>\d{8})(?!\d)"
    r"|(?<!\d)(?P<m2>\d{1,2})\s*[./월]\s*(?P<d2>\d{1,2})\s*일?"
)
_NIGHTS_RE = re.compile(r"(\d{1,2})\s*박")
_GUESTS_RE = re.compile(r"(?:성인\s*)?(\d{1,2})\s*(?:명|인)(?!\s*분의)")


class DateParseError(ValueError):
    """날짜를 이해하지 못했을 때."""


def today_kst():
    return datetime.now(KST).date()


def _weekend_range(base, offset_weeks=0):
    """이번/다음 주말(토~일) 범위."""
    # 월=0 ... 토=5, 일=6
    days_ahead = (5 - base.weekday()) % 7
    saturday = base + timedelta(days=days_ahead + 7 * offset_weeks)
    return saturday, saturday + timedelta(days=1)


def _expand_keywords(text, today):
    """'오늘/내일/이번주말' 같은 표현을 ISO 날짜 문자열로 치환."""
    out = text

    for key, weeks in (("다음주말", 1), ("담주말", 1), ("이번주말", 0), ("주말", 0)):
        pattern = re.compile(key.replace("주말", r"\s*주\s*말"))
        if pattern.search(out):
            sat, sun = _weekend_range(today, weeks)
            out = pattern.sub(f"{sat.isoformat()}~{sun.isoformat()}", out, count=1)
            break

    for word, delta in sorted(RELATIVE_DAYS.items(), key=lambda kv: -len(kv[0])):
        if word in out:
            out = out.replace(word, (today + timedelta(days=delta)).isoformat())
    return out


def _resolve_year(month, day, today):
    """연도가 없는 날짜는 '오늘 이후 가장 가까운 연도'로 해석."""
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    raise DateParseError(f"{month}월 {day}일은 올바른 날짜가 아니에요.")


def _find_dates(text, today):
    """문자열에서 날짜와 그 위치(span)를 순서대로 추출."""
    found = []
    for m in _DATE_RE.finditer(text):
        try:
            if m.group("y1"):
                value = date(int(m.group("y1")), int(m.group("m1")), int(m.group("d1")))
            elif m.group("ymd"):
                raw = m.group("ymd")
                value = date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
            else:
                value = _resolve_year(int(m.group("m2")), int(m.group("d2")), today)
        except (ValueError, DateParseError):
            continue
        found.append((value, m.span()))
    return found


def parse_stay(text, today=None):
    """숙박 기간을 파싱해 (checkin, checkout, spans)을 반환. 실패하면 None."""
    today = today or today_kst()
    expanded = _expand_keywords(text, today)
    found = _find_dates(expanded, today)
    if not found:
        return None

    spans = [span for _, span in found]
    nights_match = _NIGHTS_RE.search(expanded)
    nights = int(nights_match.group(1)) if nights_match else None
    if nights_match:
        spans.append(nights_match.span())

    checkin = found[0][0]
    if len(found) >= 2:
        checkout = found[1][0]
        # 12/30~1/2 처럼 해를 넘기는 입력
        if checkout <= checkin:
            try:
                checkout = checkout.replace(year=checkout.year + 1)
            except ValueError:
                checkout = checkout + timedelta(days=365)
    else:
        checkout = checkin + timedelta(days=nights or 1)

    stay_nights = (checkout - checkin).days
    if stay_nights <= 0:
        raise DateParseError("체크아웃 날짜가 체크인보다 빨라요.")
    if stay_nights > MAX_NIGHTS:
        raise DateParseError(f"최대 {MAX_NIGHTS}박까지만 등록할 수 있어요.")
    if checkout < today:
        raise DateParseError("이미 지난 날짜예요.")

    return checkin, checkout, spans


def parse_guests(text):
    """'4명' 같은 인원 표현을 추출. 없으면 None."""
    m = _GUESTS_RE.search(text)
    if not m:
        return None
    guests = int(m.group(1))
    if 1 <= guests <= 20:
        return guests
    return None


def strip_spans(text, spans):
    """날짜/인원 표현을 제거한 나머지 문자열(=숙소 이름)."""
    out = list(text)
    for start, end in spans:
        for i in range(start, min(end, len(out))):
            out[i] = " "
    cleaned = "".join(out)
    cleaned = re.sub(r"[~～∼\-–—]+", " ", cleaned)
    for word in ("부터", "까지", "체크인", "체크아웃", "숙박", "예약"):
        cleaned = cleaned.replace(word, " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_request(text, today=None):
    """한 줄 입력('비토애 산청 5/2~5/3 4명')을 통째로 해석."""
    today = today or today_kst()
    guests = parse_guests(text)
    guest_span = _GUESTS_RE.search(text).span() if guests else None

    stay = parse_stay(text, today=today)
    if stay is None:
        return {"name": text.strip(), "checkin": None, "checkout": None, "guests": guests}

    checkin, checkout, spans = stay
    if guest_span:
        spans = list(spans) + [guest_span]
    return {
        "name": strip_spans(text, spans),
        "checkin": checkin,
        "checkout": checkout,
        "guests": guests,
    }


def nights_between(checkin, checkout):
    return (date.fromisoformat(checkout) - date.fromisoformat(checkin)).days
