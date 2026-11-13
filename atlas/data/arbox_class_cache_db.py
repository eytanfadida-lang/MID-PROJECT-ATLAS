import sqlite3

from atlas.data.db import DB_FILE


# אחראית על החיבור למסד הנתונים ועל יצירת טבלת קאש לוח השיעורים מ-Arbox - תמונת
# מצב מקומית של השיעורים הקרובים (לא נגישה בזמן אמת בתוך webhook, ראו §3.8 בתוכנית
# ו-arbox_member_cache_db.py לאותה הנמקה בדיוק, רק כאן על לוח שיעורים ולא על מנויים)
class ArboxClassCacheDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arbox_class_cache (
                schedule_id INTEGER PRIMARY KEY,
                date TEXT NOT NULL,
                start_time TEXT,
                end_time TEXT,
                location_name TEXT,
                session_name TEXT,
                staff_name TEXT,
                max_participants INTEGER,
                synced_at TEXT NOT NULL
            )
        """)
        self._ensure_location_id_column(conn)
        return conn

    # מיגרציה קלה: מוסיפה location_id (דרוש ליצירת ליד חדש באותו סניף, ראו §3.8 -
    # שיעור ניסיון) אם עוד לא קיימת. הטבלה מתמלאת מחדש כל 15 דקות (replace_range),
    # אז NULL עד לרענון הבא זה בסדר
    @staticmethod
    def _ensure_location_id_column(conn):
        columns = {row[1] for row in conn.execute("PRAGMA table_info(arbox_class_cache)").fetchall()}
        if "location_id" not in columns:
            conn.execute("ALTER TABLE arbox_class_cache ADD COLUMN location_id INTEGER")

    def close(self):
        self.conn.close()
