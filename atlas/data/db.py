import os
import sqlite3

from atlas.paths import data

DB_FILE = os.environ.get("DB_FILE", str(data("appointments.db")))


# אחראית על החיבור למסד הנתונים ועל יצירת הטבלה
class AppointmentDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    # פותחת חיבור ל-SQLite ומוודאת שהטבלה appointments קיימת
    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id_client TEXT PRIMARY KEY,
                name_of_client TEXT,
                phone_client TEXT,
                name_of_store TEXT,
                appointment_date TEXT,
                appointment_time TEXT,
                created_datetime_stamp TEXT
            )
        """)
        self._ensure_customer_id_column(conn)
        return conn

    # מיגרציה קלה: מוסיפה את עמודת customer_id (מפתח זר ללקוח) אם עוד לא קיימת -
    # כך שגם מסדי נתונים קיימים מהגרסה הקודמת ימשיכו לעבוד
    @staticmethod
    def _ensure_customer_id_column(conn):
        columns = [row[1] for row in conn.execute("PRAGMA table_info(appointments)").fetchall()]
        if "customer_id" not in columns:
            conn.execute("ALTER TABLE appointments ADD COLUMN customer_id INTEGER REFERENCES customers(id)")

    def close(self):
        self.conn.close()
