import os
import requests
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# 1. 텔레그램 세팅 (깃허브 환경변수에서 토큰을 안전하게 불러옵니다)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = "652517175"

# 2. 타겟 URL (5월 2일~3일, 4인 가족 비토애글램핑 산청점)
TARGET_URL = "https://m.place.naver.com/accommodation/1259756405/room?entry=pll&bk_query=%EB%B9%84%ED%86%A0%EC%95%A0%20%EC%82%B0%EC%B2%AD&businessCategory=pension&level=top&guest=4&checkin=20260502&checkout=20260503"

def send_telegram_msg(message):
    """텔레그램 메시지 발송 함수"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"텔레그램 발송 실패: {e}")

def check_naver_reservation():
    """네이버 예약 페이지 크롤링"""
    # 깃허브 클라우드(리눅스) 환경에 맞춘 크롬 옵션 설정
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36')
    
    driver = webdriver.Chrome(options=options)
    
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 예약 상태 확인 시작...")
        driver.get(TARGET_URL)
        
        # 동적 데이터 로딩 대기
        time.sleep(5) 
        
        # 전체 텍스트 가져오기
        page_text = driver.find_element(By.TAG_NAME, 'body').text
        
        # 예약 가능 여부 판단
        if "예약마감" in page_text:
            if "객실 선택" in page_text or "잔여" in page_text: 
                msg = f"🚨 [빈자리 포착] 비토애글램핑 5/2 일정에 빈자리가 발생한 것 같습니다!\n\n바로 접속하세요:\n{TARGET_URL}"
                send_telegram_msg(msg)
                print("빈자리 알림 전송 완료 (일부 예약마감, 일부 잔여)!")
            else:
                print("현재 전 객실 예약 마감 상태입니다.")
        else:
            msg = f"🚨 [빈자리 포착] 비토애글램핑 예약 가능 상태입니다!\n\n바로 접속하세요:\n{TARGET_URL}"
            send_telegram_msg(msg)
            print("빈자리 알림 전송 완료 (전체 예약 가능)!")
            
    except Exception as e:
        print(f"크롤링 에러 발생: {e}")
        
    finally:
        driver.quit()

if __name__ == "__main__":
    check_naver_reservation()
