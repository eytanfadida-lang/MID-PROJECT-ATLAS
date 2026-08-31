from atlas.integrations.arbox.client import fetch_arbox_users, load_arbox_api_key

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


# מושכת מ-Arbox את כל מי שהפך ללקוח (only_clients=1, active=1) ומעדכנת לידים קיימים בהתאם.
# משתמשת ב-API key מקומי, ולכן דורשת גישת רשת יוצאת ל-Arbox (מתאים להרצה מקומית/מהמחשב שלך,
# לא בהכרח מכל סביבת אירוח)
def sync_arbox_clients(repos):
    api_key = load_arbox_api_key()
    if not api_key:
        return {"skipped": True, "reason": "missing_api_key"}

    arbox_users = fetch_arbox_users(api_key, only_clients="1", active="1")
    return apply_arbox_users_to_leads(repos, arbox_users)
