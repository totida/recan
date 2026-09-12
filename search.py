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

# 해외 사이트는 숙소를 영문으로 적는다(부킹닷컴: '라한셀렉트 경주' → 'Lahan Select
# Gyeongju'). 한글을 로마자로 바꿔 대조하되, 같은 도시의 다른 호텔
# ('Hanwha Resort Gyeongju' 0.64)을 잘못 잡지 않도록 기준을 높게 둔다.
ROMAN_THRESHOLD = 0.68
ROMAN_MIN_BLOCK = 6
ROMAN_MIN_LENGTH = 8
ROMAN_TITLE_LINES = 2

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


def _card_head(text, lines=ROMAN_TITLE_LINES):
    """카드 맨 앞(숙소 이름이 있는 곳)만 잘라낸다.

    부킹닷컴은 다른 숙소 카드에도 '13.1 miles from Lahan Select Gyeongju' 처럼
    기준 숙소 이름을 적어두기 때문에, 본문 전체로 대조하면 엉뚱한 숙소가 걸린다.
    """
    head = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return " ".join(head[:lines])[:80]


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
    blocks = [b for b in difflib.SequenceMatcher(None, nq, nt, autojunk=False)
              .get_matching_blocks() if b.size]
    if not blocks:
        return 0.0, 0
    return sum(b.size for b in blocks) / len(nq), max(b.size for b in blocks)


def card_matches(query, text, threshold=0.6):
    """카드가 찾는 숙소인지 판단."""
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


def analyze_cards(query, cards, search_url="", limit=3, address=None):
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

    offers, soldout, unknown = [], 0, 0
    seen = set()
    for card, score in scored:
        text = card.get("text", "")
        if is_soldout(text):
            soldout += 1
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
    if soldout:
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


def load_sites(path=None):
    config = _load_config(path)
    return [site for site in config.get("sites", []) if site.get("enabled", True)]


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
        name = card_title(text, fallback=query, query=query)
        if normalize(name) == normalize(address):
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


def first_place_link(query, cards):
    """검색 카드 중 이름이 맞는 네이버 장소 링크를 하나 고른다."""
    for card in cards:
        url = card.get("url", "")
        if "naver" not in url or "place" not in url:
            continue
        if card_matches(query, card.get("text", "")):
            room_url = naver_room_url(url)
            if "accommodation" in room_url:
                return room_url
    return ""


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

    def collect_cards(self, url, selectors, wait=6, scrolls=2, retry_wait=5):
        """페이지를 열고 검색결과 카드 후보를 (텍스트, 링크)로 수집."""
        import time as _time

        driver = self.driver
        driver.get(url)
        _time.sleep(wait)
        for _ in range(scrolls):
            driver.execute_script("window.scrollBy(0, document.body.scrollHeight/2);")
            _time.sleep(2)

        cards = self._pick_cards(selectors)
        if not cards and retry_wait:
            # 늦게 그려지는 화면(SPA)을 위해 한 번 더 기다렸다 본다.
            _time.sleep(retry_wait)
            driver.execute_script("window.scrollBy(0, document.body.scrollHeight/2);")
            _time.sleep(2)
            cards = self._pick_cards(selectors)
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
            cards = browser.collect_cards(url, site.get("card_selectors"),
                                          site.get("wait", 6), site.get("scrolls", 2))
        except Exception as exc:  # noqa: BLE001
            result = SiteResult(site["key"], site["name"], STATUS_ERROR, url,
                                note=str(exc).splitlines()[0][:120])
            continue

        # 네이버는 검색 결과의 장소 링크를 따라가 객실 상태까지 확인한다.
        detail = None
        if site.get("follow_place"):
            place_url = first_place_link(term, cards)
            if place_url:
                detail = naver_detail_result(browser, watch, place_url, site["name"])
                detail.key = site["key"]
                if detail.status != STATUS_UNKNOWN:
                    return detail

        status, offers = analyze_cards(term, cards, url,
                                       address=watch.get("address"))
        if detail is not None and status == STATUS_NONE:
            return detail  # 상세도 검색도 확실치 않으면 상세 쪽 안내를 쓴다
        result = SiteResult(site["key"], site["name"], status, url, offers)
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


def search_watch(browser, watch, sites=None):
    """감시 항목 하나에 대해 모든 사이트를 검색."""
    sites = sites if sites is not None else load_sites()
    results = []

    registered = watch.get("url") or ""
    if "naver" in registered:
        results.append(naver_detail_result(browser, watch, registered,
                                           "네이버 예약(등록 링크)"))

    for site in sites:
        if "naver" in registered and site["key"] == "naver":
            continue  # 상세 링크로 이미 확인함
        results.append(_search_site(browser, watch, site))
    return results
