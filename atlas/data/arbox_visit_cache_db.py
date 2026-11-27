import sqlite3

from atlas.data.db import DB_FILE


# אחראית על החיבור למסד הנתונים ועל יצירת טבלת קאש היסטוריית ביקורים/הזמנות שיעור מ-Arbox
# (bookingsReport) - בניגוד ל-arbox_entrance_counts (מונה מצטבר בלבד), כאן שורה לכל ביקור/הזמנה
# בפועל, כדי להציג "ביקורים אחרונים" לפי טלפון (ראו atlas/web/blueprints/extension_api.py).
# מפתח מורכב (phone, visit_date, class_name) כדי שסנכרון חוזר על אותו טווח תאריכים ידרוס נקי
# בלי ליצור כפילויות, באותו עקרון כמו arbox_class_cache_db.py
class ArboxVisitCacheDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arbox_visit_cache (
                phone TEXT NOT NULL,
                visit_date TEXT NOT NULL,
                visit_time TEXT,
                class_name TEXT,
                location_name TEXT,
                check_in TEXT,
                synced_at TEXT NOT NULL,
                PRIMARY KEY (phone, visit_date, class_name)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_arbox_visit_cache_phone ON arbox_visit_cache (phone)"
        )
        return conn

    def close(self):
        self.conn.close()
