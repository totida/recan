#!/usr/bin/env python3
"""주소 하나를 열어 무엇이 읽히는지 그대로 보여준다.

검색 페이지가 아니라 숙소 상세 페이지를 감시할 수 있는지 판단하기 위한 도구.

    python tools/check_url.py --url "https://..." [--address "경남 …"]
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import search  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--address", default="", help="주소 대조까지 볼 때")
    parser.add_argument("--name", default="", help="이 이름이 페이지에 있는지 확인")
    parser.add_argument("--wait", type=int, default=12)
    parser.add_argument("--chars", type=int, default=1200, help="본문을 몇 글자까지 볼지")
    parser.add_argument("--links", default="",
                        help="이 문구가 든 링크만 뽑아서 보여준다 (예: triple.guide/hotels)")
    parser.add_argument("--grep", default="",
                        help="페이지 소스에서 이 정규식과 맞는 부분을 뽑아본다")
    args = parser.parse_args()

    browser = search.Browser()
    try:
        print("=" * 70)
        print(f"🔗 {args.url}")
        try:
            text = browser.page_text(args.url, wait=args.wait, scrolls=3)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ 열지 못했습니다: {str(exc).splitlines()[0][:200]}")
            return

        info = browser.info()
        print(f"\n⛳ 실제 주소: {info['url'][:200]}")
        print(f"⛳ 제목: {info['title'][:120]}")
        print(f"⛳ 본문 {len(text)}자")

        print("\n--- 판정에 쓰이는 값 ---")
        price = search.find_price(text)
        print(f"가격: {price or '(못 찾음)'}")
        found = [word for word in search.SOLDOUT_KEYWORDS if word in text.lower()]
        print(f"마감 표시: {', '.join(found) if found else '(없음)'}")
        empty = [p for p in search.EMPTY_RESULT_PHRASES if p in text]
        print(f"결과 없음 문구: {', '.join(empty) if empty else '(없음)'}")
        if args.name:
            print(f"이름 '{args.name}' 포함: {search.card_matches(args.name, text)}")
        if args.address:
            score = search.address_match_score(args.address, text, ignore=args.name)
            print(f"주소 일치도: {score:.2f} → {search.verification_flag(score)}")
        print(f"주소로 보이는 줄: {search.address_line(text) or '(없음)'}")

        if args.links:
            print(f"\n--- '{args.links}' 가 든 링크 ---")
            cards = browser._pick_cards(["a"])
            hits, seen = 0, set()
            for card in cards:
                url = card.get("url", "")
                if args.links in url and url not in seen:
                    seen.add(url)
                    hits += 1
                    print(f"  {hits}. {card['text'].splitlines()[0][:60]}")
                    print(f"     {url[:160]}")
                    if hits >= 8:
                        break
            if not hits:
                print("  (없음)")

        if args.grep:
            print(f"\n--- 소스에서 '{args.grep}' 찾기 ---")
            try:
                source = browser.driver.page_source
            except Exception as exc:  # noqa: BLE001
                source = ""
                print(f"  (소스를 읽지 못했습니다: {str(exc).splitlines()[0][:80]})")
            found = []
            for match in re.finditer(args.grep, source):
                text = match.group(0)
                if text not in found:
                    found.append(text)
                if len(found) >= 40:
                    break
            print(f"  {len(found)}개")
            for index, text in enumerate(found, start=1):
                print(f"  {index}. {text[:160]}")

        print(f"\n--- 본문 앞 {args.chars}자 ---")
        print(text[:args.chars].replace("\n", " / "))
    finally:
        browser.quit()


if __name__ == "__main__":
    main()
