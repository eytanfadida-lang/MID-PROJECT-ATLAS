import sqlite3

from atlas.data.db import DB_FILE


# אחראית על החיבור למסד הנתונים ועל יצירת טבלאות "תגובות מהירות" - הודעות שמורות שהמנהלת מכניסה
# בלחיצה לתיבת הכתיבה בעמוד שיחות הבוט (כותרת, טקסט, קטגוריה, מועדף). הקטגוריות נשמרות בטבלה
# נפרדת כדי שקטגוריה חדשה תופיע גם לפני שיש בה תגובה
class QuickReplyDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quick_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                favorite INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quick_reply_categories (
                name TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
        """)
        return conn

    def close(self):
        self.conn.close()
