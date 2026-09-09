"""여러 예약사이트에서 숙소 이름 + 날짜로 예약 가능 여부를 확인한다.

- providers.json 의 설정대로 각 사이트 검색 페이지를 열고
- 검색결과 카드들을 모아
- 숙소 이름이 일치하는 카드에서 가격/마감 여부를 읽어낸다.

화면 해석 로직(analyze_cards 등)은 브라우저 없이도 테스트할 수 있도록
순수 함수로 분리해 두었다.
"""

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
)

PRICE_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원")
NOISE_LINE_RE = re.compile(r"^(\d|[₩$]|리뷰|평점|후기|쿠폰|할인|무료|광고|AD|배지)")

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


def card_matches(query, text, threshold=0.6):
    """카드가 찾는 숙소인지 판단."""
    if match_score(query, text) >= threshold:
        return True
    tokens = sorted(query_tokens(query), key=len, reverse=True)
    if tokens and len(normalize(tokens[0])) >= 3:
        return normalize(tokens[0]) in normalize(text)
    return False


def is_soldout(text):
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in SOLDOUT_KEYWORDS)


def find_price(text):
    match = PRICE_RE.search(text or "")
    if not match:
        return ""
    raw = match.group(1)
    if "," not in raw:
        raw = f"{int(raw):,}"
    return f"{raw}원"


def card_title(text, fallback=""):
    """카드 텍스트의 첫 의미있는 줄을 숙소/객실 이름으로 사용."""
    for line in (text or "").splitlines():
        line = line.strip()
        if len(line) < 2 or NOISE_LINE_RE.match(line):
            continue
        return line[:45]
    return fallback[:45]


# --- 주소 검증 -------------------------------------------------------------

ADDRESS_STOPWORDS = {"대한민국", "한국", "korea", "번지", "일원", "인근", "부근"}
ADDRESS_SUFFIXES = ("특별시", "광역시", "특별자치도", "특별자치시", "도", "시", "군", "구",
                    "읍", "면", "리", "동", "로", "길", "가")
ADDRESS_THRESHOLD = 0.25
ADDRESS_LINE_RE = re.compile(r"[가-힣]{2,}\s*(?:시|군|구|읍|면|동|리)(?:\s|$|,)")


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


def address_line(text):
    """카드 텍스트에서 주소로 보이는 줄을 찾아준다."""
    for line in (text or "").splitlines():
        line = line.strip()
        if len(line) >= 4 and ADDRESS_LINE_RE.search(line) and not PRICE_RE.search(line):
            return line[:60]
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
        title = card_title(text, fallback=query)
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
        name = card_title(text, fallback=query)
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

    def collect_cards(self, url, selectors, wait=6, scrolls=2):
        """페이지를 열고 검색결과 카드 후보를 (텍스트, 링크)로 수집."""
        import time as _time

        from selenium.webdriver.common.by import By

        driver = self.driver
        driver.get(url)
        _time.sleep(wait)
        for _ in range(scrolls):
            driver.execute_script("window.scrollBy(0, document.body.scrollHeight/2);")
            _time.sleep(2)

        for selector in selectors or []:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            cards = _elements_to_cards(elements)
            if len(cards) >= 1:
                return cards

        # 설정한 선택자가 모두 빗나가면 링크 전체를 훑는다.
        return _elements_to_cards(driver.find_elements(By.CSS_SELECTOR, "a"))

    def page_text(self, url, wait=7, scrolls=2):
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

def analyze_naver_detail(page_text):
    """네이버 숙소 상세 페이지 텍스트에서 빈 객실 여부를 판단."""
    if len(page_text or "") < 100:
        return STATUS_UNKNOWN, 0, 0
    room_count = min(
        page_text.count("기준"), page_text.count("최대"), page_text.count("최소")
    )
    closed = page_text.count("예약마감")
    if room_count == 0:
        return STATUS_UNKNOWN, 0, closed
    if closed < room_count:
        return STATUS_AVAILABLE, room_count, closed
    return STATUS_SOLDOUT, room_count, closed


def _naver_detail_url(url, checkin, checkout, guests):
    base = re.sub(r"([?&])(checkin|checkout|guest)=[^&]*", r"\1", url).rstrip("?&")
    base = re.sub(r"[?&]{2,}", "&", base)
    joiner = "&" if "?" in base else "?"
    ci = checkin.replace("-", "")
    co = checkout.replace("-", "")
    return f"{base}{joiner}checkin={ci}&checkout={co}&guest={guests}"


def search_watch(browser, watch, sites=None):
    """감시 항목 하나에 대해 모든 사이트를 검색."""
    sites = sites if sites is not None else load_sites()
    results = []

    if watch.get("url") and "naver" in watch["url"]:
        url = _naver_detail_url(
            watch["url"], watch["checkin"], watch["checkout"], watch.get("guests", 2)
        )
        try:
            page = browser.page_text(url)
            status, rooms, closed = analyze_naver_detail(page)
            note = f"객실 {rooms}개 중 {closed}개 마감" if rooms else "객실 정보를 읽지 못했어요"
            score = address_match_score(watch.get("address"), page,
                                        ignore=watch.get("query", ""))
            verified = verification_flag(score)
            if verified is False:
                note += " · 주소 미확인"
            offers = ([Offer(title="빈 객실 있음", url=url,
                             address=address_line(page), verified=verified)]
                      if status == STATUS_AVAILABLE else [])
            results.append(
                SiteResult("naver_detail", "네이버 예약(등록 링크)", status, url, offers, note)
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                SiteResult("naver_detail", "네이버 예약(등록 링크)", STATUS_ERROR, url,
                           note=str(exc)[:120])
            )

    for site in sites:
        if watch.get("url") and site["key"] == "naver" and "naver" in watch["url"]:
            continue  # 상세 링크로 이미 확인함
        try:
            url = build_url(
                site["url"], watch["query"], watch["checkin"], watch["checkout"],
                watch.get("guests", 2),
            )
        except (KeyError, ValueError) as exc:
            results.append(SiteResult(site["key"], site["name"], STATUS_ERROR,
                                      note=f"URL 설정 오류: {exc}"))
            continue
        try:
            cards = browser.collect_cards(
                url, site.get("card_selectors"), site.get("wait", 6), site.get("scrolls", 2)
            )
            status, offers = analyze_cards(
                watch["query"], cards, url, address=watch.get("address")
            )
            results.append(SiteResult(site["key"], site["name"], status, url, offers))
        except Exception as exc:  # noqa: BLE001
            results.append(SiteResult(site["key"], site["name"], STATUS_ERROR, url,
                                      note=str(exc).splitlines()[0][:120]))
    return results
