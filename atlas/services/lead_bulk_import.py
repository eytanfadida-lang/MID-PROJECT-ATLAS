import pandas as pd

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


# קוראת רק את שורת הכותרות, כדי לזהות את שם עמודת הטלפון לפני הקריאה המלאה
def _read_header(file_storage):
    filename = (file_storage.filename or "").lower()
    file_storage.seek(0)
    if filename.endswith(".csv"):
        try:
            return pd.read_csv(file_storage, nrows=0, encoding="utf-8-sig").columns
        except UnicodeDecodeError:
            file_storage.seek(0)
            return pd.read_csv(file_storage, nrows=0, encoding="cp1255").columns
    return pd.read_excel(file_storage, nrows=0).columns


# קוראת את הקובץ המלא ל-DataFrame. עמודת הטלפון נכפית ל-str כדי שלא יאבד האפס המוביל;
# שאר העמודות נשארות עם הסקה רגילה כדי שתאים ריקים יהפכו ל-NaN אמיתי (ולא למחרוזת "nan")
def _read_dataframe(file_storage, phone_column):
    filename = (file_storage.filename or "").lower()
    dtype = {phone_column: str} if phone_column else None
    file_storage.seek(0)
    if filename.endswith(".csv"):
        try:
            return pd.read_csv(file_storage, dtype=dtype, encoding="utf-8-sig")
        except UnicodeDecodeError:
            file_storage.seek(0)
            return pd.read_csv(file_storage, dtype=dtype, encoding="cp1255")
    return pd.read_excel(file_storage, dtype=dtype)


def _build_column_map(columns):
    normalized = {str(column).strip(): column for column in columns}
    column_map = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                column_map[field] = normalized[alias]
                break
    return column_map


def _cell(row, column_map, field):
    if field not in column_map:
        return ""
    value = row[column_map[field]]
    # pd.isna (לא רק "value is None") כי iterrows() מחזירה תאים ריקים כ-NaN צף,
    # גם כשה-DataFrame עצמו כבר עבר טיוב ל-None
    return "" if pd.isna(value) else str(value).strip()


# מייבאת לידים מקובץ CSV/Excel שהועלה, לפי מיפוי עמודות גמיש, ומחזירה סיכום:
# כמה שורות נוצרו בהצלחה וכמה דולגו (עם הסיבה)
def import_leads_from_file(file_storage, repos, default_status, default_channel):
    header_columns = _read_header(file_storage)
    column_map = _build_column_map(header_columns)

    if "full_name" not in column_map or "phone" not in column_map:
        return {"error": "לא נמצאו עמודות 'שם מלא' ו'טלפון' בקובץ. יש לוודא ששמות העמודות תואמים."}

    df = _read_dataframe(file_storage, column_map["phone"])
    df = df.where(pd.notnull(df), None)

    existing_statuses = set(repos.lead_statuses.get_names())

    created = 0
    skipped = []
    for index, row in df.iterrows():
        full_name = _cell(row, column_map, "full_name")
        phone = _cell(row, column_map, "phone")
        if not full_name or not phone:
            skipped.append(f"שורה {index + 2}: חסר שם מלא או טלפון")
            continue

        status = _cell(row, column_map, "status")
        if status not in existing_statuses:
            status = default_status

        channel = _cell(row, column_map, "channel") or default_channel

        lead = {
            "full_name": full_name,
            "phone": phone,
            "status": status,
            "channel": channel,
            "branch": _cell(row, column_map, "branch"),
            "assigned_user": _cell(row, column_map, "assigned_user"),
            "notes": _cell(row, column_map, "notes"),
        }
        repos.leads.create(lead)
        created += 1

    return {"total_rows": len(df), "created": created, "skipped": skipped}
