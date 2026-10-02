import json

import requests

from atlas.paths import secret

API_BASE_URL = "https://arboxserver.arboxapp.com/api/public/v3"
API_KEY_FILE = secret(".arbox_api_key")
API_KEY_PLACEHOLDER = "PUT_YOUR_ARBOX_API_KEY_HERE"
LOCATION_MAP_FILE = secret("arbox_location_map.json")
PAGE_LIMIT = 500


# קוראת את מפתח ה-API של Arbox מקובץ מקומי (לא נכנס לגיט); מחזירה None אם הקובץ חסר/ריק
def load_arbox_api_key():
    if not API_KEY_FILE.exists():
        return None
    key = API_KEY_FILE.read_text().strip()
    if not key or key == API_KEY_PLACEHOLDER:
        return None
    return key


# קוראת את מיפוי location_id (של Arbox) -> שם סניף שלנו, מקובץ JSON מקומי (לא נכנס לגיט)
def load_location_branch_map():
    if not LOCATION_MAP_FILE.exists():
        return {}
    try:
        return json.loads(LOCATION_MAP_FILE.read_text())
    except (ValueError, OSError):
        return {}


# מושכת את כל המשתמשים מ-Arbox (עם pagination), לפי פרמטרי הסינון שהועברו
def fetch_arbox_users(api_key, **filters):
    users = []
    page = 1
    while True:
        response = requests.get(
            f"{API_BASE_URL}/users",
            headers={"Accept": "application/json", "api-key": api_key},
            params={**filters, "limit": PAGE_LIMIT, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        page_users = response.json().get("data", []) or []
        users.extend(page_users)
        if len(page_users) < PAGE_LIMIT:
            break
        page += 1
    return users


# מושכת את לוח השיעורים האמיתי מ-Arbox (עם pagination) בין שני תאריכים - שם שיעור,
# תאריך/שעה, סניף, מדריך, מקסימום משתתפים. אין ב-Arbox endpoint שחושף כמה מקומות
# נותרו בפועל (רק את המקסימום) - ראה ה"שאלה פתוחה ל-Arbox support" בתוכנית
def fetch_arbox_schedule(api_key, from_date, to_date):
    sessions = []
    page = 1
    while True:
        response = requests.get(
            f"{API_BASE_URL}/schedule",
            headers={"Accept": "application/json", "api-key": api_key},
            params={"from_date": from_date, "to_date": to_date, "limit": PAGE_LIMIT, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        page_sessions = response.json().get("data", []) or []
        sessions.extend(page_sessions)
        if len(page_sessions) < PAGE_LIMIT:
            break
        page += 1
    return sessions


# מושכת את כל המנויים הפעילים מ-Arbox (עם pagination) - מידע עשיר יותר מ-/users:
# סוג מנוי, חוב פתוח, האם בוטל, ו-membership_user_id (דרוש לרישום/ביטול שיעור בפועל
# דרך /schedule/bookSession, ראו §3.8). מסוננים ל-active=1 בכוונה - זו רשימת כל המנויים
# שאי-פעם נוצרו (כולל מ-2018), בלי הסינון הכמות תהיה עצומה ולא רלוונטית לבוט
def fetch_arbox_active_memberships(api_key):
    memberships = []
    page = 1
    while True:
        response = requests.get(
            f"{API_BASE_URL}/users/memberships",
            headers={"Accept": "application/json", "api-key": api_key},
            params={"active": "1", "limit": PAGE_LIMIT, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        page_memberships = response.json().get("data", []) or []
        memberships.extend(page_memberships)
        if len(page_memberships) < PAGE_LIMIT:
            break
        page += 1
    return memberships


# רושמת משתמש קיים לשיעור אמיתי ב-Arbox (לא ליומן הפנימי שלנו) - כתיבה בזמן אמת,
# ולכן דורשת שהתהליך שקורא לפונקציה הזו יוכל להגיע ל-Arbox יוצא (לא PythonAnywhere
# בתוכנית החינמית, ראו §3.8 בתוכנית)
def book_arbox_session(api_key, user_id, schedule_id, membership_user_id):
    response = requests.post(
        f"{API_BASE_URL}/schedule/bookSession",
        headers={"Accept": "application/json", "api-key": api_key},
        json={"user_id": user_id, "schedule_id": schedule_id, "membership_user_id": membership_user_id},
        timeout=30,
    )
    return response


# מבטלת רישום קיים של משתמש לשיעור ב-Arbox
def cancel_arbox_booking(api_key, user_id, schedule_id):
    response = requests.post(
        f"{API_BASE_URL}/schedule/cancelUserBooking",
        headers={"Accept": "application/json", "api-key": api_key},
        json={"user_id": user_id, "schedule_id": schedule_id},
        timeout=30,
    )
    return response


# מחפשת משתמש קיים ב-Arbox לפי טלפון (מספר-מלא-אחד, לא רשימה) - מחזירה user_id
# ראשון שנמצא, או None אם אין. נחוץ כדי לדעת אם לקוחה/מתעניינת חדשה כבר קיימת
# ב-Arbox (כליד, למשל) לפני שרושמים אותה לשיעור ניסיון
def search_arbox_user_by_phone(api_key, phone):
    response = requests.get(
        f"{API_BASE_URL}/users/searchUser",
        headers={"Accept": "application/json", "api-key": api_key},
        params={"type": "phone", "value": phone},
        timeout=30,
    )
    response.raise_for_status()
    results = response.json().get("data", []) or []
    return results[0]["user_id"] if results else None


# יוצרת ליד חדש ב-Arbox (POST /v3/users נבדק ולא הצליח - השיעור-ניסיון דוחה את
# ה-user_id שהוא מחזיר עם "not valid"; רק לידים שנוצרו דרך /leads עובדים) - למשל
# מתעניינת חדשה שרוצה שיעור ניסיון ועדיין לא קיימת ב-Arbox בכלל. מחזירה את ה-user_id
def create_arbox_lead(api_key, first_name, last_name, phone, location_id):
    response = requests.post(
        f"{API_BASE_URL}/leads",
        headers={"Accept": "application/json", "api-key": api_key},
        json={"first_name": first_name, "last_name": last_name, "phone": phone, "location_id": location_id},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["data"]["user_id"]


# רושמת (משתמש קיים או חדש) לשיעור ניסיון ב-Arbox - endpoint ייעודי שלא דורש מנוי
# פעיל (בשונה מ-bookSession הרגיל). Arbox עצמה דוחה את הבקשה אם השיעור מלא, וזו
# בפועל הדרך היחידה לדעת אם יש מקום פנוי (אין endpoint נפרד לכך)
def book_arbox_trial(api_key, user_id, schedule_id):
    response = requests.post(
        f"{API_BASE_URL}/schedule/booking/trial",
        headers={"Accept": "application/json", "api-key": api_key},
        json={"user_id": user_id, "schedule_id": schedule_id},
        timeout=30,
    )
    return response


# מבטלת רישום קיים לשיעור ניסיון
def cancel_arbox_trial(api_key, user_id, schedule_id):
    response = requests.delete(
        f"{API_BASE_URL}/schedule/booking/trial",
        headers={"Accept": "application/json", "api-key": api_key},
        params={"user_id": user_id, "schedule_id": schedule_id},
        timeout=30,
    )
    return response
