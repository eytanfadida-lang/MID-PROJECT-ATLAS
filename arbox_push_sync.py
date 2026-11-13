import datetime
import os
import sys

import requests

from atlas.integrations.arbox.client import (
    fetch_arbox_users, fetch_arbox_schedule, fetch_arbox_active_memberships, fetch_arbox_bookings,
)

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# רץ מחוץ לסביבת האירוח (למשל GitHub Actions) - מושך מ-Arbox (דורש גישת רשת יוצאת פתוחה),
# ודוחף את התוצאה ל-POST /tasks/arbox-sync-data באתר עצמו, שרק מעדכן את ה-DB המקומי שלו
# בלי לגשת בעצמו ל-Arbox. משתני הסביבה מגיעים מ-GitHub Actions secrets, לא מקבצים מקומיים

SCHEDULE_DAYS_AHEAD = 10
# "ביקורים אחרונים" לתוסף ה-Chrome (extension_api.py) - חלון נע אחורה, לא צריך היסטוריה עמוקה
BOOKINGS_DAYS_BACK = 45


def main():
    api_key = os.environ["ARBOX_API_KEY"]
    target_url = os.environ["ARBOX_SYNC_TARGET_URL"]
    token = os.environ["ARBOX_SYNC_TOKEN"]

    # לא מסננים active="1" - כדי שגם מנויים שפגו יגיעו עם active=0, ותהיה לבוט הלקוחות
    # תשובה אמיתית ("המנוי שלך הסתיים בתאריך X") במקום "לא נמצא במערכת", ראו §3.8 בתוכנית
    arbox_users = fetch_arbox_users(api_key, only_clients="1")
    print(f"Fetched {len(arbox_users)} clients from Arbox.")

    arbox_memberships = fetch_arbox_active_memberships(api_key)
    print(f"Fetched {len(arbox_memberships)} active memberships from Arbox.")

    today = datetime.date.today()
    from_date = today.isoformat()
    to_date = (today + datetime.timedelta(days=SCHEDULE_DAYS_AHEAD)).isoformat()
    schedule = fetch_arbox_schedule(api_key, from_date, to_date)
    print(f"Fetched {len(schedule)} class sessions from Arbox ({from_date}..{to_date}).")

    # bookingsReport לא מתועד כמוגבל ל-31 יום (בניגוד ל-expiringSessionsReport/lostLeadsReport -
    # ראו client.py), אבל מפצלים לבקשות של עד 30 יום בכל זאת, כמו fetch_arbox_trial_classes_range,
    # כדי לא לגלות מגבלה לא-מתועדת בייצור
    bookings_from = today - datetime.timedelta(days=BOOKINGS_DAYS_BACK)
    bookings_to = today
    bookings = []
    cursor = bookings_from
    while cursor <= bookings_to:
        chunk_end = min(cursor + datetime.timedelta(days=29), bookings_to)
        bookings.extend(fetch_arbox_bookings(api_key, cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + datetime.timedelta(days=1)
    print(f"Fetched {len(bookings)} bookings from Arbox ({bookings_from.isoformat()}..{bookings_to.isoformat()}).")

    response = requests.post(
        target_url,
        params={"token": token},
        json={
            "users": arbox_users,
            "memberships": arbox_memberships,
            "schedule": schedule,
            "schedule_from_date": from_date,
            "schedule_to_date": to_date,
            "bookings": bookings,
            "bookings_from_date": bookings_from.isoformat(),
            "bookings_to_date": bookings_to.isoformat(),
        },
        timeout=60,
    )
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
