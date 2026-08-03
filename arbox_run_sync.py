import sys
from types import SimpleNamespace

from lead_db import LeadDB
from lead_repository import LeadRepository
from arbox_sync import sync_arbox_clients

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# סקריפט הרצה ידנית של סנכרון Arbox (במקום להמתין ל-thread האוטומטי שרץ כל שעה בתוך app.py)


def main():
    db = LeadDB()
    repos = SimpleNamespace(leads=LeadRepository(db.conn))

    result = sync_arbox_clients(repos)
    if result.get("skipped"):
        print(f"Sync skipped: {result.get('reason')}")
    else:
        print(
            f"Fetched {result['total_fetched']} clients from Arbox.\n"
            f"Updated {result['updated_to_converted']} existing leads to status 'הפך ללקוח'.\n"
            f"Already 'הפך ללקוח' (no change needed): {result['already_converted']}.\n"
            f"Not found in leads (not imported): {result['not_found']}.\n"
            f"Skipped {result['no_phone']} (no phone number in Arbox)."
        )

    db.close()


if __name__ == "__main__":
    main()
