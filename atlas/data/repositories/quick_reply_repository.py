import datetime
import json

TABLE_NAME = "quick_replies"
CATEGORIES_TABLE = "quick_reply_categories"


# אחראית על התגובות המהירות בעמוד שיחות הבוט (ראו quick_reply_db.py)
class QuickReplyRepository:
    def __init__(self, conn):
        self.conn = conn

    def get_all(self):
        rows = self.conn.execute(
            f"SELECT id, title, body, category, favorite, image_url, image_urls FROM {TABLE_NAME} ORDER BY favorite DESC, title"
        ).fetchall()
        result = []
        for row in rows:
            urls = _urls(row[5], row[6])
            result.append({
                "id": row[0], "title": row[1], "body": row[2], "category": row[3], "favorite": bool(row[4]),
                "image_urls": urls, "image_url": urls[0] if urls else "",
            })
        return result

    # רשימת התמונות של תגובה (None אם התגובה לא קיימת)
    def get_image_urls(self, reply_id):
        row = self.conn.execute(f"SELECT image_url, image_urls FROM {TABLE_NAME} WHERE id = ?", (reply_id,)).fetchone()
        return _urls(row[0], row[1]) if row else None

    def set_images(self, reply_id, urls):
        self.conn.execute(
            f"UPDATE {TABLE_NAME} SET image_urls = ?, image_url = ?, updated_at = ? WHERE id = ?",
            (json.dumps(urls), urls[0] if urls else "", _now(), reply_id),
        )
        self.conn.commit()

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


# image_urls (JSON) הוא המקור; תגובות שנשמרו לפני שהיו כמה תמונות - רק image_url
def _urls(single, many):
    try:
        urls = json.loads(many) if many else []
    except ValueError:
        urls = []
    if not urls and single:
        urls = [single]
    return [u for u in urls if isinstance(u, str) and u]


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")
