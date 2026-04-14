import json
import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DB_FILE = "users.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"last_update_id": 0, "users": {}}

def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def sync_telegram_requests(db):
    offset = db["last_update_id"] + 1
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}"
    
    try:
        response = requests.get(url).json()
        if response.get("ok") and response.get("result"):
            for update in response["result"]:
                update_id = update["update_id"]
                db["last_update_id"] = update_id
                
                message = update.get("message", {})
                text = message.get("text", "")
                chat_id = str(message.get("chat", {}).get("id", ""))
                
                if text.startswith("http"):
                    if chat_id not in db["users"]:
                        db["users"][chat_id] = []
                    
                    if text not in db["users"][chat_id]:
                        db["users"][chat_id].append(text)
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                      data={"chat_id": chat_id, "text": "✅ 새로운 숙소 알림이 등록되었습니다!\n(15분 주기로 감시를 시작합니다)"})
            save_db(db)
    except Exception as e:
        print(f"메시지 동기화 에러: {e}")

def check_vacancy(target_url):
    """실제 네이버 예약 페이지를 확인하는 엄격한 셀레늄 로직"""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    
    driver = webdriver.Chrome(options=options)
    
    try:
        driver.get(target_url)
        # 1. 깃허브 서버는 조금 느릴 수 있으므로 대기 시간을 8초로 늘립니다.
        time.sleep(8) 
        
        page_text = driver.find_element(By.TAG_NAME, 'body').text
        
        # 2. 철통 방어막: 화면 로딩이 덜 돼서 글씨가 100자도 안 되거나 '네이버' 글자가 없으면 튕겨냅니다.
        if len(page_text) < 100 or "네이버" not in page_text:
            print("화면 로딩 지연. (오알림 방지)")
            return False
            
        # 3. 명확히 방이 없다고 안내된 경우
        if "예약 가능한 객실이 없습니다" in page_text:
            return False
            
        # 4. 깐깐한 상태 검사
        if "예약마감" in page_text:
            # 기본적으로 예약마감이 도배되어 있으면 만실입니다.
            # 단, 누군가 방금 취소해서 1~2개 방만 열린 상태를 잡기 위해 '잔여' 같은 확고한 증거가 있는지 봅니다.
            if "잔여" in page_text or "남은객실" in page_text:
                return True
            else:
                return False
        else:
            # 예약마감이라는 단어가 아예 없다면 널널한 곳입니다.
            # 단, 빈 화면이 아니라 실제 예약창이라는 증거('원', '객실')가 있어야만 인정합니다.
            if "원" in page_text and "객실" in page_text:
                return True
            else:
                return False
                
    except Exception as e:
        print(f"크롤링 에러 발생: {e}")
        return False
        
    finally:
        driver.quit()

def run_multi_scrapers(db):
    for chat_id, urls in db["users"].items():
        for target_url in urls:
            print(f"\n[{chat_id}]님의 요청 링크 확인 중...")
            print(f"URL: {target_url[:50]}...") # 로그창이 지저분해지지 않게 주소 일부만 출력
            
            is_vacant = check_vacancy(target_url)
            
            if is_vacant:
                msg = f"🚨 [빈자리 포착] 요청하신 숙소에 빈자리가 났습니다!\n바로 접속하세요:\n{target_url}"
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                              data={"chat_id": chat_id, "text": msg})

if __name__ == "__main__":
    current_db = load_db()
    sync_telegram_requests(current_db)
    run_multi_scrapers(current_db)
