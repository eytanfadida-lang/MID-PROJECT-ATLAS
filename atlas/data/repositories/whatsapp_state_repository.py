import datetime

TABLE_NAME = "whatsapp_processed_messages"


# אחראית על מניעת עיבוד כפול של אותה הודעת וואטסאפ נכנסת (wamid) - למשל כשמטא
# שולחת שוב את אותו webhook כי התגובה שלנו לא הגיעה מהר מספיק
class WhatsAppStateRepository:
    def __init__(self, conn):
        self.conn = conn

    def has_processed(self, wamid):
        row = self.conn.execute(
            f"SELECT 1 FROM {TABLE_NAME} WHERE wamid = ?", (wamid,)
        ).fetchone()
        return row is not None

    # INSERT OR IGNORE - בטוח גם אם שתי בקשות מקבילות מנסות לסמן את אותו wamid בו-זמנית
    def mark_processed(self, wamid):
        self.conn.execute(
            f"INSERT OR IGNORE INTO {TABLE_NAME} (wamid, processed_at) VALUES (?, ?)",
            (wamid, datetime.datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()
