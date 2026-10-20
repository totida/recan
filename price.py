"""가격대(1박 기준) 입력 해석과 표시.

지원 예시
    10~15만, 10만~15만원, 100,000~150,000원
    15만 이하, ~15만, 최대 15만
    10만 이상, 10만~, 최소 10만
    28만, 28 (가격을 묻는 자리에서만 — '최대 얼마까지'에 대한 답이라 그 값 이하)
"""

import re

MANWON = 10000
# 1박에 이보다 비싼 값은 금액이 아니라 날짜(20260502) 같은 숫자로 본다.
MAX_WON = 1000 * MANWON

_NUM = r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?"
_UNIT = r"만\s*원?|원"
_DASH = r"[~～∼\-–—]"
# 날짜(5/2~5/3, 2026.5.2) 안의 숫자를 금액으로 읽지 않도록 앞뒤를 막는다.
_BEFORE = r"(?<![\d./,])"
_AFTER = r"(?![\d./])"

_RANGE_RE = re.compile(
    rf"{_BEFORE}(?P<a>{_NUM})\s*(?P<au>{_UNIT})?\s*{_DASH}\s*"
    rf"(?P<b>{_NUM})\s*(?P<bu>{_UNIT})?{_AFTER}")
_UPPER_RES = (
    re.compile(rf"{_BEFORE}(?P<n>{_NUM})\s*(?P<u>{_UNIT})?\s*(?:이하|미만|까지|아래)"),
    re.compile(rf"(?:{_DASH}|최대|최고)\s*(?P<n>{_NUM})\s*(?P<u>{_UNIT})?{_AFTER}"),
)
# 가격을 묻는 자리에 금액 하나만 보낸 경우
_SINGLE_RE = re.compile(rf"(?P<n>{_NUM})\s*(?P<u>{_UNIT})?")
_LOWER_RES = (
    re.compile(rf"{_BEFORE}(?P<n>{_NUM})\s*(?P<u>{_UNIT})?\s*"
               rf"(?:이상|넘는|초과|부터|{_DASH}(?!\s*\d))"),
    re.compile(rf"최소\s*(?P<n>{_NUM})\s*(?P<u>{_UNIT})?{_AFTER}"),
)


def _won(number, unit, bare):
    """금액 하나를 원 단위로. 단위가 없으면 bare 일 때만 읽는다.

    가격대를 묻는 자리에서는 '10~15' 처럼 단위를 빼고 적어도 만 원으로 본다.
    숙소 이름과 함께 적은 한 줄 입력에서는 단위가 있어야 금액으로 친다.
    """
    value = float(number.replace(",", ""))
    unit = re.sub(r"\s", "", unit or "")
    if unit.startswith("만"):
        won = value * MANWON
    elif unit == "원" or (bare and value >= 1000):
        won = value
    elif bare:
        won = value * MANWON
    else:
        return None
    return round(won) if won <= MAX_WON else None


def parse_range(text, bare=False):
    """가격대를 (최저, 최고, 위치) 로. 한쪽이 열려 있으면 None. 못 읽으면 None."""
    text = text or ""
    for match in _RANGE_RE.finditer(text):
        au, bu = match.group("au") or match.group("bu"), match.group("bu") or match.group("au")
        low = _won(match.group("a"), au, bare)
        high = _won(match.group("b"), bu, bare)
        if low is None or high is None:
            continue
        low, high = sorted((low, high))
        if high > 0:
            return low or None, high, match.span()
    for patterns, upper in ((_UPPER_RES, True), (_LOWER_RES, False)):
        for pattern in patterns:
            for match in pattern.finditer(text):
                value = _won(match.group("n"), match.group("u"), bare)
                if value:
                    span = match.span()
                    return (None, value, span) if upper else (value, None, span)
    # '최대 얼마까지 괜찮으세요?' 에 '28만' 이라고만 답하면 28만 이하다.
    # 숙소 이름과 함께 적은 줄에서는 다른 숫자와 헷갈리므로 받지 않는다.
    single = _SINGLE_RE.fullmatch(text.strip()) if bare else None
    if single:
        value = _won(single.group("n"), single.group("u"), bare)
        if value:
            return None, value, (0, len(text))
    return None


def _man(won):
    return f"{won / MANWON:g}"


def describe(low, high):
    """'10~15만원', '15만원 이하', '10만원 이상', 정하지 않았으면 '상관없음'."""
    if low and high:
        return f"{_man(low)}~{_man(high)}만원"
    if high:
        return f"{_man(high)}만원 이하"
    if low:
        return f"{_man(low)}만원 이상"
    return "상관없음"


def short_label(low, high):
    """버튼에 쓸 짧은 표기: '15만 이하', '10~15만', '50만 이상'."""
    if low and high:
        return f"{_man(low)}~{_man(high)}만"
    if high:
        return f"{_man(high)}만 이하"
    return f"{_man(low)}만 이상"
