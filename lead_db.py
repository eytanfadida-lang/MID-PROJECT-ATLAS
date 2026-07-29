import sqlite3

DB_FILE = "appointments.db"


# אחראית על החיבור למסד הנתונים ועל יצירת טבלת הלידים (leads) - נפרדת מטבלת appointments
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
        return conn

    def close(self):
        self.conn.close()
