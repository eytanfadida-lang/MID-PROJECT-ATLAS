import datetime

TABLE_NAME = "bot_content_gaps"


# אחראית על תיעוד שאלות שבוט הלקוחות לא הצליח לענות עליהן (ראו bot_content_gap_db.py)
class BotContentGapRepository:
    def __init__(self, conn):
        self.conn = conn

    def log(self, phone, question, reason):
        self.conn.execute(
            f"INSERT INTO {TABLE_NAME} (phone, question, reason, created_at) VALUES (?, ?, ?, ?)",
            (phone, question, reason, datetime.datetime.now().isoformat(timespec="minutes")),
        )
        self.conn.commit()
