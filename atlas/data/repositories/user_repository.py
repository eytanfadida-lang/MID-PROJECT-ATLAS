import json

import pandas as pd

from atlas.core.password_hashing import hash_password, verify_password

TABLE_NAME = "users"


# אחראית על כל הגישה לנתונים (CRUD + אימות) מול טבלת users
class UserRepository:
    def __init__(self, conn):
        self.conn = conn
        self._ensure_permissions_column()

    def _ensure_permissions_column(self):
        columns = self.conn.execute(f"PRAGMA table_info({TABLE_NAME})").fetchall()
        if any(column[1] == "permissions" for column in columns):
            return
        self.conn.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN permissions TEXT DEFAULT '[]'")
        self.conn.commit()

    @staticmethod
    def _permissions_to_text(permissions):
        return json.dumps(permissions or [])

    @staticmethod
    def _permissions_from_text(value):
        if not value:
            return []
        return json.loads(value)

    # יוצרת משתמש חדש עם סיסמה מסולסלת (hash+salt), ומחזירה את המזהה שנוצר.
    # זורקת sqlite3.IntegrityError אם שם המשתמש כבר קיים (UNIQUE constraint)
    def create(self, username, password, role, permissions=None):
        password_hash, salt = hash_password(password)
        permissions_text = self._permissions_to_text(permissions)
        cursor = self.conn.execute(
            f"INSERT INTO {TABLE_NAME} (username, password_hash, salt, role, permissions) VALUES (?, ?, ?, ?, ?)",
            (username, password_hash, salt, role, permissions_text),
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
        result = df.iloc[0].to_dict()
        result["permissions"] = self._permissions_from_text(result.get("permissions"))
        return result

    # מחזירה משתמש לפי מזהה, או None אם לא נמצא
    def get_by_id(self, user_id):
        df = pd.read_sql_query(
            f"SELECT * FROM {TABLE_NAME} WHERE id = ?", self.conn, params=(user_id,)
        )
        if df.empty:
            return None
        result = df.iloc[0].to_dict()
        result["permissions"] = self._permissions_from_text(result.get("permissions"))
        return result

    # מחזירה את כל המשתמשים (ללא עמודות הסיסמה) כ-DataFrame
    def get_all(self):
        df = pd.read_sql_query(f"SELECT id, username, role, permissions FROM {TABLE_NAME}", self.conn)
        df["permissions"] = df["permissions"].apply(self._permissions_from_text)
        return df

    # מעדכנת את שם המשתמש; זורקת sqlite3.IntegrityError אם השם החדש כבר תפוס (UNIQUE constraint)
    def update_username(self, user_id, username):
        self.conn.execute(f"UPDATE {TABLE_NAME} SET username = ? WHERE id = ?", (username, user_id))
        self.conn.commit()

    def update_role(self, user_id, role):
        self.conn.execute(f"UPDATE {TABLE_NAME} SET role = ? WHERE id = ?", (role, user_id))
        self.conn.commit()

    def update_password(self, user_id, password):
        password_hash, salt = hash_password(password)
        self.conn.execute(
            f"UPDATE {TABLE_NAME} SET password_hash = ?, salt = ? WHERE id = ?",
            (password_hash, salt, user_id),
        )
        self.conn.commit()

    def update_permissions(self, user_id, permissions):
        permissions_text = self._permissions_to_text(permissions)
        self.conn.execute(
            f"UPDATE {TABLE_NAME} SET permissions = ? WHERE id = ?",
            (permissions_text, user_id),
        )
        self.conn.commit()

    def delete(self, user_id):
        self.conn.execute(f"DELETE FROM {TABLE_NAME} WHERE id = ?", (user_id,))
        self.conn.commit()

    # בודקת שם משתמש+סיסמה מול הרשומה השמורה, ומחזירה את ה-role בהצלחה או None בכישלון
    def authenticate(self, username, password):
        user = self.get_by_username(username)
        if user is None:
            return None
        if not verify_password(password, user["salt"], user["password_hash"]):
            return None
        return user["role"]
