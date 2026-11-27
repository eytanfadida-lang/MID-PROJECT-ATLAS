import datetime
import hashlib
import secrets

TABLE_NAME = "api_tokens"


def _hash_token(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# אחראית על טוקני-API פר-משתמש (תוסף ה-Chrome מתחבר עם שם משתמש+סיסמה פעם אחת - ראו
# extension_api.py - ומקבל טוקן שנשמר במקום ה-session/עוגייה הרגילים). ראו atlas/core/api_auth.py
# לבדיקת הטוקן בכל בקשה
class ApiTokenRepository:
    def __init__(self, conn):
        self.conn = conn

    # יוצרת טוקן חדש למשתמש נתון (label - למשל שם המכשיר/תוסף), ומחזירה את הטוקן הגולמי
    # (היחיד שמוצג פעם אחת - אחר כך יש רק את ה-hash שלו)
    def create(self, user_id, label=""):
        raw_token = secrets.token_urlsafe(32)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            f"INSERT INTO {TABLE_NAME} (user_id, token_hash, label, created_at) VALUES (?, ?, ?, ?)",
            (user_id, _hash_token(raw_token), label, now),
        )
        self.conn.commit()
        return raw_token

    # מאמתת טוקן גולמי (מכותרת Authorization: Bearer) ומחזירה dict עם פרטי המשתמש אם תקף
    # ולא בוטל, אחרת None. מעדכנת גם את last_used_at כאגב
    def get_user_by_token(self, raw_token):
        row = self.conn.execute(
            f"SELECT api_tokens.id, users.id, users.username, users.role, users.permissions "
            f"FROM {TABLE_NAME} "
            f"JOIN users ON users.id = api_tokens.user_id "
            f"WHERE api_tokens.token_hash = ? AND api_tokens.revoked_at IS NULL",
            (_hash_token(raw_token),),
        ).fetchone()
        if row is None:
            return None
        token_id, user_id, username, role, permissions = row
        now = datetime.datetime.now().isoformat(timespec="seconds")
        self.conn.execute(f"UPDATE {TABLE_NAME} SET last_used_at = ? WHERE id = ?", (now, token_id))
        self.conn.commit()
        return {
            "id": user_id, "username": username, "role": role, "permissions": permissions,
            "token_id": token_id,
        }

    # מבטלת טוקן קיים (לא מוחקת - נשאר לתיעוד "מי היה מחובר עד מתי")
    def revoke(self, token_id):
        now = datetime.datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            f"UPDATE {TABLE_NAME} SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (now, token_id)
        )
        self.conn.commit()

    # כל הטוקנים (פעילים ומבוטלים) עם שם המשתמש - לעמוד ניהול הטוקנים באדמין
    def list_all(self):
        rows = self.conn.execute(
            f"SELECT api_tokens.id, users.username, api_tokens.label, api_tokens.created_at, "
            f"api_tokens.last_used_at, api_tokens.revoked_at "
            f"FROM {TABLE_NAME} JOIN users ON users.id = api_tokens.user_id "
            f"ORDER BY api_tokens.revoked_at IS NOT NULL, api_tokens.created_at DESC"
        ).fetchall()
        return [
            {
                "id": row[0], "username": row[1], "label": row[2],
                "created_at": row[3], "last_used_at": row[4], "revoked_at": row[5],
            }
            for row in rows
        ]
