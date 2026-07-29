import pandas as pd

from password_hashing import hash_password, verify_password

TABLE_NAME = "users"


# אחראית על כל הגישה לנתונים (CRUD + אימות) מול טבלת users
class UserRepository:
    def __init__(self, conn):
        self.conn = conn

    # יוצרת משתמש חדש עם סיסמה מסולסלת (hash+salt), ומחזירה את המזהה שנוצר.
    # זורקת sqlite3.IntegrityError אם שם המשתמש כבר קיים (UNIQUE constraint)
    def create(self, username, password, role):
        password_hash, salt = hash_password(password)
        cursor = self.conn.execute(
            f"INSERT INTO {TABLE_NAME} (username, password_hash, salt, role) VALUES (?, ?, ?, ?)",
            (username, password_hash, salt, role),
        )
        self.conn.commit()
        return cursor.lastrowid

    # מחזירה משתמש לפי שם, או None אם לא נמצא
    def get_by_username(self, username):
        df = pd.read_sql_query(
            f"SELECT * FROM {TABLE_NAME} WHERE username = ?", self.conn, params=(username,)
        )
        if df.empty:
            return None
        return df.iloc[0].to_dict()

    # מחזירה את כל המשתמשים (ללא עמודות הסיסמה) כ-DataFrame
    def get_all(self):
        return pd.read_sql_query(f"SELECT id, username, role FROM {TABLE_NAME}", self.conn)

    # בודקת שם משתמש+סיסמה מול הרשומה השמורה, ומחזירה את ה-role בהצלחה או None בכישלון
    def authenticate(self, username, password):
        user = self.get_by_username(username)
        if user is None:
            return None
        if not verify_password(password, user["salt"], user["password_hash"]):
            return None
        return user["role"]
