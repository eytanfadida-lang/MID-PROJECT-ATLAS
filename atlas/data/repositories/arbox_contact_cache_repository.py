import datetime

from atlas.services.phone_utils import normalize_phone

TABLE_NAME = "arbox_contact_cache"

# כשלאותו טלפון יש כמה משתמשים ב-Arbox (נפוץ: ליד ישן + רשומת עובדת), מעדיפים את התפקיד
# שהכי רלוונטי לכרטיס - עובדת לפני מנוי אגרגטור לפני ליד
ROLE_PRIORITY = {"staffMember": 3, "aggregatorMember": 2, "lead": 1}


# אחראית על קאש משתמשי Arbox שאינם לקוחות - ראו arbox_contact_cache_db.py
class ArboxContactCacheRepository:
    def __init__(self, conn):
        self.conn = conn

    def replace_all(self, contacts):
        synced_at = datetime.datetime.now().isoformat(timespec="minutes")
        by_phone = {}
        for contact in contacts:
            phone = normalize_phone(contact.get("phone"))
            if not phone:
                continue
            existing = by_phone.get(phone)
            priority = ROLE_PRIORITY.get(contact.get("user_role"), 0)
            if existing is None or priority > ROLE_PRIORITY.get(existing.get("user_role"), 0):
                by_phone[phone] = contact

        rows = [
            (
                phone,
                contact.get("user_id"),
                contact.get("first_name") or "",
                contact.get("last_name") or "",
                contact.get("user_role") or "",
                contact.get("email") or "",
                contact.get("birthday") or "",
                contact.get("location_id"),
                (contact.get("created_time") or "")[:10],
                synced_at,
            )
            for phone, contact in by_phone.items()
        ]
        self.conn.execute(f"DELETE FROM {TABLE_NAME}")
        self.conn.executemany(
            f"INSERT INTO {TABLE_NAME} (phone, user_id, first_name, last_name, role, email, birthday, "
            "location_id, created_date, synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def get_by_phone(self, phone):
        row = self.conn.execute(
            f"SELECT phone, user_id, first_name, last_name, role, email, birthday, location_id, created_date "
            f"FROM {TABLE_NAME} WHERE phone = ?",
            (normalize_phone(phone),),
        ).fetchone()
        if row is None:
            return None
        return {
            "phone": row[0], "user_id": row[1], "first_name": row[2], "last_name": row[3], "role": row[4],
            "email": row[5], "birthday": row[6], "location_id": row[7], "created_date": row[8],
        }
