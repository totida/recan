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
    """새로운 메시지를 읽어 링크 추가/삭제/목록 확인 (디버깅 & 인식률 강화)"""
    # 1. 토큰 누락 방어막
    if not TELEGRAM_TOKEN:
        print("🚨 에러: TELEGRAM_TOKEN이 없습니다! .yml 파일의 env 설정을 확인하세요.")
        return

    offset = db.get("last_update_id", 0) + 1
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}"
    
    try:
        response = requests.get(url).json()
        
        # ⭐️ 2. 봇이 텔레그램에서 무슨 대답을 들었는지 깃허브 로그에 박제 (원인 파악용)
        print(f"--- 텔레그램 서버 응답 확인 ---\n{response}\n-----------------------------")
        
        if response.get("ok") and response.get("result"):
            for update in response["result"]:
                db["last_update_id"] = update["update_id"]
                message = update.get("message", {})
                text = message.get("text", "").strip()
                chat_id = str(message.get("chat", {}).get("id", ""))
                
                # ⭐️ 3. 메시지 중간에 링크가 섞여 있어도 찰떡같이 찾아내는 로직
                if "http" in text:
                    # 띄어쓰기를 기준으로 쪼개서 진짜 링크만 쏙 뽑아냅니다.
                    target_url = next((word for word in text.split() if word.startswith("http")), None)
                    
                    if target_url:
                        if chat_id not in db["users"]:
                            db["users"][chat_id] = []
                        
                        existing_urls = [item['url'] for item in db["users"][chat_id]]
                        if target_url not in existing_urls:
                            db["users"][chat_id].append({"url": target_url, "last_notified": 0})
                            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                          data={"chat_id": chat_id, "text": "✅ 알림 등록 완료! (빈자리 발생 시 1시간 간격으로 알려드려요)"})
                
                elif text in ["삭제", "초기화"]:
                    db["users"][chat_id] = []
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                  data={"chat_id": chat_id, "text": "🗑️ 모든 알림이 삭제되었습니다."})
                
                elif text == "목록":
                    items = db.get("users", {}).get(chat_id, [])
                    if items:
                        msg = "\n\n".join([f"{i+1}. {item['url']}" for i, item in enumerate(items)])
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                      data={"chat_id": chat_id, "text": f"📋 감시 중인 목록:\n\n{msg}"})
                    else:
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                      data={"chat_id": chat_id, "text": "등록된 링크가 없습니다."})
            save_db(db)
    except Exception as e:
        print(f"메시지 동기화 에러: {e}")

def check_vacancy(target_url):
    """'예약마감' 글자가 사라졌는지 확인하는 모바일 위장 로직"""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=390,844')
    options.add_argument('--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1')
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(target_url)
        time.sleep(7)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        
        page_text = driver.find_element(By.TAG_NAME, 'body').text
        if len(page_text) < 100 or "네이버" not in page_text:
            return False
            
        # '예약마감' 글자가 없으면 자리가 난 것으로 판단
        return "예약마감" not in page_text
                
    except Exception:
        return False
    finally:
        driver.quit()

def run_multi_scrapers(db):
    """1시간 간격 재알림 실행 로직"""
    current_time = time.time()
    updated = False

    for chat_id, items in db.get("users", {}).items():
        for item in items:
            # 기존 데이터가 구버전(문자열)인 경우를 대비한 안전장치
            if isinstance(item, str): continue 
            
            target_url = item['url']
            last_notified = item['last_notified']
            
            if check_vacancy(target_url):
                # 마지막 알림 후 1시간(3600초) 지났는지 체크
                if current_time - last_notified >= 3600:
                    msg = f"🚨 [빈자리 포착] 예약마감 해제!\n{target_url}"
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                  data={"chat_id": chat_id, "text": msg})
                    item['last_notified'] = current_time
                    updated = True
    
    if updated:
        save_db(db)

if __name__ == "__main__":
    current_db = load_db()
    sync_telegram_requests(current_db)
    run_multi_scrapers(current_db)
