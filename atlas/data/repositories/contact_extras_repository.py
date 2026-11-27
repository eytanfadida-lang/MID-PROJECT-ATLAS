import datetime


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


# תגיות, משימות ויומן פעילות לפי מספר טלפון - ראו contact_extras_db.py.
# הטלפון מגיע לכאן כבר מנורמל (הקורא אחראי - ראו extension_api.py)
class ContactExtrasRepository:
    def __init__(self, conn):
        self.conn = conn

    # --- תגיות ---

    def get_tags(self, phone):
        rows = self.conn.execute(
            "SELECT tag FROM contact_tags WHERE phone = ? ORDER BY created_at", (phone,)
        ).fetchall()
        return [row[0] for row in rows]

    # כל התגיות שבשימוש אצל מישהי - להשלמה אוטומטית כשמוסיפים תגית, כדי שלא ייווצרו
    # "VIP" ו-"vip" כשתי תגיות שונות
    def get_all_tag_names(self):
        rows = self.conn.execute("SELECT DISTINCT tag FROM contact_tags ORDER BY tag").fetchall()
        return [row[0] for row in rows]

    def add_tag(self, phone, tag):
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO contact_tags (phone, tag, created_at) VALUES (?, ?, ?)",
            (phone, tag, _now()),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def remove_tag(self, phone, tag):
        cursor = self.conn.execute("DELETE FROM contact_tags WHERE phone = ? AND tag = ?", (phone, tag))
        self.conn.commit()
        return cursor.rowcount == 1

    # --- משימות ---

    def get_tasks(self, phone):
        rows = self.conn.execute(
            "SELECT id, title, due_date, done, created_by, created_at, done_at FROM contact_tasks "
            "WHERE phone = ? ORDER BY done, COALESCE(due_date, '9999'), created_at",
            (phone,),
        ).fetchall()
        return [
            {
                "id": row[0], "title": row[1], "due_date": row[2], "done": bool(row[3]),
                "created_by": row[4], "created_at": row[5], "done_at": row[6],
            }
            for row in rows
        ]

    def get_task(self, task_id):
        row = self.conn.execute(
            "SELECT id, phone, title, done FROM contact_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "phone": row[1], "title": row[2], "done": bool(row[3])}

    def add_task(self, phone, title, due_date, created_by):
        cursor = self.conn.execute(
            "INSERT INTO contact_tasks (phone, title, due_date, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (phone, title, due_date or None, created_by, _now()),
        )
        self.conn.commit()
        return cursor.lastrowid

    def set_task_done(self, task_id, done):
        self.conn.execute(
            "UPDATE contact_tasks SET done = ?, done_at = ? WHERE id = ?",
            (1 if done else 0, _now() if done else None, task_id),
        )
        self.conn.commit()

    def delete_task(self, task_id):
        self.conn.execute("DELETE FROM contact_tasks WHERE id = ?", (task_id,))
        self.conn.commit()

    # --- יומן פעילות ---

    def log(self, phone, text, username):
        self.conn.execute(
            "INSERT INTO contact_activity (phone, text, username, created_at) VALUES (?, ?, ?, ?)",
            (phone, text, username, _now()),
        )
        self.conn.commit()

    def get_activity(self, phone, limit=50):
        rows = self.conn.execute(
            "SELECT text, username, created_at FROM contact_activity WHERE phone = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (phone, limit),
        ).fetchall()
        return [{"text": row[0], "username": row[1], "created_at": row[2]} for row in rows]
