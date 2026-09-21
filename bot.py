"""숙소 예약 알림 텔레그램 봇.

사용 흐름
    1) 사용자가 숙소 이름을 보낸다.              예) 비토애 산청
    2) 봇이 네이버에서 그 이름의 숙소를 찾아 주소와 함께 후보를 보여주고 고르게 한다.
    3) 오늘 날짜 기준 달력에서 체크인 · 체크아웃 날짜를 누르게 한다.
    4) 등록 후 1시간마다 여기어때·야놀자·네이버 예약·하나투어를 검색해
       예약 가능한 방이 보이면 알려준다. (승인받은 주소로 같은 숙소인지 재확인)
"""

import os
import re
import time
from datetime import date

import dateparse
import keyboards
import search
import storage
import telegram_api

SEARCH_INTERVAL = int(os.environ.get("SEARCH_INTERVAL_MIN", "60")) * 60
# 빈방이 계속 열려 있는 동안 같은 숙소를 다시 알리는 간격.
# 처음 열린 순간은 이 간격과 상관없이 바로 알린다.
NOTIFY_INTERVAL = int(os.environ.get("NOTIFY_INTERVAL_MIN", "120")) * 60
MAX_WATCHES = int(os.environ.get("MAX_WATCHES", "10"))
DEFAULT_GUESTS = 2
MAX_GUESTS = 20

# 실행 방식은 두 가지다.
#   IDLE_EXIT_SEC > 0 : 조용하면 곧바로 종료 (비공개 저장소·사용 시간 절약)
#   IDLE_EXIT_SEC = 0 : 대화가 없어도 MAX_RUN_SEC 까지 계속 켜둔다 (상시 대기)
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT_SEC", "20"))
IDLE_EXIT = int(os.environ.get("IDLE_EXIT_SEC", "60"))
MAX_RUN = int(os.environ.get("MAX_RUN_SEC", "300"))
ALWAYS_ON = IDLE_EXIT <= 0

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
# 숙소는 찾았는데 가격·마감 표시가 없을 때 왜 그런지 알려준다.
UNKNOWN_NOTE = "숙소는 찾았지만 가격 표시가 없어 판정 보류 · 링크에서 확인해 주세요"

# 대화가 끊긴 지 이만큼 지나야 크롬을 내린다. 방금 대화하던 중이면 켜둔 채로
# 두어, 숙소 이름을 넣었을 때 크롬이 새로 뜨는 시간을 기다리지 않게 한다.
BROWSER_IDLE = int(os.environ.get("BROWSER_IDLE_SEC", "300"))

# 등록을 하다 말고 이만큼 지나면, 다음 메시지는 새 요청으로 본다.
STATE_TTL = int(os.environ.get("STATE_TTL_MIN", "30")) * 60

SKIP_WORDS = ("건너뛰기", "건너뜀", "스킵", "skip", "모름", "몰라", "패스")
NONE_WORDS = ("없음", "없어요", "없어", "직접", "직접입력", "기타")
YES_WORDS = ("예", "네", "넹", "ㅇ", "ㅇㅇ", "응", "yes", "y", "ok", "확인",
             "맞아", "맞아요", "맞습니다", "등록")
NO_WORDS = ("아니오", "아니요", "아뇨", "아니", "ㄴ", "no", "n", "틀려", "틀렸어요", "다시")

HELP_TEXT = (
    "🏨 숙소 빈방 알림봇\n\n"
    "타이핑은 숙소 이름 한 번이면 됩니다. 나머지는 전부 버튼이에요.\n"
    "입력창 아래 메뉴로 추가 · 목록 · 삭제 · 지금 검색을 하실 수 있어요.\n\n"
    "1️⃣ 원하는 숙소 이름을 보내주세요. (예: 비토애 산청)\n"
    "2️⃣ 네이버에서 찾은 숙소 후보를 주소와 함께 보여드릴게요. 버튼으로 고르시면 돼요.\n"
    "3️⃣ 오늘 날짜 기준 달력에서 체크인 · 체크아웃 날짜를 눌러주세요.\n"
    "    이어서 인원을 고르면 그 인원이 묵을 수 있는 객실만 찾아드려요.\n"
    "4️⃣ 켜져 있는 예약 사이트를 주기적으로 검색해서\n"
    "    예약 가능한 방이 보이면 바로 알려드려요.\n"
    "    (고르신 주소로 같은 숙소가 맞는지 검색 결과를 다시 대조합니다)\n\n"
    "날짜는 버튼 대신 직접 입력해도 됩니다: 5/2~5/3, 내일 2박, 이번주말\n"
    "네이버 숙소 링크를 붙여넣어도 등록돼요.\n"
    "인터파크 트리플은 이름으로 검색이 안 돼요. 트리플 숙소 링크를 보내주시면\n"
    "그 숙소에 연결해 두고 날짜·인원을 바꿔가며 함께 확인해 드려요.\n\n"
    "📌 명령어\n"
    "  목록 — 등록된 알림 보기\n"
    "  삭제 2 — 2번 알림 삭제 (삭제 전체 = 모두 삭제)\n"
    "  인원 2 4 — 2번 알림을 4명으로 변경\n"
    "  지금 — 기다리지 않고 바로 검색\n"
    "  취소 — 입력 중이던 등록 취소\n"
    "  도움말 — 이 안내 다시 보기"
)


def mask(chat_id):
    """공개 저장소의 실행 로그에 채팅 ID가 그대로 남지 않도록 가린다."""
    chat_id = str(chat_id)
    return f"…{chat_id[-4:]}" if len(chat_id) > 4 else "…"


def reply(text, keyboard=None, edit=False):
    """봇이 보낼 한 건의 응답. edit=True 면 누른 메시지를 그 자리에서 고친다."""
    return {"text": text, "keyboard": keyboard, "edit": edit}


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
        if result.note == search.NOT_LISTED_NOTE:
            icon, label = "🚫", "미취급"
        note = result.note
        if result.status == search.STATUS_UNKNOWN and not note:
            note = UNKNOWN_NOTE
        suffix = f" — {note}" if note else ""
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
        if watch.get("triple"):
            lines.append("   🔗 인터파크 트리플 연결됨")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 등록
# --------------------------------------------------------------------------

def _ask_triple_target(chat, link):
    """트리플 링크를 어느 알림에 붙일지 물어본다."""
    watches = chat["watches"]
    if not watches:
        return [reply("먼저 숙소 이름을 보내서 알림을 등록해 주세요. "
                      "그 다음 트리플 링크를 보내면 함께 감시할게요.")]
    if len(watches) == 1:
        return _attach_triple(chat, link, 0)

    chat["state"] = {"step": "await_triple_target", "triple": link,
                     "touched_at": int(time.time())}
    lines = ["🔗 트리플 링크를 받았어요. 어느 숙소에 붙일까요?", ""]
    for index, watch in enumerate(watches, start=1):
        lines.append(f"{index}. {watch['query']} · {watch['checkin']} → {watch['checkout']}")
    return [reply("\n".join(lines), keyboards.watch_keyboard(watches))]


def _attach_triple(chat, link, index, edit=False):
    """고른 알림에 트리플 링크를 저장한다."""
    chat["state"] = None
    watches = chat["watches"]
    if not 0 <= index < len(watches):
        return [reply("그 번호의 알림이 없어요. '목록'으로 번호를 확인해 주세요.")]
    watch = watches[index]
    watch["triple"] = link
    watch["force"] = True
    return [reply(
        f"🔗 '{watch['query']}'에 인터파크 트리플을 연결했어요.\n"
        "이제 이 숙소는 트리플에서도 함께 확인할게요. 바로 한 번 검색해 볼게요!",
        edit=edit,
    )]


# 하단 메뉴 버튼을 누르면 그 글자가 그대로 온다. 명령으로 바꿔 읽는다.
MENU_COMMANDS = {
    "숙소 추가": "추가", "추가": "추가",
    "목록": "목록",
    "삭제": "삭제",
    "지금 검색": "지금", "지금": "지금",
    "도움말": "도움말",
}


def _menu_command(text):
    """'➕ 숙소 추가' 처럼 앞에 붙은 그림글자를 떼고 명령으로 바꾼다."""
    stripped = re.sub(r"^[^\w가-힣]+", "", text or "").strip()
    return MENU_COMMANDS.get(stripped, stripped)


def _ask_delete(chat):
    """어느 알림을 지울지 버튼으로 고르게 한다."""
    watches = chat["watches"]
    if not watches:
        return [reply("삭제할 알림이 없어요.")]
    lines = ["🗑️ 어느 알림을 지울까요?", ""]
    for index, watch in enumerate(watches, start=1):
        lines.append(f"{index}. {watch['query']} · {watch['checkin']} → {watch['checkout']}")
    return [reply("\n".join(lines), keyboards.delete_keyboard(watches))]


def _delete_one(chat, index, edit=False):
    watches = chat["watches"]
    if not 0 <= index < len(watches):
        return [reply("그 번호의 알림이 없어요.", edit=edit)]
    removed = watches.pop(index)
    return [reply(f"🗑️ 삭제했어요: {removed['query']} "
                  f"({removed['checkin']} → {removed['checkout']})", edit=edit)]


def _extract_url(text):
    return next((word for word in text.split() if word.startswith("http")), None)


def _guests_in_url(url):
    """링크에 인원이 적혀 있으면 그 값을, 없으면 None (나중에 물어본다)."""
    for key in ("guest", "personal", "adultCount", "group_adults", "adults"):
        match = re.search(rf"[?&]{key}=(\d+)", url or "")
        if match:
            return int(match.group(1))
    return None


def _looks_like_new_name(text):
    """날짜로 못 읽은 글이 새 숙소 이름처럼 보이는가.

    날짜 입력을 기다리는 중에 '소노캄 경주' 를 보내면 날짜로 읽으려다
    실패한다. 숫자가 하나도 없는 두 글자 이상의 말이면 새 숙소로 본다.
    """
    text = (text or "").strip()
    return len(text) >= 2 and len(text) <= 60 and not any(c.isdigit() for c in text)


def _object_particle(word):
    """받침에 맞는 조사(을/를)를 고른다."""
    last = (word or "").strip()[-1:] or ""
    if "가" <= last <= "힣":
        return "을" if (ord(last) - 0xAC00) % 28 else "를"
    return "을"


def site_summary():
    """지금 켜져 있는 사이트 이름과 검색 주기를 안내문에 쓰기 좋게."""
    try:
        names = " · ".join(site["name"] for site in search.load_sites())
    except (OSError, ValueError):
        names = "예약 사이트"
    return names, max(1, SEARCH_INTERVAL // 60)


def register_watch(chat, query, checkin, checkout, guests, url=None, address="",
                   keyword=""):
    """감시 항목 등록. (watch, 안내문) 반환."""
    if len(chat["watches"]) >= MAX_WATCHES:
        return None, (f"알림은 최대 {MAX_WATCHES}개까지 등록할 수 있어요. "
                      "'목록' 후 '삭제 번호'로 정리해 주세요.")

    ci = checkin if isinstance(checkin, str) else checkin.isoformat()
    co = checkout if isinstance(checkout, str) else checkout.isoformat()
    for existing in chat["watches"]:
        if (
            search.normalize(existing["query"]) == search.normalize(query)
            and existing["checkin"] == ci
            and existing["checkout"] == co
        ):
            return None, f"이미 등록된 알림이에요: {query} ({ci} → {co})"

    watch = storage.new_watch(query, ci, co, guests, url, address, keyword)
    watch["force"] = True  # 등록 직후 한 번 바로 검색
    chat["watches"].append(watch)
    nights = dateparse.nights_between(ci, co)
    sites, minutes = site_summary()
    address_line = f"📍 {address}\n" if address else ""
    keyword_line = (f"🔎 검색어: {keyword}\n"
                    if keyword and search.normalize(keyword) != search.normalize(query)
                    else "")
    verify_line = (
        "예약사이트 검색 결과도 이 주소와 대조해서 같은 숙소인지 확인할게요.\n"
        if address
        else "주소를 건너뛰어서 이름만으로 대조해요. 동명의 다른 숙소가 섞일 수 있어요.\n"
    )
    return watch, (
        f"✅ 등록 완료!\n"
        f"🏨 {query}\n"
        f"{address_line}"
        f"{keyword_line}"
        f"📅 {ci} → {co} ({nights}박 · {guests}명)\n\n"
        f"{verify_line}"
        f"{sites}{_object_particle(sites)} {minutes}분마다 검색할게요.\n"
        "잠시 후 첫 검색 결과를 보내드립니다."
    )


# --------------------------------------------------------------------------
# 등록 단계별 되묻기
# --------------------------------------------------------------------------

def _start_registration(chat, query, guests, today, url=None,
                        checkin=None, checkout=None, lookup=None):
    """숙소 이름을 받은 뒤 네이버에서 후보를 찾아 되묻는다."""
    state = {
        "query": query, "keyword": query, "guests": guests or DEFAULT_GUESTS,
        "guests_set": bool(guests), "url": url,
        "checkin": checkin, "checkout": checkout,
        "address": "", "address_source": "",
        "touched_at": int(time.time()),
    }

    if url:  # 링크를 직접 주신 경우엔 숙소가 이미 특정된다.
        state["address_source"] = "link"
        return _after_identity(chat, state, today)

    candidates = []
    if lookup:
        try:
            candidates = lookup(query) or []
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ 주소 후보 검색 실패: {exc}")

    if candidates:
        state["step"] = "await_place_choice"
        state["candidates"] = candidates
        chat["state"] = state
        return [reply(keyboards.place_message(query, candidates),
                      keyboards.place_keyboard(candidates))]
    return _ask_address(chat, state, searched=bool(lookup))


def _ask_address(chat, state, searched=False, edit=False):
    """네이버에서 못 찾았을 때 주소를 직접 받는다."""
    state["step"] = "await_address"
    chat["state"] = state
    prefix = (
        f"네이버에서 '{state['query']}'을(를) 찾지 못했어요.\n"
        if searched else ""
    )
    return [reply(
        f"{prefix}📍 숙소 주소를 알려주세요.\n"
        "같은 이름의 다른 숙소와 헷갈리지 않도록, 예약사이트 검색 결과와 대조하는 데 씁니다.\n\n"
        "예) 경남 산청군 시천면 지리산대로 123\n"
        "지역만 아셔도 괜찮아요. (예: 산청군 시천면)\n"
        "몰라도 괜찮아요 — 아래 버튼을 누르시면 됩니다.",
        keyboards.address_keyboard(),
        edit=edit,
    )]


def _ask_checkin(chat, state, today, edit=False):
    state["step"] = "await_checkin"
    chat["state"] = state
    year, month = keyboards.default_month(today)
    return [reply(
        keyboards.calendar_message(state["query"], "in"),
        keyboards.month_calendar(year, month, today, min_date=today, mode="in"),
        edit=edit,
    )]


def _ask_checkout(chat, state, today, edit=False):
    state["step"] = "await_checkout"
    chat["state"] = state
    min_date = keyboards.next_day(state["checkin"])
    year, month = keyboards.default_month(today, min_date)
    return [reply(
        keyboards.calendar_message(state["query"], "out", state["checkin"]),
        keyboards.month_calendar(year, month, today, min_date=min_date, mode="out"),
        edit=edit,
    )]


def _ask_guests(chat, state, edit=False):
    """인원을 물어본다. 인원에 따라 검색되는 객실이 달라진다."""
    state["step"] = "await_guests"
    chat["state"] = state
    nights = dateparse.nights_between(state["checkin"], state["checkout"])
    return [reply(
        keyboards.guests_message(state["query"], state["checkin"],
                                 state["checkout"], nights),
        keyboards.guests_keyboard(),
        edit=edit,
    )]


def _set_guests(chat, state, guests, edit=False):
    if not 1 <= guests <= MAX_GUESTS:
        return [reply(f"1 ~ {MAX_GUESTS}명 사이로 알려주세요.")]
    state["guests"] = guests
    state["guests_set"] = True
    return _finish(chat, state, edit=edit)


def _ask_confirm(chat, state, edit=False):
    state["step"] = "await_confirm"
    chat["state"] = state
    nights = dateparse.nights_between(state["checkin"], state["checkout"])
    address = state.get("address") or "(입력 안 함)"
    return [reply(
        "아래 내용이 맞는지 확인해 주세요.\n\n"
        f"🏨 숙소: {state['query']}\n"
        f"📍 주소: {address}\n"
        f"📅 일정: {state['checkin']} → {state['checkout']} ({nights}박)\n"
        f"👤 인원: {state['guests']}명\n\n"
        "맞으면 '예', 다시 입력하려면 '아니오'를 보내주세요.",
        keyboards.confirm_keyboard(),
        edit=edit,
    )]


def _after_identity(chat, state, today, edit=False):
    """숙소(주소)가 정해진 뒤 — 날짜가 없으면 달력을, 있으면 마무리를."""
    if state.get("checkin") and state.get("checkout"):
        return _finish(chat, state, edit=edit)
    return _ask_checkin(chat, state, today, edit=edit)


def _finish(chat, state, edit=False):
    """네이버에서 고른 숙소는 바로 등록, 직접 입력한 주소는 한 번 더 확인."""
    if not state.get("guests_set"):
        return _ask_guests(chat, state, edit=edit)
    if state.get("address_source") in ("naver", "link"):
        chat["state"] = None
        _, message = register_watch(
            chat, state["query"], state["checkin"], state["checkout"],
            state.get("guests", DEFAULT_GUESTS), state.get("url"),
            state.get("address", ""), state.get("keyword", ""),
        )
        return [reply(message, edit=edit)]
    return _ask_confirm(chat, state, edit=edit)


def _pick_candidate(chat, state, index, today, edit=False):
    candidates = state.get("candidates") or []
    if not 0 <= index < len(candidates):
        return [reply(f"1 ~ {len(candidates)} 사이의 번호를 눌러주세요.")]
    chosen = candidates[index]
    name = chosen.get("name") or state["query"]
    # 네이버 표기 이름이 엉뚱하면 사용자가 적은 이름을 그대로 쓴다.
    if not search.card_matches(state.get("keyword") or state["query"], name):
        name = state["query"]
    state["query"] = name  # 표시용 이름(정식 명칭)
    # 검색어는 사용자가 처음 적은 짧은 이름을 유지한다.
    # 정식 명칭이 길면 다른 예약사이트에서 오히려 검색이 안 되기 때문.
    state.setdefault("keyword", state["query"])
    state["address"] = chosen.get("address", "")
    state["address_source"] = "naver"
    if chosen.get("url"):
        state["url"] = chosen["url"]
    state.pop("candidates", None)
    return _after_identity(chat, state, today, edit=edit)


def _change_guests(chat, argument):
    """등록된 알림의 인원을 바꾼다. '인원 2 4' = 2번 알림을 4명으로."""
    watches = chat["watches"]
    if not watches:
        return "등록된 알림이 없어요."
    numbers = [int(part) for part in argument.split() if part.isdigit()]
    if len(numbers) == 1 and len(watches) == 1:
        index, guests = 1, numbers[0]
    elif len(numbers) >= 2:
        index, guests = numbers[0], numbers[1]
    else:
        return ("'인원 2 4' 처럼 보내주세요. (2번 알림을 4명으로)\n"
                "'목록' 으로 번호를 확인할 수 있어요.")
    if not 1 <= index <= len(watches):
        return f"1 ~ {len(watches)} 사이의 번호를 알려주세요."
    if not 1 <= guests <= MAX_GUESTS:
        return f"인원은 1 ~ {MAX_GUESTS}명 사이로 알려주세요."

    watch = watches[index - 1]
    watch["guests"] = guests
    watch["force"] = True          # 바뀐 인원으로 바로 다시 검색
    return (f"👤 인원을 {guests}명으로 바꿨어요.\n"
            f"🏨 {watch['query']} ({watch['checkin']} → {watch['checkout']})\n"
            "바뀐 인원으로 지금 다시 검색할게요.")


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
            return (f"🗑️ 삭제했어요: {removed['query']} "
                    f"({removed['checkin']} → {removed['checkout']})")
        return f"1 ~ {len(watches)} 사이의 번호를 알려주세요."
    return "'삭제 2' 처럼 번호를 붙이거나 '삭제 전체'라고 보내주세요."


# --------------------------------------------------------------------------
# 사용자 입력 처리
# --------------------------------------------------------------------------

def handle_text(db, chat_id, text, today=None, lookup=None):
    """사용자가 보낸 글자 메시지 하나를 처리한다."""
    today = today or dateparse.today_kst()
    chat = storage.get_chat(db, chat_id)
    text = (text or "").strip()
    if not text:
        return []

    command = _menu_command(text.lstrip("/").strip())
    head, _, argument = command.partition(" ")
    head_lower = head.lower()
    argument = argument.strip()

    if head_lower in ("start", "help", "시작", "도움말", "사용법"):
        chat["state"] = None
        return [reply(HELP_TEXT)]

    if head_lower in ("추가", "등록", "add"):
        chat["state"] = None
        return [reply("🏨 감시할 숙소 이름을 보내주세요.\n"
                      "예) 비토애 산청\n\n"
                      "이름만 보내시면 주소·날짜·인원은 버튼으로 고르시면 돼요.")]

    if head_lower in ("목록", "list", "리스트"):
        return [reply(format_watch_list(chat["watches"]))]

    if head_lower in ("삭제", "delete", "제거", "초기화"):
        if not argument:
            return _ask_delete(chat)
        return [reply(_handle_delete(chat, argument))]

    if head_lower in ("취소", "cancel"):
        if chat.get("state"):
            chat["state"] = None
            return [reply("입력을 취소했어요. 다른 숙소 이름을 보내주세요.")]
        return [reply("진행 중인 등록이 없어요.")]

    if head_lower in ("인원", "사람", "guests"):
        return [reply(_change_guests(chat, argument))]

    if head_lower in ("지금", "지금검색", "새로고침", "now", "refresh"):
        if not chat["watches"]:
            return [reply("등록된 알림이 없어요. 숙소 이름부터 보내주세요.")]
        for watch in chat["watches"]:
            watch["force"] = True
        return [reply("🔄 지금 바로 검색할게요. 잠시만 기다려 주세요!")]

    state = chat.get("state") or {}
    if state and time.time() - state.get("touched_at", 0) > STATE_TTL:
        chat["state"] = state = {}   # 하다 만 등록은 잊는다
    elif state:
        state["touched_at"] = int(time.time())
    step = state.get("step")

    # 1) 네이버 후보 선택 (버튼 대신 번호를 적어도 되게)
    if step == "await_place_choice":
        if command.isdigit():
            return _pick_candidate(chat, state, int(command) - 1, today)
        if command.lower() in NONE_WORDS:
            return _ask_address(chat, state)
        if command.lower() in SKIP_WORDS:
            state["address"] = ""
            state["address_source"] = "skip"
            return _after_identity(chat, state, today)
        return [reply("목록의 번호를 보내주시거나 버튼을 눌러주세요.\n"
                      "목록에 없으면 '없음', 주소 없이 진행하려면 '건너뛰기'.")]

    # 2) 주소 직접 입력
    if step == "await_address":
        if command.lower() in SKIP_WORDS or command.lower() in NONE_WORDS:
            state["address"] = ""
            state["address_source"] = "skip"
        elif len(text) < 2:
            return [reply("주소를 조금 더 자세히 알려주세요. (모르시면 '건너뛰기')")]
        else:
            state["address"] = text[:100]
            state["address_source"] = "manual"
        return _after_identity(chat, state, today)

    # 3) 달력 대신 날짜를 직접 입력한 경우
    if step in ("await_checkin", "await_checkout"):
        stay, problem = None, ""
        try:
            stay = dateparse.parse_stay(text, today=today)
        except dateparse.DateParseError as exc:
            problem = f"⚠️ {exc}"
        if stay is None:
            if _looks_like_new_name(text):
                # 날짜가 아니라 다른 숙소 이름을 보낸 것으로 본다.
                chat["state"] = None
                started = _start_registration(chat, text, None, today, lookup=lookup)
                return [reply(f"'{state.get('query', '')}' 등록은 그만두고 "
                              f"'{text}' 부터 다시 시작할게요.")] + started
            return [reply((problem or "날짜를 이해하지 못했어요 😅") + "\n"
                          "달력 버튼을 누르시거나 '5/2~5/3'처럼 보내주세요.\n"
                          "그만두려면 '취소' 라고 보내주세요.")]
        checkin, checkout, _ = stay
        state["checkin"] = checkin.isoformat()
        state["checkout"] = checkout.isoformat()
        typed_guests = dateparse.parse_guests(text)
        if typed_guests:
            state["guests"] = typed_guests
            state["guests_set"] = True
        return _finish(chat, state)

    # 4) 인원 입력 (버튼 대신 숫자로 적어도 되게)
    if step == "await_guests":
        guests = dateparse.parse_guests(text)
        if guests is None and command.isdigit():
            guests = int(command)
        if guests is None:
            return [reply("인원을 숫자로 알려주세요. (예: 4 또는 4명)")]
        return _set_guests(chat, state, guests)

    # 5) 최종 확인
    if step == "await_confirm":
        answer = command.lower().rstrip("!.~ ")
        if answer in YES_WORDS:
            return _confirm_yes(chat, state)
        if answer in NO_WORDS:
            chat["state"] = None
            return [reply("알겠습니다. 숙소 이름부터 다시 알려주세요. (예: 비토애 산청)")]
        return [reply("'예' 또는 '아니오'로 답해주세요. 처음부터 다시 하려면 '취소'.")]

    # 6) 트리플 링크를 붙일 알림 고르기
    if step == "await_triple_target":
        if command.isdigit():
            return _attach_triple(chat, state.get("triple", ""), int(command) - 1)
        return [reply("목록의 번호를 보내주시거나 버튼을 눌러주세요. (취소하려면 '취소')")]

    # 7) 새 요청 — 링크 또는 숙소 이름
    triple = search.triple_link(text)
    if triple:
        return _ask_triple_target(chat, triple)

    url = _extract_url(text)
    if url:
        legacy = storage._watch_from_legacy_url(url)
        checkin = legacy["checkin"]
        checkout = legacy["checkout"]
        if not (checkin and checkout and checkout > checkin):
            checkin = checkout = None
        return _start_registration(
            chat, legacy["query"], _guests_in_url(url), today,
            url=search.naver_room_url(url), checkin=checkin, checkout=checkout,
        )

    try:
        parsed = dateparse.parse_request(text, today=today)
    except dateparse.DateParseError as exc:
        return [reply(f"⚠️ {exc}\n다시 알려주세요. (예: 비토애 산청 5/2~5/3)")]

    name = parsed["name"].strip()
    guests = parsed["guests"]   # 안 적었으면 None → 나중에 버튼으로 물어본다
    if not name:
        return [reply("숙소 이름을 함께 알려주세요. (예: 비토애 산청 5/2~5/3)")]
    if len(name) > 60:
        return [reply("숙소 이름이 너무 길어요. 짧게 다시 보내주세요.")]

    return _start_registration(
        chat, name, guests, today, lookup=lookup,
        checkin=parsed["checkin"].isoformat() if parsed["checkin"] else None,
        checkout=parsed["checkout"].isoformat() if parsed["checkout"] else None,
    )


def _confirm_yes(chat, state, edit=False):
    chat["state"] = None
    _, message = register_watch(
        chat, state["query"], state["checkin"], state["checkout"],
        state.get("guests", DEFAULT_GUESTS), state.get("url"),
        state.get("address", ""), state.get("keyword", ""),
    )
    return [reply(message, edit=edit)]


def handle_callback(db, chat_id, data, today=None):
    """인라인 버튼(달력·후보 선택)을 처리한다."""
    today = today or dateparse.today_kst()
    chat = storage.get_chat(db, chat_id)
    state = chat.get("state") or {}
    action, _, payload = (data or "").partition(":")
    kind, _, value = payload.partition(":")

    if data == keyboards.NOOP:
        return []

    if action == "del":
        if kind == "pick" and value.isdigit():
            return _delete_one(chat, int(value), edit=True)
        if kind == "all":
            chat["watches"] = []
            chat["state"] = None
            return [reply("🗑️ 모든 알림을 삭제했어요.", edit=True)]
        if kind == "cancel":
            return [reply("삭제를 취소했어요.", edit=True)]
        return []

    if not state:
        return [reply("진행 중인 등록이 없어요. 숙소 이름을 다시 보내주세요.")]

    if action == "triple":
        if kind == "pick" and value.isdigit():
            return _attach_triple(chat, state.get("triple", ""), int(value), edit=True)
        if kind == "cancel":
            chat["state"] = None
            return [reply("트리플 링크 연결을 취소했어요.", edit=True)]
        return []

    if action == "place":
        if kind == "pick" and value.isdigit():
            return _pick_candidate(chat, state, int(value), today, edit=True)
        if kind == "none":
            return _ask_address(chat, state, edit=True)
        if kind == "skip":
            state["address"] = ""
            state["address_source"] = "skip"
            return _after_identity(chat, state, today, edit=True)
        if kind == "cancel":
            chat["state"] = None
            return [reply("등록을 취소했어요.", edit=True)]

    if action == "cal":
        if kind == "m":  # 달 이동
            try:
                year, month = (int(part) for part in value.split("-"))
            except ValueError:
                return []
            mode = "out" if state.get("step") == "await_checkout" else "in"
            min_date = (keyboards.next_day(state["checkin"])
                        if mode == "out" and state.get("checkin") else today)
            return [reply(
                keyboards.calendar_message(state["query"], mode, state.get("checkin")),
                keyboards.month_calendar(year, month, today, min_date, mode),
                edit=True,
            )]
        if kind == "in":
            state["checkin"] = value
            state["checkout"] = None
            return _ask_checkout(chat, state, today, edit=True)
        if kind == "out":
            if not state.get("checkin"):
                return _ask_checkin(chat, state, today, edit=True)
            if value <= state["checkin"]:
                return [reply("체크아웃은 체크인 다음 날부터 고를 수 있어요.")]
            state["checkout"] = value
            return _finish(chat, state, edit=True)
        if kind == "type":
            return [reply("날짜를 직접 보내주세요. (예: 5/2~5/3, 내일 2박, 이번주말)")]
        if kind == "cancel":
            chat["state"] = None
            return [reply("등록을 취소했어요.", edit=True)]

    if action == "guests":
        if kind == "pick" and value.isdigit():
            return _set_guests(chat, state, int(value), edit=True)
        if kind == "type":
            return [reply("인원을 숫자로 보내주세요. (예: 4)")]
        if kind == "cancel":
            chat["state"] = None
            return [reply("등록을 취소했어요.", edit=True)]

    if action == "confirm":
        if kind == "yes":
            return _confirm_yes(chat, state, edit=True)
        if kind == "no":
            chat["state"] = None
            return [reply("알겠습니다. 숙소 이름부터 다시 알려주세요.", edit=True)]

    return []


# --------------------------------------------------------------------------
# 텔레그램 폴링
# --------------------------------------------------------------------------

def _send_replies(chat_id, replies, message_id=None):
    for item in replies:
        # 달력처럼 자리에서 갱신할 응답은 편집을 먼저 시도하고, 실패하면 새로 보낸다.
        if item.get("edit") and message_id:
            if telegram_api.edit_message(chat_id, message_id, item["text"],
                                         item.get("keyboard")):
                continue
        telegram_api.send_message(chat_id, item["text"], keyboard=item.get("keyboard"),
                                  menu=keyboards.menu_keyboard())


def greet_owner_about(db, chat_id):
    """처음 보는 사람이 봇을 쓰기 시작하면 주인에게 알린다.

    봇 주소를 아는 사람은 누구나 쓸 수 있다. 남이 쓰기 시작하면 검색도
    그만큼 늘어나므로, 주인이 알고는 있어야 한다.
    """
    chat_id = str(chat_id)
    owner = storage.ensure_owner(db)
    if not owner:
        db["owner"] = chat_id     # 처음 말을 건 사람이 주인이 된다
        return
    if chat_id == owner or chat_id in db.get("chats", {}):
        return
    people = len(db.get("chats", {}))
    telegram_api.send_message(
        owner,
        f"👤 새로운 사람이 봇을 쓰기 시작했어요. (chat {mask(chat_id)})\n"
        f"지금까지 이 봇을 쓴 사람은 모두 {people + 1}명이에요.\n"
        "나만 쓰게 막고 싶으시면 알려주세요.",
    )


def process_updates(db, browser=None, timeout=0):
    """새 메시지·버튼 입력을 처리하고 처리 건수를 돌려준다."""
    offset = db.get("last_update_id", 0) + 1
    try:
        updates = telegram_api.get_updates(offset, timeout=timeout) or []
    except telegram_api.TelegramError as exc:
        print(f"🚨 업데이트 수신 실패: {exc}")
        return 0

    if updates:
        print(f"📨 새 입력 {len(updates)}건")

    def make_lookup(chat_id):
        """네이버에서 후보를 찾기 전에 '찾는 중'이라고 먼저 알린다.

        크롬을 띄워 네이버를 훑는 동안 몇 초가 걸린다. 그동안 아무 말이
        없으면 먹통처럼 보인다.
        """
        def lookup(query):
            telegram_api.send_message(
                chat_id, f"🔎 '{query}' 찾는 중이에요… 잠시만요!")
            return search.lookup_places(browser, query)
        return lookup

    for update in updates:
        db["last_update_id"] = max(db.get("last_update_id", 0), update["update_id"])

        callback = update.get("callback_query")
        if callback:
            message = callback.get("message") or {}
            chat_id = str((message.get("chat") or {}).get("id", ""))
            telegram_api.answer_callback(callback.get("id", ""))
            if not chat_id:
                continue
            greet_owner_about(db, chat_id)
            try:
                replies = handle_callback(db, chat_id, callback.get("data", ""))
            except Exception as exc:  # noqa: BLE001
                print(f"⚠️ 버튼 처리 오류(chat {mask(chat_id)}): {exc}")
                replies = [reply("처리 중 문제가 생겼어요 😢 다시 시도해 주세요.")]
            _send_replies(chat_id, replies, message.get("message_id"))
            continue

        message = update.get("message") or update.get("edited_message") or {}
        text = (message.get("text") or "").strip()
        chat_id = str((message.get("chat") or {}).get("id", ""))
        if not chat_id or not text:
            continue
        greet_owner_about(db, chat_id)
        try:
            replies = handle_text(db, chat_id, text,
                                  lookup=make_lookup(chat_id) if browser else None)
        except Exception as exc:  # noqa: BLE001 - 한 명의 오류가 전체를 멈추지 않도록
            print(f"⚠️ 메시지 처리 오류(chat {mask(chat_id)}): {exc}")
            replies = [reply("처리 중 문제가 생겼어요 😢 다시 한 번 보내주시겠어요?")]
        _send_replies(chat_id, replies)

    return len(updates)


# --------------------------------------------------------------------------
# 주기 검색
# --------------------------------------------------------------------------

def decide_notification(watch, results, now, forced):
    """보낼 알림 종류를 정한다: 'report' | 'closed' | None.

    빈방이 처음 열린 순간은 바로 알린다. 그 뒤로도 계속 열려 있으면
    NOTIFY_INTERVAL 마다 한 번만 다시 알린다. 예전에는 값이나 객실 이름이
    조금만 달라져도 다시 알려서, 열려 있는 동안 검색할 때마다 알림이 갔다.
    """
    available = any(r.available for r in results)
    if forced:
        return "report", available
    if available:
        opened = not watch.get("was_available")
        overdue = now - watch.get("last_notified", 0) >= NOTIFY_INTERVAL
        if opened or overdue:
            return "report", available
        return None, available
    if watch.get("was_available"):
        return "closed", available
    return None, available


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


def run_due_searches(db, now=None, today=None, browser=None, between=None):
    now = now or time.time()
    today = today or dateparse.today_kst()
    due, notices = _collect_due(db, now, today)

    for chat_id, message in notices:
        telegram_api.send_message(chat_id, message)

    if not due:
        return False

    sites = search.load_sites()
    owns_browser = browser is None
    browser = browser or search.Browser()
    try:
        for chat_id, watch in due:
            forced = bool(watch.get("force"))
            print(f"🔎 검색: {watch['query']} {watch['checkin']}~{watch['checkout']} "
                  f"(chat {mask(chat_id)})")
            results = search.search_watch(browser, watch, sites,
                                          after_site=between)
            for result in results:
                print(f"   - {result.name}: {result.status} "
                      f"({len(result.offers)}건) {result.note}")

            watch["last_searched"] = int(now)
            watch["force"] = False
            kind, available = decide_notification(watch, results, now, forced)

            if kind == "report":
                header = ("🔄 요청하신 검색 결과예요." if forced and not available
                          else "🚨 예약 가능한 방을 찾았어요!")
                if telegram_api.send_message(chat_id, format_report(watch, results, header)):
                    watch["last_notified"] = int(now)
            elif kind == "closed":
                telegram_api.send_message(
                    chat_id,
                    f"🔕 '{watch['query']}' ({watch['checkin']} → {watch['checkout']}) "
                    "방금 전까지 보이던 빈방이 모두 마감됐어요. 계속 지켜볼게요.",
                )
            watch["was_available"] = available
    finally:
        if owns_browser:
            browser.quit()
    return True


def main():
    """조용하면 곧바로 끝내고, 대화 중이면 잠시 더 머물며 버튼에 바로 반응한다."""
    db = storage.load_db()
    watches = sum(len(chat.get("watches", [])) for chat in db["chats"].values())
    print(f"📂 감시 중인 숙소 {watches}건을 불러왔습니다.")
    browser = search.Browser()  # 크롬은 실제로 필요할 때만 뜬다
    started = time.time()
    seen = {"activity": None}
    timeout = POLL_TIMEOUT if ALWAYS_ON else 0  # 상시 대기면 처음부터 기다린다
    if ALWAYS_ON:
        print(f"🟢 상시 대기 모드 (최대 {MAX_RUN // 60}분, 검색 주기 "
              f"{SEARCH_INTERVAL // 60}분)")
    try:
        def pump():
            """검색이 도는 중에도 텔레그램 입력을 계속 받아준다."""
            if process_updates(db, browser, timeout=0):
                seen["activity"] = time.time()

        while True:
            handled = process_updates(db, browser, timeout=timeout)
            if handled:
                seen["activity"] = time.time()
            searched = run_due_searches(db, browser=browser, between=pump)
            storage.save_db(db)
            storage.persist()

            now = time.time()
            last_activity = seen["activity"]
            idle = last_activity is None or now - last_activity >= BROWSER_IDLE
            if searched and ALWAYS_ON and idle:
                browser.quit()  # 오래 켜둘 때 크롬이 메모리를 물고 있지 않도록

            if now - started >= MAX_RUN:
                break
            if not ALWAYS_ON:
                if last_activity is None:
                    break  # 대화가 없으면 바로 종료 (실행 시간 절약)
                if now - last_activity >= IDLE_EXIT or POLL_TIMEOUT <= 0:
                    break
            timeout = POLL_TIMEOUT  # long polling 으로 버튼에 즉시 반응
    finally:
        browser.quit()
        storage.save_db(db)
        storage.persist()


if __name__ == "__main__":
    main()
