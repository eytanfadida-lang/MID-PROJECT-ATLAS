import datetime

TABLE_NAME = "arbox_class_cache"


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
            ))

        self.conn.execute(
            f"DELETE FROM {TABLE_NAME} WHERE date >= ? AND date <= ?", (from_date, to_date)
        )
        self.conn.executemany(
            f"INSERT OR REPLACE INTO {TABLE_NAME} "
            "(schedule_id, date, start_time, end_time, location_name, session_name, staff_name, "
            "max_participants, synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def get_by_date(self, date):
        rows = self.conn.execute(
            f"SELECT date, start_time, end_time, location_name, session_name, staff_name, max_participants "
            f"FROM {TABLE_NAME} WHERE date = ? ORDER BY start_time",
            (date,),
        ).fetchall()
        return [
            {
                "date": row[0],
                "start_time": row[1],
                "end_time": row[2],
                "location_name": row[3],
                "session_name": row[4],
                "staff_name": row[5],
                "max_participants": row[6],
            }
            for row in rows
        ]
