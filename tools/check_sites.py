#!/usr/bin/env python3
"""providers.json 설정이 실제로 동작하는지 진단한다. (크롬 필요)

    python tools/check_sites.py --query "비토애 산청" --checkin 2026-10-03 --checkout 2026-10-05

각 사이트에 대해
    - 검색 주소가 열리는지
    - 결과 카드가 몇 개 잡히는지 (0이면 card_selectors 조정 필요)
    - 그중 숙소 이름이 맞는 카드가 있는지 (0이면 url 형식 확인 필요)
    - 가격/마감 판정 결과
를 출력한다. --dump 를 주면 잡힌 카드 원문을 함께 보여준다.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import search  # noqa: E402

LABEL = {
    search.STATUS_AVAILABLE: "예약 가능",
    search.STATUS_SOLDOUT: "마감",
    search.STATUS_NONE: "이름이 맞는 카드 없음",
    search.STATUS_UNKNOWN: "가격을 못 읽음",
    search.STATUS_ERROR: "오류",
}


def preview(cards, count=3):
    for card in cards[:count]:
        text = card["text"].replace("\n", " / ")[:150]
        print(f"      · {text}")
        if card.get("url"):
            print(f"        {card['url'][:110]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True, help="숙소 이름")
    parser.add_argument("--checkin", required=True, help="YYYY-MM-DD")
    parser.add_argument("--checkout", required=True, help="YYYY-MM-DD")
    parser.add_argument("--guests", type=int, default=2)
    parser.add_argument("--address", default="", help="주소 대조까지 확인하려면 입력")
    parser.add_argument("--dump", action="store_true", help="잡힌 카드 원문 보기")
    args = parser.parse_args()

    browser = search.Browser()
    problems = []
    try:
        # 1) 네이버 주소 후보 검색
        print("=" * 70)
        print(f"📍 네이버 주소 후보 검색: {args.query}")
        lookup = search.load_place_lookup()
        found = []
        for template in lookup.get("urls", []):
            url = template.format(query=search.quote(args.query))
            print(f"\n  → {url}")
            try:
                cards = browser.collect_cards(url, lookup.get("card_selectors"),
                                              lookup.get("wait", 5),
                                              lookup.get("scrolls", 1))
            except Exception as exc:  # noqa: BLE001
                print(f"    ⚠️ 열지 못했습니다: {str(exc).splitlines()[0][:120]}")
                continue
            found = search.parse_place_cards(args.query, cards,
                                             lookup.get("max_candidates", 5))
            print(f"    카드 {len(cards)}개 · 주소 후보 {len(found)}개")
            if args.dump:
                preview(cards)
            for candidate in found:
                print(f"      ✅ {candidate['name']} — {candidate['address']}")
                if candidate.get("url"):
                    print(f"         {candidate['url']}")
            if found:
                break
        if not found:
            problems.append("네이버 주소 후보를 찾지 못했습니다 "
                            "→ providers.json 의 place_lookup.urls / card_selectors 확인")

        address = args.address or (found[0]["address"] if found else "")

        # 2) 예약사이트별 검색
        watch = {"query": args.query, "checkin": args.checkin, "checkout": args.checkout,
                 "guests": args.guests, "address": address}
        for site in search.load_sites():
            print("\n" + "=" * 70)
            print(f"🏨 {site['name']}")
            best = None
            for index, template in enumerate(search.site_urls(site), start=1):
                url = search.build_url(template, args.query, args.checkin,
                                       args.checkout, args.guests)
                print(f"\n  [{index}] {url}")
                try:
                    cards = browser.collect_cards(url, site.get("card_selectors"),
                                                  site.get("wait", 6), site.get("scrolls", 2))
                except Exception as exc:  # noqa: BLE001
                    print(f"      ⚠️ 열지 못했습니다: {str(exc).splitlines()[0][:120]}")
                    continue

                if not cards:  # 왜 못 읽었는지(404·차단·지연) 알 수 있게
                    state = browser.info()
                    print(f"      ⛳ 실제 주소: {state['url'][:120]}")
                    print(f"      ⛳ 제목: {state['title'][:80]} · 본문 {state['text_length']}자")
                    print(f"      ⛳ 본문 앞부분: {state['text_head'][:160]}")

                matched = [c for c in cards if search.card_matches(args.query, c["text"])]
                status, offers = search.analyze_cards(args.query, cards, url, address=address)
                print(f"      카드 {len(cards)}개 · 이름 일치 {len(matched)}개 "
                      f"→ {LABEL.get(status, status)}")
                if args.dump or matched:
                    preview(matched or cards)
                for offer in offers:
                    mark = {True: "주소 일치", False: "주소 미확인",
                            None: "주소 미등록"}[offer.verified]
                    print(f"      ✅ {offer.title} {offer.price} ({mark})")

                if site.get("follow_place"):
                    place_url = search.first_place_link(args.query, cards)
                    if place_url:
                        print(f"      ↪ 장소 페이지 확인: {place_url}")
                        detail = search.naver_detail_result(browser, watch, place_url,
                                                            site["name"])
                        print(f"        → {LABEL.get(detail.status, detail.status)}"
                              f" ({detail.note})")
                        best = ("ok", url)
                        break

                if matched:
                    best = ("ok", url)
                    break
                best = best or ("none" if cards else "empty", url)

            if best is None:
                problems.append(f"{site['name']}: 모든 주소에서 페이지를 열지 못함")
            elif best[0] == "empty":
                problems.append(f"{site['name']}: 카드를 하나도 못 읽음 → card_selectors 확인")
            elif best[0] == "none":
                problems.append(f"{site['name']}: 검색 결과에 숙소가 없음 → urls 형식 확인")
            else:
                print(f"\n  ✅ 사용 가능한 주소: {best[1]}")
    finally:
        browser.quit()

    print("\n" + "=" * 70)
    if problems:
        print("⚠️ 확인이 필요한 항목")
        for item in problems:
            print(f"  - {item}")
    else:
        print("✅ 모든 사이트에서 숙소를 찾았습니다.")
    print(f"(설정 파일: {search.PROVIDER_FILE})")


if __name__ == "__main__":
    main()
