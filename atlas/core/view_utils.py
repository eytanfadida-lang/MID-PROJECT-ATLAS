import datetime

import pandas as pd

ROLE_BADGE_CLASSES = {
    "admin": "badge-red",
    "user": "badge-gray",
}


# ממירה DataFrame לרשימת dict-ים רגילים לשימוש ב-Jinja, עם NaN/NaT מוחלף ב-None
# (כדי שלא יודפס "nan" בטמפלט על עמודות ריקות, למשל customer_id שלא קושר עדיין)
def to_records(df):
    return df.where(pd.notnull(df), None).to_dict("records")


def role_badge_class(role):
    return ROLE_BADGE_CLASSES.get(role, "badge-gray")


# ממירה מספר טלפון ישראלי מקומי (למשל "0501234567") לקישור wa.me תקין (972501234567)
def whatsapp_link(phone):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("0"):
        digits = "972" + digits[1:]
    elif not digits.startswith("972"):
        digits = "972" + digits
    return f"https://wa.me/{digits}"


# מציגה חותמת זמן ISO (למשל "2026-07-31T15:03") כ-"HH:MM DD/MM/YYYY", לתצוגה בטבלאות
def format_lead_datetime(value):
    if not value:
        return "-"
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return value
    return parsed.strftime("%H:%M %d/%m/%Y")
