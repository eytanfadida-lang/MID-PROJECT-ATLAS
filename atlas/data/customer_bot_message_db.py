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
        self._ensure_columns(conn)
        return conn

    # מיגרציה קלה: מוסיפה עמודות חדשות אם עוד לא קיימות -
    # bot_phone_number_id: באיזה מהמספרים שלנו התנהלה השיחה (רלוונטי מרגע שכמה
    #   מספרים רשמיים מחוברים לאותה אפליקציה)
    # attachment_url: קישור לקובץ/תמונה מצורפים (נשמר תחת static/uploads, ראו
    #   bot_conversations.py) - להצגה בתוך בועת הצ'אט בממשק הניהול
    @staticmethod
    def _ensure_columns(conn):
        columns = {row[1] for row in conn.execute("PRAGMA table_info(customer_bot_messages)").fetchall()}
        new_columns = {"bot_phone_number_id": "TEXT", "attachment_url": "TEXT"}
        for name, column_type in new_columns.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE customer_bot_messages ADD COLUMN {name} {column_type}")

    def close(self):
        self.conn.close()
