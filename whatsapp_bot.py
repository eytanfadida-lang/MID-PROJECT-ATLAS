import hashlib
import hmac

import requests

from paths import secret

VERIFY_TOKEN_FILE = secret(".whatsapp_verify_token")
APP_SECRET_FILE = secret(".whatsapp_app_secret")
ACCESS_TOKEN_FILE = secret(".whatsapp_access_token")
ALLOWED_NUMBERS_FILE = secret(".whatsapp_allowed_numbers")

GRAPH_API_VERSION = "v21.0"
PHONE_NUMBER_ID = "986207831253626"


def _read_local_file(path):
    if not path.exists():
        return None
    value = path.read_text().strip()
    return value or None


def load_verify_token():
    return _read_local_file(VERIFY_TOKEN_FILE)


def load_app_secret():
    return _read_local_file(APP_SECRET_FILE)


def load_access_token():
    return _read_local_file(ACCESS_TOKEN_FILE)


# רשימת מספרי טלפון מורשים לשוחח עם הבוט - קובץ טקסט, מספר בכל שורה (עם קידומת מדינה,
# בלי +, כמו שוואטסאפ שולחת אותם ב-webhook). אם הקובץ לא קיים/ריק, אף אחד לא מורשה
# (ברירת מחדל בטוחה - לא נענה לכל מי שכותב לעסק)
def load_allowed_numbers():
    raw = _read_local_file(ALLOWED_NUMBERS_FILE)
    if not raw:
        return set()
    return {line.strip() for line in raw.splitlines() if line.strip()}


def verify_signature(raw_body, signature_header):
    app_secret = load_app_secret()
    if not app_secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, provided)


def send_text_message(to, body):
    access_token = load_access_token()
    if not access_token:
        return None
    response = requests.post(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


# מפענחת הודעת טקסט נכנסת אחת מ-payload של webhook. מתעלמת מהתראות אחרות (כמו עדכוני
# סטטוס משלוח - "נשלח"/"נקרא") שגם הן מגיעות לאותו webhook אבל לא מכילות הודעת טקסט
def extract_incoming_message(payload):
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for message in value.get("messages") or []:
                if message.get("type") != "text":
                    continue
                from_number = message.get("from", "")
                text = (message.get("text") or {}).get("body", "")
                if from_number and text:
                    return from_number, text
    return None, None
