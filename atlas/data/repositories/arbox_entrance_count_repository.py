TABLE_NAME = "arbox_entrance_counts"


class ArboxEntranceCountRepository:
    def __init__(self, conn):
        self.conn = conn

    # מוסיפה ביקור אחד (שיעור אחד שהגיעה אליו בפועל) ומחזירה את המונה המצטבר החדש. בלי
    # הגנת "כבר נספר היום" - לקוחה יכולה להגיע לכמה שיעורים באותו יום, וכל אחד נספר
    # בנפרד (ראו _resolve_attendance_milestone_recipients). ההגנה מפני ריצה כפולה של
    # ה-poller באותו יום היא ברמת האוטומציה עצמה (last_run_at/stage_instant, כמו כל
    # קהל דינמי אחר), לא כאן
    def record_visit(self, phone, full_name, visit_date):
        row = self.conn.execute(
            f"SELECT visit_count FROM {TABLE_NAME} WHERE phone = ?", (phone,)
        ).fetchone()
        if row is None:
            self.conn.execute(
                f"INSERT INTO {TABLE_NAME} (phone, full_name, visit_count, last_counted_date) "
                "VALUES (?, ?, 1, ?)",
                (phone, full_name, visit_date),
            )
            self.conn.commit()
            return 1

        new_count = row[0] + 1
        self.conn.execute(
            f"UPDATE {TABLE_NAME} SET visit_count = ?, full_name = ?, last_counted_date = ? WHERE phone = ?",
            (new_count, full_name, visit_date, phone),
        )
        self.conn.commit()
        return new_count
