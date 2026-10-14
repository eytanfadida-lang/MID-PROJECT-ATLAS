import pandas as pd

from atlas.services import file_import_utils

COLUMN_ALIASES = {
    "full_name": ["full_name", "שם מלא", "שם"],
    "phone": ["phone", "טלפון"],
}


# מייבאת נמענים לאוטומציה (רשימה ידנית) מקובץ CSV/Excel שהועלה - אותו דפוס בדיוק כמו
# ייבוא לידים (ראו lead_bulk_import.py), רק שם+טלפון בלבד. מדלגת על טלפון כפול בתוך
# הקובץ עצמו (לא מול נמענים קיימים באוטומציה - הוספה כפולה שם לא מזיקה, פשוט תישלח פעמיים)
def import_recipients_from_file(file_storage, repos, automation_id):
    header_columns = file_import_utils.read_header(file_storage)
    column_map = file_import_utils.build_column_map(header_columns, COLUMN_ALIASES)

    if "phone" not in column_map:
        return {"error": "לא נמצאה עמודת 'טלפון' בקובץ. יש לוודא ששם העמודה תואם."}

    df = file_import_utils.read_dataframe(file_storage, column_map["phone"])
    df = df.where(pd.notnull(df), None)

    created = 0
    skipped = []
    seen_phones = set()
    for index, row in df.iterrows():
        phone = file_import_utils.cell(row, column_map, "phone")
        full_name = file_import_utils.cell(row, column_map, "full_name")
        if not phone:
            skipped.append(f"שורה {index + 2}: חסר טלפון")
            continue
        if phone in seen_phones:
            skipped.append(f"שורה {index + 2}: טלפון כפול בקובץ ({phone}), דולג")
            continue
        seen_phones.add(phone)
        repos.automations.add_recipient(automation_id, phone, full_name)
        created += 1

    return {"total_rows": len(df), "created": created, "skipped": skipped}
