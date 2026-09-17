import sqlite3

from atlas.data.db import DB_FILE


# אחראית על החיבור למסד הנתונים ועל יצירת טבלת קאש המנויים מ-Arbox - תמונת מצב
# מקומית של סטטוס המנוי (לא ליד-מיפוי, זה כבר קיים ב-leads), מרוענת כל 15 דקות
# ע"י arbox_push_sync.py. קיימת כי PythonAnywhere בתוכנית החינמית חוסם גישה יוצאת
# ל-Arbox, אז לא ניתן לשלוף בזמן אמת בתוך בקשת ה-webhook (ראו §3.8 בתוכנית)
class ArboxMemberCacheDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arbox_member_cache (
                phone TEXT PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                active INTEGER,
                membership_start_date TEXT,
                membership_end_date TEXT,
                synced_at TEXT NOT NULL
            )
        """)
        return conn

    def close(self):
        self.conn.close()
