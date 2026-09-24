import datetime
import re
from urllib.parse import urlparse, parse_qs

TABLE_NAME = "arbox_class_cache"


# מחלצת location_id מתוך registration_link (למשל "...?location=856") - זה המקום
# היחיד שבו Arbox חושפת אותו ב-GET /schedule (אין שדה location_id ישיר בתשובה)
def _extract_location_id(registration_link):
    if not registration_link:
        return None
    query = parse_qs(urlparse(registration_link).query)
    values = query.get("location")
    if not values:
        return None
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return None


# אחראית על קאש מקומי של לוח השיעורים החי מ-Arbox (GET /schedule) - ראו
# arbox_class_cache_db.py
class ArboxClassCacheRepository:
    def __init__(self, conn):
        self.conn = conn

    # מחליפה רק את הטווח שנשלף בפועל (מהיום והלאה) - לא את כל הטבלה, כדי שריצות
    # שונות עם טווחי תאריכים חופפים חלקית לא ימחקו שיעורים עדכניים ששלפה ריצה אחרת
    def replace_range(self, from_date, to_date, sessions):
        synced_at = datetime.datetime.now().isoformat(timespec="minutes")
        rows = []
        for session in sessions:
            staff = session.get("staff_member") or {}
            rows.append((
                session.get("schedule_id"),
                session.get("date"),
                session.get("start_time"),
                session.get("end_time"),
                session.get("location_name") or "",
                session.get("session_name") or "",
                staff.get("name") or "",
                session.get("max_participants"),
                synced_at,
                _extract_location_id(session.get("registration_link")),
            ))

        self.conn.execute(
            f"DELETE FROM {TABLE_NAME} WHERE date >= ? AND date <= ?", (from_date, to_date)
        )
        self.conn.executemany(
            f"INSERT OR REPLACE INTO {TABLE_NAME} "
            "(schedule_id, date, start_time, end_time, location_name, session_name, staff_name, "
            "max_participants, synced_at, location_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def get_by_date(self, date):
        rows = self.conn.execute(
            f"SELECT schedule_id, date, start_time, end_time, location_name, session_name, staff_name, "
            f"max_participants FROM {TABLE_NAME} WHERE date = ? ORDER BY start_time",
            (date,),
        ).fetchall()
        return [
            {
                "schedule_id": row[0],
                "date": row[1],
                "start_time": row[2],
                "end_time": row[3],
                "location_name": row[4],
                "session_name": row[5],
                "staff_name": row[6],
                "max_participants": row[7],
            }
            for row in rows
        ]

    # מחזירה שיעור בודד לפי schedule_id, כולל location_id - נחוץ לרישום שיעור ניסיון
    # (צריך לדעת לאיזה סניף/location_id ליצור את הליד החדש ב-Arbox)
    def get_by_schedule_id(self, schedule_id):
        row = self.conn.execute(
            f"SELECT schedule_id, date, start_time, end_time, location_name, session_name, staff_name, "
            f"max_participants, location_id FROM {TABLE_NAME} WHERE schedule_id = ?",
            (schedule_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "schedule_id": row[0],
            "date": row[1],
            "start_time": row[2],
            "end_time": row[3],
            "location_name": row[4],
            "session_name": row[5],
            "staff_name": row[6],
            "max_participants": row[7],
            "location_id": row[8],
        }
