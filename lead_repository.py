import datetime

import pandas as pd

TABLE_NAME = "leads"
DUPLICATE_STATUS = "ליד כפול"


# אחראית על כל הגישה לנתונים (CRUD) מול טבלת leads
class LeadRepository:
    def __init__(self, conn):
        self.conn = conn

    def _normalize_phone(self, phone):
        return (phone or "").strip()

    def _has_duplicate_phone(self, phone, exclude_id=None):
        normalized_phone = self._normalize_phone(phone)
        if not normalized_phone:
            return False

        query = f"SELECT id FROM {TABLE_NAME} WHERE phone = ?"
        params = [normalized_phone]
        if exclude_id is not None:
            query += " AND id != ?"
            params.append(exclude_id)

        result = pd.read_sql_query(query, self.conn, params=params)
        return not result.empty

    # יוצרת ליד חדש, עם routings_count=1 ו-sms_count=0 כברירת מחדל, ומחזירה את המזהה שנוצר
    def create(self, lead):
        now = datetime.datetime.now().isoformat(timespec="minutes")
        phone = self._normalize_phone(lead.get("phone", ""))
        status = lead.get("status", "")
        if phone and self._has_duplicate_phone(phone):
            status = DUPLICATE_STATUS

        cursor = self.conn.execute(
            f"INSERT INTO {TABLE_NAME} "
            "(full_name, phone, status, channel, assigned_user, routings_count, sms_count, notes, "
            "branch, created_datetime_stamp, last_updated_datetime_stamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                lead["full_name"],
                phone,
                status,
                lead["channel"],
                lead["assigned_user"],
                1,
                0,
                lead.get("notes", ""),
                lead.get("branch", ""),
                now,
                now,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    # מחזירה ליד לפי מזהה, או None אם לא נמצא
    def get_by_id(self, lead_id):
        df = pd.read_sql_query(
            f"SELECT * FROM {TABLE_NAME} WHERE id = ?", self.conn, params=(lead_id,)
        )
        if df.empty:
            return None
        return df.iloc[0].to_dict()

    # מעדכנת שדה בודד בליד קיים, ומרעננת את חותמת העדכון האחרון.
    # field_name חייב להגיע מרשימת שדות קבועה (whitelist) בצד הקורא ולא מטקסט חופשי מהמשתמש
    def update_field(self, lead_id, field_name, value):
        if field_name == "phone" and self._has_duplicate_phone(value, exclude_id=lead_id):
            self.conn.execute(
                f"UPDATE {TABLE_NAME} SET {field_name} = ?, status = ?, last_updated_datetime_stamp = ? WHERE id = ?",
                (
                    self._normalize_phone(value),
                    DUPLICATE_STATUS,
                    datetime.datetime.now().isoformat(timespec="minutes"),
                    lead_id,
                ),
            )
        else:
            self.conn.execute(
                f"UPDATE {TABLE_NAME} SET {field_name} = ?, last_updated_datetime_stamp = ? WHERE id = ?",
                (value, datetime.datetime.now().isoformat(timespec="minutes"), lead_id),
            )
        self.conn.commit()

    # מוחקת ליד לפי מזהה, ומחזירה האם נמחקה רשומה בפועל
    def delete(self, lead_id):
        cursor = self.conn.execute(f"DELETE FROM {TABLE_NAME} WHERE id = ?", (lead_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    # מעדכנת את הסטטוס של כמה לידים בבת אחת (בחירה מרובה), ומרעננת את חותמת העדכון האחרון של כולם
    def bulk_update_status(self, lead_ids, status):
        if not lead_ids:
            return
        now = datetime.datetime.now().isoformat(timespec="minutes")
        placeholders = ",".join("?" for _ in lead_ids)
        self.conn.execute(
            f"UPDATE {TABLE_NAME} SET status = ?, last_updated_datetime_stamp = ? WHERE id IN ({placeholders})",
            (status, now, *lead_ids),
        )
        self.conn.commit()

    # מנתבת (משייכת) כמה לידים בבת אחת למשתמש נתון, ומרעננת את חותמת העדכון האחרון של כולם
    def bulk_assign(self, lead_ids, assigned_user):
        if not lead_ids:
            return
        now = datetime.datetime.now().isoformat(timespec="minutes")
        placeholders = ",".join("?" for _ in lead_ids)
        self.conn.execute(
            f"UPDATE {TABLE_NAME} SET assigned_user = ?, last_updated_datetime_stamp = ? WHERE id IN ({placeholders})",
            (assigned_user, now, *lead_ids),
        )
        self.conn.commit()

    # מוחקת כמה לידים בבת אחת (בחירה מרובה), ומחזירה כמה רשומות נמחקו בפועל
    def bulk_delete(self, lead_ids):
        if not lead_ids:
            return 0
        placeholders = ",".join("?" for _ in lead_ids)
        cursor = self.conn.execute(f"DELETE FROM {TABLE_NAME} WHERE id IN ({placeholders})", tuple(lead_ids))
        self.conn.commit()
        return cursor.rowcount

    # מחזירה את כל הלידים, החדש ביותר קודם
    def get_all(self):
        return pd.read_sql_query(f"SELECT * FROM {TABLE_NAME} ORDER BY id DESC", self.conn)

    # מחזירה את הלידים לפי סטטוס נתון
    def get_by_status(self, status):
        return pd.read_sql_query(
            f"SELECT * FROM {TABLE_NAME} WHERE status = ? ORDER BY id DESC",
            self.conn,
            params=(status,),
        )

    # מחזירה את הלידים לפי מספר טלפון
    def get_by_phone(self, phone):
        return pd.read_sql_query(
            f"SELECT * FROM {TABLE_NAME} WHERE phone = ? ORDER BY id DESC",
            self.conn,
            params=(phone,),
        )
