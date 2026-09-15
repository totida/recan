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

        # 3) 도시 항목이 실제로 어떤 요소인지 들여다본다.
        #    누르면 앱 설치 안내창이 떠서 이동이 막히므로, 창을 닫고 다시 눌러 본다.
        body = driver.find_element(By.TAG_NAME, "body").text
        log(f"국내도시 화면 글자 {len(body)}자")

        skip = {"인기도시", "해외도시", "국내도시", "국내", "어디론가 떠나고 싶을 때"}
        names = [line.strip() for line in body.splitlines()
                 if 1 < len(line.strip()) <= 20 and line.strip() not in skip
                 and "," not in line]
        names = list(dict.fromkeys(names))[:limit]
        log(f"도시 {len(names)}곳: {', '.join(names)}")

        # 3-1) 첫 도시의 생김새를 위로 세 겹까지 찍어 본다.
        if names:
            for element in driver.find_elements(By.XPATH, f"//*[text()='{names[0]}']")[:2]:
                node = element
                for depth in range(4):
                    try:
                        html = (node.get_attribute("outerHTML") or "")[:220]
                        log(f"  [{names[0]} 위로 {depth}겹] {node.tag_name} "
                            f"href={node.get_attribute('href')} :: {html}")
                        node = node.find_element(By.XPATH, "..")
                    except Exception:  # noqa: BLE001
                        break

        # 3-2) 안내창을 닫고 다시 눌러 본다.
        closers = ("닫기", "괜찮아요", "웹으로 볼게요", "다음에", "취소", "✕", "×")
        for name in names:
            try:
                targets = driver.find_elements(By.XPATH, f"//*[text()='{name}']")
                if not targets or not _click(driver, targets[-1]):
                    continue
                time.sleep(2)
                if "modal" in driver.current_url or "app-install" in driver.current_url:
                    for word in closers:
                        buttons = driver.find_elements(By.XPATH, f"//*[text()='{word}']")
                        if buttons and _click(driver, buttons[-1]):
                            log(f"  안내창을 '{word}' 로 닫았습니다.")
                            time.sleep(1.5)
                            break
                    else:
                        from selenium.webdriver.common.keys import Keys
                        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                        time.sleep(1.5)
                    targets = driver.find_elements(By.XPATH, f"//*[text()='{name}']")
                    if targets:
                        _click(driver, targets[-1])
                        time.sleep(2.5)
                match = REGION_RE.search(driver.current_url)
                if match:
                    regions[name] = match.group(1)
                    log(f"  {name} → {match.group(1)}")
                else:
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
