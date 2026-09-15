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

        # 3) 링크가 없으면 하나씩 눌러 보고 주소가 바뀌는지 확인한다
        names = []
        for element in driver.find_elements(By.CSS_SELECTOR, "li, button, div[role='button']"):
            text = (element.text or "").strip()
            if 1 < len(text) <= 20 and "\n" not in text and text != DOMESTIC_TAB:
                names.append(text)
        names = list(dict.fromkeys(names))[:limit]
        log(f"눌러볼 후보 {len(names)}곳: {', '.join(names[:10])} …")

        for name in names:
            try:
                targets = driver.find_elements(By.XPATH, f"//*[text()='{name}']")
                if not targets or not _click(driver, targets[0]):
                    continue
                time.sleep(2.5)
                match = REGION_RE.search(driver.current_url)
                if match:
                    regions[name] = match.group(1)
                    log(f"  {name} → {match.group(1)}")
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
