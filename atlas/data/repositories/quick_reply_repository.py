import datetime

TABLE_NAME = "quick_replies"
CATEGORIES_TABLE = "quick_reply_categories"


# אחראית על התגובות המהירות בעמוד שיחות הבוט (ראו quick_reply_db.py)
class QuickReplyRepository:
    def __init__(self, conn):
        self.conn = conn

    def get_all(self):
        rows = self.conn.execute(
            f"SELECT id, title, body, category, favorite FROM {TABLE_NAME} ORDER BY favorite DESC, title"
        ).fetchall()
        return [
            {"id": row[0], "title": row[1], "body": row[2], "category": row[3], "favorite": bool(row[4])}
            for row in rows
        ]

    # הקטגוריות שנוצרו במפורש + כל קטגוריה שיש בה תגובה (למקרה שנמחקה מהרשימה אבל עדיין בשימוש)
    def get_categories(self):
        names = {row[0] for row in self.conn.execute(f"SELECT name FROM {CATEGORIES_TABLE}")}
        names |= {row[0] for row in self.conn.execute(f"SELECT DISTINCT category FROM {TABLE_NAME} WHERE category != ''")}
        return sorted(names)

    def add_category(self, name):
        self.conn.execute(
            f"INSERT OR IGNORE INTO {CATEGORIES_TABLE} (name, created_at) VALUES (?, ?)",
            (name, _now()),
        )
        self.conn.commit()

    def create(self, title, body, category, favorite):
        if category:
            self.add_category(category)
        now = _now()
        cursor = self.conn.execute(
            f"INSERT INTO {TABLE_NAME} (title, body, category, favorite, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (title, body, category, 1 if favorite else 0, now, now),
        )
        self.conn.commit()
        return cursor.lastrowid

    def update(self, reply_id, title, body, category, favorite):
        if category:
            self.add_category(category)
        cursor = self.conn.execute(
            f"UPDATE {TABLE_NAME} SET title = ?, body = ?, category = ?, favorite = ?, updated_at = ? WHERE id = ?",
            (title, body, category, 1 if favorite else 0, _now(), reply_id),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def set_favorite(self, reply_id, favorite):
        cursor = self.conn.execute(
            f"UPDATE {TABLE_NAME} SET favorite = ?, updated_at = ? WHERE id = ?",
            (1 if favorite else 0, _now(), reply_id),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def delete(self, reply_id):
        cursor = self.conn.execute(f"DELETE FROM {TABLE_NAME} WHERE id = ?", (reply_id,))
        self.conn.commit()
        return cursor.rowcount == 1


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")
