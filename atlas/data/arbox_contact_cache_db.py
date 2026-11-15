import sqlite3

from atlas.data.db import DB_FILE


# אחראית על קאש של משתמשי Arbox שאינם לקוחות (לידים, עובדות, מנויי אגרגטור כמו FreeFit) - בשביל
# כרטיס איש הקשר בתוסף ה-Chrome. נפרד בכוונה מ-arbox_member_cache: הבוט משתמש שם ב"לא נמצא" כדי
# לדעת שמישהי אינה לקוחה, ושילוב לידים באותה טבלה היה גורם לו לענות לליד כאילו המנוי שלה הסתיים
class ArboxContactCacheDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arbox_contact_cache (
                phone TEXT PRIMARY KEY,
                user_id INTEGER,
                first_name TEXT,
                last_name TEXT,
                role TEXT,
                email TEXT,
                birthday TEXT,
                location_id INTEGER,
                created_date TEXT,
                synced_at TEXT NOT NULL
            )
        """)
        return conn

    def close(self):
        self.conn.close()
