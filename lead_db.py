import os
import sqlite3

DB_FILE = os.environ.get("DB_FILE", "appointments.db")

# סטטוסים וצבעים שנטענים כברירת מחדל בפעם הראשונה שטבלת lead_statuses נוצרת
DEFAULT_STATUSES = [
    ("חדש", "#2f80ed"),
    ("בטיפול", "#f2994a"),
    ("קיבל מידע על ההדרכות", "#17a2b8"),
    ("קיבל מידע על VIP", "#9b59b6"),
    ("לא רלוונטי", "#95a5a6"),
    ("הפך ללקוח", "#27ae60"),
    ("ליד כפול", "#e74c3c"),
]


# אחראית על החיבור למסד הנתונים ועל יצירת טבלת הלידים (leads) וטבלת הסטטוסים (lead_statuses) - נפרדות מטבלת appointments
class LeadDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT,
                phone TEXT,
                status TEXT,
                channel TEXT,
                assigned_user TEXT,
                routings_count INTEGER,
                sms_count INTEGER,
                notes TEXT,
                created_datetime_stamp TEXT,
                last_updated_datetime_stamp TEXT
            )
        """)
        has_branch_column = conn.execute(
            "SELECT COUNT(*) FROM pragma_table_info('leads') WHERE name='branch'"
        ).fetchone()[0]
        if not has_branch_column:
            conn.execute("ALTER TABLE leads ADD COLUMN branch TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS lead_statuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                color TEXT NOT NULL
            )
        """)
        has_statuses = conn.execute("SELECT COUNT(*) FROM lead_statuses").fetchone()[0]
        if not has_statuses:
            conn.executemany(
                "INSERT INTO lead_statuses (name, color) VALUES (?, ?)", DEFAULT_STATUSES
            )
            conn.commit()
        return conn

    def close(self):
        self.conn.close()
