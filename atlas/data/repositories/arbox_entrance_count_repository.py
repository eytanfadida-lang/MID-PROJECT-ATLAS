TABLE_NAME = "arbox_entrance_counts"


class ArboxEntranceCountRepository:
    def __init__(self, conn):
        self.conn = conn

    # רושמת כניסה אחת (ליום נתון) ומחזירה את המונה המצטבר החדש. אידמפוטנטית לפי
    # last_counted_date - אם כבר נרשמה כניסה לטלפון הזה היום, לא סופרת שוב (מגינה מפני
    # ריצה כפולה של ה-poller באותו יום) ומחזירה את המונה הקיים בלי לשנות אותו
    def record_visit(self, phone, full_name, today_iso):
        row = self.conn.execute(
            f"SELECT visit_count, last_counted_date FROM {TABLE_NAME} WHERE phone = ?", (phone,)
        ).fetchone()
        if row is None:
            self.conn.execute(
                f"INSERT INTO {TABLE_NAME} (phone, full_name, visit_count, last_counted_date) "
                "VALUES (?, ?, 1, ?)",
                (phone, full_name, today_iso),
            )
            self.conn.commit()
            return 1

        visit_count, last_counted_date = row
        if last_counted_date == today_iso:
            return visit_count

        new_count = visit_count + 1
        self.conn.execute(
            f"UPDATE {TABLE_NAME} SET visit_count = ?, full_name = ?, last_counted_date = ? WHERE phone = ?",
            (new_count, full_name, today_iso, phone),
        )
        self.conn.commit()
        return new_count
