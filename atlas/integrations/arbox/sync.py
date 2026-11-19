import datetime

from atlas.integrations.arbox.client import (
    fetch_arbox_users,
    fetch_arbox_schedule,
    fetch_arbox_active_memberships,
    load_arbox_api_key,
)

SCHEDULE_DAYS_AHEAD = 10

ARBOX_CONVERTED_STATUS = "הפך ללקוח"


# בודקת מי מרשימת משתמשי Arbox שהועברה כבר קיים אצלנו כליד (לפי טלפון), ומעדכנת את הסטטוס
# שלו ל"הפך ללקוח". לא מייבאת/יוצרת אף ליד חדש. לא עושה שום קריאת רשת - קלט הוא רשימה מוכנה,
# כדי שאפשר יהיה להריץ את החלק הזה (עדכון ה-DB) בנפרד מהחלק שמושך מ-Arbox (למשל דרך
# GitHub Actions, בסביבות אירוח שחוסמות גישה יוצאת לדומיין של Arbox)
def apply_arbox_users_to_leads(repos, arbox_users):
    updated_to_converted = 0
    already_converted = 0
    not_found = 0
    no_phone = 0
    for user in arbox_users:
        phone = (user.get("phone") or "").strip()
        if not phone:
            no_phone += 1
            continue

        existing_leads = repos.leads.get_by_phone(phone)
        if existing_leads.empty:
            not_found += 1
            continue

        for _, existing_lead in existing_leads.iterrows():
            if existing_lead["status"] == ARBOX_CONVERTED_STATUS:
                already_converted += 1
            else:
                repos.leads.update_field(int(existing_lead["id"]), "status", ARBOX_CONVERTED_STATUS)
                updated_to_converted += 1

    return {
        "skipped": False,
        "updated_to_converted": updated_to_converted,
        "already_converted": already_converted,
        "not_found": not_found,
        "no_phone": no_phone,
        "total_fetched": len(arbox_users),
    }


# מושכת מ-Arbox את כל מי שהוא לקוח (only_clients=1, כולל לא-פעילים) ומעדכנת לידים קיימים
# בהתאם, וכן מרעננת את קאש המנויים המקומי (ראו arbox_member_cache_repository.py, §3.8).
# משתמשת ב-API key מקומי, ולכן דורשת גישת רשת יוצאת ל-Arbox (מתאים להרצה מקומית/מהמחשב שלך,
# לא בהכרח מכל סביבת אירוח)
def sync_arbox_clients(repos):
    api_key = load_arbox_api_key()
    if not api_key:
        return {"skipped": True, "reason": "missing_api_key"}

    arbox_users = fetch_arbox_users(api_key, only_clients="1")
    arbox_memberships = fetch_arbox_active_memberships(api_key)
    repos.arbox_member_cache.replace_all(arbox_users, arbox_memberships)

    today = datetime.date.today()
    from_date = today.isoformat()
    to_date = (today + datetime.timedelta(days=SCHEDULE_DAYS_AHEAD)).isoformat()
    schedule = fetch_arbox_schedule(api_key, from_date, to_date)
    repos.arbox_class_cache.replace_range(from_date, to_date, schedule)

    return apply_arbox_users_to_leads(repos, arbox_users)
