import hashlib
import hmac
from pathlib import Path

import requests

VERIFY_TOKEN_FILE = Path(".meta_verify_token")
APP_SECRET_FILE = Path(".meta_app_secret")
PAGE_ACCESS_TOKEN_FILE = Path(".meta_page_access_token")

GRAPH_API_VERSION = "v21.0"


def _read_local_file(path):
    if not path.exists():
        return None
    value = path.read_text().strip()
    return value or None


def load_verify_token():
    return _read_local_file(VERIFY_TOKEN_FILE)


def load_app_secret():
    return _read_local_file(APP_SECRET_FILE)


def load_page_access_token():
    return _read_local_file(PAGE_ACCESS_TOKEN_FILE)


# מאמתת את חתימת ה-webhook (Meta חותמת כל POST עם X-Hub-Signature-256 לפי ה-App Secret,
# בניגוד לשאר האינטגרציות שלנו שמשתמשות בטוקן פשוט ב-URL - כאן ככה מטא בנתה את זה)
def verify_signature(raw_body, signature_header):
    app_secret = load_app_secret()
    if not app_secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, provided)


# ה-webhook notification מכיל רק leadgen_id, לא את הנתונים עצמם - צריך קריאה נפרדת
# ל-Graph API עם Page Access Token כדי לקבל את השם/טלפון בפועל
def fetch_lead_data(leadgen_id):
    access_token = load_page_access_token()
    if not access_token:
        return None
    response = requests.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{leadgen_id}",
        params={"access_token": access_token},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def extract_lead_fields(lead_data):
    values = {}
    for field in lead_data.get("field_data") or []:
        name = (field.get("name") or "").strip().lower()
        field_values = field.get("values") or []
        values[name] = field_values[0] if field_values else ""

    full_name = values.get("full_name") or f"{values.get('first_name', '')} {values.get('last_name', '')}".strip()
    phone = values.get("phone_number") or values.get("phone") or ""
    email = values.get("email") or ""
    return full_name.strip(), phone.strip(), email.strip()
