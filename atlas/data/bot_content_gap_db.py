import sqlite3

from atlas.data.db import DB_FILE


# אחראית על החיבור למסד הנתונים ועל יצירת טבלת "פערי תוכן" - שאלות של לקוחות שבוט
# הלקוחות לא הצליח לענות עליהן מתוך business_info.md ולא באמצעות אף כלי. לפי ההחלטה
# ב-WHATSAPP_CUSTOMER_BOT_PLAN.md סעיף 3.5: הבוט לא "לומד" את עצמו אוטומטית מהשיחות
# (סיכון להטמעת מידע שגוי) - רק מתעד כאן, ובן אדם בוחן את הרשימה ומחליט מה להוסיף
# ל-business_info.md
class BotContentGapDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_content_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                question TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            )
        """)
        return conn

    def close(self):
        self.conn.close()
