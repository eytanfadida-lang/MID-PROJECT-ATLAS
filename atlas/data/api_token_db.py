import sqlite3

from atlas.data.db import DB_FILE


# אחראית על החיבור למסד הנתונים ועל יצירת טבלת טוקני-API פר-משתמש - משמשת את תוסף ה-Chrome
# (ראו atlas/web/blueprints/extension_api.py) להזדהות מול השרת בלי session/עוגיית דפדפן.
# שומרים רק את ה-hash של הטוקן (לא את הטוקן הגולמי עצמו) - כמו סיסמה, כדי שדליפת ה-DB
# לא תחשוף ישירות גישה לחשבונות
class ApiTokenDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                revoked_at TEXT
            )
        """)
        return conn

    def close(self):
        self.conn.close()
