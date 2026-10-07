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

CUSTOMER_BOT = WhatsAppBotConfig(
    verify_token_file=secret(".whatsapp_customer_verify_token"),
    app_secret_file=secret(".whatsapp_customer_app_secret"),
    access_token_file=secret(".whatsapp_customer_access_token"),
    phone_number_id="1220667597806529",
)

# כמה מספרים רשמיים יכולים לחלוק את אותה אפליקציה/WABA (ראו extract_metadata_phone_number_id) -
# המיפוי הזה הוא רק לתצוגה באדמין (עמוד שיחות בוט הלקוחות), כדי לדעת דרך איזה מספר
# התנהלה כל שיחה. לא משפיע על לוגיקת השליחה/קבלה בפועל
CUSTOMER_BOT_NUMBER_LABELS = {
    "1220667597806529": "+1 808-309-7433",
    "413443605196685": "+972 50-306-6767",
}


def describe_phone_number_id(phone_number_id):
    return CUSTOMER_BOT_NUMBER_LABELS.get(phone_number_id, phone_number_id or "לא ידוע")


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


# phone_number_id אופציונלי דורס את זה שב-config - נחוץ כשלאותה אפליקציה/WABA מחוברים
# כמה מספרים (ראו extract_metadata_phone_number_id), כדי שהתגובה תישלח מאותו מספר
# שהלקוח כתב אליו, לא תמיד מהמספר ה"ברירת מחדל" שקבוע ב-config
def send_text_message(config, to, body, phone_number_id=None):
    access_token = load_access_token(config)
    if not access_token:
        return None
    target_phone_number_id = phone_number_id or config.phone_number_id
    response = requests.post(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{target_phone_number_id}/messages",
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


# מעלה קובץ (תמונה/מסמך) לשרתי Meta ומחזירה media_id - שלב מקדים הכרחי לפני שליחת
# הודעת מדיה, לפי ה-Cloud API (לא ניתן לשלוח בייטים ישירות בהודעה עצמה)
def upload_media(config, file_bytes, filename, mime_type, phone_number_id=None):
    access_token = load_access_token(config)
    if not access_token:
        return None
    target_phone_number_id = phone_number_id or config.phone_number_id
    response = requests.post(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{target_phone_number_id}/media",
        headers={"Authorization": f"Bearer {access_token}"},
        data={"messaging_product": "whatsapp"},
        files={"file": (filename, file_bytes, mime_type)},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["id"]


# שולחת הודעת מדיה (תמונה/מסמך) שכבר הועלתה (media_id מ-upload_media). media_type
# הוא "image" או "document" - קובע גם את שם המפתח בגוף הבקשה (ככה ה-API של מטא דורש)
def send_media_message(config, to, media_id, media_type, phone_number_id=None, caption=None):
    access_token = load_access_token(config)
    if not access_token:
        return None
    target_phone_number_id = phone_number_id or config.phone_number_id
    media_payload = {"id": media_id}
    if caption:
        media_payload["caption"] = caption
    response = requests.post(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{target_phone_number_id}/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": media_type,
            media_type: media_payload,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


# שולחת הודעת תבנית (template) מאושרת מראש - בניגוד להודעת טקסט חופשית, זו יכולה
# להגיע גם מחוץ לחלון 24 השעות מההודעה האחרונה של הנמען (למשל התראה יזומה לבעלים
# שלא בהכרח כתבה לבוט לאחרונה). body_params הן רשימת המחרוזות שממלאות את ה-{{1}},
# {{2}} וכו' בגוף התבנית, לפי הסדר שבו הוגדרו כשהתבנית נוצרה ב-WhatsApp Manager
def send_template_message(config, to, template_name, language_code, body_params=None, phone_number_id=None):
    access_token = load_access_token(config)
    if not access_token:
        return None
    target_phone_number_id = phone_number_id or config.phone_number_id
    template_payload = {"name": template_name, "language": {"code": language_code}}
    if body_params:
        template_payload["components"] = [{
            "type": "body",
            "parameters": [{"type": "text", "text": value} for value in body_params],
        }]
    response = requests.post(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{target_phone_number_id}/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": template_payload,
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
                if message_type == "document":
                    document = message.get("document") or {}
                    return from_number, message_id, "document", {
                        "media_id": document.get("id"),
                        "filename": document.get("filename") or "מסמך",
                        "mime_type": document.get("mime_type") or "application/octet-stream",
                    }
                if message_type in ("image", "video"):
                    media = message.get(message_type) or {}
                    return from_number, message_id, message_type, {
                        "media_id": media.get("id"),
                        "caption": media.get("caption") or "",
                        "mime_type": media.get("mime_type") or "application/octet-stream",
                    }
                return from_number, message_id, message_type or "unknown", None
    return None, None, None, None


# מחלצת את השם שהלקוח הגדיר לעצמו בוואטסאפ (שם הפרופיל שלו) - לא בהכרח שמו האמיתי,
# אבל שימושי לפנייה אישית ("הי דנה!") עוד לפני שהוא הציג את עצמו בשיחה בפועל
def extract_sender_profile_name(payload):
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for contact in value.get("contacts") or []:
                name = (contact.get("profile") or {}).get("name")
                if name:
                    return name
    return None


# מורידה קובץ שהתקבל בהודעה נכנסת (למשל קורות חיים) - שלב כפול לפי ה-Cloud API:
# קודם שליפת כתובת זמנית לפי media_id, ואז הורדת הבייטים עצמם מאותה כתובת
def download_media(config, media_id):
    access_token = load_access_token(config)
    if not access_token:
        return None, None
    meta_response = requests.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{media_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    meta_response.raise_for_status()
    media_info = meta_response.json()
    file_response = requests.get(
        media_info["url"], headers={"Authorization": f"Bearer {access_token}"}, timeout=60
    )
    file_response.raise_for_status()
    return file_response.content, media_info.get("mime_type", "application/octet-stream")


# מחלצת את phone_number_id של המספר שהלקוח כתב אליו (לא ממי שהוא כתב) - כדי לתמוך
# בכמה מספרים תחת אותה אפליקציה/WABA (ראו §multi-number). נחוץ כדי לדעת מאיזה מספר
# לענות - config.phone_number_id הוא רק ברירת מחדל, לא בהכרח המספר הנכון יותר מהיום
def extract_metadata_phone_number_id(payload):
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            phone_number_id = metadata.get("phone_number_id")
            if phone_number_id:
                return phone_number_id
    return None


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
