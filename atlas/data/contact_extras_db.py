import sqlite3

from atlas.data.db import DB_FILE


# אחראית על יצירת הטבלאות של "כרטיס איש קשר" בתוסף ה-Chrome: תגיות, משימות ויומן פעילות.
# המפתח הוא מספר טלפון מנורמל (לא מזהה ליד) - כדי שאפשר יהיה לתייג/לתת משימה גם ללקוחה
# שקיימת רק ב-Arbox ואין לה ליד ב-CRM
class ContactExtrasDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contact_tags (
                phone TEXT NOT NULL,
                tag TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (phone, tag)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contact_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                title TEXT NOT NULL,
                due_date TEXT,
                done INTEGER NOT NULL DEFAULT 0,
                created_by TEXT,
                created_at TEXT NOT NULL,
                done_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contact_tasks_phone ON contact_tasks (phone)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contact_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                text TEXT NOT NULL,
                username TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contact_activity_phone ON contact_activity (phone)")
        return conn

    def close(self):
        self.conn.close()
