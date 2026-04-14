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
    """새로운 메시지를 읽어 링크를 추가하거나 삭제하는 로직"""
    offset = db["last_update_id"] + 1
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}"
    
    try:
        response = requests.get(url).json()
        if response.get("ok") and response.get("result"):
            for update in response["result"]:
                update_id = update["update_id"]
                db["last_update_id"] = update_id
                
                message = update.get("message", {})
                text = message.get("text", "").strip() # 앞뒤 공백 제거
                chat_id = str(message.get("chat", {}).get("id", ""))
                
                # 1. 사용자가 새로운 링크를 보냈을 때 (기존과 동일)
                if text.startswith("http"):
                    if chat_id not in db["users"]:
                        db["users"][chat_id] = []
                    
                    if text not in db["users"][chat_id]:
                        db["users"][chat_id].append(text)
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                      data={"chat_id": chat_id, "text": "✅ 새로운 숙소 알림이 등록되었습니다!\n(15분 주기로 감시를 시작합니다)"})
                
                # 2. ⭐️ [신규] "삭제" 또는 "초기화"라고 보냈을 때
                elif text == "삭제" or text == "초기화":
                    if chat_id in db["users"]:
                        db["users"][chat_id] = [] # 해당 유저의 링크 목록을 텅 비움
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                      data={"chat_id": chat_id, "text": "🗑️ 등록하신 모든 알림이 삭제(초기화)되었습니다.\n다시 알림을 원하시면 링크를 새로 보내주세요."})
                
                # 3. ⭐️ [신규] "목록"이라고 보냈을 때
                elif text == "목록":
                    urls = db.get("users", {}).get(chat_id, [])
                    if urls:
                        url_list_text = "\n\n".join([f"{i+1}. {u}" for i, u in enumerate(urls)])
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                      data={"chat_id": chat_id, "text": f"📋 현재 감시 중인 링크 목록입니다:\n\n{url_list_text}"})
                    else:
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                      data={"chat_id": chat_id, "text": "텅~ 등록된 링크가 없습니다. 링크를 보내주시면 감시를 시작할게요!"})
                        
            save_db(db)
    except Exception as e:
        print(f"메시지 동기화 에러: {e}")

def check_vacancy(target_url):
    """'예약마감' 글자가 없어졌을 때만 알림을 보내는 초심플 로직"""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=390,844') # 아이폰 크기 유지
    options.add_argument('--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1')
    
    driver = webdriver.Chrome(options=options)
    
    try:
        driver.get(target_url)
        time.sleep(5) 
        
        # 화면을 아래로 내려 숨겨진 글씨를 띄움
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(5) 
        
        page_text = driver.find_element(By.TAG_NAME, 'body').text
        
        # 안전장치: 화면 자체가 안 켜진 경우(하얀 화면)는 무시함
        if len(page_text) < 100 or "네이버" not in page_text:
            print("화면 로딩 지연. (판단 보류)")
            return False
            
        # ⭐️ 경환님 맞춤형 초심플 판단 로직
        if "예약마감" not in page_text:
            # 정상적으로 로딩된 화면인데 '예약마감' 글자가 없다면? = 빈자리!
            print("🚨 '예약마감' 글자가 사라졌습니다! (빈자리 포착)")
            return True
        else:
            # 화면 어딘가에 '예약마감'이 한 글자라도 있으면 만실
            print("만실 유지 중 ('예약마감' 글자 있음)")
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
