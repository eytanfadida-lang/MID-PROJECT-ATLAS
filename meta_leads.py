import hashlib
import hmac
import json
import time
from datetime import datetime
from pathlib import Path

import requests

VERIFY_TOKEN_FILE = Path(".meta_verify_token")
APP_SECRET_FILE = Path(".meta_app_secret")
PAGE_ACCESS_TOKEN_FILE = Path(".meta_page_access_token")
POLL_TOKEN_FILE = Path(".meta_poll_token")
LAST_POLL_FILE = Path(".meta_last_poll_time")
PROCESSED_LEADS_FILE = Path(".meta_processed_leads.json")

GRAPH_API_VERSION = "v21.0"
PAGE_ID = "725716050843235"


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


def load_poll_token():
    return _read_local_file(POLL_TOKEN_FILE)


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


def load_last_poll_time():
    if not LAST_POLL_FILE.exists():
        # בהרצה ראשונה לא רוצים לייבא היסטוריה ישנה - רק מהיום האחרון
        return int(time.time()) - 86400
    try:
        return int(LAST_POLL_FILE.read_text().strip())
    except ValueError:
        return int(time.time()) - 86400


def save_last_poll_time(timestamp):
    LAST_POLL_FILE.write_text(str(timestamp))


def load_processed_lead_ids():
    if not PROCESSED_LEADS_FILE.exists():
        return set()
    try:
        return set(json.loads(PROCESSED_LEADS_FILE.read_text()))
    except (ValueError, json.JSONDecodeError):
        return set()


def save_processed_lead_ids(lead_ids):
    PROCESSED_LEADS_FILE.write_text(json.dumps(list(lead_ids)))


def list_page_forms():
    access_token = load_page_access_token()
    if not access_token:
        return []
    response = requests.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PAGE_ID}/leadgen_forms",
        params={"access_token": access_token, "limit": 100},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("data", [])


def list_leads_since(form_id, since_timestamp):
    access_token = load_page_access_token()
    if not access_token:
        return []
    response = requests.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{form_id}/leads",
        params={"access_token": access_token, "since": since_timestamp, "limit": 100},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("data", [])


def _parse_created_time(value):
    try:
        return int(datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").timestamp())
    except (ValueError, TypeError):
        return None


# חלופה ל-webhook בזמן אמת של מטא (שלא הצליח לספק לנו נתונים בפועל, למרות שכל ההגדרות תקינות) -
# עוברת על כל טפסי הלידים של הדף ומייבאת לידים חדשים שנוצרו מאז הבדיקה הקודמת. שומרת גם רשימת
# leadgen_id שכבר טופלו, כדי למנוע כפילות גם אם יש חפיפה בין שני ריצות פולינג עוקבות
def poll_new_leads(repos, channels):
    since_timestamp = load_last_poll_time()
    processed_ids = load_processed_lead_ids()
    newest_created_time = since_timestamp

    statuses = repos.lead_statuses.get_names()
    created_count = 0

    forms = list_page_forms()
    for form in forms:
        form_id = form.get("id")
        if not form_id:
            continue

        for lead_data in list_leads_since(form_id, since_timestamp):
            lead_id = lead_data.get("id")
            if not lead_id or lead_id in processed_ids:
                continue
            processed_ids.add(lead_id)

            created_ts = _parse_created_time(lead_data.get("created_time", ""))
            if created_ts:
                newest_created_time = max(newest_created_time, created_ts)

            full_name, phone, email = extract_lead_fields(lead_data)
            if not phone:
                continue

            lead = {
                "full_name": full_name or "ליד ממטא",
                "phone": phone,
                "status": statuses[0] if statuses else "",
                "channel": "פייסבוק" if "פייסבוק" in channels else channels[0],
                "assigned_user": "",
                "notes": f"אימייל: {email}" if email else "",
            }
            repos.leads.create(lead)
            created_count += 1

    save_last_poll_time(newest_created_time + 1)
    save_processed_lead_ids(processed_ids)
    return {"status": "ok", "created": created_count, "forms_checked": len(forms)}
