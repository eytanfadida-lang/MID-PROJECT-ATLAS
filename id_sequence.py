import sqlite3


# אחראית על הקצאת מזהים ייחודיים המשותפים בין תורים (id_client) ולקוחות (customer id),
# כדי שלעולם לא יהיה ערך זהה בין השניים
class IdSequence:
    def __init__(self, conn):
        self.conn = conn
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS id_sequence (
                id INTEGER PRIMARY KEY AUTOINCREMENT
            )
        """)
        self._seed_if_empty()

    # בהרצה הראשונה (טבלה ריקה) - מוצא את המזהה הגבוה ביותר שכבר קיים בנתונים
    # (מתורים ומלקוחות ישנים) וממשיך מהמספר שאחריו, כדי לא להתנגש בנתונים קיימים
    def _seed_if_empty(self):
        count = self.conn.execute("SELECT COUNT(*) FROM id_sequence").fetchone()[0]
        if count > 0:
            return

        max_existing = self._max_existing_id()
        if max_existing > 0:
            self.conn.execute("INSERT INTO id_sequence (id) VALUES (?)", (max_existing,))
            self.conn.commit()

    def _max_existing_id(self):
        max_id = 0

        try:
            rows = self.conn.execute("SELECT id_client FROM appointments").fetchall()
            for (value,) in rows:
                if value and value.isdigit():
                    max_id = max(max_id, int(value))
        except sqlite3.OperationalError:
            pass

        try:
            rows = self.conn.execute("SELECT id FROM customers").fetchall()
            for (value,) in rows:
                if value is not None:
                    max_id = max(max_id, int(value))
        except sqlite3.OperationalError:
            pass

        return max_id

    # מקצה ומחזירה מזהה חדש וייחודי
    def next_id(self):
        cursor = self.conn.execute("INSERT INTO id_sequence DEFAULT VALUES")
        self.conn.commit()
        return cursor.lastrowid
