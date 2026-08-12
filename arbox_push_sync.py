import os
import sys

import requests

from arbox_client import fetch_arbox_users

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# רץ מחוץ לסביבת האירוח (למשל GitHub Actions) - מושך מ-Arbox (דורש גישת רשת יוצאת פתוחה),
# ודוחף את התוצאה ל-POST /tasks/arbox-sync-data באתר עצמו, שרק מעדכן את ה-DB המקומי שלו
# בלי לגשת בעצמו ל-Arbox. משתני הסביבה מגיעים מ-GitHub Actions secrets, לא מקבצים מקומיים


def main():
    api_key = os.environ["ARBOX_API_KEY"]
    target_url = os.environ["ARBOX_SYNC_TARGET_URL"]
    token = os.environ["ARBOX_SYNC_TOKEN"]

    arbox_users = fetch_arbox_users(api_key, only_clients="1", active="1")
    print(f"Fetched {len(arbox_users)} clients from Arbox.")

    response = requests.post(
        target_url,
        params={"token": token},
        json={"users": arbox_users},
        timeout=60,
    )
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
