import datetime

TABLE_NAME = "customer_bot_messages"


# אחראית על יומן ההודעות הקבוע של בוט הלקוחות - לצפייה בממשק הניהול (ראו
# customer_bot_message_db.py). "direction" הוא "in" (מהלקוח) או "out" (מהבוט).
# bot_phone_number_id הוא איזה מהמספרים שלנו התנהלה בו השיחה - רלוונטי מרגע
# שכמה מספרים רשמיים מחוברים לאותה אפליקציה (ראו webhooks.py)
class CustomerBotMessageRepository:
    def __init__(self, conn):
        self.conn = conn

    def log(self, phone, direction, body, bot_phone_number_id=None, attachment_url=None):
        self.conn.execute(
            f"INSERT INTO {TABLE_NAME} (phone, direction, body, created_at, bot_phone_number_id, attachment_url) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                phone,
                direction,
                body,
                datetime.datetime.now().isoformat(timespec="seconds"),
                bot_phone_number_id,
                attachment_url,
            ),
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
                    WHERE m2.phone = m1.phone ORDER BY m2.id DESC LIMIT 1) AS last_message_body,
                   (SELECT bot_phone_number_id FROM {TABLE_NAME} m3
                    WHERE m3.phone = m1.phone AND m3.bot_phone_number_id IS NOT NULL
                    ORDER BY m3.id DESC LIMIT 1) AS bot_phone_number_id
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
                "bot_phone_number_id": row[4],
            }
            for row in rows
        ]

    def get_by_phone(self, phone):
        rows = self.conn.execute(
            f"SELECT direction, body, created_at, attachment_url FROM {TABLE_NAME} WHERE phone = ? ORDER BY id",
            (phone,),
        ).fetchall()
        return [
            {"direction": row[0], "body": row[1], "created_at": row[2], "attachment_url": row[3]}
            for row in rows
        ]

    # מוצאת את מספר-הבוט האחרון שבו נוהלה שיחה עם לקוח נתון - כדי שתגובה ידנית
    # (ראו bot_conversations.py) תישלח מאותו מספר, לא תמיד מברירת המחדל
    def get_latest_bot_phone_number_id(self, phone):
        row = self.conn.execute(
            f"SELECT bot_phone_number_id FROM {TABLE_NAME} "
            "WHERE phone = ? AND bot_phone_number_id IS NOT NULL ORDER BY id DESC LIMIT 1",
            (phone,),
        ).fetchone()
        return row[0] if row else None
