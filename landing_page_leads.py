import re
from pathlib import Path

TOKEN_FILE = Path(".landing_page_token")

# Elementor Pro שולחת form-encoded עם מפתחות בסגנון PHP array, למשל:
# fields[phone][id]=phone, fields[phone][type]=tel, fields[phone][value]=0501234567
# (אומת מול payload אמיתי מטופס חי - זה לא ניחוש)
FIELD_VALUE_RE = re.compile(r"^fields\[([^\]]+)\]\[value\]$")
FIELD_TYPE_RE = re.compile(r"^fields\[([^\]]+)\]\[type\]$")

NAME_IDS = {"name", "full_name", "your-name", "full-name"}
PHONE_IDS = {"phone", "tel", "phone_number", "your-phone"}
PHONE_TYPES = {"tel"}
EMAIL_IDS = {"email", "your-email"}
EMAIL_TYPES = {"email"}
NOTES_IDS = {"message", "notes", "comment", "your-message"}
NOTES_TYPES = {"textarea"}

# מפתחות שטוחים אפשריים (למקרה של טופס/הגדרה אחרת ששולחת JSON פשוט במקום מבנה fields[...])
FLAT_NAME_KEYS = ("name", "full_name", "your-name", "full-name", "שם", "שם מלא")
FLAT_PHONE_KEYS = ("phone", "tel", "phone_number", "your-phone", "טלפון")
FLAT_EMAIL_KEYS = ("email", "your-email", "אימייל")
FLAT_NOTES_KEYS = ("message", "notes", "comment", "your-message", "הערות")


def load_token():
    if not TOKEN_FILE.exists():
        return None
    token = TOKEN_FILE.read_text().strip()
    return token or None


def _parse_elementor_fields(data):
    values_by_id = {}
    types_by_id = {}
    for key, value in data.items():
        match = FIELD_VALUE_RE.match(key)
        if match:
            values_by_id[match.group(1).lower()] = value
            continue
        match = FIELD_TYPE_RE.match(key)
        if match:
            types_by_id[match.group(1).lower()] = value
    return values_by_id, types_by_id


def _find_elementor_value(values_by_id, types_by_id, ids, types):
    for field_id in ids:
        if field_id in values_by_id:
            return values_by_id[field_id]
    for field_id, field_type in types_by_id.items():
        if field_type in types:
            return values_by_id.get(field_id, "")
    return ""


def _first_present(data, keys):
    for key in keys:
        value = data.get(key)
        if value:
            return str(value).strip()
    return ""


# שולפת שם/טלפון/אימייל/הערות מ-payload של טופס Elementor - קודם לפי מבנה ה-fields[...]
# האמיתי של Elementor, ואם לא נמצא כלום נופלת חזרה למפתחות שטוחים (JSON פשוט)
def extract_lead_fields(data):
    values_by_id, types_by_id = _parse_elementor_fields(data)

    if values_by_id:
        full_name = _find_elementor_value(values_by_id, types_by_id, NAME_IDS, set())
        phone = _find_elementor_value(values_by_id, types_by_id, PHONE_IDS, PHONE_TYPES)
        email = _find_elementor_value(values_by_id, types_by_id, EMAIL_IDS, EMAIL_TYPES)
        notes = _find_elementor_value(values_by_id, types_by_id, NOTES_IDS, NOTES_TYPES)
    else:
        full_name = _first_present(data, FLAT_NAME_KEYS)
        phone = _first_present(data, FLAT_PHONE_KEYS)
        email = _first_present(data, FLAT_EMAIL_KEYS)
        notes = _first_present(data, FLAT_NOTES_KEYS)

    return (str(full_name).strip(), str(phone).strip(), str(email).strip(), str(notes).strip())
