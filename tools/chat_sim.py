#!/usr/bin/env python3
"""텔레그램 없이 봇 대화를 직접 해보는 시뮬레이터.

    python tools/chat_sim.py           # 네이버 검색은 가짜 후보로 대체 (크롬·인터넷 불필요)
    python tools/chat_sim.py --live    # 실제 크롬으로 네이버 주소 검색까지 수행

명령
    아무 글자     봇에게 메시지 보내기 (예: 비토애 산청)
    b1, b2 ...    화면에 보이는 버튼 누르기
    !search       지금 등록된 항목 검색 실행 (--live 면 실제 사이트, 아니면 가짜 결과)
    !db           현재 저장 상태 보기
    !quit         종료
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot  # noqa: E402
import search  # noqa: E402
import storage  # noqa: E402

CHAT = "sim-chat"

FAKE_CANDIDATES = [
    {"name": "{q}", "address": "경남 산청군 시천면 지리산대로 123",
     "url": "https://m.place.naver.com/accommodation/1259756405/room"},
    {"name": "{q} 별관", "address": "경남 산청군 단성면 2-3", "url": ""},
]

FAKE_CARDS = [
    {"text": "{q}\n경남 산청군 시천면\n디럭스 더블 120,000원", "url": "https://example.com/1"},
    {"text": "{q}\n제주시 애월읍\n99,000원", "url": "https://example.com/2"},
    {"text": "{q} 스위트\n산청군 시천면\n예약마감", "url": "https://example.com/3"},
]


class FakeBrowser:
    """크롬 없이 검색 결과를 흉내 내는 브라우저."""

    def __init__(self, query="숙소"):
        self.query = query

    def collect_cards(self, url, selectors, wait=6, scrolls=2):
        return [{"text": card["text"].format(q=self.query), "url": card["url"]}
                for card in FAKE_CARDS]

    def page_text(self, url, wait=7, scrolls=2):
        return ("네이버 예약 " + "객실 안내 " * 12 + "경남 산청군 시천면 "
                + "기준 최대 최소 예약마감 " * 2 + "기준 최대 최소 130,000원")

    def quit(self):
        pass


def show(replies, buttons):
    """봇 응답과 버튼을 출력하고 버튼 목록을 갱신한다."""
    buttons.clear()
    for item in replies:
        print("\n🤖 " + item["text"].replace("\n", "\n   "))
        for row in item.get("keyboard") or []:
            labels = []
            for button in row:
                if button["callback_data"] == "cal:x":
                    labels.append(f"  {button['text']}  ")
                    continue
                buttons.append(button["callback_data"])
                labels.append(f"[b{len(buttons)}] {button['text']}")
            print("   " + " ".join(labels))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                        help="실제 크롬으로 네이버 주소 검색 / 사이트 검색 수행")
    args = parser.parse_args()

    db = storage.default_db()
    buttons = []
    browser = search.Browser() if args.live else None

    def lookup(query):
        if args.live:
            return search.lookup_places(browser, query)
        return [{**c, "name": c["name"].format(q=query)} for c in FAKE_CANDIDATES]

    print(__doc__)
    while True:
        try:
            text = input("\n👤 ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text or text in ("!quit", "!q"):
            break

        if text == "!db":
            import json
            print(json.dumps(db["chats"].get(CHAT, {}), ensure_ascii=False, indent=2))
            continue

        if text == "!search":
            sent = []
            original = bot.telegram_api.send_message
            bot.telegram_api.send_message = lambda cid, msg, preview=False, keyboard=None: (
                sent.append(msg) or True)
            try:
                query = (storage.get_chat(db, CHAT)["watches"] or [{}])[0].get("query", "숙소")
                for watch in storage.get_chat(db, CHAT)["watches"]:
                    watch["force"] = True
                bot.run_due_searches(db, now=time.time(),
                                     browser=browser or FakeBrowser(query))
            finally:
                bot.telegram_api.send_message = original
            for message in sent:
                print("\n🤖 " + message.replace("\n", "\n   "))
            continue

        if text.startswith("b") and text[1:].isdigit():
            index = int(text[1:]) - 1
            if not 0 <= index < len(buttons):
                print("⚠️ 그런 번호의 버튼이 없어요.")
                continue
            show(bot.handle_callback(db, CHAT, buttons[index]), buttons)
            continue

        show(bot.handle_text(db, CHAT, text, lookup=lookup), buttons)

    if browser:
        browser.quit()
    print("\n👋 종료합니다.")


if __name__ == "__main__":
    main()
