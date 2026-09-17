import datetime

from atlas.services.phone_utils import normalize_phone

TABLE_NAME = "arbox_member_cache"


# אחראית על קאש מקומי של סטטוס מנוי מ-Arbox, מפתח לפי מספר טלפון מנורמל (ראו
# phone_utils.py) - כדי שחיפוש לפי המספר שהגיע מוואטסאפ יעבוד בלי תלות בפורמט
# שבו הוא שמור ב-Arbox עצמו (יש 8 פורמטים שונים בנתונים האמיתיים, ראו התוכנית)
class ArboxMemberCacheRepository:
    def __init__(self, conn):
        self.conn = conn

    # מחליפה את כל תוכן הקאש בתמונת המצב העדכנית מ-Arbox (delete + insert בעסקה אחת) -
    # מתאים כי Arbox הוא מקור האמת היחיד כאן, אין שום כתיבה מקומית לטבלה הזו מלבד זו
    def replace_all(self, arbox_users):
        synced_at = datetime.datetime.now().isoformat(timespec="minutes")
        rows = []
        for user in arbox_users:
            phone = normalize_phone(user.get("phone"))
            if not phone:
                continue
            rows.append((
                phone,
                user.get("first_name") or "",
                user.get("last_name") or "",
                1 if user.get("active") else 0,
                user.get("membership_start_date") or "",
                user.get("membership_end_date") or "",
                synced_at,
            ))

        self.conn.execute(f"DELETE FROM {TABLE_NAME}")
        self.conn.executemany(
            f"INSERT OR REPLACE INTO {TABLE_NAME} "
            "(phone, first_name, last_name, active, membership_start_date, membership_end_date, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def get_by_phone(self, phone):
        row = self.conn.execute(
            f"SELECT phone, first_name, last_name, active, membership_start_date, membership_end_date, synced_at "
            f"FROM {TABLE_NAME} WHERE phone = ?",
            (normalize_phone(phone),),
        ).fetchone()
        if row is None:
            return None
        return {
            "phone": row[0],
            "first_name": row[1],
            "last_name": row[2],
            "active": bool(row[3]),
            "membership_start_date": row[4],
            "membership_end_date": row[5],
            "synced_at": row[6],
        }
