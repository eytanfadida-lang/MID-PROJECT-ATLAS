import base64
import binascii
import datetime
import re

from atlas.services.phone_utils import normalize_phone, to_whatsapp_format

# שיחות וואטסאפ דרך חשבון "לא רשמי" (מכשיר מקושר, ראו gateway/). ביומן ההודעות (customer_bot_messages) הן נרשמות
# באותה טבלה כמו שיחות המספרים הרשמיים, והמספר שלנו (bot_phone_number_id) הוא "linked:<מזהה החשבון>" - כך אותו
# עמוד שיחות, אותן התראות ואותו מונה "לא נקראו" עובדים בלי שינוי, ותשובה ידנית יוצאת מאותו חשבון
LINKED_PREFIX = "linked:"

MAX_BODY_LENGTH = 4000
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MIN_PHONE_DIGITS = 7
MAX_PHONE_DIGITS = 15
RECEIPT_STATUSES = ("sent", "delivered", "read", "failed")

_EXTENSION_BY_MIME = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
    "video/mp4": ".mp4", "video/3gpp": ".3gp",
    "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/aac": ".aac", "audio/amr": ".amr",
    "application/pdf": ".pdf",
}


def bot_id(account_id):
    return f"{LINKED_PREFIX}{int(account_id)}"


def account_id_of(bot_phone_number_id):
    """מזהה החשבון המקושר מתוך bot_phone_number_id, או None אם זה מספר רשמי."""
    if bot_phone_number_id and str(bot_phone_number_id).startswith(LINKED_PREFIX):
        try:
            return int(str(bot_phone_number_id)[len(LINKED_PREFIX):])
        except ValueError:
            return None
    return None


def phone_key(digits):
    """המפתח של השיחה: מספר ישראלי בצורה המקומית (0501234567) כמו בשאר המערכת, ומספר זר - הספרות כמו שהן."""
    digits = re.sub(r"\D", "", str(digits or ""))
    return normalize_phone(digits) or digits


def send_digits(phone):
    """הספרות שאליהן שולחים בוואטסאפ עבור מפתח שיחה (ישראלי: 9725...; זר: כמו שנשמר)."""
    return to_whatsapp_format(phone) or re.sub(r"\D", "", str(phone or ""))


def label_for(repos, bot_phone_number_id):
    """שם להצגה של חשבון מקושר (למשל 'מספר משני · +972501234567'), או None אם זה לא חשבון מקושר."""
    account_id = account_id_of(bot_phone_number_id)
    if account_id is None:
        return None
    account = repos.linked_whatsapp.get(account_id)
    if account is None:
        return "חשבון שנמחק"
    return f"{account['label']} · +{account['phone']}" if account["phone"] else account["label"]


def _to_local_iso(timestamp):
    try:
        value = datetime.datetime.fromtimestamp(float(timestamp))
        if abs((datetime.datetime.now() - value).total_seconds()) > 60 * 60 * 24 * 400:
            raise ValueError
        return value.isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return datetime.datetime.now().isoformat(timespec="seconds")


def _save_attachment(key, attachment):
    """שומרת קובץ שהגיע מהתהליך תחת static/uploads (כמו קבצים מהלקוחות ברשמי). מחזירה כתובת, או None אם לא תקין."""
    if not isinstance(attachment, dict) or not attachment.get("data"):
        return None
    try:
        data = base64.b64decode(attachment["data"], validate=True)
    except (binascii.Error, ValueError):
        return None
    if not data or len(data) > MAX_ATTACHMENT_BYTES:
        return None
    mime = str(attachment.get("mime") or "").split(";")[0].strip().lower()
    name = str(attachment.get("name") or "")[:120]
    if "." not in name:
        name = f"{name or 'attachment'}{_EXTENSION_BY_MIME.get(mime, '')}"
    from atlas.web.webhooks import _save_incoming_document  # מיובא כאן כדי להימנע מייבוא מעגלי בעלייה

    return _save_incoming_document(key, name, data)


def ingest(repos, account_id, items):
    """רושמת ביומן הודעות שהתקבלו מהתהליך (נכנסות, או יוצאות שנשלחו מהטלפון עצמו). כפילות (אותו wamid) מדולגת.
    מחזירה (כמה נרשמו, כמה דולגו)."""
    accepted = skipped = 0
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            skipped += 1
            continue
        direction = item.get("direction")
        digits = re.sub(r"\D", "", str(item.get("phone") or ""))
        wamid = str(item.get("wamid") or "")[:128] or None
        if direction not in ("in", "out") or not (MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS):
            skipped += 1
            continue
        if wamid and repos.customer_bot_messages.wamid_exists(wamid):
            skipped += 1
            continue
        key = phone_key(digits)
        attachment_url = _save_attachment(key, item.get("attachment"))
        body = str(item.get("body") or "")[:MAX_BODY_LENGTH]
        if not body and not attachment_url:
            skipped += 1
            continue
        repos.customer_bot_messages.log(
            key, direction, body, bot_id(account_id), attachment_url, wamid=wamid,
            created_at=_to_local_iso(item.get("timestamp")), delivery_status="sent" if direction == "out" else None,
        )
        accepted += 1
    return accepted, skipped


def apply_receipts(repos, updates):
    """עדכוני סטטוס משלוח (נמסרה/נקראה) לפי wamid. הסטטוס רק מתקדם (נקראה לא חוזרת ל"נמסרה")."""
    applied = 0
    for update in updates if isinstance(updates, list) else []:
        if isinstance(update, dict) and update.get("status") in RECEIPT_STATUSES and update.get("wamid"):
            applied += repos.customer_bot_messages.advance_delivery_status(str(update["wamid"])[:128], update["status"])
    return applied


def queue_outgoing(repos, account_id, phone, body, attachment_url=None, attachment_mime=None, attachment_name=None):
    """מכניסה הודעה לתור השליחה של חשבון מקושר, ורושמת אותה ביומן במצב 'ממתינה'.
    מחזירה (True, מזהה ההודעה) או (False, הסבר בעברית)."""
    account = repos.linked_whatsapp.get(account_id)
    if account is None:
        return False, "החשבון המקושר לא נמצא (ייתכן שנמחק)."
    if account["status"] != "connected":
        return False, "החשבון המקושר לא מחובר כרגע. אפשר לחבר אותו מחדש בעמוד האינטגרציות."
    if not repos.linked_whatsapp.is_gateway_online():
        return False, "שירות החיבור לוואטסאפ לא פועל כרגע, ולכן ההודעה לא נשלחה."
    log_body = body or ("[קובץ] " + (attachment_name or "") if attachment_url else "")
    message_id = repos.customer_bot_messages.log(
        phone, "out", log_body, bot_id(account_id), attachment_url, delivery_status="queued"
    )
    repos.linked_whatsapp.enqueue(
        account_id, message_id, send_digits(phone), body or None, attachment_url, attachment_mime, attachment_name
    )
    return True, message_id
