import websocket
import json
import time
import ssl
from playwright.sync_api import sync_playwright
from database import *

# Load Config
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
processed_matches = set()

def fetch_and_save_via_browser(match_id):
    """Intercepts the JSON payload in RAM and ships it to the database."""
    if not EMAIL or not PASSWORD:
        print("[BROWSER-ERROR] Email or password missing in config.json!")
        return

    print(f"\n[BROWSER] Launching invisible browser for Match {match_id}...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            page.goto("https://play.autodarts.io/")
            page.wait_for_timeout(2000)
            
            page.fill('input[type="email"], input[name="username"]', EMAIL)
            page.fill('input[type="password"], input[name="password"]', PASSWORD)
            
            print("[BROWSER] Submitted credentials. Logging in...")
            page.keyboard.press("Enter")
            
            page.wait_for_url("https://play.autodarts.io/**", timeout=15000)
            print("[BROWSER] Login successful! Deploying dragnet wiretap...")
            
            history_url = f"https://play.autodarts.io/history/matches/{match_id}"
            captured_data = []

            # THE WIRETAP: Catch the JSON in RAM
            def intercept_response(response):
                if match_id in response.url and response.status in [200, 304]:
                    try:
                        data = response.json()
                        if isinstance(data, dict) and "games" in data:
                            captured_data.append(data)
                    except Exception:
                        pass 

            page.on("response", intercept_response)
            
            # Go to history page to trigger the network request
            page.goto(history_url)
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(2000) 
            
            if captured_data:
                print("[BROWSER] BINGO! Intercepted pristine match JSON in RAM.")
                match_data = captured_data[0]
                
                # Hand it directly to the DB without saving a file!
                save_pristine_match(match_data)
            else:
                print("[BROWSER-ERROR] Failed to intercept the JSON payload.")
            
            browser.close()

    except Exception as e:
        print(f"[BROWSER-ERROR] Browser automation failed: {e}")

def on_message(ws, message):
    global current_match_id
    global processed_matches
    
    if message == "2": ws.send("3"); return
    if message.startswith("0"): ws.send("40"); return
    if not message.startswith("42"): return
    
    try:
        payload = json.loads(message[2:])
        if payload[0] != "message": return
        
        data = payload[1]
        event_type = data.get("event")
        
        found_id = data.get("matchId") or data.get("id") or data.get("game", {}).get("id") or data.get("game", {}).get("matchId")
        if found_id:
            current_match_id = found_id
        
        if event_type in ["match-won", "match-ended", "match-aborted"]:
            if current_match_id in processed_matches:
                return

            print(f"\n==================================================")
            print(f"[EVENT] MATCH TERMINATED: {event_type.upper()}")
            print(f"==================================================")
            
            if not current_match_id:
                print("[WARNING] Match ID not found in cache. Cannot fetch data.")
                return
                
            print(f"[SYSTEM] Holding for 5 seconds to let Autodarts finalize the math...")
            time.sleep(5)
            
            fetch_and_save_via_browser(current_match_id)
            
            processed_matches.add(current_match_id)
            print("\n[NETWORK] Returning to standby mode. Waiting for next match...")

    except Exception as e:
        pass

def connect():
    socket_url = WS_URL if "socket.io" in WS_URL else f"{WS_URL.rstrip('/')}/socket.io/?EIO=4&transport=websocket"
    print(f"[NETWORK] Attempting to connect to {socket_url} ...")
    ws = websocket.WebSocketApp(
        socket_url,
        on_message=on_message,
        on_open=lambda ws: print("[NETWORK] Connected! Waiting for matches to end...")
    )
    ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

if __name__ == "__main__":
    while True:
        try:
            connect()
        except KeyboardInterrupt:
            break
        except Exception:
            pass
        time.sleep(5)