import datetime

TABLE_NAME = "customer_bot_messages"


# אחראית על יומן ההודעות הקבוע של בוט הלקוחות - לצפייה בממשק הניהול (ראו
# customer_bot_message_db.py). "direction" הוא "in" (מהלקוח) או "out" (מהבוט)
class CustomerBotMessageRepository:
    def __init__(self, conn):
        self.conn = conn

    def log(self, phone, direction, body):
        self.conn.execute(
            f"INSERT INTO {TABLE_NAME} (phone, direction, body, created_at) VALUES (?, ?, ?, ?)",
            (phone, direction, body, datetime.datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    # מחזירה סיכום שיחה אחת לכל מספר טלפון (ההודעה האחרונה + כמה הודעות בסך הכל),
    # החדש ביותר קודם - למסך הרשימה בממשק הניהול
    def get_conversation_summaries(self):
        rows = self.conn.execute(f"""
            SELECT phone,
                   COUNT(*) AS message_count,
                   MAX(created_at) AS last_message_at,
                   (SELECT body FROM {TABLE_NAME} m2
                    WHERE m2.phone = m1.phone ORDER BY m2.id DESC LIMIT 1) AS last_message_body
            FROM {TABLE_NAME} m1
            GROUP BY phone
            ORDER BY last_message_at DESC
        """).fetchall()
        return [
            {
                "phone": row[0],
                "message_count": row[1],
                "last_message_at": row[2],
                "last_message_body": row[3],
            }
            for row in rows
        ]

    def get_by_phone(self, phone):
        rows = self.conn.execute(
            f"SELECT direction, body, created_at FROM {TABLE_NAME} WHERE phone = ? ORDER BY id",
            (phone,),
        ).fetchall()
        return [{"direction": row[0], "body": row[1], "created_at": row[2]} for row in rows]
