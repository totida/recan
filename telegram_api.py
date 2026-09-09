"""텔레그램 Bot API 얇은 래퍼."""

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
    return _call(
        "getUpdates",
        {"offset": offset, "timeout": timeout, "limit": limit},
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


def send_message(chat_id, text, preview=False):
    """긴 메시지는 자동으로 나눠 보낸다."""
    for chunk in _chunks(text):
        try:
            _call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": "false" if preview else "true",
                },
            )
        except TelegramError as exc:
            print(f"⚠️ 메시지 전송 실패(chat {chat_id}): {exc}")
            return False
    return True
