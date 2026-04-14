import websocket
import json
import time
import ssl
import re
import sqlite3
import threading
from playwright.sync_api import sync_playwright
from database import *

print("[SYSTEM] Starting Autodarts Playwright Pipeline...")
try:
    with open("config.json", "r") as f:
        config = json.load(f)
    WS_URL = config.get("websocket", "wss://localhost:8079/socket.io/?EIO=4&transport=websocket")
    EMAIL = config.get("autodarts_email", "")
    PASSWORD = config.get("autodarts_password", "")
except Exception as e:
    print(f"[SYSTEM-ERROR] Failed to load config.json: {e}")
    exit(1)

init_db()

current_match_id = None
processed_timestamps = {}
debounce_lock = threading.Lock()
DEBOUNCE_SECONDS = 15

def is_match_already_saved(match_id):
    try:
        conn = sqlite3.connect("dartstats.db")
        c = conn.cursor()
        c.execute("SELECT 1 FROM matches WHERE id = ?", (match_id,))
        exists = c.fetchone() is not None
        conn.close()
        return exists
    except Exception:
        return False

def fetch_and_save_via_browser(match_id):
    if not EMAIL or not PASSWORD:
        print("[BROWSER-ERROR] Missing credentials.")
        return

    print(f"\n[BROWSER] Launching invisible browser for Match {match_id}...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            page.goto("https://play.autodarts.io/")
            page.wait_for_timeout(2000)
            page.fill('input[type="email"], input[name="username"]', EMAIL)
            page.fill('input[type="password"], input[name="password"]', PASSWORD)
            page.keyboard.press("Enter")
            page.wait_for_url("https://play.autodarts.io/**", timeout=15000)
            
            captured_data = []

            def intercept_response(response):
                if match_id in response.url and response.status in [200, 304]:
                    try:
                        data = response.json()
                        if isinstance(data, dict) and "games" in data:
                            captured_data.append(data)
                    except Exception:
                        pass 

            page.on("response", intercept_response)
            page.goto(f"https://play.autodarts.io/history/matches/{match_id}")
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(2500) 
            
            if captured_data:
                save_pristine_match(captured_data[0])
                print(f"[DB] Successfully vaulted Match {match_id}!")
            else:
                print("[BROWSER-ERROR] Failed to intercept JSON payload.")
            
            browser.close()
    except Exception as e:
        print(f"[BROWSER-ERROR] {e}")

def process_match_event(match_id):
    try:
        if is_match_already_saved(match_id):
            print(f"[DB-CHECK] Match {match_id} already exists. Skipping.")
            return
            
        print(f"[SYSTEM] Holding 2 seconds for Autodarts math...")
        time.sleep(2)
        fetch_and_save_via_browser(match_id)
    finally:
        print("\n[NETWORK] Standby mode. Waiting for next match...")

def on_message(ws, message):
    global current_match_id
    
    if message == "2": ws.send("3"); return
    if message.startswith("0"): ws.send("40"); return
    if not message.startswith("42"): return
    
    try:
        payload = json.loads(message[2:])
        if not payload: return
        
        data = payload[1] if len(payload) > 1 else {}
        event_type = data.get("event", "") if isinstance(data, dict) else payload[0]
        if not isinstance(data, dict): data = {}

        found_id = (
            data.get("matchId") or data.get("id") or data.get("gameId") or 
            data.get("game", {}).get("id") or data.get("state", {}).get("id")
        )
        if found_id: current_match_id = found_id
        
        if event_type.lower() in ["match-ended", "match-aborted"]:
            target_id = current_match_id
            
            if not target_id:
                fallback = re.search(r'"matchId"\s*:\s*"([a-f0-9\-]{36})"', message)
                if fallback:
                    target_id = fallback.group(1)
                else:
                    return

            with debounce_lock:
                current_time = time.time()
                if target_id in processed_timestamps:
                    if (current_time - processed_timestamps[target_id]) < DEBOUNCE_SECONDS:
                        return  # Silently drop duplicates
                processed_timestamps[target_id] = current_time

            print(f"\n==================================================")
            print(f"[EVENT] FINAL MATCH STATE: {event_type.upper()}")
            print(f"==================================================")
            
            threading.Thread(target=process_match_event, args=(target_id,)).start()

    except Exception:
        pass

def connect():
    url = WS_URL if "socket.io" in WS_URL else f"{WS_URL.rstrip('/')}/socket.io/?EIO=4&transport=websocket"
    print(f"[NETWORK] Connecting to {url} ...")
    ws = websocket.WebSocketApp(url, on_message=on_message, on_open=lambda ws: print("[NETWORK] Connected!"))
    ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

if __name__ == "__main__":
    while True:
        try: connect()
        except KeyboardInterrupt: break
        except Exception: pass
        time.sleep(5)