"""여러 예약사이트에서 숙소 이름 + 날짜로 예약 가능 여부를 확인한다.

- providers.json 의 설정대로 각 사이트 검색 페이지를 열고
- 검색결과 카드들을 모아
- 숙소 이름이 일치하는 카드에서 가격/마감 여부를 읽어낸다.

화면 해석 로직(analyze_cards 등)은 브라우저 없이도 테스트할 수 있도록
순수 함수로 분리해 두었다.
"""

import difflib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import quote

PROVIDER_FILE = os.environ.get("PROVIDER_FILE", "providers.json")

SOLDOUT_KEYWORDS = (
    "예약마감", "판매마감", "마감", "매진", "솔드아웃", "sold out", "soldout",
    "판매완료", "예약불가", "만실", "품절", "객실없음", "잔여없음", "예약종료",
    "no rooms", "not available", "unavailable", "fully booked", "매진임박아님",
    # 여기어때는 그 날짜에 안 파는 숙소에 가격 대신 '다른 날짜 확인' 을 띄운다.
    "다른 날짜 확인", "다른 날짜 보기", "예약 가능한 날짜 확인", "판매중인 상품이 없",
)

PRICE_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원")
# 아고다·부킹닷컴 등은 ₩ 또는 KRW 로 적는다.
PRICE_SYMBOL_RE = re.compile(r"[₩]\s*(\d{1,3}(?:,\d{3})+|\d{4,8})")
PRICE_KRW_RE = re.compile(r"(?:KRW|krw)\s*(\d{1,3}(?:,\d{3})+|\d{4,8})")
NOISE_LINE_RE = re.compile(r"^(\d|[₩$(]|리뷰|평점|후기|쿠폰|할인|무료|광고|AD|배지)")
# 사이트마다 카드 맨 위에 붙는 분류/버튼 문구 — 숙소 이름이 아니다.
NOISE_WORDS = {
    "예약", "예약하기", "주소보기", "지도", "지도보기", "길찾기", "내비게이션", "전화", "공유",
    "사이트", "네이버페이", "톡톡", "숙박", "대실", "국내숙소", "해외숙소", "메뉴닫기",
    "펜션", "호텔", "모텔", "리조트", "게스트하우스", "글램핑", "캠핑", "풀빌라", "한옥",
    "해외여행", "국내여행", "항공", "패키지", "더보기", "광고", "특가", "쿠폰",
}

# 사이트가 직접 '결과 없음'이라고 알려주는 문구 — 취급하지 않는 숙소라는 뜻이다.
EMPTY_RESULT_PHRASES = (
    "검색 결과가 없", "검색결과가 없", "결과가 없어요", "일치하는 숙소가 없",
    "조건에 맞는 숙소가 없", "찾으시는 숙소가 없",
    "no properties found", "no results found",
)
# 카드가 이만큼 넘게 떠 있으면 '결과 없음' 문구가 있어도 화면 어딘가의
# 안내 문구일 뿐이므로 미취급으로 단정하지 않는다.
EMPTY_RESULT_MAX_CARDS = 3
NOT_LISTED_NOTE = "이 사이트에는 없는 숙소예요"

STATUS_AVAILABLE = "available"
STATUS_SOLDOUT = "soldout"
STATUS_NONE = "none"
STATUS_UNKNOWN = "unknown"
STATUS_ERROR = "error"


@dataclass
class Offer:
    title: str
    price: str = ""
    url: str = ""
    address: str = ""
    verified: bool = None  # True=주소 일치, False=주소 미확인, None=등록된 주소 없음

    def signature(self):
        return f"{self.title}|{self.price}"


@dataclass
class SiteResult:
    key: str
    name: str
    status: str
    url: str = ""
    offers: list = field(default_factory=list)
    note: str = ""

    @property
    def available(self):
        return self.status == STATUS_AVAILABLE


# --------------------------------------------------------------------------
# 순수 해석 로직
# --------------------------------------------------------------------------

def normalize(text):
    """비교용 정규화: 공백/기호 제거 + 소문자."""
    return re.sub(r"[\s\-_·,./()\[\]&'\"]+", "", text or "").lower()


def query_tokens(query):
    return [t for t in re.split(r"\s+", (query or "").strip()) if t]


def match_score(query, text):
    """숙소 이름 토큰이 카드 텍스트에 얼마나 들어있는지(0~1)."""
    tokens = query_tokens(query)
    if not tokens:
        return 0.0
    target = normalize(text)
    if not target:
        return 0.0
    hits = sum(1 for t in tokens if normalize(t) and normalize(t) in target)
    return hits / len(tokens)


SIMILARITY_THRESHOLD = 0.7
SIMILARITY_MIN_BLOCK = 3
# 이어진 조각이 이만큼은 돼야 근거로 친다 (한 글자 우연 방지)
SIMILARITY_MIN_PIECE = 2

# 해외 사이트는 숙소를 영문으로 적는다(부킹닷컴: '라한셀렉트 경주' → 'Lahan Select
# Gyeongju'). 한글을 로마자로 바꿔 대조하되, 같은 도시의 다른 호텔
# ('Hanwha Resort Gyeongju' 0.64)을 잘못 잡지 않도록 기준을 높게 둔다.
ROMAN_THRESHOLD = 0.68
ROMAN_MIN_BLOCK = 6
ROMAN_MIN_LENGTH = 8
ROMAN_TITLE_LINES = 1

_CHO = ("g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj",
        "ch", "k", "t", "p", "h")
_JUNG = ("a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe",
         "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i")
_JONG = ("", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p",
         "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t")


def romanize(text):
    """한글을 로마자로 옮긴다 (국어의 로마자 표기법 기준)."""
    out = []
    for char in text or "":
        code = ord(char)
        if 0xAC00 <= code <= 0xD7A3:
            index = code - 0xAC00
            out.append(_CHO[index // 588] + _JUNG[(index % 588) // 28]
                       + _JONG[index % 28])
        elif char.isalnum():
            out.append(char.lower())
    return "".join(out)


def _latin_only(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


# '15.4 miles from Lahan Select Gyeongju' 처럼 다른 숙소 카드에 적히는 거리 안내.
DISTANCE_RE = re.compile(
    r"[\d.]+\s*(?:miles?|km|m|킬로|미터)\s*(?:from|away from)?\s*[^\n]*", re.I)


def _card_head(text, lines=ROMAN_TITLE_LINES):
    """카드 맨 앞(숙소 이름이 있는 곳)만 잘라낸다.

    부킹닷컴은 다른 숙소 카드에도 '15.4 miles from Lahan Select Gyeongju' 처럼
    기준 숙소 이름을 적어둔다. 그 줄까지 보면 엉뚱한 숙소를 그 숙소로 착각한다.
    """
    head = [line.strip() for line in (text or "").splitlines() if line.strip()]
    joined = " ".join(head[:lines])
    return DISTANCE_RE.sub(" ", joined)[:80]


def roman_matches(query, text):
    """영문으로 적힌 카드를 한글 이름과 대조 (카드 맨 앞 줄 기준)."""
    roman_query = romanize(query)
    latin_text = _latin_only(_card_head(text))
    if len(roman_query) < ROMAN_MIN_LENGTH or len(latin_text) < ROMAN_MIN_LENGTH:
        return False
    blocks = [b for b in difflib.SequenceMatcher(None, roman_query, latin_text,
                                                 autojunk=False)
              .get_matching_blocks() if b.size]
    if not blocks:
        return False
    ratio = sum(b.size for b in blocks) / len(roman_query)
    return ratio >= ROMAN_THRESHOLD and max(b.size for b in blocks) >= ROMAN_MIN_BLOCK


def similarity(query, text):
    """글자 단위 유사도 (일치 비율, 가장 긴 연속 일치 길이).

    예약사이트마다 이름 표기가 조금씩 다르다.
    '사천 비토애풀빌라&글램핑' vs '사천 비토애풀빌라펜션&글램핑' 처럼
    중간에 단어가 끼어들어도 같은 숙소로 보기 위한 장치.
    """
    nq, nt = normalize(query), normalize(text)
    if len(nq) < 2 or not nt:
        return 0.0, 0
    # 한 글자가 우연히 겹치는 것은 근거로 치지 않는다.
    # '스테이루나' 를 찾는데 카드에 '사우나' 가 있다고 해서 같은 숙소일 리 없다.
    blocks = [b for b in difflib.SequenceMatcher(None, nq, nt, autojunk=False)
              .get_matching_blocks() if b.size >= SIMILARITY_MIN_PIECE]
    if not blocks:
        return 0.0, 0
    return sum(b.size for b in blocks) / len(nq), max(b.size for b in blocks)


def card_matches(query, text, threshold=0.6):
    """카드가 찾는 숙소인지 판단."""
    # 부킹닷컴은 모든 카드에 '15.3 miles from 스테이루헤' 처럼 기준 숙소
    # 이름을 적어둔다. 그 문구까지 보면 엉뚱한 카드가 전부 걸린다.
    text = DISTANCE_RE.sub(" ", text or "")
    if match_score(query, text) >= threshold:
        return True
    ratio, longest = similarity(query, text)
    if ratio >= SIMILARITY_THRESHOLD and longest >= SIMILARITY_MIN_BLOCK:
        return True
    tokens = sorted(query_tokens(query), key=len, reverse=True)
    if tokens and len(normalize(tokens[0])) >= 3:
        if normalize(tokens[0]) in normalize(text):
            return True
    return roman_matches(query, text)


def is_soldout(text):
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in SOLDOUT_KEYWORDS)


def find_price(text):
    """카드에서 가격을 읽는다. 원 / ₩ / KRW 표기를 모두 지원."""
    for pattern in (PRICE_RE, PRICE_SYMBOL_RE, PRICE_KRW_RE):
        match = pattern.search(text or "")
        if match:
            raw = match.group(1)
            if "," not in raw:
                raw = f"{int(raw):,}"
            return f"{raw}원"
    return ""


def _title_candidates(text):
    for line in (text or "").splitlines():
        line = line.strip()
        if len(line) < 2 or NOISE_LINE_RE.match(line):
            continue
        if line in NOISE_WORDS or looks_like_address(line):
            continue
        yield line


def card_title(text, fallback="", query=""):
    """카드에서 숙소/객실 이름으로 보이는 줄을 고른다.

    분류·버튼 문구와 주소 줄은 건너뛰고, 찾는 이름이 들어간 줄을 우선한다.
    """
    lines = list(_title_candidates(text))
    if query:
        for line in lines:
            if match_score(query, line) >= 0.5:
                return line[:45]
    if lines:
        return lines[0][:45]
    return fallback[:45]


# --- 주소 검증 -------------------------------------------------------------

ADDRESS_STOPWORDS = {"대한민국", "한국", "korea", "번지", "일원", "인근", "부근"}
ADDRESS_SUFFIXES = ("특별시", "광역시", "특별자치도", "특별자치시", "도", "시", "군", "구",
                    "읍", "면", "리", "동", "로", "길", "가")
ADDRESS_THRESHOLD = 0.25

# '럭셔리'의 '리' 처럼 우연히 걸리는 것을 막기 위해, 행정구역 표기를 제대로 확인한다.
PROVINCE_RE = re.compile(
    r"^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주"
    r"|서울특별시|경기도|강원특별자치도|충청북도|충청남도|전라북도|전북특별자치도|전라남도"
    r"|경상북도|경상남도|제주특별자치도)(\s|특별시|광역시|도\s)"
)
ADMIN_CITY_RE = re.compile(r"[가-힣]{1,6}(?:시|군|구)(?:\s|$|,)")
ADMIN_TOWN_RE = re.compile(r"[가-힣]{1,8}(?:읍|면|동|리|로|길|가)(?:\s|\d|$|,)")


def address_tokens(address):
    """주소를 비교용 토큰 묶음으로. 각 묶음은 (원형, 접미사 제거형) 변형 집합."""
    groups = []
    for raw in re.split(r"[\s,]+", address or ""):
        token = re.sub(r"[0-9\-~()]+", "", raw).strip()
        if len(token) < 2 or token.lower() in ADDRESS_STOPWORDS:
            continue
        variants = {normalize(token)}
        for suffix in ADDRESS_SUFFIXES:
            if token.endswith(suffix) and len(token) - len(suffix) >= 2:
                variants.add(normalize(token[: -len(suffix)]))
        groups.append({v for v in variants if v})
    return groups


def address_match_score(address, text, ignore=""):
    """카드 텍스트가 등록된 주소와 얼마나 겹치는지(0~1). 주소가 없으면 None.

    숙소 이름에 지역명이 들어있는 경우(예: '비토애 산청')가 많아,
    이름 토큰은 한 번씩 지운 뒤에 주소를 대조한다.
    """
    groups = address_tokens(address)
    if not groups:
        return None
    target = normalize(text)
    for token in query_tokens(ignore):
        normalized = normalize(token)
        if normalized:
            target = target.replace(normalized, " ", 1)
    hits = sum(1 for variants in groups if any(v in target for v in variants))
    return hits / len(groups)


def city_tokens(text, ignore=""):
    """글에서 '경주시', '화성시', '산청군' 같은 시·군·구 이름만 뽑는다."""
    cleaned = text or ""
    for token in query_tokens(ignore):
        if token:
            cleaned = cleaned.replace(token, " ")
    return {match.group(0).strip(" ,") for match in ADMIN_CITY_RE.finditer(cleaned + " ")}


def address_conflicts(address, text, ignore=""):
    """카드에 적힌 시·군·구가 등록된 주소와 아예 다른가.

    이름이 비슷한 다른 지역 숙소를 거르는 마지막 안전망이다.
    카드에 지역이 안 적혀 있으면(빈 집합) 판단하지 않는다 — 모르는 것과
    다른 것은 다르다.
    """
    if not address:
        return False
    ours = city_tokens(address)
    theirs = city_tokens(text, ignore=ignore)
    if not ours or not theirs:
        return False
    return not (ours & theirs)


def address_verified(score):
    """주소 검증을 통과했는가. 등록된 주소가 없으면(None) 통과로 본다."""
    return score is None or score >= ADDRESS_THRESHOLD


def verification_flag(score):
    """True=주소 일치, False=주소 미확인/불일치, None=등록된 주소 없음."""
    return None if score is None else score >= ADDRESS_THRESHOLD


def looks_like_address(line):
    """'경상남도 …', '산청군 신안면' 같은 줄만 주소로 인정한다."""
    line = (line or "").strip()
    if len(line) < 4 or find_price(line):
        return False
    if PROVINCE_RE.match(line):
        return True
    return bool(ADMIN_CITY_RE.search(line) and ADMIN_TOWN_RE.search(line))


def address_line(text):
    """카드 텍스트에서 주소로 보이는 줄을 찾아준다."""
    for line in (text or "").splitlines():
        if looks_like_address(line):
            return line.strip()[:60]
    return ""


# 객실 카드에 적힌 '최대 5인' 같은 인원. 숫자만 있는 '최대 12' 는 할인율 등일
# 수 있으므로 단위가 붙은 것만 인정한다.
CAPACITY_RE = re.compile(r"최대\s*(\d{1,2})\s*(?:인|명)")


def room_capacity(text):
    """카드에 적힌 최대 투숙 인원. 안 적혀 있으면 None."""
    found = [int(m.group(1)) for m in CAPACITY_RE.finditer(text or "")]
    return max(found) if found else None


def fits_guests(text, guests):
    """그 인원이 묵을 수 있는 객실인가.

    예약사이트는 '인원 기준에는 맞지 않지만 이런 객실도 있어요' 하면서
    작은 방까지 함께 보여준다. 7명을 찾는데 '기준 4인 / 최대 5인' 짜리가
    예약 가능으로 올라오면 안 된다.

    인원이 안 적힌 카드는 판단하지 않는다 — 모르는 것과 안 맞는 것은 다르다.
    """
    if not guests:
        return True
    capacity = room_capacity(text)
    return capacity is None or capacity >= guests


def too_small_count(query, cards, guests):
    """이름은 맞지만 인원이 모자라 걸러낸 카드 수."""
    return sum(1 for card in cards or []
               if card_matches(query, card.get("text", ""))
               and not fits_guests(card.get("text", ""), guests))


def analyze_cards(query, cards, search_url="", limit=3, address=None, guests=None):
    """검색결과 카드 목록 → 예약 가능 여부.

    cards: [{"text": ..., "url": ...}, ...]
    """
    matched = [c for c in cards if card_matches(query, c.get("text", ""))]
    if not matched:
        return STATUS_NONE, []

    # 이름이 같은 다른 숙소를 거르기 위해 등록된 주소와 한 번 더 대조한다.
    scored = [
        (c, address_match_score(address, c.get("text", ""), ignore=query))
        for c in matched
    ]
    if any(s is not None and s >= ADDRESS_THRESHOLD for _, s in scored):
        scored = [(c, s) for c, s in scored if s is None or s >= ADDRESS_THRESHOLD]

    # 주소를 통과한 카드가 하나도 없더라도, 카드에 적힌 지역이 등록 주소와
    # 아예 다르면 그건 같은 이름의 다른 숙소다.
    scored = [(c, s) for c, s in scored
              if not address_conflicts(address, c.get("text", ""), ignore=query)]
    if not scored:
        return STATUS_NONE, []

    offers, soldout, unknown, too_small = [], 0, 0, 0
    seen = set()
    for card, score in scored:
        text = card.get("text", "")
        if is_soldout(text):
            soldout += 1
            continue
        if not fits_guests(text, guests):
            too_small += 1     # 인원이 안 맞는 방은 빈방이라도 소용없다
            continue
        price = find_price(text)
        title = card_title(text, fallback=query, query=query)
        key = normalize(title) + price
        if key in seen:
            continue
        seen.add(key)
        if not price:
            unknown += 1
            continue
        offers.append(Offer(
            title=title,
            price=price,
            url=card.get("url") or search_url,
            address=address_line(text),
            verified=verification_flag(score),
        ))

    if offers:
        return STATUS_AVAILABLE, offers[:limit]
    if soldout or too_small:
        return STATUS_SOLDOUT, []
    if unknown:
        return STATUS_UNKNOWN, []
    return STATUS_NONE, []


def build_url(template, query, checkin, checkout, guests=2):
    """설정 파일의 URL 템플릿을 실제 검색 주소로."""
    ci = date.fromisoformat(checkin)
    co = date.fromisoformat(checkout)
    values = {
        "query": quote(query),
        "checkin": ci.isoformat(),
        "checkout": co.isoformat(),
        "checkin_compact": ci.strftime("%Y%m%d"),
        "checkout_compact": co.strftime("%Y%m%d"),
        "checkin_dot": ci.strftime("%Y.%m.%d"),
        "checkout_dot": co.strftime("%Y.%m.%d"),
        "guests": guests,
        "nights": (co - ci).days,
    }
    return template.format(**values)


def _load_config(path=None):
    path = path or PROVIDER_FILE
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_sites(path=None, include_disabled=False):
    """켜져 있는 사이트 목록. 점검할 때는 꺼진 것도 포함해서 본다."""
    sites = _load_config(path).get("sites", [])
    if include_disabled:
        return list(sites)
    return [site for site in sites if site.get("enabled", True)]


def site_urls(site):
    """사이트 설정에서 시도할 검색 주소 목록. urls(리스트) 또는 url(단일) 모두 지원."""
    urls = site.get("urls") or ([site["url"]] if site.get("url") else [])
    return [u for u in urls if u]


def load_place_lookup(path=None):
    return _load_config(path).get("place_lookup", {})


NAVER_ID_PATTERNS = (
    re.compile(r"/(?:place|accommodation|restaurant|hairshop)/(\d{6,})"),
    re.compile(r"(?:[?&](?:id|code|no|entry|placeId)=)(\d{6,})"),
    re.compile(r"/(\d{7,})(?:[/?#]|$)"),
)


def naver_room_url(href):
    """네이버 장소 링크를 숙소 객실 페이지 주소로 바꾼다. 못 찾으면 원래 주소."""
    if not href or "naver" not in href:
        return href or ""
    for pattern in NAVER_ID_PATTERNS:
        match = pattern.search(href)
        if match:
            return f"https://m.place.naver.com/accommodation/{match.group(1)}/room"
    return href


# 네이버는 숙소 이름 뒤에 업종을 붙여 적는다. ('한우산별천지기타숙박업')
PLACE_NAME_SUFFIXES = ("기타숙박업", "숙박업", "부속시설", "전기차충전소", "주차장",
                       "관리실", "사이트", "정보")
# 숙소가 아닌 부속 장소는 후보에서 뺀다.
NON_LODGING_WORDS = ("주차장", "충전소", "부속시설", "관리실", "마켓", "뷔페", "식당",
                     "카페", "편의점", "매점", "입구", "매표소")


def clean_place_name(name):
    """'한우산별천지기타숙박업' → '한우산별천지'"""
    name = (name or "").strip()
    changed = True
    while changed:
        changed = False
        for suffix in PLACE_NAME_SUFFIXES:
            if name.endswith(suffix) and len(name) - len(suffix) >= 2:
                name = name[: -len(suffix)].strip()
                changed = True
    return name


def parse_place_cards(query, cards, limit=5):
    """검색 카드에서 (숙소 이름, 주소, 링크) 후보를 뽑는다."""
    candidates, seen = [], set()
    for card in cards:
        text = card.get("text", "")
        if not card_matches(query, text):
            continue
        address = address_line(text)
        if not address:
            continue
        raw_name = card_title(text, fallback=query, query=query)
        if any(word in raw_name for word in NON_LODGING_WORDS):
            continue  # 주차장·부속시설 등은 숙소가 아니다 (업종 제거 전에 걸러낸다)
        name = clean_place_name(raw_name)
        if not name or normalize(name) == normalize(address):
            continue
        key = (normalize(name), normalize(address))
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "name": name,
            "address": address,
            "url": naver_room_url(card.get("url", "")),
        })
        if len(candidates) >= limit:
            break
    return candidates


def first_place_link(query, cards, prefer=""):
    """검색 카드 중 이름이 가장 잘 맞는 네이버 장소 링크를 고른다.

    '스테이루나'로 검색하면 민박·게스트하우스·펜션이 함께 나온다.
    맨 위 것을 집으면 엉뚱한 숙소의 객실을 보게 되므로,
    등록된 정식 이름('스테이루나펜션')과 가장 비슷한 것을 고른다.
    """
    best, best_score = "", -1.0
    for card in cards:
        url = card.get("url", "")
        if "naver" not in url or "place" not in url:
            continue
        text = card.get("text", "")
        if not card_matches(query, text):
            continue
        room_url = naver_room_url(url)
        if "accommodation" not in room_url:
            continue
        score = similarity(prefer or query, text)[0]
        if score > best_score:
            best, best_score = room_url, score
    return best


def lookup_places(browser, query, config=None):
    """네이버에서 숙소 이름으로 주소 후보를 찾아온다."""
    config = config if config is not None else load_place_lookup()
    limit = config.get("max_candidates", 5)
    for template in config.get("urls", []):
        url = template.format(query=quote(query))
        try:
            cards = browser.collect_cards(
                url,
                config.get("card_selectors"),
                config.get("wait", 5),
                config.get("scrolls", 1),
                ready=lambda found: bool(parse_place_cards(query, found, limit)),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ 주소 검색 실패({url}): {str(exc).splitlines()[0][:100]}")
            continue
        candidates = parse_place_cards(query, cards, limit)
        if candidates:
            return candidates
    return []


# --------------------------------------------------------------------------
# 브라우저 (필요할 때만 띄운다)
# --------------------------------------------------------------------------

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)


class Browser:
    """게으르게 생성되는 셀레니움 드라이버 래퍼."""

    def __init__(self):
        self._driver = None

    @property
    def driver(self):
        if self._driver is None:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options

            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=390,900")
            options.add_argument(f"--user-agent={MOBILE_UA}")
            self._driver = webdriver.Chrome(options=options)
            self._driver.set_page_load_timeout(60)
        return self._driver

    def _pick_cards(self, selectors):
        from selenium.webdriver.common.by import By

        for selector in selectors or []:
            cards = _elements_to_cards(
                self.driver.find_elements(By.CSS_SELECTOR, selector))
            if cards:
                return cards
        # 설정한 선택자가 모두 빗나가면 링크 전체를 훑는다.
        return _elements_to_cards(self.driver.find_elements(By.CSS_SELECTOR, "a"))

    def _watch_cards(self, selectors, done, timeout, poll=0.4):
        """찾던 것이 나오면 곧바로 돌려준다. 안 나오면 timeout 까지만 기다린다.

        예전에는 정해진 초를 무조건 다 세고 봤다. 화면이 1초 만에 다 떠도
        7초를 기다리느라 숙소 이름을 넣고 한참 멍하니 있어야 했다.
        """
        import time as _time

        deadline = _time.time() + timeout
        cards = self._pick_cards(selectors)
        while not done(cards) and _time.time() < deadline:
            _time.sleep(poll)
            cards = self._pick_cards(selectors)
        return cards

    def collect_cards(self, url, selectors, wait=6, scrolls=2, retry_wait=5,
                      ready=None):
        """페이지를 열고 검색결과 카드 후보를 (텍스트, 링크)로 수집.

        ready(cards) 가 참이 되는 순간 기다리기를 멈춘다. 넘기지 않으면
        카드가 하나라도 잡히는 것을 신호로 본다.
        """
        driver = self.driver
        driver.get(url)

        def done(cards):
            return bool(ready(cards)) if ready else bool(cards)

        cards = self._watch_cards(selectors, done, wait)
        if done(cards):
            return cards

        for _ in range(scrolls):
            driver.execute_script("window.scrollBy(0, document.body.scrollHeight/2);")
            cards = self._watch_cards(selectors, done, 2)
            if done(cards):
                return cards

        if retry_wait:
            # 늦게 그려지는 화면(SPA)을 위해 한 번 더 기다려 본다.
            cards = self._watch_cards(selectors, done, retry_wait)
        return cards

    def body_text(self, limit=2000):
        from selenium.webdriver.common.by import By

        try:
            return self.driver.find_element(By.TAG_NAME, "body").text[:limit]
        except Exception:  # noqa: BLE001
            return ""

    def info(self):
        """진단용: 실제로 열린 주소와 화면 제목, 본문 길이."""
        from selenium.webdriver.common.by import By

        try:
            body = self.driver.find_element(By.TAG_NAME, "body").text
        except Exception:  # noqa: BLE001
            body = ""
        return {"url": self.driver.current_url, "title": self.driver.title,
                "text_length": len(body), "text_head": body[:200].replace("\n", " / ")}

    def page_text(self, url, wait=10, scrolls=3):
        import time as _time

        from selenium.webdriver.common.by import By

        driver = self.driver
        driver.get(url)
        _time.sleep(wait)
        for _ in range(scrolls):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            _time.sleep(2)
        return driver.find_element(By.TAG_NAME, "body").text

    def quit(self):
        if self._driver is not None:
            try:
                self._driver.quit()
            finally:
                self._driver = None


def _elements_to_cards(elements, limit=120):
    cards = []
    for element in elements[:limit]:
        try:
            text = (element.text or "").strip()
            if len(text) < 4:
                continue
            href = element.get_attribute("href") or ""
            cards.append({"text": text, "url": href})
        except Exception:  # noqa: BLE001 - 스크롤 중 사라진 요소 등
            continue
    return cards


# --------------------------------------------------------------------------
# 네이버 상세 페이지(등록된 링크가 있을 때) — 객실 수 vs 예약마감 수 비교
# --------------------------------------------------------------------------

EMPTY_ROOM_PHRASES = (
    "예약 가능한 객실이 없", "판매중인 객실이 없", "판매 중인 객실이 없",
    "선택하신 날짜에 예약", "객실이 없습니다",
)


def analyze_naver_detail(page_text):
    """네이버 숙소 상세 페이지 텍스트에서 빈 객실 여부를 판단.

    객실 카드마다 '기준/최대/최소' 가 함께 나오는 점을 이용해 객실 수를 세고,
    '예약마감' 수와 비교한다. 숫자가 어긋날 수 있으므로 가격 표시와
    '예약 가능한 객실이 없습니다' 문구로 한 번 더 확인한다.
    """
    page_text = page_text or ""
    if len(page_text) < 100:
        return STATUS_UNKNOWN, 0, 0

    room_count = min(
        page_text.count("기준"), page_text.count("최대"), page_text.count("최소")
    )
    closed = page_text.count("예약마감")

    if any(phrase in page_text for phrase in EMPTY_ROOM_PHRASES):
        return STATUS_SOLDOUT, room_count, closed
    if room_count == 0:
        return STATUS_UNKNOWN, 0, closed
    if closed < room_count and find_price(page_text):
        return STATUS_AVAILABLE, room_count, closed
    return STATUS_SOLDOUT, room_count, closed


def _naver_detail_url(url, checkin, checkout, guests):
    base = re.sub(r"([?&])(checkin|checkout|guest)=[^&]*", r"\1", url).rstrip("?&")
    base = re.sub(r"[?&]{2,}", "&", base)
    joiner = "&" if "?" in base else "?"
    ci = checkin.replace("-", "")
    co = checkout.replace("-", "")
    return f"{base}{joiner}checkin={ci}&checkout={co}&guest={guests}"


def naver_detail_result(browser, watch, place_url, name="네이버 예약"):
    """네이버 숙소 상세 페이지에서 객실 수와 예약마감 수를 비교한다."""
    url = _naver_detail_url(place_url, watch["checkin"], watch["checkout"],
                            watch.get("guests", 2))
    try:
        page = browser.page_text(url)
    except Exception as exc:  # noqa: BLE001
        return SiteResult("naver_detail", name, STATUS_ERROR, url,
                          note=str(exc).splitlines()[0][:120])

    status, rooms, closed = analyze_naver_detail(page)
    if rooms and closed <= rooms:
        note = f"객실 {rooms}개 중 {closed}개 마감"
    elif closed:
        note = f"예약마감 {closed}건"
    elif len(page) > 300 and not find_price(page):
        note = "네이버 예약을 쓰지 않는 숙소 같아요"
    else:
        note = "객실 정보를 읽지 못했어요"
    verified = verification_flag(
        address_match_score(watch.get("address"), page, ignore=watch.get("query", ""))
    )
    if verified is False:
        note += " · 주소 미확인"
    offers = ([Offer(title="빈 객실 있음", url=url, address=address_line(page),
                     verified=verified)]
              if status == STATUS_AVAILABLE else [])
    return SiteResult("naver_detail", name, status, url, offers, note)


# --------------------------------------------------------------------------
# 인터파크 트리플(등록된 링크가 있을 때)
#
# 트리플은 검색 화면이 자바스크립트로만 그려져서 숙소 이름으로는 찾아갈 수 없다.
# (덕덕고·빙·구글·네이버·인터파크 검색에서도 트리플 숙소 주소가 나오지 않는다.)
# 대신 숙소 상세 페이지는 그대로 읽히므로, 링크를 한 번 등록해 두면
# 날짜·인원을 우리가 바꿔 끼워 계속 감시할 수 있다.
# --------------------------------------------------------------------------

TRIPLE_HOTEL_RE = re.compile(
    r"https?://(?:www\.)?triple\.guide/hotels/[0-9a-fA-F]{8}-[0-9a-fA-F-]{4,}\S*",
    re.IGNORECASE,
)
# 이 값들은 우리가 새로 채워 넣으므로 원래 링크에서 떼어낸다.
TRIPLE_OWN_PARAMS = ("checkIn", "checkOut", "numberOfAdults", "skipInitialCache")
# 트리플은 객실마다 '선택' 버튼을 붙인다. 이 말이 하나도 없으면 살 수 있는 방이 없다.
TRIPLE_ROOM_WORD = "선택"
TRIPLE_ROOM_LIST_WORDS = ("객실 목록", "객실목록")
TRIPLE_SOLDOUT_PHRASES = ("판매 완료", "판매완료", "예약 가능한 객실이 없",
                          "판매중인 객실이 없", "객실이 없습니다")


def triple_link(text):
    """글 안에서 트리플 숙소 링크를 찾아준다. 없으면 빈 문자열."""
    match = TRIPLE_HOTEL_RE.search(text or "")
    return match.group(0) if match else ""


def triple_detail_url(url, checkin, checkout, guests=2):
    """등록된 트리플 링크에 감시 중인 날짜·인원을 끼워 넣는다.

    skipInitialCache 를 붙이지 않으면 트리플이 캐시해 둔 기본 날짜 화면을
    돌려주기 때문에, 우리가 물어본 날짜가 반영되지 않는다.
    """
    base, _, query = (url or "").partition("?")
    kept = [part for part in query.split("&")
            if part and part.split("=")[0] not in TRIPLE_OWN_PARAMS]
    kept += [f"checkIn={checkin}", f"checkOut={checkout}",
             f"numberOfAdults={max(1, int(guests or 1))}", "skipInitialCache=true"]
    return f"{base}?{'&'.join(kept)}"


def _triple_room_section(page_text):
    """'객실 목록'부터 '기본정보' 앞까지, 즉 파는 방들만 잘라낸다.

    페이지 위쪽의 '최저가 예약' 미리보기에도 값과 버튼이 있어서,
    그 부분까지 세면 마감된 날짜를 예약 가능으로 잘못 읽는다.
    """
    start = min((page_text.find(word) for word in TRIPLE_ROOM_LIST_WORDS
                 if page_text.find(word) >= 0), default=-1)
    if start < 0:
        return ""
    end = page_text.find("기본정보", start)
    return page_text[start:end] if end > start else page_text[start:]


def analyze_triple_detail(page_text):
    """트리플 숙소 상세 페이지에서 예약 가능한 객실이 있는지 판단."""
    page_text = page_text or ""
    if len(page_text) < 100:
        return STATUS_UNKNOWN, 0

    section = _triple_room_section(page_text)
    if not section:
        if any(phrase in page_text for phrase in TRIPLE_SOLDOUT_PHRASES):
            return STATUS_SOLDOUT, 0
        return STATUS_UNKNOWN, 0

    rooms = section.count(TRIPLE_ROOM_WORD)
    if rooms and find_price(section):
        return STATUS_AVAILABLE, rooms
    return STATUS_SOLDOUT, 0


def triple_detail_result(browser, watch, link, name="인터파크 트리플"):
    """등록된 트리플 링크를 열어 빈 객실을 확인한다."""
    url = triple_detail_url(link, watch["checkin"], watch["checkout"],
                            watch.get("guests", 2))
    try:
        page = browser.page_text(url)
    except Exception as exc:  # noqa: BLE001
        return SiteResult("triple", name, STATUS_ERROR, url,
                          note=str(exc).splitlines()[0][:120])

    status, rooms = analyze_triple_detail(page)
    if status == STATUS_AVAILABLE:
        note = f"예약 가능한 객실 {rooms}개"
    elif status == STATUS_SOLDOUT:
        note = "이 날짜에 파는 객실이 없어요"
    else:
        note = "객실 정보를 읽지 못했어요"

    verified = verification_flag(
        address_match_score(watch.get("address"), page, ignore=watch.get("query", ""))
    )
    if verified is False:
        note += " · 주소 미확인"
    offers = ([Offer(title="빈 객실 있음", price=find_price(page), url=url,
                     address=address_line(page), verified=verified)]
              if status == STATUS_AVAILABLE else [])
    return SiteResult("triple", name, status, url, offers, note)


def search_term(watch):
    """예약사이트 검색에 쓸 말.

    네이버 정식 명칭(예: '비토애 럭셔리 글램핑 산청점')을 그대로 넣으면
    다른 사이트에서는 오히려 결과가 안 나온다. 사용자가 처음 적은 짧은 이름
    (예: '비토애 산청')으로 찾고, 진짜 그 숙소인지는 주소로 확인한다.
    """
    return watch.get("keyword") or watch.get("query", "")


def _search_site(browser, watch, site):
    """사이트 하나를 검색. url 후보를 차례로 시도하고 마지막 결과를 돌려준다."""
    term = search_term(watch)
    result = SiteResult(site["key"], site["name"], STATUS_ERROR,
                        note="검색 주소가 설정되지 않았습니다")
    for template in site_urls(site):
        try:
            url = build_url(template, term, watch["checkin"],
                            watch["checkout"], watch.get("guests", 2))
        except (KeyError, ValueError) as exc:
            result = SiteResult(site["key"], site["name"], STATUS_ERROR,
                                note=f"URL 설정 오류: {exc}")
            continue
        try:
            cards = browser.collect_cards(
                url, site.get("card_selectors"),
                site.get("wait", 6), site.get("scrolls", 2),
                ready=lambda found: any(card_matches(term, c.get("text", ""))
                                        for c in found),
            )
        except Exception as exc:  # noqa: BLE001
            result = SiteResult(site["key"], site["name"], STATUS_ERROR, url,
                                note=str(exc).splitlines()[0][:120])
            continue

        # 네이버는 검색 결과의 장소 링크를 따라가 객실 상태까지 확인한다.
        detail = None
        if site.get("follow_place"):
            place_url = first_place_link(term, cards,
                                         prefer=watch.get("query", ""))
            if place_url:
                detail = naver_detail_result(browser, watch, place_url, site["name"])
                detail.key = site["key"]
                if detail.status != STATUS_UNKNOWN:
                    return detail

        guests = watch.get("guests")
        status, offers = analyze_cards(term, cards, url,
                                       address=watch.get("address"),
                                       guests=guests)
        note = ""
        if status == STATUS_SOLDOUT and not offers:
            dropped = too_small_count(term, cards, guests)
            if dropped:
                note = f"{guests}명이 묵을 수 있는 방이 없어요"
        if detail is not None and status == STATUS_NONE:
            return detail  # 상세도 검색도 확실치 않으면 상세 쪽 안내를 쓴다
        result = SiteResult(site["key"], site["name"], status, url, offers, note)
        if status != STATUS_NONE:
            return result  # 이름이 맞는 카드를 찾았으니 이 주소를 쓴다

        # 사이트가 '검색 결과가 없어요'라고 답했다면 설정 문제가 아니라
        # 그 숙소를 취급하지 않는 것이다. 다른 주소를 더 시도할 이유가 없다.
        reader = getattr(browser, "body_text", None)
        if (reader and len(cards) <= EMPTY_RESULT_MAX_CARDS
                and any(phrase in reader() for phrase in EMPTY_RESULT_PHRASES)):
            return SiteResult(site["key"], site["name"], STATUS_NONE, url,
                              note=NOT_LISTED_NOTE)
    return result


def search_watch(browser, watch, sites=None, after_site=None):
    """감시 항목 하나에 대해 모든 사이트를 검색.

    after_site 를 주면 사이트 하나를 끝낼 때마다 불러준다. 검색 한 바퀴가
    길어도 그 사이에 텔레그램 입력을 처리해 봇이 먹통으로 보이지 않게 한다.
    사이트 사이에서만 부르므로, 다음 사이트는 어차피 페이지를 새로 열어
    브라우저를 같이 써도 문제가 없다.
    """
    sites = sites if sites is not None else load_sites()
    results = []

    def done():
        if after_site:
            after_site()

    registered = watch.get("url") or ""
    if "naver" in registered:
        results.append(naver_detail_result(browser, watch, registered,
                                           "네이버 예약(등록 링크)"))
        done()

    if watch.get("triple"):
        results.append(triple_detail_result(browser, watch, watch["triple"]))
        done()

    for site in sites:
        if "naver" in registered and site["key"] == "naver":
            continue  # 상세 링크로 이미 확인함
        results.append(_search_site(browser, watch, site))
        done()
    return results
