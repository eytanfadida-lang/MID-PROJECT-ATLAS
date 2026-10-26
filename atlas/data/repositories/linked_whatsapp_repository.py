import datetime

TABLE_NAME = "linked_whatsapp_accounts"

# מה התהליך (gateway) רשאי לדווח, ומה המנהלת רשאית לבקש
STATUSES = ("starting", "waiting_qr", "connected", "disconnected", "logged_out", "error")
DESIRED = ("connect", "disconnect", "delete")

# התהליך נחשב "לא פועל" אם לא פנה לאפליקציה כל כך הרבה שניות (הוא פונה כל ~3 שניות)
GATEWAY_ONLINE_WITHIN_SECONDS = 30
# גודל מקסימלי לתמונת ה-QR שמתקבלת מהתהליך (PNG ב-base64 הוא ~5KB) - הגנה מפני נתון שרירותי גדול
MAX_QR_IMAGE_LENGTH = 40000

_COLUMNS = (
    "id, label, phone, status, desired, qr_image, qr_ttl, qr_updated_at, error, connected_at, created_at, updated_at"
)


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _row_to_dict(row):
    keys = [c.strip() for c in _COLUMNS.split(",")]
    return dict(zip(keys, row))


# חשבונות וואטסאפ מקושרים (לא רשמיים). ראו linked_whatsapp_db.py ו-blueprints/gateway.py
class LinkedWhatsAppRepository:
    def __init__(self, conn):
        self.conn = conn

    def create(self, label):
        now = _now()
        cursor = self.conn.execute(
            f"INSERT INTO {TABLE_NAME} (label, status, desired, created_at, updated_at) VALUES (?, 'starting', 'connect', ?, ?)",
            (label, now, now),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get(self, account_id):
        row = self.conn.execute(f"SELECT {_COLUMNS} FROM {TABLE_NAME} WHERE id = ?", (account_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def get_all(self):
        rows = self.conn.execute(f"SELECT {_COLUMNS} FROM {TABLE_NAME} ORDER BY id").fetchall()
        return [_row_to_dict(r) for r in rows]

    def rename(self, account_id, label):
        self.conn.execute(f"UPDATE {TABLE_NAME} SET label = ?, updated_at = ? WHERE id = ?", (label, _now(), account_id))
        self.conn.commit()

    # מה המנהלת מבקשת: connect (חיבור/חיבור מחדש), disconnect (ניתוק זמני, ההתחברות נשמרת), delete (ניתוק מלא ומחיקה)
    def set_desired(self, account_id, desired):
        if desired not in DESIRED:
            raise ValueError(desired)
        if desired == "connect":
            current = self.get(account_id)
            # כבר מתחבר/ממתין לסריקה/מחובר - לא מאפסים (פתיחה חוזרת של המודל לא אמורה למחוק את ה-QR שמוצג עכשיו)
            if current and current["desired"] == "connect" and current["status"] in ("starting", "waiting_qr", "connected"):
                return
            # חיבור מחדש מתחיל מנקי: בלי QR ישן ובלי שגיאה קודמת
            self.conn.execute(
                f"UPDATE {TABLE_NAME} SET desired = ?, status = CASE WHEN status = 'connected' THEN status ELSE 'starting' END, "
                "qr_image = NULL, qr_ttl = NULL, qr_updated_at = NULL, error = NULL, updated_at = ? WHERE id = ?",
                (desired, _now(), account_id),
            )
        else:
            self.conn.execute(f"UPDATE {TABLE_NAME} SET desired = ?, updated_at = ? WHERE id = ?", (desired, _now(), account_id))
        self.conn.commit()

    # מה התהליך מדווח. status "deleted" = הוא ניתק ומחק את ההתחברות, ואפשר להסיר את השורה.
    # ה-QR נשמר רק במצב ממתין-לסריקה; כל מצב אחר מנקה אותו (QR ישן שמוצג = בלבול)
    def apply_state(self, account_id, status, qr_image=None, qr_ttl=None, phone=None, error=None):
        if status == "deleted":
            return self.delete(account_id)
        if status not in STATUSES:
            raise ValueError(status)
        now = _now()
        if status == "waiting_qr" and qr_image:
            if len(qr_image) > MAX_QR_IMAGE_LENGTH or not qr_image.startswith("data:image/png;base64,"):
                raise ValueError("qr_image")
            self.conn.execute(
                f"UPDATE {TABLE_NAME} SET status = ?, qr_image = ?, qr_ttl = ?, qr_updated_at = ?, error = NULL, updated_at = ? WHERE id = ?",
                (status, qr_image, int(qr_ttl or 20), now, now, account_id),
            )
        elif status == "connected":
            self.conn.execute(
                f"UPDATE {TABLE_NAME} SET status = ?, phone = COALESCE(?, phone), qr_image = NULL, qr_ttl = NULL, qr_updated_at = NULL, "
                "error = NULL, connected_at = ?, updated_at = ? WHERE id = ?",
                (status, phone, now, now, account_id),
            )
        else:
            self.conn.execute(
                f"UPDATE {TABLE_NAME} SET status = ?, qr_image = NULL, qr_ttl = NULL, qr_updated_at = NULL, error = ?, updated_at = ? WHERE id = ?",
                (status, (error or None) and str(error)[:300], now, account_id),
            )
        self.conn.commit()
        return True

    def delete(self, account_id):
        cursor = self.conn.execute(f"DELETE FROM {TABLE_NAME} WHERE id = ?", (account_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    # --- דופק של התהליך ---
    def touch_gateway(self):
        now = _now()
        cursor = self.conn.execute("UPDATE linked_whatsapp_gateway SET seen_at = ? WHERE id = 1", (now,))
        if cursor.rowcount == 0:
            self.conn.execute("INSERT INTO linked_whatsapp_gateway (id, seen_at) VALUES (1, ?)", (now,))
        self.conn.commit()

    def gateway_seconds_since_seen(self):
        row = self.conn.execute("SELECT seen_at FROM linked_whatsapp_gateway WHERE id = 1").fetchone()
        if not row:
            return None
        return (datetime.datetime.now() - datetime.datetime.fromisoformat(row[0])).total_seconds()

    def is_gateway_online(self):
        age = self.gateway_seconds_since_seen()
        return age is not None and age <= GATEWAY_ONLINE_WITHIN_SECONDS
