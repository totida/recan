#!/usr/bin/env python3
"""트리플의 국내 지역 주소록을 한 번만 수집한다.

트리플은 지역마다 고유 번호(UUID)를 쓰는데, 그 목록을 공개하는 페이지가 없다.
검색 화면의 '국내도시' 탭을 눌러 도시를 하나씩 열어 보며 주소를 받아 적는다.
결과를 triple_regions.json 으로 저장해 두면 봇은 숙소 주소만 보고
그 지역의 숙소 목록을 바로 열 수 있다.

    python tools/harvest_triple_regions.py > triple_regions.json
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import search  # noqa: E402

SEARCH_URL = "https://triple.guide/search"
REGION_RE = re.compile(r"/regions/([0-9a-f-]{20,})", re.IGNORECASE)
DOMESTIC_TAB = "국내도시"


def log(message):
    print(message, file=sys.stderr, flush=True)


def _click(driver, element):
    try:
        driver.execute_script("arguments[0].click();", element)
        return True
    except Exception:  # noqa: BLE001
        return False


def harvest(limit=80):
    from selenium.webdriver.common.by import By

    browser = search.Browser()
    regions = {}
    try:
        driver = browser.driver
        driver.get(SEARCH_URL)
        time.sleep(8)

        # 1) '국내도시' 탭 누르기
        for element in driver.find_elements(By.XPATH, f"//*[text()='{DOMESTIC_TAB}']"):
            if _click(driver, element):
                log(f"'{DOMESTIC_TAB}' 탭을 눌렀습니다.")
                time.sleep(4)
                break
        else:
            log(f"'{DOMESTIC_TAB}' 탭을 찾지 못했습니다.")

        # 2) 링크로 이미 나와 있으면 그대로 받아 적는다
        for anchor in driver.find_elements(By.CSS_SELECTOR, "a[href*='/regions/']"):
            name = (anchor.text or "").strip().splitlines()[0:1]
            href = anchor.get_attribute("href") or ""
            match = REGION_RE.search(href)
            if name and match:
                regions.setdefault(name[0], match.group(1))
        if regions:
            log(f"링크에서 {len(regions)}곳을 찾았습니다.")
            return regions

        # 3) 링크가 없으면 화면에 보이는 도시 이름을 하나씩 눌러 본다.
        #    도시 항목이 어떤 태그인지 사이트마다 달라서, 글자를 기준으로 잡는다.
        body = driver.find_element(By.TAG_NAME, "body").text
        log(f"국내도시 화면 글자 {len(body)}자: {body[:300]!r}")

        skip = {"인기도시", "해외도시", "국내도시", "닫기", "검색", "취소"}
        names = [line.strip() for line in body.splitlines()
                 if 1 < len(line.strip()) <= 20 and line.strip() not in skip
                 and "," not in line]
        names = list(dict.fromkeys(names))[:limit]
        log(f"눌러볼 후보 {len(names)}곳: {', '.join(names[:15])} …")

        for name in names:
            try:
                targets = driver.find_elements(By.XPATH, f"//*[text()='{name}']")
                if not targets or not _click(driver, targets[-1]):
                    continue
                time.sleep(2.5)
                match = REGION_RE.search(driver.current_url)
                if match:
                    regions[name] = match.group(1)
                    log(f"  {name} → {match.group(1)}")
                elif driver.current_url != SEARCH_URL:
                    log(f"  {name}: {driver.current_url[:90]}")
                driver.get(SEARCH_URL)
                time.sleep(4)
                for element in driver.find_elements(By.XPATH, f"//*[text()='{DOMESTIC_TAB}']"):
                    if _click(driver, element):
                        time.sleep(3)
                        break
            except Exception as exc:  # noqa: BLE001
                log(f"  {name}: {str(exc).splitlines()[0][:80]}")
        return regions
    finally:
        browser.quit()


def main():
    regions = harvest()
    log(f"모두 {len(regions)}곳을 받아 적었습니다.")
    json.dump(regions, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()

# 수집 시각: 첫 실행
