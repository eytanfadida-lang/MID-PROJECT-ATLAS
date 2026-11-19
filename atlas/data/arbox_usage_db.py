import sqlite3

from atlas.data.db import DB_FILE


# אחראית על טבלת מונה הבקשות ל-Arbox: שורה לכל יום (שעון ישראל) ומקור (סנכרון / אוטומציות /
# בוט ותוסף), עם מספר הבקשות. ל-Arbox יש מכסה של 20,000 בקשות בחודש - המונה הוא מה שמאפשר
# לדעת איפה אנחנו (עמוד "שימוש ב-Arbox" באדמין) ולעצור את הסנכרון לפני שחורגים. טבלה שנייה
# זוכרת אילו התראות כבר נשלחו החודש, כדי שכל סף יתריע פעם אחת בלבד
class ArboxUsageDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arbox_api_usage (
                day TEXT NOT NULL,
                source TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (day, source)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arbox_usage_alerts (
                month TEXT NOT NULL,
                threshold INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (month, threshold)
            )
        """)
        return conn

    def close(self):
        self.conn.close()
