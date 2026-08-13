from pathlib import Path

WEBHOOK_KEY_FILE = Path(".google_leads_webhook_key")

# שמות שדות אפשריים ב-user_column_data של Google (לא כולם מאומתים מול payload אמיתי עדיין -
# מכוונים לרשימה רחבה בכוונה, ומתאימים בפועל אחרי שרואים lead-בדיקה אמיתי מ-Google Ads)
FULL_NAME_COLUMN_IDS = {"FULL_NAME"}
FIRST_NAME_COLUMN_IDS = {"FIRST_NAME"}
LAST_NAME_COLUMN_IDS = {"LAST_NAME"}
PHONE_COLUMN_IDS = {"PHONE_NUMBER", "PHONE"}


def load_webhook_key():
    if not WEBHOOK_KEY_FILE.exists():
        return None
    key = WEBHOOK_KEY_FILE.read_text().strip()
    return key or None


def _column_value(item):
    return (item.get("string_value") or item.get("column_value") or "").strip()


# שולפת שם וטלפון מתוך user_column_data של Google Lead Form webhook.
# מחזירה גם את הרשימה הגולמית (לצורך לוג/דיבוג בפעם הראשונה שמחברים ל-Google בפועל)
def extract_lead_fields(payload):
    full_name = ""
    first_name = ""
    last_name = ""
    phone = ""

    for item in payload.get("user_column_data") or []:
        column_id = (item.get("column_id") or "").strip().upper()
        value = _column_value(item)
        if not value:
            continue
        if column_id in FULL_NAME_COLUMN_IDS:
            full_name = value
        elif column_id in FIRST_NAME_COLUMN_IDS:
            first_name = value
        elif column_id in LAST_NAME_COLUMN_IDS:
            last_name = value
        elif column_id in PHONE_COLUMN_IDS:
            phone = value

    if not full_name:
        full_name = f"{first_name} {last_name}".strip()

    return full_name, phone
