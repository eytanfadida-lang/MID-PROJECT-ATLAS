import sqlite3

DB_FILE = "appointments.db"


# אחראית על החיבור למסד הנתונים ועל יצירת טבלת users - נפרדת משאר הטבלאות
class UserDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL
            )
        """)
        return conn

    def close(self):
        self.conn.close()
