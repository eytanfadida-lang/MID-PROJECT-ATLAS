import datetime

TABLE_NAME = "push_subscriptions"


# מנויי התראות דחיפה (ראו push_subscription_db.py). מנוי = מכשיר אחד; ההתראות על הודעות נכנסות
# נשלחות לכל המנויים (המנהלת בלבד - נרשמים רק ממשתמש אדמין, ראו blueprints/push.py)
class PushSubscriptionRepository:
    def __init__(self, conn):
        self.conn = conn

    # שומרת מנוי חדש, או מעדכנת קיים לפי ה-endpoint (אותו מכשיר שנרשם שוב / מפתחות שהתחלפו).
    # upsert ידני (לא ON CONFLICT) כדי להישאר תואם לגרסאות sqlite ישנות, כמו בשאר הפרויקט
    def upsert(self, endpoint, p256dh, auth, username=None, user_agent=None):
        cursor = self.conn.execute(
            f"UPDATE {TABLE_NAME} SET p256dh = ?, auth = ?, username = ?, user_agent = ? WHERE endpoint = ?",
            (p256dh, auth, username, user_agent, endpoint),
        )
        if cursor.rowcount == 0:
            self.conn.execute(
                f"INSERT INTO {TABLE_NAME} (endpoint, p256dh, auth, username, user_agent, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (endpoint, p256dh, auth, username, user_agent, datetime.datetime.now().isoformat(timespec="seconds")),
            )
        self.conn.commit()

    def delete_by_endpoint(self, endpoint):
        cursor = self.conn.execute(f"DELETE FROM {TABLE_NAME} WHERE endpoint = ?", (endpoint,))
        self.conn.commit()
        return cursor.rowcount > 0

    def get_all(self):
        rows = self.conn.execute(
            f"SELECT endpoint, p256dh, auth, username, user_agent, created_at, last_success_at FROM {TABLE_NAME} ORDER BY id"
        ).fetchall()
        return [
            {
                "endpoint": r[0], "p256dh": r[1], "auth": r[2], "username": r[3],
                "user_agent": r[4], "created_at": r[5], "last_success_at": r[6],
            }
            for r in rows
        ]

    def count(self):
        return self.conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]

    def mark_success(self, endpoint):
        self.conn.execute(
            f"UPDATE {TABLE_NAME} SET last_success_at = ? WHERE endpoint = ?",
            (datetime.datetime.now().isoformat(timespec="seconds"), endpoint),
        )
        self.conn.commit()
