import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path

import requests

from atlas.paths import secret

GRAPH_API_VERSION = "v21.0"


# תצורה של בוט וואטסאפ בודד (מספר טלפון + סט קבצי סוד משלו) - כדי שאפשר יהיה
# להריץ כמה בוטים על אותו קוד (הבוט הפנימי לבעל העסק, ובעתיד בוט ללקוחות על
# מספר נפרד), בלי לשכפל את כל הלוגיקה הזו
@dataclass(frozen=True)
class WhatsAppBotConfig:
    verify_token_file: Path
    app_secret_file: Path
    access_token_file: Path
    phone_number_id: str


ADMIN_BOT = WhatsAppBotConfig(
    verify_token_file=secret(".whatsapp_verify_token"),
    app_secret_file=secret(".whatsapp_app_secret"),
    access_token_file=secret(".whatsapp_access_token"),
    phone_number_id="986207831253626",
)


def _read_local_file(path):
    if not path.exists():
        return None
    value = path.read_text().strip()
    return value or None


def load_verify_token(config):
    return _read_local_file(config.verify_token_file)


def load_app_secret(config):
    return _read_local_file(config.app_secret_file)


def load_access_token(config):
    return _read_local_file(config.access_token_file)


def verify_signature(config, raw_body, signature_header):
    app_secret = load_app_secret(config)
    if not app_secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, provided)


def send_text_message(config, to, body):
    access_token = load_access_token(config)
    if not access_token:
        return None
    response = requests.post(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{config.phone_number_id}/messages",
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


# מפענחת הודעה נכנסת אחת מ-payload של webhook, מכל סוג (לא רק טקסט) - כדי שאפשר
# יהיה להבחין בין "אין הודעה בכלל" (למשל התראת סטטוס משלוח) לבין "הודעה שהגיעה
# אבל היא לא טקסט" (הודעה קולית/תמונה/מדבקה), ולהגיב לכל אחד מהם אחרת
def extract_incoming_event(payload):
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for message in value.get("messages") or []:
                from_number = message.get("from", "")
                if not from_number:
                    continue
                message_id = message.get("id", "")
                message_type = message.get("type", "")
                if message_type == "text":
                    text = (message.get("text") or {}).get("body", "")
                    if text:
                        return from_number, message_id, "text", text
                return from_number, message_id, message_type or "unknown", None
    return None, None, None, None


# תאימות לאחור לקוד קיים שקורא רק להודעות טקסט (הבוט הפנימי) - עוטפת את
# extract_incoming_event ומתעלמת משאר סוגי ההודעות, בדיוק כמו ההתנהגות הקודמת
def extract_incoming_message(payload):
    from_number, _message_id, message_type, text = extract_incoming_event(payload)
    if message_type == "text" and from_number and text:
        return from_number, text
    return None, None


# רשימת מספרי טלפון מורשים לשוחח עם הבוט - קובץ טקסט, מספר בכל שורה (עם קידומת מדינה,
# בלי +, כמו שוואטסאפ שולחת אותם ב-webhook). אם הקובץ לא קיים/ריק, אף אחד לא מורשה
# (ברירת מחדל בטוחה - לא נענה לכל מי שכותב לעסק)
def load_allowed_numbers():
    raw = _read_local_file(secret(".whatsapp_allowed_numbers"))
    if not raw:
        return set()
    return {line.strip() for line in raw.splitlines() if line.strip()}
