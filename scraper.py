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
    """실제 네이버 예약 페이지를 확인하는 셀레늄 로직"""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    
    driver = webdriver.Chrome(options=options)
    
    try:
        driver.get(target_url)
        time.sleep(5) # 네이버 페이지 로딩 대기
        
        page_text = driver.find_element(By.TAG_NAME, 'body').text
        
        if "예약마감" in page_text:
            if "객실 선택" in page_text or "잔여" in page_text:
                print("일부 빈자리 발견!")
                return True
            else:
                print("전 객실 예약 마감 상태입니다.")
                return False
        else:
            print("빈자리 발견! (예약마감 텍스트 없음)")
            return True
            
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
