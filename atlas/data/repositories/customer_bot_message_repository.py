import datetime

TABLE_NAME = "customer_bot_messages"

# פונקציות שנקראות על כל הודעה *נכנסת* (מהלקוחה) מיד אחרי שנרשמה ביומן: (phone, body, attachment_url).
# נרשמות באתחול האפליקציה (ראו factory.py) - כך התראות דחיפה (atlas/services/web_push.py) מקבלות כל
# הודעה נכנסת ממקום אחד, בלי להוסיף קריאה בכל אחד מהמסלולים השונים ב-webhook (טקסט/תמונה/קולית/תגובה...).
# כשל בפונקציה כזו לעולם לא מפיל את רישום ההודעה
incoming_listeners = []


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
    # created_at: ברירת המחדל "עכשיו"; הודעה שהגיעה מחשבון מקושר נושאת את זמן השליחה האמיתי שלה.
    # delivery_status: למשל 'queued' להודעה יוצאת שממתינה בתור. מחזירה את מזהה השורה שנוצרה
    def log(self, phone, direction, body, bot_phone_number_id=None, attachment_url=None, wamid=None,
            created_at=None, delivery_status=None):
        cursor = self.conn.execute(
            f"INSERT INTO {TABLE_NAME} (phone, direction, body, created_at, bot_phone_number_id, "
            "attachment_url, wamid, delivery_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                phone,
                direction,
                body,
                created_at or datetime.datetime.now().isoformat(timespec="seconds"),
                bot_phone_number_id,
                attachment_url,
                wamid,
                delivery_status,
            ),
        )
        message_id = cursor.lastrowid
        self.conn.commit()
        if direction == "in":
            for listener in incoming_listeners:
                try:
                    listener(phone, body, attachment_url)
                except Exception:  # noqa: BLE001
                    pass
        return message_id

    # כמו update_delivery_status, אבל הסטטוס רק מתקדם (sent < delivered < read; failed נקבע רק אם עוד לא נמסרה) -
    # עדכוני קבלה מגיעים לפעמים בסדר הפוך. מחזירה כמה שורות עודכנו
    def advance_delivery_status(self, wamid, status):
        rank = {"queued": 1, "sent": 2, "delivered": 3, "read": 4}
        new_rank = 5 if status == "failed" else rank.get(status, 0)
        row = self.conn.execute(f"SELECT delivery_status FROM {TABLE_NAME} WHERE wamid = ? LIMIT 1", (wamid,)).fetchone()
        if not row:
            return 0
        current = row[0]
        current_rank = 5 if current == "failed" else rank.get(current, 0)
        if status == "failed" and current_rank >= 3:
            return 0
        if new_rank <= current_rank and status != "failed":
            return 0
        self.conn.execute(f"UPDATE {TABLE_NAME} SET delivery_status = ? WHERE wamid = ?", (status, wamid))
        self.conn.commit()
        return 1

    def wamid_exists(self, wamid):
        return self.conn.execute(f"SELECT 1 FROM {TABLE_NAME} WHERE wamid = ? LIMIT 1", (wamid,)).fetchone() is not None

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
                    WHERE m2.phone = m1.phone AND m2.deleted_at IS NULL
                    ORDER BY m2.id DESC LIMIT 1) AS last_message_body,
                   (SELECT bot_phone_number_id FROM {TABLE_NAME} m3
                    WHERE m3.phone = m1.phone AND m3.bot_phone_number_id IS NOT NULL
                    ORDER BY m3.id DESC LIMIT 1) AS bot_phone_number_id,
                   (SELECT last_read_message_id FROM bot_conversation_read_state r
                    WHERE r.phone = m1.phone) AS last_read_message_id
            FROM {TABLE_NAME} m1
            WHERE m1.deleted_at IS NULL
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
                # המזהה של ההודעה הנכנסת האחרונה - None אם הלקוחה מעולם לא כתבה (רק הודעות יוצאות).
                # בשימוש לכפתור "סמן כלא נקרא", שאפשרי רק כשיש הודעה נכנסת לסמן
                "last_incoming_message_id": row[3],
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

    # כמה שיחות מחכות לתשובה (יש בהן הודעה נכנסת שעוד לא נקראה) - לתגית בסרגל הניווט. שאילתה אחת
    # מצטברת, בלי המידע המלא של get_conversation_summaries (שמריצה שאילתות משנה לכל שיחה)
    def count_unread_conversations(self):
        return self.conn.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT phone, MAX(CASE WHEN direction = 'in' THEN id END) AS last_in
                FROM {TABLE_NAME} WHERE deleted_at IS NULL GROUP BY phone
            ) t LEFT JOIN bot_conversation_read_state r ON r.phone = t.phone
            WHERE t.last_in IS NOT NULL AND (r.last_read_message_id IS NULL OR r.last_read_message_id < t.last_in)
        """).fetchone()[0]

    # הופכת שיחה ל"לא נקראה" ידנית: מחזירה את מצב הקריאה להודעה שלפני ההודעה הנכנסת האחרונה,
    # כך שההודעה הזו נחשבת שוב חדשה (ראו get_conversation_summaries). אפשרי רק לשיחה שיש בה
    # הודעה נכנסת אחת לפחות - אחרת אין מה "לא לקרוא" (הודעות יוצאות לא נחשבות לא-נקראות).
    # מחזירה True אם הסימון בוצע, False אם אין הודעה נכנסת
    def mark_unread(self, phone):
        last_incoming_id = self.conn.execute(
            f"SELECT MAX(id) FROM {TABLE_NAME} WHERE phone = ? AND direction = 'in' AND deleted_at IS NULL",
            (phone,),
        ).fetchone()[0]
        if last_incoming_id is None:
            return False
        self.conn.execute("DELETE FROM bot_conversation_read_state WHERE phone = ?", (phone,))
        self.conn.execute(
            "INSERT INTO bot_conversation_read_state (phone, last_read_message_id) VALUES (?, ?)",
            (phone, last_incoming_id - 1),
        )
        self.conn.commit()
        return True

    # "חתימה" זולה של מצב כל השיחות (הודעה אחרונה + מצב קריאה) - העמוד בודק אותה כל כמה שניות
    # (ראו bot_conversations.poll_state) וטוען מחדש את הרשימה/השיחה רק כשהיא משתנה, כדי שלא
    # נריץ את השאילתות הכבדות של הרשימה (כולל חיפוש בקאש Arbox לכל שיחה) בכל בדיקה
    def get_state_signature(self):
        max_id = self.conn.execute(f"SELECT MAX(id) FROM {TABLE_NAME}").fetchone()[0] or 0
        read_count, read_sum = self.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(last_read_message_id), 0) FROM bot_conversation_read_state"
        ).fetchone()
        deleted_count = self.conn.execute(
            f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE deleted_at IS NOT NULL"
        ).fetchone()[0]
        # סטטוס משלוח של ההודעות (נשלחת/נמסרה/נקראה/נכשלה) משתנה בלי הודעה חדשה - נכלל בחתימה כדי שהתצוגה תתרענן
        status_score = self.conn.execute(
            f"SELECT COALESCE(SUM(CASE delivery_status WHEN 'queued' THEN 1 WHEN 'sent' THEN 2 WHEN 'delivered' THEN 3 "
            f"WHEN 'read' THEN 4 WHEN 'failed' THEN 5 ELSE 0 END), 0) FROM {TABLE_NAME}"
        ).fetchone()[0]
        return f"{max_id}:{read_count}:{read_sum}:{deleted_count}:{status_score}"

    def get_by_phone(self, phone):
        rows = self.conn.execute(
            f"SELECT direction, body, created_at, attachment_url, delivery_status, id FROM {TABLE_NAME} "
            "WHERE phone = ? AND deleted_at IS NULL ORDER BY id",
            (phone,),
        ).fetchall()
        return [
            {
                "direction": row[0], "body": row[1], "created_at": row[2], "attachment_url": row[3],
                "delivery_status": row[4], "id": row[5],
            }
            for row in rows
        ]

    # מוחקת הודעה מהיומן בממשק - מחיקה "רכה" (deleted_at), לא פיזית: ההודעה נשארת במסד ולכן לא
    # משבשת את get_last_incoming_at (חלון 24 השעות של וואטסאפ קיים בפועל גם אם מחקנו את ההודעה
    # מהתצוגה). חשוב: זה לא מוחק את ההודעה מוואטסאפ של הלקוחה - ל-Cloud API אין אפשרות כזו.
    # בודקת שההודעה שייכת לטלפון הנתון (אי אפשר למחוק הודעה של שיחה אחרת דרך כתובת מזויפת).
    # מחזירה את מספר ההודעות שנשארו בשיחה (לא נמחקו), או None אם ההודעה לא נמצאה/כבר נמחקה
    def delete_message(self, phone, message_id):
        cursor = self.conn.execute(
            f"UPDATE {TABLE_NAME} SET deleted_at = ? WHERE id = ? AND phone = ? AND deleted_at IS NULL",
            (datetime.datetime.now().isoformat(timespec="seconds"), message_id, phone),
        )
        self.conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.conn.execute(
            f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE phone = ? AND deleted_at IS NULL", (phone,)
        ).fetchone()[0]

    # שולפת הודעה בודדת (לפי שייכות לטלפון, אותה בדיקה כמו edit_message/delete_message) -
    # נחוצה לפני עריכה כדי לדעת את ה-direction וממנה לענות (bot_phone_number_id), כדי
    # להחליט אם לשלוח גם תיקון אמיתי בוואטסאפ (רק להודעות יוצאות, ראו edit_message בבלופרינט)
    def get_by_id(self, phone, message_id):
        row = self.conn.execute(
            f"SELECT id, direction, body, bot_phone_number_id FROM {TABLE_NAME} "
            "WHERE id = ? AND phone = ? AND deleted_at IS NULL",
            (message_id, phone),
        ).fetchone()
        if not row:
            return None
        return {"id": row[0], "direction": row[1], "body": row[2], "bot_phone_number_id": row[3]}

    # בודקת אם הבוט מושהה לשיחה הזו (נציגה אנושית כותבת ישירות) - ראו set_bot_paused.
    # נבדקת ב-webhooks.py לפני כל טיפול בבוט (גם לפני fallback של הודעה לא-טקסטואלית)
    def is_bot_paused(self, phone):
        row = self.conn.execute(
            "SELECT 1 FROM bot_paused_conversations WHERE phone = ?", (phone,)
        ).fetchone()
        return row is not None

    # משהה/מפעילה מחדש את הבוט לשיחה נתונה - נוכחות שורה בטבלה = מושהה. נקראת מכפתור
    # "השהה בוט"/"הפעל בוט" בראש השיחה בממשק, כשנציגה מתכתבת ישירות עם הלקוחה והתערבות
    # אוטומטית של הבוט מפריעה לשיחה
    def set_bot_paused(self, phone, paused):
        if paused:
            self.conn.execute(
                "INSERT OR REPLACE INTO bot_paused_conversations (phone, paused_at) VALUES (?, ?)",
                (phone, datetime.datetime.now().isoformat(timespec="seconds")),
            )
        else:
            self.conn.execute("DELETE FROM bot_paused_conversations WHERE phone = ?", (phone,))
        self.conn.commit()

    # עורכת את טקסט ההודעה ביומן בממשק - רק התיעוד המקומי אצלנו, לא ההודעה עצמה שכבר
    # נשלחה/התקבלה בוואטסאפ (לא קיים API למטא לערוך הודעה שכבר נשלחה/התקבלה). שימושי
    # למשל לתקן טעות הקלדה בתיעוד או להבהיר הודעה לא-טקסטואלית. אותה בדיקת שייכות-לטלפון
    # כמו delete_message. מחזירה True אם עודכן, False אם ההודעה לא נמצאה/כבר נמחקה
    def edit_message(self, phone, message_id, new_body):
        cursor = self.conn.execute(
            f"UPDATE {TABLE_NAME} SET body = ? WHERE id = ? AND phone = ? AND deleted_at IS NULL",
            (new_body, message_id, phone),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    # מוצאת את מספר-הבוט האחרון שבו נוהלה שיחה עם לקוח נתון - כדי שתגובה ידנית
    # (ראו bot_conversations.py) תישלח מאותו מספר, לא תמיד מברירת המחדל
    def get_latest_bot_phone_number_id(self, phone):
        row = self.conn.execute(
            f"SELECT bot_phone_number_id FROM {TABLE_NAME} "
            "WHERE phone = ? AND bot_phone_number_id IS NOT NULL ORDER BY id DESC LIMIT 1",
            (phone,),
        ).fetchone()
        return row[0] if row else None

    # (בכוונה כולל הודעות שנמחקו מהיומן - ראו delete_message)
    # מתי הלקוחה כתבה לבוט לאחרונה (direction='in') - בשימוש לבדיקת "חלון 24 השעות" של
    # וואטסאפ (ראו atlas/automations/engine.py, process_due_action) לפני שליחת הודעה חופשית.
    # None אם מעולם לא כתבה (למשל "לקוחות פעילים" ששלחנו להן יזום, לא בתגובה לפנייה שלהן)
    def get_last_incoming_at(self, phone):
        row = self.conn.execute(
            f"SELECT MAX(created_at) FROM {TABLE_NAME} WHERE phone = ? AND direction = 'in'",
            (phone,),
        ).fetchone()
        return row[0] if row else None
