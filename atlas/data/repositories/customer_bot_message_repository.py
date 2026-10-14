import datetime

TABLE_NAME = "customer_bot_messages"


# אחראית על יומן ההודעות הקבוע של בוט הלקוחות - לצפייה בממשק הניהול (ראו
# customer_bot_message_db.py). "direction" הוא "in" (מהלקוח) או "out" (מהבוט).
# bot_phone_number_id הוא איזה מהמספרים שלנו התנהלה בו השיחה - רלוונטי מרגע
# שכמה מספרים רשמיים מחוברים לאותה אפליקציה (ראו webhooks.py)
class CustomerBotMessageRepository:
    def __init__(self, conn):
        self.conn = conn

    # wamid: מזהה ההודעה שהוחזר מוואטסאפ (רק להודעות יוצאות, direction='out') - מפתח
    # לקישור חזרה לעדכון סטטוס משלוח עתידי (ראו update_delivery_status). None עבור הודעות
    # נכנסות (אין "שליחה" שלנו) או אם השליחה נכשלה לפני שהוחזר wamid בכלל
    def log(self, phone, direction, body, bot_phone_number_id=None, attachment_url=None, wamid=None):
        self.conn.execute(
            f"INSERT INTO {TABLE_NAME} (phone, direction, body, created_at, bot_phone_number_id, "
            "attachment_url, wamid) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                phone,
                direction,
                body,
                datetime.datetime.now().isoformat(timespec="seconds"),
                bot_phone_number_id,
                attachment_url,
                wamid,
            ),
        )
        self.conn.commit()

    # מעדכנת את סטטוס המשלוח (sent/delivered/read/failed) לפי wamid - נקראת מ-webhook עדכוני
    # סטטוס אמיתי מוואטסאפ (ראו atlas/web/webhooks.py, whatsapp_customer_webhook). לא כל
    # wamid נמצא כאן (ייתכן שהוא שייך להודעה שנרשמה רק ב-automation_executions, לא כאן) -
    # זה בסדר, פשוט לא מתעדכן כלום (0 שורות הושפעו)
    def update_delivery_status(self, wamid, status):
        self.conn.execute(f"UPDATE {TABLE_NAME} SET delivery_status = ? WHERE wamid = ?", (status, wamid))
        self.conn.commit()

    # מחזירה סיכום שיחה אחת לכל מספר טלפון (ההודעה האחרונה + כמה הודעות בסך הכל),
    # החדש ביותר קודם - למסך הרשימה בממשק הניהול. "unread" - יש הודעה **נכנסת** (מהלקוחה,
    # direction='in') חדשה (לפי id, לא timestamp - ראו mark_read) מאז שהשיחה נפתחה לאחרונה.
    # הודעות יוצאות (תגובה ידנית/אוטומטית/אוטומציה) לא הופכות שיחה ל"לא נקראה" - זו הודעה
    # שאנחנו שלחנו ביודעין, לא משהו שהלקוחה שלחה אלינו וטרם ראינו
    def get_conversation_summaries(self):
        rows = self.conn.execute(f"""
            SELECT phone,
                   COUNT(*) AS message_count,
                   MAX(created_at) AS last_message_at,
                   MAX(CASE WHEN direction = 'in' THEN id END) AS last_incoming_message_id,
                   (SELECT body FROM {TABLE_NAME} m2
                    WHERE m2.phone = m1.phone ORDER BY m2.id DESC LIMIT 1) AS last_message_body,
                   (SELECT bot_phone_number_id FROM {TABLE_NAME} m3
                    WHERE m3.phone = m1.phone AND m3.bot_phone_number_id IS NOT NULL
                    ORDER BY m3.id DESC LIMIT 1) AS bot_phone_number_id,
                   (SELECT last_read_message_id FROM bot_conversation_read_state r
                    WHERE r.phone = m1.phone) AS last_read_message_id
            FROM {TABLE_NAME} m1
            GROUP BY phone
            ORDER BY last_message_at DESC
        """).fetchall()
        return [
            {
                "phone": row[0],
                "message_count": row[1],
                "last_message_at": row[2],
                "last_message_body": row[4],
                "bot_phone_number_id": row[5],
                "unread": row[3] is not None and (row[6] is None or row[6] < row[3]),
            }
            for row in rows
        ]

    # קוראת לשיחה - נקראת כשהמנהלת פותחת אותה (ראו bot_conversations.view_conversation).
    # upsert ידני (לא ON CONFLICT) כדי להישאר תואם לגרסאות sqlite ישנות שכבר בשימוש בפרויקט.
    # שקטה (לא זורקת) אם אין עדיין הודעות לטלפון הזה - פשוט לא עושה כלום
    def mark_read(self, phone):
        last_id = self.conn.execute(
            f"SELECT MAX(id) FROM {TABLE_NAME} WHERE phone = ?", (phone,)
        ).fetchone()[0]
        if last_id is None:
            return
        self.conn.execute("DELETE FROM bot_conversation_read_state WHERE phone = ?", (phone,))
        self.conn.execute(
            "INSERT INTO bot_conversation_read_state (phone, last_read_message_id) VALUES (?, ?)",
            (phone, last_id),
        )
        self.conn.commit()

    def get_by_phone(self, phone):
        rows = self.conn.execute(
            f"SELECT direction, body, created_at, attachment_url, delivery_status FROM {TABLE_NAME} "
            "WHERE phone = ? ORDER BY id",
            (phone,),
        ).fetchall()
        return [
            {
                "direction": row[0], "body": row[1], "created_at": row[2], "attachment_url": row[3],
                "delivery_status": row[4],
            }
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

    # מתי הלקוחה כתבה לבוט לאחרונה (direction='in') - בשימוש לבדיקת "חלון 24 השעות" של
    # וואטסאפ (ראו atlas/automations/engine.py, process_due_action) לפני שליחת הודעה חופשית.
    # None אם מעולם לא כתבה (למשל "לקוחות פעילים" ששלחנו להן יזום, לא בתגובה לפנייה שלהן)
    def get_last_incoming_at(self, phone):
        row = self.conn.execute(
            f"SELECT MAX(created_at) FROM {TABLE_NAME} WHERE phone = ? AND direction = 'in'",
            (phone,),
        ).fetchone()
        return row[0] if row else None
