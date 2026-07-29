import pandas as pd

STATUS_BADGE_CLASSES = {
    "New": "badge-blue",
    "In progress": "badge-orange",
    "Received info about the trainings": "badge-teal",
    "Received info about VIP": "badge-purple",
    "Not relevant": "badge-gray",
    "Became a client": "badge-green",
}

ROLE_BADGE_CLASSES = {
    "admin": "badge-red",
    "user": "badge-gray",
}


# ממירה DataFrame לרשימת dict-ים רגילים לשימוש ב-Jinja, עם NaN/NaT מוחלף ב-None
# (כדי שלא יודפס "nan" בטמפלט על עמודות ריקות, למשל customer_id שלא קושר עדיין)
def to_records(df):
    return df.where(pd.notnull(df), None).to_dict("records")


def status_badge_class(status):
    return STATUS_BADGE_CLASSES.get(status, "badge-gray")


def role_badge_class(role):
    return ROLE_BADGE_CLASSES.get(role, "badge-gray")
