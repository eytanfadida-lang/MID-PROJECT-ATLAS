import sqlite3

from atlas.data.db import DB_FILE


# אחראית על החיבור למסד הנתונים ועל יצירת טבלת יומן ההודעות של בוט הלקוחות - תיעוד
# קבוע של כל הודעה נכנסת/יוצאת, בנפרד מהיסטוריית ההקשר הקצרה שמוזנת ל-LLM (זו נחתכת
# ל-6 תורים אחרונים ומתעדכנת תדיר - לא מתאימה כיומן ביקורת לבעלת העסק)
class CustomerBotMessageDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_bot_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                direction TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_bot_messages_phone ON customer_bot_messages(phone)"
        )
        return conn

    def close(self):
        self.conn.close()
