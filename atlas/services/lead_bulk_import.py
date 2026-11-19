import pandas as pd

from atlas.services import file_import_utils

# מיפוי גמיש בין שמות עמודות אפשריים בקובץ (עברית או אנגלית) לבין שדות הליד הפנימיים
COLUMN_ALIASES = {
    "full_name": ["full_name", "שם מלא", "שם"],
    "phone": ["phone", "טלפון"],
    "status": ["status", "סטטוס"],
    "channel": ["channel", "ערוץ"],
    "branch": ["branch", "סניף"],
    "assigned_user": ["assigned_user", "מנהל לקוח", "משתמש משויך"],
    "notes": ["notes", "הערות"],
}


# מייבאת לידים מקובץ CSV/Excel שהועלה, לפי מיפוי עמודות גמיש, ומחזירה סיכום:
# כמה שורות נוצרו בהצלחה וכמה דולגו (עם הסיבה)
def import_leads_from_file(file_storage, repos, default_status, default_channel):
    header_columns = file_import_utils.read_header(file_storage)
    column_map = file_import_utils.build_column_map(header_columns, COLUMN_ALIASES)

    if "full_name" not in column_map or "phone" not in column_map:
        return {"error": "לא נמצאו עמודות 'שם מלא' ו'טלפון' בקובץ. יש לוודא ששמות העמודות תואמים."}

    df = file_import_utils.read_dataframe(file_storage, column_map["phone"])
    df = df.where(pd.notnull(df), None)

    existing_statuses = set(repos.lead_statuses.get_names())

    created = 0
    skipped = []
    for index, row in df.iterrows():
        full_name = file_import_utils.cell(row, column_map, "full_name")
        phone = file_import_utils.cell(row, column_map, "phone")
        if not full_name or not phone:
            skipped.append(f"שורה {index + 2}: חסר שם מלא או טלפון")
            continue
        if file_import_utils.looks_like_scientific_notation(phone):
            skipped.append(
                f"שורה {index + 2}: הטלפון ({phone}) נראה כמו מספר שהתעוות לכתיב מדעי באקסל "
                "(הספרות המקוריות אבדו) - יש לעצב את עמודת הטלפון כ'טקסט' באקסל ולהעלות מחדש"
            )
            continue

        status = file_import_utils.cell(row, column_map, "status")
        if status not in existing_statuses:
            status = default_status

        channel = file_import_utils.cell(row, column_map, "channel") or default_channel

        lead = {
            "full_name": full_name,
            "phone": phone,
            "status": status,
            "channel": channel,
            "branch": file_import_utils.cell(row, column_map, "branch"),
            "assigned_user": file_import_utils.cell(row, column_map, "assigned_user"),
            "notes": file_import_utils.cell(row, column_map, "notes"),
        }
        repos.leads.create(lead)
        created += 1

    return {"total_rows": len(df), "created": created, "skipped": skipped}
