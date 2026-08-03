import json
from pathlib import Path

import requests

API_BASE_URL = "https://arboxserver.arboxapp.com/api/public/v3"
API_KEY_FILE = Path(".arbox_api_key")
API_KEY_PLACEHOLDER = "PUT_YOUR_ARBOX_API_KEY_HERE"
LOCATION_MAP_FILE = Path("arbox_location_map.json")
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
