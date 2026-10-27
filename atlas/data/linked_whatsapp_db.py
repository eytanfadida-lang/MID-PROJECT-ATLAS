import sqlite3

from atlas.data.db import DB_FILE


# אחראית על החיבור למסד הנתונים ועל יצירת הטבלאות של חיבור וואטסאפ "לא רשמי" (מכשיר מקושר, כמו WhatsApp Web).
# החיבור עצמו רץ בתהליך נפרד (תיקיית gateway/, משימה שרצה כל הזמן ב-PythonAnywhere) - האפליקציה רק שומרת
# כאן מה המנהלת ביקשה (desired) ומה התהליך דיווח (status, QR, מספר). שני הצדדים מדברים דרך
# blueprints/gateway.py ולא נוגעים במסד אחד של השני
class LinkedWhatsAppDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS linked_whatsapp_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                phone TEXT,
                status TEXT NOT NULL DEFAULT 'starting',
                desired TEXT NOT NULL DEFAULT 'connect',
                qr_image TEXT,
                qr_ttl INTEGER,
                qr_updated_at TEXT,
                error TEXT,
                connected_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # שורה אחת: מתי התהליך שמחבר את הוואטסאפ פנה לאפליקציה לאחרונה (לזיהוי "השירות לא פועל")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS linked_whatsapp_gateway (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                seen_at TEXT NOT NULL
            )
        """)
        # תור הודעות יוצאות מהחשבון הלא רשמי: האפליקציה כותבת, והתהליך (gateway/) שולף ושולח. message_id מצביע
        # על שורת היומן (customer_bot_messages) שמתעדכנת עם ה-wamid והסטטוס כשהשליחה מסתיימת
        conn.execute("""
            CREATE TABLE IF NOT EXISTS linked_whatsapp_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                to_digits TEXT NOT NULL,
                body TEXT,
                attachment_url TEXT,
                attachment_mime TEXT,
                attachment_name TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                error TEXT,
                created_at TEXT NOT NULL,
                picked_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_linked_outbox_status ON linked_whatsapp_outbox(status)")
        return conn

    def close(self):
        self.conn.close()
