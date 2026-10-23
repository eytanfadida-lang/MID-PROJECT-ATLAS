import sqlite3

from atlas.data.db import DB_FILE


# אחראית על החיבור למסד הנתונים ועל יצירת טבלת יומן ההודעות של בוט הלקוחות - תיעוד
# קבוע של כל הודעה נכנסת/יוצאת, בנפרד מהיסטוריית ההקשר הקצרה שמוזנת ל-LLM (זו נחתכת
# ל-6 תורים אחרונים ומתעדכנת תדיר - לא מתאימה כיומן ביקורת לבעלת העסק)
class CustomerBotMessageDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_bot_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                direction TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_bot_messages_phone ON customer_bot_messages(phone)"
        )
        self._ensure_columns(conn)
        # עד איזו הודעה (לפי id, לא timestamp - נמנעים מתיקו אם קריאה והודעה חדשה קורות
        # באותה שנייה ממש) מנהלת העסק כבר ראתה בכל שיחה - לסימון "לא נקרא" ברשימת השיחות
        # (ראו get_conversation_summaries/mark_read) - שורה אחת לכל טלפון, לא יומן
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_conversation_read_state (
                phone TEXT PRIMARY KEY,
                last_read_message_id INTEGER NOT NULL
            )
        """)
        # שיחות שבהן הבוט מושהה (נציגה אנושית מתכתבת ישירות) - נוכחות שורה = מושהה, אין
        # שורה = פעיל כרגיל (ברירת מחדל). ראו set_bot_paused/is_bot_paused בריפוזיטורי
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_paused_conversations (
                phone TEXT PRIMARY KEY,
                paused_at TEXT NOT NULL
            )
        """)
        return conn

    # מיגרציה קלה: מוסיפה עמודות חדשות אם עוד לא קיימות -
    # bot_phone_number_id: באיזה מהמספרים שלנו התנהלה השיחה (רלוונטי מרגע שכמה
    #   מספרים רשמיים מחוברים לאותה אפליקציה)
    # attachment_url: קישור לקובץ/תמונה מצורפים (נשמר תחת static/uploads, ראו
    #   bot_conversations.py) - להצגה בתוך בועת הצ'אט בממשק הניהול
    # wamid: מזהה ההודעה שהוחזר מוואטסאפ בזמן השליחה (רק להודעות יוצאות) - מפתח לקישור
    #   חזרה לעדכוני סטטוס משלוח (webhook נפרד, ראו extract_status_updates ב-bot.py)
    # deleted_at: מתי המנהלת מחקה את ההודעה מהיומן בממשק (מחיקה רכה - לא נמחקת פיזית, כדי לא
    #   לשבש את חישוב "חלון 24 השעות" בשליחת אוטומציות, ראו get_last_incoming_at). None = לא נמחקה
    # delivery_status: sent/delivered/read/failed - מתעדכן ע"י אותו webhook, None עד שמגיע
    #   עדכון ראשון (או להודעות ישנות שנשלחו לפני התכונה הזו)
    @staticmethod
    def _ensure_columns(conn):
        columns = {row[1] for row in conn.execute("PRAGMA table_info(customer_bot_messages)").fetchall()}
        new_columns = {
            "bot_phone_number_id": "TEXT", "attachment_url": "TEXT",
            "wamid": "TEXT", "delivery_status": "TEXT",
            # מחיקה "רכה" מהיומן שבממשק (ראו delete_message בריפוזיטורי) - ההודעה נשארת במסד
            "deleted_at": "TEXT",
        }
        for name, column_type in new_columns.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE customer_bot_messages ADD COLUMN {name} {column_type}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_bot_messages_wamid ON customer_bot_messages(wamid)")

    def close(self):
        self.conn.close()
