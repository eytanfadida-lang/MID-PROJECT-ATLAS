import sqlite3

from atlas.data.db import DB_FILE


# אחראית על החיבור למסד הנתונים ועל יצירת טבלת מנויי התראות הדחיפה (Web Push) - שורה אחת לכל
# מכשיר/דפדפן שהמנהלת אישרה בו קבלת התראות על הודעות חדשות מלקוחות. ה-endpoint הוא כתובת שירות
# הדחיפה של הדפדפן (גוגל/אפל/מיקרוסופט) הייחודית למכשיר, וה-p256dh/auth הם מפתחות ההצפנה שלו
# (ראו atlas/services/web_push.py). אין כאן שום תוכן הודעות - רק מי להתריע
class PushSubscriptionDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL UNIQUE,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                username TEXT,
                user_agent TEXT,
                created_at TEXT NOT NULL,
                last_success_at TEXT
            )
        """)
        return conn

    def close(self):
        self.conn.close()
