import sqlite3

from atlas.data.db import DB_FILE


# אחראית על החיבור למסד הנתונים ועל יצירת טבלת ה-wamid שכבר טופלו. מונעת כפילות
# (הודעה כפולה/הזמנת תור כפולה) כשמטא שולחת שוב את אותה הודעת webhook כי התגובה
# שלנו לא הגיעה מהר מספיק - ראו WHATSAPP_CUSTOMER_BOT_PLAN.md סעיף 3.1
class WhatsAppStateDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_processed_messages (
                wamid TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL
            )
        """)
        return conn

    def close(self):
        self.conn.close()
