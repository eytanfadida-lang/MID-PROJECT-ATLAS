import datetime

TABLE_NAME = "linked_whatsapp_accounts"

# מה התהליך (gateway) רשאי לדווח, ומה המנהלת רשאית לבקש
STATUSES = ("starting", "waiting_qr", "connected", "disconnected", "logged_out", "error")
DESIRED = ("connect", "disconnect", "delete")

# התהליך נחשב "לא פועל" אם לא פנה לאפליקציה כל כך הרבה שניות (הוא פונה כל ~3 שניות)
GATEWAY_ONLINE_WITHIN_SECONDS = 30
# הודעה שנתקעה "בשליחה" כל כך הרבה שניות נחשבת כושלת (ראו take_pending)
STALE_SENDING_SECONDS = 90
# קצב הפנייה של התהליך לאפליקציה: מהר (שנייה) כשיש פעילות עכשיו, איטי (3 שניות) כשהכל שקט - כדי לא להעמיס
# על האתר (כל פנייה היא בקשה לשרת האינטרנט)
FAST_POLL_MS = 1000
IDLE_POLL_MS = 3000
ACTIVE_WINDOW_SECONDS = 60
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

    # --- תור הודעות יוצאות ---
    def enqueue(self, account_id, message_id, to_digits, body=None, attachment_url=None, attachment_mime=None, attachment_name=None):
        cursor = self.conn.execute(
            "INSERT INTO linked_whatsapp_outbox (account_id, message_id, to_digits, body, attachment_url, attachment_mime, "
            "attachment_name, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?)",
            (account_id, message_id, to_digits, body, attachment_url, attachment_mime, attachment_name, _now()),
        )
        self.conn.commit()
        return cursor.lastrowid

    # מחזירה לתהליך את ההודעות שממתינות לשליחה ומסמנת אותן "בשליחה", כדי שלא יישלחו פעמיים. הודעה שנתקעה
    # "בשליחה" יותר מדי זמן (התהליך קרס באמצע) לא נשלחת שוב אוטומטית - זה עלול לשלוח כפול - אלא מסומנת כנכשלה
    def take_pending(self, limit=20):
        cutoff = (datetime.datetime.now() - datetime.timedelta(seconds=STALE_SENDING_SECONDS)).isoformat(timespec="seconds")
        stale = self.conn.execute(
            "SELECT id FROM linked_whatsapp_outbox WHERE status = 'sending' AND picked_at < ?", (cutoff,)
        ).fetchall()
        for (outbox_id,) in stale:
            self.complete(outbox_id, ok=False, error="לא התקבל אישור שליחה - ייתכן שההודעה לא נשלחה")
        rows = self.conn.execute(
            "SELECT id, account_id, to_digits, body, attachment_url, attachment_mime, attachment_name "
            "FROM linked_whatsapp_outbox WHERE status = 'queued' ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
        now = _now()
        for row in rows:
            self.conn.execute("UPDATE linked_whatsapp_outbox SET status = 'sending', picked_at = ? WHERE id = ?", (now, row[0]))
        self.conn.commit()
        keys = ("id", "account_id", "to", "body", "attachment_url", "attachment_mime", "attachment_name")
        return [dict(zip(keys, r)) for r in rows]

    # התהליך מדווח על תוצאת השליחה: מעדכנת את שורת התור, ואת שורת היומן (wamid + sent/failed).
    # אם בינתיים הגיעה מוואטסאפ "הודעה יוצאת" עם אותו wamid ונרשמה כשורה נוספת - מסירה את הכפילות
    def complete(self, outbox_id, ok, wamid=None, error=None):
        row = self.conn.execute("SELECT message_id FROM linked_whatsapp_outbox WHERE id = ?", (outbox_id,)).fetchone()
        if row is None:
            return False
        message_id = row[0]
        self.conn.execute(
            "UPDATE linked_whatsapp_outbox SET status = ?, error = ? WHERE id = ?",
            ("sent" if ok else "failed", None if ok else (str(error or "")[:300] or None), outbox_id),
        )
        if ok:
            if wamid:
                self.conn.execute("DELETE FROM customer_bot_messages WHERE wamid = ? AND id != ?", (wamid, message_id))
            self.conn.execute(
                "UPDATE customer_bot_messages SET wamid = COALESCE(?, wamid), delivery_status = 'sent' WHERE id = ?",
                (wamid, message_id),
            )
        else:
            self.conn.execute("UPDATE customer_bot_messages SET delivery_status = 'failed' WHERE id = ?", (message_id,))
        self.conn.commit()
        return True

    def has_pending_outbox(self):
        if self.conn.execute(
            "SELECT 1 FROM linked_whatsapp_group_jobs WHERE status IN ('queued', 'sending') LIMIT 1"
        ).fetchone():
            return True
        return self.conn.execute(
            "SELECT 1 FROM linked_whatsapp_outbox WHERE status IN ('queued', 'sending') LIMIT 1"
        ).fetchone() is not None

    # --- קבוצות ---
    # התהליך מדווח את כל הקבוצות של החשבון בבת אחת - מחליפים את הרשימה (קבוצה שיצאו ממנה נעלמת)
    def replace_groups(self, account_id, groups):
        now = _now()
        self.conn.execute("DELETE FROM linked_whatsapp_groups WHERE account_id = ?", (account_id,))
        for g in groups or []:
            jid = str(g.get("jid") or "")
            if not jid.endswith("@g.us") or len(jid) > 64:
                continue
            size = g.get("size")
            self.conn.execute(
                "INSERT OR REPLACE INTO linked_whatsapp_groups (account_id, jid, subject, is_admin, size, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (account_id, jid, str(g.get("subject") or "")[:200], 1 if g.get("is_admin") else 0,
                 int(size) if isinstance(size, int) else None, now),
            )
        self.conn.commit()

    def get_groups(self):
        rows = self.conn.execute(
            "SELECT account_id, jid, subject, is_admin, size FROM linked_whatsapp_groups ORDER BY subject"
        ).fetchall()
        return [dict(zip(("account_id", "jid", "subject", "is_admin", "size"), r)) for r in rows]

    def get_branch_groups(self):
        rows = self.conn.execute(
            "SELECT location, account_id, group_jid, group_subject FROM linked_whatsapp_branch_groups"
        ).fetchall()
        return {r[0]: {"account_id": r[1], "group_jid": r[2], "group_subject": r[3]} for r in rows}

    def set_branch_group(self, location, account_id=None, group_jid=None, group_subject=None):
        if not group_jid:
            self.conn.execute("DELETE FROM linked_whatsapp_branch_groups WHERE location = ?", (location,))
        else:
            self.conn.execute(
                "INSERT OR REPLACE INTO linked_whatsapp_branch_groups (location, account_id, group_jid, group_subject, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (location, account_id, group_jid, group_subject, _now()),
            )
        self.conn.commit()

    # --- תור הוספה לקבוצות ---
    def enqueue_group_add(self, account_id, group_jid, to_digits, invite_text=None, due_action_id=None, automation_id=None):
        cursor = self.conn.execute(
            "INSERT INTO linked_whatsapp_group_jobs (account_id, group_jid, to_digits, invite_text, due_action_id, "
            "automation_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)",
            (account_id, group_jid, to_digits, invite_text, due_action_id, automation_id, _now()),
        )
        self.conn.commit()
        return cursor.lastrowid

    # כמו take_pending: מסמנת "בביצוע" כדי שלא יבוצע פעמיים; עבודה שנתקעה מסומנת ככושלת ולא נשלחת שוב
    # עבודות שנתקעו "בביצוע" (התהליך קרס/הופעל מחדש באמצע) - מסומנות ככושלות ומוחזרות לרישום ביומן
    def expire_stale_group_jobs(self):
        cutoff = (datetime.datetime.now() - datetime.timedelta(seconds=STALE_SENDING_SECONDS)).isoformat(timespec="seconds")
        stale = self.conn.execute(
            "SELECT id FROM linked_whatsapp_group_jobs WHERE status = 'sending' AND picked_at < ?", (cutoff,)
        ).fetchall()
        expired = []
        for (job_id,) in stale:
            job = self.complete_group_job(job_id, result="failed", error="לא התקבלה תשובה מהחיבור - ייתכן שההוספה לא בוצעה")
            if job:
                expired.append(job)
        return expired

    def take_pending_group_jobs(self, limit=10):
        rows = self.conn.execute(
            "SELECT id, account_id, group_jid, to_digits, invite_text FROM linked_whatsapp_group_jobs "
            "WHERE status = 'queued' ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
        now = _now()
        for row in rows:
            self.conn.execute("UPDATE linked_whatsapp_group_jobs SET status = 'sending', picked_at = ? WHERE id = ?", (now, row[0]))
        self.conn.commit()
        keys = ("id", "account_id", "group_jid", "to", "invite_text")
        return [dict(zip(keys, r)) for r in rows]

    # result: added / already / invited / failed. מחזירה את שורת העבודה (לרישום ביומן האוטומציה) או None
    def complete_group_job(self, job_id, result, error=None):
        row = self.conn.execute(
            "SELECT id, status, to_digits, due_action_id, automation_id, group_jid FROM linked_whatsapp_group_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None or row[1] in ("done", "failed"):
            return None
        self.conn.execute(
            "UPDATE linked_whatsapp_group_jobs SET status = ?, result = ?, error = ? WHERE id = ?",
            ("failed" if result == "failed" else "done", result, (str(error or "")[:300] or None), job_id),
        )
        self.conn.commit()
        return dict(zip(("id", "status", "to_digits", "due_action_id", "automation_id", "group_jid"), row))

    # האם היה "קצב" לאחרונה (הודעה יוצאת בתור או הודעה מחשבון מקושר) - התהליך מתעורר מהר כשיש פעילות
    # וחוסך בקשות כשהכל רגוע (ראו poll_interval_ms)
    def seconds_since_activity(self):
        latest = []
        row = self.conn.execute("SELECT MAX(created_at) FROM linked_whatsapp_outbox").fetchone()
        if row and row[0]:
            latest.append(row[0])
        row = self.conn.execute(
            "SELECT created_at FROM customer_bot_messages WHERE bot_phone_number_id LIKE 'linked:%' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row and row[0]:
            latest.append(row[0])
        if not latest:
            return None
        return (datetime.datetime.now() - datetime.datetime.fromisoformat(max(latest))).total_seconds()

    def poll_interval_ms(self):
        if self.has_pending_outbox():
            return FAST_POLL_MS
        age = self.seconds_since_activity()
        return FAST_POLL_MS if age is not None and age <= ACTIVE_WINDOW_SECONDS else IDLE_POLL_MS

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
