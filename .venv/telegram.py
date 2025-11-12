import os, time, requests
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ENABLED = os.getenv("TELEGRAM_ENABLED", "true").lower() == "true"

API_BASE = f"https://api.telegram.org/bot{TOKEN}"

def _habilitado() -> bool:
    return ENABLED and bool(TOKEN) and bool(CHAT_ID)

class Debouncer:
    """Evita spam: solo envía si cambió el payload o pasó el intervalo."""
    def __init__(self, min_interval_sec: float = 20):
        self.min_interval = min_interval_sec
        self._last_payload = None
        self._last_time = 0
    def should_send(self, payload: str) -> bool:
        ahora = time.time()
        cambio = (payload != self._last_payload)
        suficiente = (ahora - self._last_time) >= self.min_interval
        if cambio or suficiente:
            self._last_payload = payload
            self._last_time = ahora
            return True
        return False

def delete_webhook() -> bool:
    if not TOKEN: return False
    try:
        requests.get(f"{API_BASE}/deleteWebhook", timeout=10)
        return True
    except Exception:
        return False

def send_message(text: str, disable_notification: bool = False, reply_markup: Optional[Dict[str, Any]] = None) -> bool:
    if not _habilitado():
        return False
    try:
        payload: Dict[str, Any] = {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": disable_notification
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        r = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=12)
        return r.ok
    except Exception:
        return False

def send_photo(image_path: str, caption: Optional[str] = None, disable_notification: bool = False) -> bool:
    if not _habilitado():
        return False
    try:
        with open(image_path, "rb") as f:
            files = {"photo": f}
            data = {
                "chat_id": CHAT_ID,
                "caption": caption or "",
                "parse_mode": "HTML",
                "disable_notification": disable_notification
            }
            r = requests.post(f"{API_BASE}/sendPhoto", data=data, files=files, timeout=20)
            return r.ok
    except Exception:
        return False

def send_document(file_path: str, caption: Optional[str] = None, disable_notification: bool = False) -> bool:
    if not _habilitado():
        return False
    try:
        with open(file_path, "rb") as f:
            files = {"document": f}
            data = {
                "chat_id": CHAT_ID,
                "caption": caption or "",
                "parse_mode": "HTML",
                "disable_notification": disable_notification
            }
            r = requests.post(f"{API_BASE}/sendDocument", data=data, files=files, timeout=25)
            return r.ok
    except Exception:
        return False
