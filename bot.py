import os
import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

if not TOKEN or not CHAT_ID:
    raise SystemExit("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en .env")

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": "Prueba OK desde Python", "parse_mode": "HTML"}
r = requests.post(url, json=payload, timeout=12)
print("Status:", r.status_code)
print("Respuesta:", r.text)
