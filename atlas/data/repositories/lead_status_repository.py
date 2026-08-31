import pandas as pd

TABLE_NAME = "lead_statuses"


# אחראית על ניהול רשימת הסטטוסים האפשריים לליד ועל הצבע המשויך לכל סטטוס
class LeadStatusRepository:
    def __init__(self, conn):
        self.conn = conn

    # מחזירה את כל הסטטוסים לפי סדר יצירתם
    def get_all(self):
        return pd.read_sql_query(f"SELECT * FROM {TABLE_NAME} ORDER BY id", self.conn)

    # מחזירה רשימת שמות הסטטוסים בלבד, לשימוש בתפריטי בחירה
    def get_names(self):
        return self.get_all()["name"].tolist()

    # מחזירה מיפוי שם סטטוס -> צבע
    def get_color_map(self):
        df = self.get_all()
        return dict(zip(df["name"], df["color"]))

    # מוסיפה סטטוס חדש עם צבע; זורקת sqlite3.IntegrityError אם השם כבר קיים
    def add(self, name, color):
        self.conn.execute(
            f"INSERT INTO {TABLE_NAME} (name, color) VALUES (?, ?)", (name, color)
        )
        self.conn.commit()

    # מעדכנת את הצבע של סטטוס קיים
    def update_color(self, status_id, color):
        self.conn.execute(
            f"UPDATE {TABLE_NAME} SET color = ? WHERE id = ?", (color, status_id)
        )
        self.conn.commit()

    # מוחקת סטטוס לפי מזהה, ומחזירה האם נמחקה רשומה בפועל
    # לידים קיימים עם סטטוס זה אינם נמחקים או משתנים - הטקסט נשאר בעמודת status
    def delete(self, status_id):
        cursor = self.conn.execute(f"DELETE FROM {TABLE_NAME} WHERE id = ?", (status_id,))
        self.conn.commit()
        return cursor.rowcount > 0
