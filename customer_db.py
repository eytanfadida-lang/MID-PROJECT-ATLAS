import os
import sqlite3

DB_FILE = os.environ.get("DB_FILE", "appointments.db")


# אחראית על החיבור למסד הנתונים ועל יצירת הטבלאות customers ו-invoices - נפרדות מטבלת appointments
class CustomerDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY,
                name TEXT,
                phone TEXT,
                email TEXT,
                address TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                invoice_number INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER REFERENCES customers(id),
                amount REAL,
                invoice_date TEXT,
                membership_type TEXT
            )
        """)
        self._add_membership_type_column(conn)
        return conn

    # מוסיפה את עמודת membership_type לטבלת invoices שנוצרה בגרסה קודמת של האפליקציה, לפני שהעמודה הוגדרה
    @staticmethod
    def _add_membership_type_column(conn):
        columns = [row[1] for row in conn.execute("PRAGMA table_info(invoices)").fetchall()]
        if "membership_type" not in columns:
            conn.execute("ALTER TABLE invoices ADD COLUMN membership_type TEXT")

    def close(self):
        self.conn.close()
