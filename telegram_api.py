"""텔레그램 Bot API 얇은 래퍼."""

import json
import os
import time

import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
API_BASE = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE_LEN = 3800  # 텔레그램 한도(4096)보다 넉넉히 여유를 둔다.


class TelegramError(RuntimeError):
    pass


def _call(method, params=None, timeout=30, retries=3):
    if not TELEGRAM_TOKEN:
        raise TelegramError("TELEGRAM_TOKEN 환경변수가 없습니다.")
    url = API_BASE.format(token=TELEGRAM_TOKEN, method=method)
    last_error = None
    for attempt in range(retries):
        try:
            response = requests.post(url, data=params or {}, timeout=timeout)
            payload = response.json()
            if payload.get("ok"):
                return payload.get("result")
            last_error = payload.get("description", "unknown error")
        except (requests.RequestException, ValueError) as exc:
            last_error = str(exc)
        time.sleep(2 ** attempt)
    raise TelegramError(f"{method} 실패: {last_error}")


def get_updates(offset, timeout=0, limit=50):
    """long polling: timeout 초 동안 새 메시지를 기다린다."""
    return _call(
        "getUpdates",
        {
            "offset": offset,
            "timeout": timeout,
            "limit": limit,
            "allowed_updates": json.dumps(["message", "edited_message", "callback_query"]),
        },
        timeout=timeout + 30,
    )


def _chunks(text):
    while len(text) > MAX_MESSAGE_LEN:
        cut = text.rfind("\n", 0, MAX_MESSAGE_LEN)
        if cut <= 0:
            cut = MAX_MESSAGE_LEN
        yield text[:cut]
        text = text[cut:].lstrip("\n")
    if text:
        yield text


def _markup(keyboard):
    return json.dumps({"inline_keyboard": keyboard}) if keyboard else None


def send_message(chat_id, text, preview=False, keyboard=None):
    """긴 메시지는 자동으로 나눠 보낸다. 성공하면 마지막 message_id 를 돌려준다."""
    message_id = None
    chunks = list(_chunks(text))
    for index, chunk in enumerate(chunks):
        params = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": "false" if preview else "true",
        }
        # 키보드는 마지막 조각에만 붙인다.
        if keyboard and index == len(chunks) - 1:
            params["reply_markup"] = _markup(keyboard)
        try:
            result = _call("sendMessage", params)
            message_id = (result or {}).get("message_id")
        except TelegramError as exc:
            print(f"⚠️ 메시지 전송 실패(chat …{str(chat_id)[-4:]}): {exc}")
            return None
    return message_id


def edit_message(chat_id, message_id, text, keyboard=None):
    """이미 보낸 메시지(달력 등)를 그 자리에서 갱신."""
    params = {"chat_id": chat_id, "message_id": message_id, "text": text[:MAX_MESSAGE_LEN],
              "disable_web_page_preview": "true"}
    if keyboard is not None:
        params["reply_markup"] = _markup(keyboard)
    try:
        _call("editMessageText", params, retries=1)
        return True
    except TelegramError as exc:
        print(f"⚠️ 메시지 수정 실패(chat …{str(chat_id)[-4:]}): {exc}")
        return False


def answer_callback(callback_id, text=""):
    """버튼 누름에 응답해 로딩 표시를 없앤다. (오래된 요청은 실패해도 무방)"""
    try:
        _call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text},
              retries=1)
        return True
    except TelegramError as exc:
        print(f"ℹ️ 버튼 응답 생략: {exc}")
        return False
