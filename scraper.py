import json
import os
import requests
from selenium import webdriver
# ... (크롬 옵션 등 기존 셀레늄 세팅 동일) ...

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DB_FILE = "users.json"

def load_db():
    """JSON DB 파일을 불러옵니다. 파일이 없으면 초기 구조를 만듭니다."""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"last_update_id": 0, "users": {}}

def save_db(data):
    """변경된 데이터를 JSON 파일에 저장합니다."""
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def sync_telegram_requests(db):
    """새로운 텔레그램 메시지를 읽어 DB에 링크를 추가합니다."""
    # last_update_id 다음 메시지부터 가져와서 중복 등록 방지
    offset = db["last_update_id"] + 1
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}"
    
    try:
        response = requests.get(url).json()
        if response.get("ok") and response.get("result"):
            for update in response["result"]:
                update_id = update["update_id"]
                db["last_update_id"] = update_id # 마지막 읽은 메시지 번호 갱신
                
                message = update.get("message", {})
                text = message.get("text", "")
                chat_id = str(message.get("chat", {}).get("id", ""))
                
                # 사용자가 보낸 메시지가 http로 시작하는 링크라면
                if text.startswith("http"):
                    # 해당 유저의 공간이 없으면 리스트(배열) 생성
                    if chat_id not in db["users"]:
                        db["users"][chat_id] = []
                    
                    # 중복 링크가 아니면 추가
                    if text not in db["users"][chat_id]:
                        db["users"][chat_id].append(text)
                        
                        # 사용자에게 등록 완료 확인 메시지 발송
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                      data={"chat_id": chat_id, "text": "✅ 새로운 숙소 알림이 등록되었습니다!"})
            save_db(db) # 변경된 내용을 파일에 덮어쓰기
    except Exception as e:
        print(f"메시지 동기화 에러: {e}")

def run_multi_scrapers(db):
    """DB에 등록된 모든 유저의 모든 링크를 순회하며 빈자리를 찾습니다."""
    for chat_id, urls in db["users"].items():
        for target_url in urls:
            # --------------------------------------------------
            # 여기에 기존 셀레늄 크롤링 로직(check_vacancy 등) 적용
            # is_vacant = check_vacancy(target_url)
            is_vacant = False # 임시 테스트용
            # --------------------------------------------------
            
            if is_vacant:
                msg = f"🚨 요청하신 숙소에 빈자리가 났습니다!\n바로가기: {target_url}"
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                              data={"chat_id": chat_id, "text": msg})

if __name__ == "__main__":
    current_db = load_db()
    sync_telegram_requests(current_db)
    run_multi_scrapers(current_db)
