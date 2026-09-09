"""숙소 예약 알림 텔레그램 봇.

사용 흐름
    1) 사용자가 숙소 이름을 보낸다.            예) 비토애 산청
    2) 봇이 숙박 날짜를 되묻는다.               예) 5/2~5/3
    3) 등록 후 1시간마다 여기어때·야놀자·네이버 예약·하나투어를 검색해
       예약 가능한 방이 보이면 알려준다.
"""

import os
import time
from datetime import date

import dateparse
import search
import storage
import telegram_api

SEARCH_INTERVAL = int(os.environ.get("SEARCH_INTERVAL_MIN", "60")) * 60
NOTIFY_INTERVAL = int(os.environ.get("NOTIFY_INTERVAL_MIN", "60")) * 60
MAX_WATCHES = int(os.environ.get("MAX_WATCHES", "10"))
DEFAULT_GUESTS = 2

STATUS_ICON = {
    search.STATUS_AVAILABLE: "✅",
    search.STATUS_SOLDOUT: "⛔",
    search.STATUS_NONE: "🔍",
    search.STATUS_UNKNOWN: "❔",
    search.STATUS_ERROR: "⚠️",
}
STATUS_LABEL = {
    search.STATUS_AVAILABLE: "예약 가능",
    search.STATUS_SOLDOUT: "마감",
    search.STATUS_NONE: "검색 결과 없음",
    search.STATUS_UNKNOWN: "확인 불가",
    search.STATUS_ERROR: "검색 실패",
}

HELP_TEXT = (
    "🏨 숙소 빈방 알림봇\n\n"
    "1️⃣ 원하는 숙소 이름을 보내주세요. (예: 비토애 산청)\n"
    "2️⃣ 제가 숙박 날짜를 여쭤볼게요. (예: 5/2~5/3, 2026-05-02~2026-05-03, 내일 2박)\n"
    "3️⃣ 숙소 주소를 여쭤보고, 최종 확인을 받은 뒤에 등록해요.\n"
    "    (주소는 예약사이트 결과가 같은 숙소가 맞는지 다시 대조하는 데 씁니다)\n"
    "4️⃣ 여기어때 · 야놀자 · 네이버 예약 · 하나투어를 1시간마다 검색해서\n"
    "    예약 가능한 방이 보이면 바로 알려드려요.\n\n"
    "한 줄로 보내도 됩니다: 비토애 산청 5/2~5/3 4명\n"
    "네이버 숙소 링크를 붙여넣어도 등록돼요.\n\n"
    "📌 명령어\n"
    "  목록 — 등록된 알림 보기\n"
    "  삭제 2 — 2번 알림 삭제 (삭제 전체 = 모두 삭제)\n"
    "  지금 — 기다리지 않고 바로 검색\n"
    "  취소 — 입력 중이던 등록 취소\n"
    "  도움말 — 이 안내 다시 보기"
)


# --------------------------------------------------------------------------
# 메시지 만들기
# --------------------------------------------------------------------------

def stay_line(watch):
    nights = dateparse.nights_between(watch["checkin"], watch["checkout"])
    return (
        f"📅 {watch['checkin']} → {watch['checkout']} "
        f"({nights}박 · {watch.get('guests', DEFAULT_GUESTS)}명)"
    )


def format_report(watch, results, header=""):
    lines = []
    if header:
        lines.append(header)
    lines.append(f"🏨 {watch['query']}")
    if watch.get("address"):
        lines.append(f"📍 {watch['address']}")
    lines.append(stay_line(watch))
    lines.append("")
    for result in results:
        icon = STATUS_ICON.get(result.status, "❔")
        label = STATUS_LABEL.get(result.status, result.status)
        suffix = f" — {result.note}" if result.note else ""
        lines.append(f"{icon} {result.name} · {label}{suffix}")
        for offer in result.offers:
            price = f" {offer.price}" if offer.price else ""
            lines.append(f"    • {offer.title}{price}")
            if offer.address:
                mark = "주소 일치" if offer.verified is not False else "주소 불일치 가능"
                lines.append(f"      📍 {offer.address} ({mark})")
            elif watch.get("address") and offer.verified is False:
                lines.append("      ⚠️ 주소 미확인 — 같은 이름의 다른 숙소일 수 있어요")
            if offer.url:
                lines.append(f"      {offer.url}")
        if not result.offers and result.url:
            lines.append(f"    {result.url}")
    return "\n".join(lines)


def format_watch_list(watches):
    if not watches:
        return "등록된 알림이 없어요. 숙소 이름을 보내서 새로 등록해 보세요!"
    lines = ["📋 감시 중인 숙소"]
    for index, watch in enumerate(watches, start=1):
        lines.append(f"{index}. {watch['query']}")
        if watch.get("address"):
            lines.append(f"   📍 {watch['address']}")
        lines.append(f"   {stay_line(watch)}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 대화 처리
# --------------------------------------------------------------------------

def _extract_url(text):
    return next((word for word in text.split() if word.startswith("http")), None)


def register_watch(chat, query, checkin, checkout, guests, url=None, address=""):
    """감시 항목 등록. (watch, 안내문) 반환."""
    if len(chat["watches"]) >= MAX_WATCHES:
        return None, f"알림은 최대 {MAX_WATCHES}개까지 등록할 수 있어요. '목록' 후 '삭제 번호'로 정리해 주세요."

    ci, co = checkin.isoformat(), checkout.isoformat()
    for existing in chat["watches"]:
        if (
            search.normalize(existing["query"]) == search.normalize(query)
            and existing["checkin"] == ci
            and existing["checkout"] == co
        ):
            return None, f"이미 등록된 알림이에요: {query} ({ci} → {co})"

    watch = storage.new_watch(query, ci, co, guests, url, address)
    watch["force"] = True  # 등록 직후 한 번 바로 검색
    chat["watches"].append(watch)
    nights = (checkout - checkin).days
    address_line = f"📍 {address}\n" if address else ""
    verify_line = (
        "예약사이트 검색 결과도 이 주소와 대조해서 같은 숙소인지 확인할게요.\n"
        if address
        else "주소를 건너뛰어서 이름만으로 대조해요. 동명의 다른 숙소가 섞일 수 있어요.\n"
    )
    return watch, (
        f"✅ 등록 완료!\n"
        f"🏨 {query}\n"
        f"{address_line}"
        f"📅 {ci} → {co} ({nights}박 · {guests}명)\n\n"
        f"{verify_line}"
        "여기어때 · 야놀자 · 네이버 예약 · 하나투어를 1시간마다 검색할게요.\n"
        "잠시 후 첫 검색 결과를 보내드립니다."
    )


SKIP_WORDS = ("건너뛰기", "건너뜀", "스킵", "skip", "모름", "몰라", "없음", "없어", "패스", "-")
YES_WORDS = ("예", "네", "넹", "ㅇ", "ㅇㅇ", "응", "yes", "y", "ok", "확인", "맞아", "맞아요", "맞습니다", "등록")
NO_WORDS = ("아니오", "아니요", "아뇨", "아니", "ㄴ", "no", "n", "틀려", "틀렸어요", "다시")


def _ask_dates(chat, query, guests, url=None):
    chat["state"] = {"step": "await_dates", "query": query, "guests": guests, "url": url}
    return (
        f"🏨 '{query}' 맞으신가요?\n"
        "언제 묵으실 건가요? 숙박 날짜를 알려주세요.\n\n"
        "예) 5/2~5/3   ·   2026-05-02~2026-05-03   ·   5월 2일부터 3일까지\n"
        "     내일 2박   ·   이번주말"
    )


def _ask_address(chat, state):
    """숙소가 맞는지 확인하기 위해 주소를 되묻는다."""
    state["step"] = "await_address"
    chat["state"] = state
    return (
        f"📍 '{state['query']}'의 숙소 주소를 알려주세요.\n"
        "같은 이름의 다른 숙소와 헷갈리지 않도록, 예약사이트 검색 결과와 대조하는 데 씁니다.\n\n"
        "예) 경남 산청군 시천면 지리산대로 123\n"
        "지역만 아셔도 괜찮아요. (예: 산청군 시천면)\n"
        "주소를 모르시면 '건너뛰기'라고 보내주세요."
    )


def _ask_confirm(chat, state):
    """최종 승인 요청."""
    state["step"] = "await_confirm"
    chat["state"] = state
    nights = (
        date.fromisoformat(state["checkout"]) - date.fromisoformat(state["checkin"])
    ).days
    address = state.get("address") or "(입력 안 함)"
    return (
        "아래 내용이 맞는지 확인해 주세요.\n\n"
        f"🏨 숙소: {state['query']}\n"
        f"📍 주소: {address}\n"
        f"📅 일정: {state['checkin']} → {state['checkout']} ({nights}박)\n"
        f"👤 인원: {state['guests']}명\n\n"
        "맞으면 '예', 다시 입력하려면 '아니오'를 보내주세요."
    )


def _handle_delete(chat, argument):
    watches = chat["watches"]
    if not watches:
        return "삭제할 알림이 없어요."
    if argument in ("전체", "모두", "all", ""):
        chat["watches"] = []
        chat["state"] = None
        return "🗑️ 모든 알림을 삭제했어요."
    if argument.isdigit():
        index = int(argument)
        if 1 <= index <= len(watches):
            removed = watches.pop(index - 1)
            return f"🗑️ 삭제했어요: {removed['query']} ({removed['checkin']} → {removed['checkout']})"
        return f"1 ~ {len(watches)} 사이의 번호를 알려주세요."
    return "'삭제 2' 처럼 번호를 붙이거나 '삭제 전체'라고 보내주세요."


def handle_text(db, chat_id, text, today=None):
    """사용자 메시지 하나를 처리하고 보낼 답장 목록을 돌려준다."""
    today = today or dateparse.today_kst()
    chat = storage.get_chat(db, chat_id)
    text = (text or "").strip()
    if not text:
        return []

    command = text.lstrip("/").strip()
    head, _, argument = command.partition(" ")
    head_lower = head.lower()
    argument = argument.strip()

    if head_lower in ("start", "help", "시작", "도움말", "사용법"):
        chat["state"] = None
        return [HELP_TEXT]

    if head_lower in ("목록", "list", "리스트"):
        return [format_watch_list(chat["watches"])]

    if head_lower in ("삭제", "delete", "제거", "초기화"):
        return [_handle_delete(chat, argument)]

    if head_lower in ("취소", "cancel"):
        if chat.get("state"):
            chat["state"] = None
            return ["입력을 취소했어요. 다른 숙소 이름을 보내주세요."]
        return ["진행 중인 등록이 없어요."]

    if head_lower in ("지금", "지금검색", "새로고침", "now", "refresh"):
        if not chat["watches"]:
            return ["등록된 알림이 없어요. 숙소 이름부터 보내주세요."]
        for watch in chat["watches"]:
            watch["force"] = True
        return ["🔄 지금 바로 검색할게요. 잠시만 기다려 주세요!"]

    state = chat.get("state") or {}

    # 날짜를 기다리는 중
    if state.get("step") == "await_dates":
        try:
            stay = dateparse.parse_stay(text, today=today)
        except dateparse.DateParseError as exc:
            return [f"⚠️ {exc}\n다시 알려주세요. (예: 5/2~5/3)"]
        if stay is None:
            return [
                "날짜를 이해하지 못했어요 😅\n"
                "예) 5/2~5/3, 2026-05-02~2026-05-03, 내일 2박, 이번주말\n"
                "다른 숙소를 등록하려면 '취소'를 보내주세요."
            ]
        checkin, checkout, _ = stay
        state["guests"] = dateparse.parse_guests(text) or state.get("guests") or DEFAULT_GUESTS
        state["checkin"] = checkin.isoformat()
        state["checkout"] = checkout.isoformat()
        return [_ask_address(chat, state)]

    # 주소를 기다리는 중
    if state.get("step") == "await_address":
        if command.lower() in SKIP_WORDS:
            state["address"] = ""
        elif len(text) < 2:
            return ["주소를 조금 더 자세히 알려주세요. (모르시면 '건너뛰기')"]
        else:
            state["address"] = text[:100]
        return [_ask_confirm(chat, state)]

    # 최종 승인을 기다리는 중
    if state.get("step") == "await_confirm":
        answer = command.lower().rstrip("!.~ ")
        if answer in YES_WORDS:
            chat["state"] = None
            _, message = register_watch(
                chat,
                state["query"],
                date.fromisoformat(state["checkin"]),
                date.fromisoformat(state["checkout"]),
                state.get("guests", DEFAULT_GUESTS),
                state.get("url"),
                state.get("address", ""),
            )
            return [message]
        if answer in NO_WORDS:
            chat["state"] = None
            return ["알겠습니다. 숙소 이름부터 다시 알려주세요. (예: 비토애 산청)"]
        return ["'예' 또는 '아니오'로 답해주세요. 처음부터 다시 하려면 '취소'."]

    # 새 요청 (숙소 이름 또는 링크)
    url = _extract_url(text)
    if url:
        legacy = storage._watch_from_legacy_url(url)
        name = legacy["query"]
        guests = legacy["guests"]
        if legacy["checkin"] and legacy["checkout"]:
            checkin = date.fromisoformat(legacy["checkin"])
            checkout = date.fromisoformat(legacy["checkout"])
            if checkout > checkin:
                return [_ask_address(chat, {
                    "query": name, "guests": guests, "url": url,
                    "checkin": legacy["checkin"], "checkout": legacy["checkout"],
                })]
        return [_ask_dates(chat, name, guests, url)]

    try:
        parsed = dateparse.parse_request(text, today=today)
    except dateparse.DateParseError as exc:
        return [f"⚠️ {exc}\n다시 알려주세요. (예: 비토애 산청 5/2~5/3)"]

    name = parsed["name"].strip()
    guests = parsed["guests"] or DEFAULT_GUESTS
    if not name:
        return ["숙소 이름을 함께 알려주세요. (예: 비토애 산청 5/2~5/3)"]
    if len(name) > 60:
        return ["숙소 이름이 너무 길어요. 짧게 다시 보내주세요."]

    if parsed["checkin"] and parsed["checkout"]:
        return [_ask_address(chat, {
            "query": name, "guests": guests, "url": None,
            "checkin": parsed["checkin"].isoformat(),
            "checkout": parsed["checkout"].isoformat(),
        })]

    return [_ask_dates(chat, name, guests)]


# --------------------------------------------------------------------------
# 텔레그램 폴링
# --------------------------------------------------------------------------

def process_updates(db):
    offset = db.get("last_update_id", 0) + 1
    try:
        updates = telegram_api.get_updates(offset) or []
    except telegram_api.TelegramError as exc:
        print(f"🚨 업데이트 수신 실패: {exc}")
        return

    print(f"📨 새 메시지 {len(updates)}건")
    for update in updates:
        db["last_update_id"] = max(db.get("last_update_id", 0), update["update_id"])
        message = update.get("message") or update.get("edited_message") or {}
        text = (message.get("text") or "").strip()
        chat_id = str((message.get("chat") or {}).get("id", ""))
        if not chat_id or not text:
            continue
        try:
            replies = handle_text(db, chat_id, text)
        except Exception as exc:  # noqa: BLE001 - 한 명의 오류가 전체를 멈추지 않도록
            print(f"⚠️ 메시지 처리 오류(chat {chat_id}): {exc}")
            replies = ["처리 중 문제가 생겼어요 😢 다시 한 번 보내주시겠어요?"]
        for reply in replies:
            telegram_api.send_message(chat_id, reply)


# --------------------------------------------------------------------------
# 주기 검색
# --------------------------------------------------------------------------

def signature_of(results):
    return "||".join(
        sorted(offer.signature() for r in results if r.available for offer in r.offers)
    )


def decide_notification(watch, results, now, forced):
    """보낼 알림 종류를 정한다: 'report' | 'closed' | None."""
    available = any(r.available for r in results)
    signature = signature_of(results)
    if forced:
        return "report", signature, available
    if available:
        changed = signature != watch.get("last_signature", "")
        overdue = now - watch.get("last_notified", 0) >= NOTIFY_INTERVAL
        if changed or overdue:
            return "report", signature, available
        return None, signature, available
    if watch.get("was_available"):
        return "closed", signature, available
    return None, signature, available


def _collect_due(db, now, today):
    """검색할 항목을 고르고, 지난 날짜/정보 부족 항목은 정리한다."""
    due, notices = [], []
    for chat_id, chat in db["chats"].items():
        remaining = []
        for watch in chat.get("watches", []):
            if not watch.get("checkin") or not watch.get("checkout"):
                notices.append((chat_id, (
                    f"⚠️ '{watch.get('query', '알 수 없음')}' 알림에 날짜 정보가 없어 삭제했어요.\n"
                    "'숙소이름 5/2~5/3' 형식으로 다시 등록해 주세요.")))
                continue
            if date.fromisoformat(watch["checkout"]) < today:
                notices.append((chat_id, (
                    f"🗓️ '{watch['query']}' ({watch['checkin']} → {watch['checkout']}) "
                    "숙박일이 지나 알림을 종료했어요.")))
                continue
            remaining.append(watch)
            if watch.get("force") or now - watch.get("last_searched", 0) >= SEARCH_INTERVAL:
                due.append((chat_id, watch))
        chat["watches"] = remaining
    return due, notices


def run_due_searches(db, now=None, today=None):
    now = now or time.time()
    today = today or dateparse.today_kst()
    due, notices = _collect_due(db, now, today)

    for chat_id, message in notices:
        telegram_api.send_message(chat_id, message)

    if not due:
        print("⏳ 이번 실행에서 검색할 항목이 없습니다.")
        return

    sites = search.load_sites()
    browser = search.Browser()
    try:
        for chat_id, watch in due:
            forced = bool(watch.get("force"))
            print(f"🔎 검색: {watch['query']} {watch['checkin']}~{watch['checkout']} (chat {chat_id})")
            results = search.search_watch(browser, watch, sites)
            for result in results:
                print(f"   - {result.name}: {result.status} ({len(result.offers)}건) {result.note}")

            watch["last_searched"] = int(now)
            watch["force"] = False
            kind, signature, available = decide_notification(watch, results, now, forced)

            if kind == "report":
                header = "🔄 요청하신 검색 결과예요." if forced and not available else "🚨 예약 가능한 방을 찾았어요!"
                if telegram_api.send_message(chat_id, format_report(watch, results, header)):
                    watch["last_notified"] = int(now)
            elif kind == "closed":
                telegram_api.send_message(
                    chat_id,
                    f"🔕 '{watch['query']}' ({watch['checkin']} → {watch['checkout']}) "
                    "방금 전까지 보이던 빈방이 모두 마감됐어요. 계속 지켜볼게요.",
                )
            watch["last_signature"] = signature
            watch["was_available"] = available
    finally:
        browser.quit()


def main():
    db = storage.load_db()
    try:
        process_updates(db)
        run_due_searches(db)
    finally:
        storage.save_db(db)


if __name__ == "__main__":
    main()
