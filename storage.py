"""users.json 저장소 (구버전 스키마 자동 마이그레이션 포함)."""

import json
import os
import re
import subprocess
import tempfile
import time
import time
import uuid
from urllib.parse import parse_qs, unquote, urlparse

DB_FILE = os.environ.get("DB_FILE", "users.json")
SCHEMA_VERSION = 2
# 오래 켜두고 도는 동안에도 등록 내용이 남도록, 바뀔 때마다 저장소에 커밋한다.
GIT_PERSIST = os.environ.get("GIT_PERSIST") == "1"


def default_db():
    return {"version": SCHEMA_VERSION, "last_update_id": 0, "chats": {}}


def new_watch(query, checkin, checkout, guests=2, url=None, address="", keyword=""):
    return {
        "id": uuid.uuid4().hex[:8],
        "query": query,             # 표시용 이름(네이버 정식 명칭일 수 있음)
        "keyword": keyword or query,  # 예약사이트 검색에 쓸 짧은 이름
        "address": address or "",   # 사용자가 승인한 숙소 주소(검증용)
        "checkin": checkin,          # "YYYY-MM-DD"
        "checkout": checkout,        # "YYYY-MM-DD"
        "guests": guests,
        "url": url,                  # 네이버 등 특정 숙소 상세 링크(선택)
        "created_at": int(time.time()),
        "last_searched": 0,
        "last_notified": 0,
        "last_signature": "",
        "was_available": False,
        "force": False,
    }


def get_chat(db, chat_id):
    return db["chats"].setdefault(str(chat_id), {"state": None, "watches": []})


def _iso_from_compact(value):
    if value and re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    return None


def _watch_from_legacy_url(url, last_notified=0):
    """구버전(URL만 등록)을 새 감시 항목으로 변환."""
    params = parse_qs(urlparse(url).query)

    def first(*keys):
        for key in keys:
            if params.get(key):
                return params[key][0]
        return None

    checkin = _iso_from_compact(first("checkin", "checkIn", "startDate", "sel_date"))
    checkout = _iso_from_compact(first("checkout", "checkOut", "endDate", "sel_date2"))
    name = first("bk_query", "keyword", "query")
    name = unquote(name) if name else "등록된 링크"
    guests = first("guest", "personal", "adultCount")

    watch = new_watch(
        query=name,
        checkin=checkin,
        checkout=checkout,
        guests=int(guests) if guests and guests.isdigit() else 2,
        url=url,
        address=unquote(first("address", "addr") or ""),
    )
    watch["last_notified"] = last_notified
    return watch


def migrate(raw):
    if not isinstance(raw, dict):
        return default_db()
    if raw.get("version") == SCHEMA_VERSION and "chats" in raw:
        for chat in raw["chats"].values():
            chat.setdefault("state", None)
            chat.setdefault("watches", [])
            for watch in chat["watches"]:
                watch.setdefault("address", "")
                watch.setdefault("keyword", watch.get("query", ""))
        return raw

    db = default_db()
    db["last_update_id"] = raw.get("last_update_id", 0)
    for chat_id, items in (raw.get("users") or {}).items():
        chat = get_chat(db, chat_id)
        for item in items or []:
            if isinstance(item, str):
                chat["watches"].append(_watch_from_legacy_url(item))
            elif isinstance(item, dict) and item.get("url"):
                chat["watches"].append(
                    _watch_from_legacy_url(item["url"], item.get("last_notified", 0))
                )
    return db


def load_db(path=None):
    path = path or DB_FILE
    if not os.path.exists(path):
        return default_db()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return migrate(json.load(f))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"⚠️ DB 로드 실패({exc}). 새 DB로 시작합니다.")
        return default_db()


def save_db(db, path=None):
    path = path or DB_FILE
    directory = os.path.dirname(os.path.abspath(path))
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
    ) as tmp:
        json.dump(db, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        temp_path = tmp.name
    os.replace(temp_path, path)


def _run_git(args, timeout=60):
    result = subprocess.run(["git", *args], capture_output=True, text=True,
                            timeout=timeout)
    return result.returncode, (result.stdout + result.stderr).strip()


def persist(path=None, message="Update user database"):
    """바뀐 users.json 을 저장소에 커밋·푸시한다.

    실행이 몇 시간씩 이어지므로 종료 시점에만 저장하면 그 사이 등록한 내용이
    날아갈 수 있다. 그래서 바뀔 때마다 바로 남긴다. 실패해도 봇은 계속 돈다.
    """
    if not GIT_PERSIST:
        return False
    path = path or DB_FILE
    try:
        _run_git(["add", path])
        if _run_git(["diff", "--cached", "--quiet"])[0] == 0:
            return False  # 바뀐 내용 없음
        _run_git(["commit", "-m", message])
        for attempt in range(3):
            _run_git(["pull", "--rebase", "--quiet"])
            code, output = _run_git(["push", "--quiet"])
            if code == 0:
                print("💾 등록 내용을 저장했습니다.")
                return True
            print(f"⚠️ 저장 실패({attempt + 1}/3): {output[:150]}")
            time.sleep(2 ** attempt)
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"⚠️ 저장 중 오류: {exc}")
    return False
