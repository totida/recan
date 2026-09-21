"""users.json 저장소 (구버전 스키마 자동 마이그레이션 포함)."""

import json
import os
import re
import subprocess
import tempfile
import time

import requests
import time
import uuid
from urllib.parse import parse_qs, unquote, urlparse

DB_FILE = os.environ.get("DB_FILE", "users.json")
SCHEMA_VERSION = 2
# 오래 켜두고 도는 동안에도 등록 내용이 남도록, 바뀔 때마다 저장소에 커밋한다.
GIT_PERSIST = os.environ.get("GIT_PERSIST") == "1"
# 예약 실행으로 뜬 작업은 브랜치가 아니라 특정 커밋에 붙은 채(detached HEAD)
# 시작한다. 그 상태에서는 인자 없는 pull/push 가 통째로 실패하므로,
# 언제나 브랜치를 명시해서 주고받는다.
GIT_BRANCH = os.environ.get("GITHUB_REF_NAME") or "main"

# 등록 내용을 저장소 대신 비공개 Gist 에 둘 수 있다.
# 저장소가 공개라도 쓰는 사람의 채팅 ID·감시 목록이 공개되지 않는다.
GIST_ID = os.environ.get("GIST_ID", "").strip()
GIST_TOKEN = os.environ.get("GIST_TOKEN", "").strip()
GIST_FILENAME = os.environ.get("GIST_FILENAME", "users.json").strip() or "users.json"
GIST_API = "https://api.github.com/gists/"

# 주인을 못 박아 두고 싶을 때. 비워 두면 이미 쓰고 있는 사람을 주인으로 본다.
# 저장소가 공개이므로 워크플로에 그대로 적지 말고 비밀값으로 넣는다.
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "").strip()


class StorageError(RuntimeError):
    """저장소를 읽지 못했을 때. 빈 상태로 시작해 덮어쓰는 사고를 막는다."""


def gist_enabled():
    return bool(GIST_ID and GIST_TOKEN)


def _gist_headers():
    return {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def gist_read():
    """Gist 에 저장된 내용을 문자열로. 파일이 없으면 빈 문자열."""
    response = requests.get(GIST_API + GIST_ID, headers=_gist_headers(), timeout=30)
    response.raise_for_status()
    files = response.json().get("files") or {}
    entry = files.get(GIST_FILENAME) or {}
    if entry.get("truncated") and entry.get("raw_url"):
        raw = requests.get(entry["raw_url"], headers=_gist_headers(), timeout=30)
        raw.raise_for_status()
        return raw.text
    return entry.get("content", "")


def gist_write(content):
    response = requests.patch(
        GIST_API + GIST_ID,
        headers=_gist_headers(),
        json={"files": {GIST_FILENAME: {"content": content}}},
        timeout=30,
    )
    response.raise_for_status()
    return True


_last_saved = {}


def default_db():
    # owner: 이 봇을 만든 사람의 채팅. 새 사람이 말을 걸면 여기로 알린다.
    return {"version": SCHEMA_VERSION, "last_update_id": 0, "owner": "", "chats": {}}


def ensure_owner(db):
    """주인을 알려준다. 한 번 정해지면 절대 바뀌지 않는다.

    순서는 이렇다.
      1) OWNER_CHAT_ID 를 넣어 두었으면 무조건 그 사람이다.
      2) 이미 정해져 있으면 그대로 둔다. 남이 숙소를 더 많이 등록해도,
         주인이 자기 숙소를 다 지워도 바뀌지 않는다.
      3) 아직 없으면 이미 쓰고 있는 사람(감시 중인 숙소가 가장 많은 채팅)을
         주인으로 삼는다. 아무도 없으면 비워 두고, 처음 말을 건 사람이 된다.
    """
    if OWNER_CHAT_ID:
        if db.get("owner") != OWNER_CHAT_ID:
            db["owner"] = OWNER_CHAT_ID
            print(f"👑 주인을 설정값으로 고정했습니다(…{OWNER_CHAT_ID[-4:]}).")
        return OWNER_CHAT_ID
    if db.get("owner"):
        return db["owner"]
    chats = db.get("chats") or {}
    if not chats:
        return ""
    best = max(chats, key=lambda key: len(chats[key].get("watches") or []))
    db["owner"] = best
    print(f"👑 주인을 정했습니다(…{best[-4:]}). 앞으로 바뀌지 않습니다.")
    return best


def new_watch(query, checkin, checkout, guests=2, url=None, address="", keyword="",
              triple=None):
    return {
        "id": uuid.uuid4().hex[:8],
        "query": query,             # 표시용 이름(네이버 정식 명칭일 수 있음)
        "keyword": keyword or query,  # 예약사이트 검색에 쓸 짧은 이름
        "address": address or "",   # 사용자가 승인한 숙소 주소(검증용)
        "checkin": checkin,          # "YYYY-MM-DD"
        "checkout": checkout,        # "YYYY-MM-DD"
        "guests": guests,
        "url": url,                  # 네이버 등 특정 숙소 상세 링크(선택)
        "triple": triple or None,    # 인터파크 트리플 숙소 링크(선택)
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
        raw.setdefault("owner", "")
        for chat in raw["chats"].values():
            chat.setdefault("state", None)
            chat.setdefault("watches", [])
            for watch in chat["watches"]:
                watch.setdefault("address", "")
                watch.setdefault("keyword", watch.get("query", ""))
        ensure_owner(raw)
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
    ensure_owner(db)
    return db


def _load_file(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return migrate(json.load(f))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"⚠️ 파일에서 불러오지 못했습니다({exc}).")
        return None


def load_db(path=None):
    path = path or DB_FILE
    if gist_enabled():
        try:
            raw = gist_read()
        except (requests.RequestException, ValueError) as exc:
            # 여기서 빈 상태로 시작하면 다음 저장 때 전부 지워진다. 차라리 멈춘다.
            raise StorageError(f"Gist 를 읽지 못했습니다: {exc}") from exc
        if raw.strip():
            print("📥 Gist 에서 등록 내용을 불러왔습니다.")
            return migrate(json.loads(raw))
        seeded = _load_file(path)
        if seeded:
            print("🌱 Gist 가 비어 있어 저장소의 users.json 으로 시작합니다.")
            return seeded
        print("🆕 새 저장소로 시작합니다.")
        return default_db()

    loaded = _load_file(path)
    if loaded is None:
        return default_db()
    return loaded


def save_db(db, path=None):
    """Gist 를 쓰는 경우 거기에, 아니면 파일에 저장한다."""
    if gist_enabled():
        content = json.dumps(db, ensure_ascii=False, indent=2) + "\n"
        if content == _last_saved.get("content"):
            return True
        try:
            gist_write(content)
            _last_saved["content"] = content
            return True
        except (requests.RequestException, ValueError) as exc:
            print(f"🚨 Gist 저장 실패: {exc}")
            return False

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
    if gist_enabled() or not GIT_PERSIST:
        return False
    path = path or DB_FILE
    try:
        _run_git(["add", path])
        if _run_git(["diff", "--cached", "--quiet"])[0] == 0:
            return False  # 바뀐 내용 없음
        _run_git(["commit", "-m", message])
        for attempt in range(3):
            _run_git(["pull", "--rebase", "--quiet", "origin", GIT_BRANCH])
            code, output = _run_git(["push", "--quiet", "origin",
                                     f"HEAD:{GIT_BRANCH}"])
            if code == 0:
                return True
            print(f"⚠️ 저장 실패({attempt + 1}/3): {output[:200]}")
            time.sleep(2 ** attempt)
        print("🚨 등록 내용을 저장하지 못했습니다. 다음 실행에서 되돌아갈 수 있습니다.")
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"⚠️ 저장 중 오류: {exc}")
    return False
