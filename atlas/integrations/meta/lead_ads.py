import hashlib
import hmac
import json
import time
from datetime import datetime

import requests

from atlas.paths import secret
from atlas.services.phone_utils import normalize_phone

VERIFY_TOKEN_FILE = secret(".meta_verify_token")
APP_SECRET_FILE = secret(".meta_app_secret")
PAGE_ACCESS_TOKEN_FILE = secret(".meta_page_access_token")
POLL_TOKEN_FILE = secret(".meta_poll_token")
LAST_POLL_FILE = secret(".meta_last_poll_time")
PROCESSED_LEADS_FILE = secret(".meta_processed_leads.json")
LAST_RESULT_FILE = secret(".meta_last_poll_result.json")

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


KNOWN_FIELD_NAMES = {"full_name", "first_name", "last_name", "phone_number", "phone", "email"}

# שם שדה שמרמז שזו שאלת טלפון בטופס מותאם אישית (למשל "מה_מספר_הוואטסאפ_שלך?") - מטא שומרת את התווית
# שהוגדרה בטופס כשם השדה, ולכן טופס חדש עם ניסוח אחר היה גורם לליד להישמט בלי טלפון
PHONE_NAME_HINTS = ("phone", "טלפון", "נייד", "פלאפון", "whatsapp", "וואטסאפ", "ווצאפ", "וואצאפ", "mobile", "tel")


def _looks_like_phone(value):
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    other = [ch for ch in str(value).strip() if not (ch.isdigit() or ch in "+-() ")]
    return 9 <= len(digits) <= 15 and not other


# מחזירה (טלפון, שם השדה שממנו נלקח): קודם השדות הסטנדרטיים, אחר כך שדה ששמו מרמז על טלפון,
# ובסוף כל שדה שהערך שלו נראה כמו מספר טלפון
def find_phone(values, order=None):
    for name in ("phone_number", "phone"):
        if values.get(name):
            return values[name], name
    names = order or list(values)
    for name in names:
        if values.get(name) and any(hint in name for hint in PHONE_NAME_HINTS):
            return values[name], name
    for name in names:
        if name != "email" and values.get(name) and _looks_like_phone(values[name]):
            return values[name], name
    return "", None


# מטא שולחת גם שדות "שאלה מותאמת אישית" שהוגדרו בטופס עצמו (מעבר לשם/טלפון/אימייל) -
# אין לנו דרך לדעת מראש את שמות השדות האלה, אז כל שדה שלא מזוהה כאחד השדות הידועים
# נחשב "שאלה נוספת" ומוחזר בנפרד כדי שנוכל לשים אותו בהערות של הליד
def extract_lead_fields(lead_data):
    values = {}
    order = []
    for field in lead_data.get("field_data") or []:
        name = (field.get("name") or "").strip().lower()
        field_values = field.get("values") or []
        values[name] = field_values[0] if field_values else ""
        order.append(name)

    full_name = values.get("full_name") or f"{values.get('first_name', '')} {values.get('last_name', '')}".strip()
    phone, phone_field = find_phone(values, order)
    email = values.get("email") or ""

    skipped = KNOWN_FIELD_NAMES | {phone_field}
    extra_answers = "\n".join(
        f"{name}: {values[name]}" for name in order if name not in skipped and values.get(name)
    )

    return full_name.strip(), phone.strip(), email.strip(), extra_answers.strip()


def lead_field_names(lead_data):
    return [(f.get("name") or "").strip() for f in (lead_data.get("field_data") or [])]


def build_notes(email, extra_answers):
    parts = []
    if email:
        parts.append(f"אימייל: {email}")
    if extra_answers:
        parts.append(extra_answers)
    return "\n".join(parts)


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


# מעבירה על כל העמודים של תשובת Graph (paging.next) - בלי זה רק 100 הפריטים הראשונים נקראים, ובדף עם
# הרבה טפסים ישנים (כל קמפיין משוכפל יוצר טופס) טופס חדש עלול לא להגיע בכלל
def _get_all(url, params, max_pages=20):
    items = []
    for _ in range(max_pages):
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        items.extend(payload.get("data", []))
        url = (payload.get("paging") or {}).get("next")
        params = None
        if not url:
            break
    return items


def list_page_forms():
    access_token = load_page_access_token()
    if not access_token:
        return []
    return _get_all(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PAGE_ID}/leadgen_forms",
        {"access_token": access_token, "limit": 100},
    )


def list_leads_since(form_id, since_timestamp):
    access_token = load_page_access_token()
    if not access_token:
        return []
    return _get_all(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{form_id}/leads",
        {"access_token": access_token, "since": since_timestamp, "limit": 100},
        max_pages=3,
    )


def _parse_created_time(value):
    try:
        return int(datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").timestamp())
    except (ValueError, TypeError):
        return None


def load_last_result():
    try:
        return json.loads(LAST_RESULT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save_result(result):
    try:
        LAST_RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# חלופה ל-webhook בזמן אמת של מטא (שלא הצליח לספק לנו נתונים בפועל, למרות שכל ההגדרות תקינות) -
# עוברת על כל טפסי הלידים של הדף ומייבאת לידים חדשים שנוצרו מאז הבדיקה הקודמת. שומרת גם רשימת
# leadgen_id שכבר טופלו, כדי למנוע כפילות גם אם יש חפיפה בין שני ריצות פולינג עוקבות.
# backfill_days: משיכה מחדש של N הימים האחרונים (להשלמת לידים שהוחמצו) - מתעלמת מזמן הבדיקה האחרונה
# ומדלגת על לידים שהטלפון שלהם כבר קיים במערכת, כדי לא ליצור כפילויות.
# כל כשל (טוקן חסר/פג, שגיאת Graph, ליד שנכשל) נרשם בתוצאה ולא נבלע; לידים בלי טלפון נספרים ושמות השדות
# שלהם נרשמים (בלי הערכים - מידע אישי), והם לא מסומנים כמטופלים כדי שאפשר יהיה להשלים אותם
def poll_new_leads(repos, channels, backfill_days=None):
    result = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "mode": f"backfill_{backfill_days}d" if backfill_days else "poll",
        "ok": True, "token": bool(load_page_access_token()),
        "forms_checked": 0, "leads_seen": 0, "created": 0,
        "already_processed": 0, "existing_phone": 0, "no_phone": 0,
        "no_phone_fields": [], "errors": [],
    }
    if not result["token"]:
        result["ok"] = False
        result["errors"].append("אין טוקן גישה לדף (.meta_page_access_token) - הקובץ חסר או ריק")
        _save_result(result)
        return result

    now_ts = int(time.time())
    since_timestamp = now_ts - backfill_days * 86400 if backfill_days else load_last_poll_time()
    processed_ids = load_processed_lead_ids()
    newest_created_time = since_timestamp
    statuses = repos.lead_statuses.get_names()
    existing_phones = None
    if backfill_days:
        existing_phones = {
            normalize_phone(p) or str(p).strip() for p in repos.leads.get_all()["phone"].fillna("").astype(str) if str(p).strip()
        }

    try:
        forms = list_page_forms()
    except Exception as exc:  # noqa: BLE001
        result["ok"] = False
        result["errors"].append(f"קריאת רשימת הטפסים נכשלה: {exc}"[:300])
        _save_result(result)
        return result
    result["forms_checked"] = len(forms)

    for form in forms:
        form_id = form.get("id")
        if not form_id:
            continue
        try:
            form_leads = list_leads_since(form_id, since_timestamp)
        except Exception as exc:  # noqa: BLE001
            result["ok"] = False
            result["errors"].append(f"טופס {form_id}: {exc}"[:300])
            continue

        for lead_data in form_leads:
            result["leads_seen"] += 1
            lead_id = lead_data.get("id")
            if not lead_id or lead_id in processed_ids:
                result["already_processed"] += 1
                continue

            created_ts = _parse_created_time(lead_data.get("created_time", ""))
            try:
                full_name, phone, email, extra_answers = extract_lead_fields(lead_data)
                if not phone:
                    result["no_phone"] += 1
                    names = ", ".join(lead_field_names(lead_data))
                    if names and names not in result["no_phone_fields"] and len(result["no_phone_fields"]) < 5:
                        result["no_phone_fields"].append(names)
                    continue
                if created_ts:
                    newest_created_time = max(newest_created_time, created_ts)
                if existing_phones is not None and (normalize_phone(phone) or phone) in existing_phones:
                    result["existing_phone"] += 1
                    processed_ids.add(lead_id)
                    continue
                repos.leads.create({
                    "full_name": full_name or "ליד ממטא",
                    "phone": phone,
                    "status": statuses[0] if statuses else "",
                    "channel": "פייסבוק" if "פייסבוק" in channels else channels[0],
                    "assigned_user": "",
                    "notes": build_notes(email, extra_answers),
                })
                processed_ids.add(lead_id)
                result["created"] += 1
            except Exception as exc:  # noqa: BLE001
                result["ok"] = False
                result["errors"].append(f"ליד {lead_id}: {exc}"[:300])

    result["errors"] = result["errors"][:8]
    if not backfill_days and result["ok"]:
        # מקדמים את נקודת ההתחלה רק כשכל הסבב הצליח - אחרת הסבב הבא ינסה שוב (כפילויות נחסמות לפי processed_ids)
        save_last_poll_time(newest_created_time + 1 if result["leads_seen"] else max(since_timestamp, now_ts - 3600))
    save_processed_lead_ids(processed_ids)
    _save_result(result)
    return result
