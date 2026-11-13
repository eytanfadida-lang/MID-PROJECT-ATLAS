import re

import pandas as pd

# פונקציות גנריות לקריאת קובץ CSV/Excel שהועלה ומיפוי עמודותיו לשדות פנימיים לפי כינויים
# (עברית/אנגלית) - משותפות בין כל תכונות הייבוא בפרויקט (לידים, נמעני אוטומציה וכו'),
# כדי לא לשכפל את לוגיקת הקידוד/הזיהוי בכל אחת מהן בנפרד


# קוראת רק את שורת הכותרות, כדי לזהות את שמות העמודות לפני הקריאה המלאה. CSV בעברית
# שנשמר מאקסל רגיל הוא לרוב cp1255, לא utf-8 - fallback אוטומטי אם הפענוח הראשון נכשל
def read_header(file_storage):
    filename = (file_storage.filename or "").lower()
    file_storage.seek(0)
    if filename.endswith(".csv"):
        try:
            return pd.read_csv(file_storage, nrows=0, encoding="utf-8-sig").columns
        except UnicodeDecodeError:
            file_storage.seek(0)
            return pd.read_csv(file_storage, nrows=0, encoding="cp1255").columns
    return pd.read_excel(file_storage, nrows=0).columns


# קוראת את הקובץ המלא ל-DataFrame. dtype_column (בד"כ עמודת הטלפון) נכפה ל-str כדי שלא
# יאבד האפס המוביל; שאר העמודות נשארות עם הסקה רגילה כדי שתאים ריקים יהפכו ל-NaN אמיתי
def read_dataframe(file_storage, dtype_column=None):
    filename = (file_storage.filename or "").lower()
    dtype = {dtype_column: str} if dtype_column else None
    file_storage.seek(0)
    if filename.endswith(".csv"):
        try:
            return pd.read_csv(file_storage, dtype=dtype, encoding="utf-8-sig")
        except UnicodeDecodeError:
            file_storage.seek(0)
            return pd.read_csv(file_storage, dtype=dtype, encoding="cp1255")
    return pd.read_excel(file_storage, dtype=dtype)


# column_aliases: {שדה-פנימי: [שמות-עמודה-אפשריים-בקובץ, ...]} - מחזירה {שדה-פנימי: שם-עמודה-בפועל}
# רק לשדות שבאמת נמצאו בקובץ
def build_column_map(columns, column_aliases):
    normalized = {str(column).strip(): column for column in columns}
    column_map = {}
    for field, aliases in column_aliases.items():
        for alias in aliases:
            if alias in normalized:
                column_map[field] = normalized[alias]
                break
    return column_map


# מחזירה את ערך השדה בשורה הנוכחית כמחרוזת חתוכה, או "" אם העמודה לא קיימת בקובץ/התא ריק.
# pd.isna (לא רק "value is None") כי iterrows() מחזירה תאים ריקים כ-NaN צף
def cell(row, column_map, field):
    if field not in column_map:
        return ""
    value = row[column_map[field]]
    return "" if pd.isna(value) else str(value).strip()


# מזהה טלפון שהתעוות לכתיב מדעי (למשל "9.72526E+11") - קורה כשתא בעמודת הטלפון באקסל
# נשמר/יוצא כמספר (לא כטקסט) ועמודה צרה מדי לתצוגה מלאה; עד שהקובץ מגיע אלינו הספרות
# המקוריות כבר אבדו לצמיתות (אי אפשר לשחזר אותן מתוך "9.72526E+11" - יש בו רק 6 ספרות
# משמעותיות) - מאומת בפועל: שידור אמיתי ניסה לשלוח בדיוק לערך הזה וקיבל שגיאה מ-Meta.
# המספר הפתרון היחיד האמיתי: לעצב את העמודה כ"טקסט" באקסל *לפני* הקלדה/הדבקה ולהעלות מחדש
_SCIENTIFIC_NOTATION_RE = re.compile(r"^\d(\.\d+)?E\+?\d+$", re.IGNORECASE)


def looks_like_scientific_notation(value):
    return bool(_SCIENTIFIC_NOTATION_RE.match((value or "").strip()))
