from pathlib import Path

TOKEN_FILE = Path(".landing_page_token")

# שמות שדה אפשריים, לפי סדר עדיפות - Elementor שולח את המפתחות לפי ה-Field ID שהוגדר
# בטופס עצמו, אז זה עשוי להשתנות. מתאימים בפועל אחרי שרואים שליחת בדיקה אמיתית מהטופס
NAME_KEYS = ("name", "full_name", "your-name", "full-name", "שם", "שם מלא")
PHONE_KEYS = ("phone", "tel", "phone_number", "your-phone", "טלפון")
EMAIL_KEYS = ("email", "your-email", "אימייל")
NOTES_KEYS = ("message", "notes", "comment", "your-message", "הערות")


def load_token():
    if not TOKEN_FILE.exists():
        return None
    token = TOKEN_FILE.read_text().strip()
    return token or None


def _first_present(data, keys):
    for key in keys:
        value = data.get(key)
        if value:
            return str(value).strip()
    return ""


# שולפת שם/טלפון/אימייל/הערות מתוך payload של טופס Elementor (JSON או form-encoded,
# תלוי בהגדרת ה-webhook בטופס עצמו)
def extract_lead_fields(data):
    full_name = _first_present(data, NAME_KEYS)
    phone = _first_present(data, PHONE_KEYS)
    email = _first_present(data, EMAIL_KEYS)
    notes = _first_present(data, NOTES_KEYS)
    return full_name, phone, email, notes
