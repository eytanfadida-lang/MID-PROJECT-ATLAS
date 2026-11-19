import argparse
import datetime
import os
import sqlite3
import sys

import requests

from atlas.integrations.arbox.client import (
    fetch_arbox_users, fetch_arbox_schedule, fetch_arbox_active_memberships, fetch_arbox_bookings,
    set_default_request_source,
)
from atlas.paths import secret
from atlas.services.time_utils import utc_now_to_israel

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# רץ כמשימה מתוזמנת ב-PythonAnywhere (פעם בשעה) - מושך מ-Arbox ודוחף את התוצאה ל-POST
# /tasks/arbox-sync-data באתר עצמו, שמעדכן את ה-DB. משתני הסביבה מוגדרים בפקודת המשימה.
#
# תקציב: ל-Arbox יש מכסה של 20,000 בקשות בחודש (עד 500 רשומות בבקשה - מאומת). לכן (19/11/26):
# - לא רץ בלילה (00:00-05:59 שעון ישראל) - 18 ריצות ביום במקום 96
# - בכל ריצה: רק לקוחות (only_clients=1, כ-17 בקשות), מנויים פעילים, לוח שיעורים, וביקורים של
#   אתמול והיום בלבד (הישנים כבר שמורים, וביקור מעל 45 יום נמחק בשרת)
# - לידים/אנשי צוות/אגרגטור (לכרטיס איש הקשר בתוסף) - פעם ביום, בריצה הראשונה של היום
# - בלם: מעל 19,000 בקשות החודש רץ רק ב-06 וב-18 עד סוף החודש
# --force עוקף את הלילה ואת הבלם, --full כולל את כל המשתמשים גם אם כבר נמשכו היום

SCHEDULE_DAYS_AHEAD = 10
BOOKINGS_DAYS_BACK = 1
NIGHT_END_HOUR = 6
BRAKE_HOURS = (6, 18)
CONTACTS_STATE_FILE = secret(".arbox_contacts_synced_date")
# רק השדות שכרטיס איש הקשר צריך - כדי לא לנפח את הבקשה ב-6000 רשומות מלאות
CONTACT_FIELDS = ("phone", "user_id", "first_name", "last_name", "user_role", "email", "birthday", "location_id", "created_time")


def _month_usage(month):
    # קריאה ישירה מה-DB של האתר (הסקריפט רץ באותה תיקייה ב-PythonAnywhere). None אם לא זמין
    try:
        from atlas.data.db import DB_FILE
        from atlas.data.repositories.arbox_usage_repository import ArboxUsageRepository
        conn = sqlite3.connect(DB_FILE, timeout=5)
        try:
            return ArboxUsageRepository(conn).month_total(month)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None


def _contacts_synced_today(today):
    try:
        return CONTACTS_STATE_FILE.read_text().strip() == today.isoformat()
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="לרוץ גם בלילה ומעל הבלם")
    parser.add_argument("--full", action="store_true", help="למשוך את כל המשתמשים, כולל לידים ואנשי צוות")
    args = parser.parse_args()

    set_default_request_source("sync")
    now_israel = utc_now_to_israel(datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
    today = now_israel.date()

    if not args.force:
        if now_israel.hour < NIGHT_END_HOUR:
            print(f"Skipping: night hours ({now_israel:%H:%M} Israel time).")
            return
        from atlas.data.repositories.arbox_usage_repository import BRAKE_THRESHOLD
        used = _month_usage(today.strftime("%Y-%m"))
        if used is not None and used >= BRAKE_THRESHOLD and now_israel.hour not in BRAKE_HOURS:
            print(f"Skipping: brake active ({used} Arbox requests this month).")
            return

    api_key = os.environ["ARBOX_API_KEY"]
    target_url = os.environ["ARBOX_SYNC_TARGET_URL"]
    token = os.environ["ARBOX_SYNC_TOKEN"]

    # לקוחות - לא מסננים active="1", כדי שגם מנויים שפגו יגיעו עם active=0 והבוט יענה "המנוי שלך
    # הסתיים" במקום "לא נמצא". פעם ביום מושכים את כולם ומפצלים: לקוחות לקאש המנויים, השאר לקאש
    # אנשי הקשר של התוסף. only_clients="1" זהה בדיוק ל-user_role="client" (מאומת: 8093 מול 8093)
    include_contacts = args.full or not _contacts_synced_today(today)
    contacts = None
    if include_contacts:
        all_users = fetch_arbox_users(api_key)
        arbox_users = [u for u in all_users if u.get("user_role") == "client"]
        contacts = [
            {key: u.get(key) for key in CONTACT_FIELDS}
            for u in all_users
            if u.get("user_role") != "client"
        ]
        print(f"Fetched {len(arbox_users)} clients and {len(contacts)} other users from Arbox.")
    else:
        arbox_users = fetch_arbox_users(api_key, only_clients="1")
        print(f"Fetched {len(arbox_users)} clients from Arbox (other users already synced today).")

    arbox_memberships = fetch_arbox_active_memberships(api_key)
    print(f"Fetched {len(arbox_memberships)} active memberships from Arbox.")

    from_date = today.isoformat()
    to_date = (today + datetime.timedelta(days=SCHEDULE_DAYS_AHEAD)).isoformat()
    schedule = fetch_arbox_schedule(api_key, from_date, to_date)
    print(f"Fetched {len(schedule)} class sessions from Arbox ({from_date}..{to_date}).")

    bookings_from = (today - datetime.timedelta(days=BOOKINGS_DAYS_BACK)).isoformat()
    bookings_to = today.isoformat()
    bookings = fetch_arbox_bookings(api_key, bookings_from, bookings_to)
    print(f"Fetched {len(bookings)} bookings from Arbox ({bookings_from}..{bookings_to}).")

    payload = {
        "users": arbox_users,
        "memberships": arbox_memberships,
        "schedule": schedule,
        "schedule_from_date": from_date,
        "schedule_to_date": to_date,
        "bookings": bookings,
        "bookings_from_date": bookings_from,
        "bookings_to_date": bookings_to,
    }
    if contacts is not None:
        payload["contacts"] = contacts

    response = requests.post(target_url, params={"token": token}, json=payload, timeout=60)
    response.raise_for_status()
    print(response.json())

    if include_contacts:
        try:
            CONTACTS_STATE_FILE.write_text(today.isoformat())
        except OSError as exc:
            print(f"Warning: could not save contacts sync date: {exc}")


if __name__ == "__main__":
    main()
