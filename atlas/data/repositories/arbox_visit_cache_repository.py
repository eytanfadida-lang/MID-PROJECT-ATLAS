import datetime

from atlas.services.phone_utils import normalize_phone

TABLE_NAME = "arbox_visit_cache"


# אחראית על קאש מקומי של היסטוריית ביקורים/הזמנות שיעור מ-Arbox (bookingsReport) - ראו
# arbox_visit_cache_db.py. בשימוש לתוסף ה-Chrome (extension_api.py), כדי להציג "ביקורים
# אחרונים" לפי טלפון בלי לקרוא ל-Arbox בזמן אמת (איטי, וחסום ברוב סביבות האירוח - ראו §3.8)
class ArboxVisitCacheRepository:
    def __init__(self, conn):
        self.conn = conn

    # מחליפה רק את הטווח שנשלף בפועל, לא את כל הטבלה - כמו arbox_class_cache_repository.replace_range,
    # כדי שריצות עם טווחים חופפים חלקית לא ימחקו ביקורים שסונכרנו ע"י ריצה אחרת
    def replace_range(self, from_date, to_date, bookings):
        synced_at = datetime.datetime.now().isoformat(timespec="minutes")
        rows = []
        for booking in bookings:
            phone = normalize_phone(booking.get("phone") or "")
            if not phone:
                continue
            rows.append((
                phone,
                booking.get("date") or "",
                booking.get("time") or "",
                booking.get("class_name") or "",
                booking.get("location_name") or "",
                booking.get("check_in") or "",
                synced_at,
            ))

        self.conn.execute(
            f"DELETE FROM {TABLE_NAME} WHERE visit_date >= ? AND visit_date <= ?", (from_date, to_date)
        )
        self.conn.executemany(
            f"INSERT OR REPLACE INTO {TABLE_NAME} "
            "(phone, visit_date, visit_time, class_name, location_name, check_in, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()
        return len(rows)

    # הביקורים האחרונים של טלפון נתון, החדש ביותר קודם - לפאנל בתוסף
    def get_recent_by_phone(self, phone, limit=10):
        rows = self.conn.execute(
            f"SELECT visit_date, visit_time, class_name, location_name, check_in FROM {TABLE_NAME} "
            f"WHERE phone = ? ORDER BY visit_date DESC, visit_time DESC LIMIT ?",
            (normalize_phone(phone), limit),
        ).fetchall()
        return [
            {
                "visit_date": row[0], "visit_time": row[1], "class_name": row[2],
                "location_name": row[3], "check_in": row[4],
            }
            for row in rows
        ]
