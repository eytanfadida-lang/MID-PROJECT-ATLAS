import datetime

# מכסת Arbox לחודש (נמסר ע"י איתן, 19/11/26) ושני ספים: התראה, ובלם שמוריד את הסנכרון
# לפעמיים ביום עד סוף החודש (ראו arbox_push_sync.py)
MONTHLY_LIMIT = 20000
ALERT_THRESHOLD = 16000
BRAKE_THRESHOLD = 19000

SOURCE_LABELS = {
    "sync": "סנכרון נתונים",
    "automation": "אוטומציות",
    "app": "בוט, תוסף ומערכת",
    "manual": "סקריפטים ידניים",
}


# מונה הבקשות ל-Arbox - ראו arbox_usage_db.py. day/month הם תאריכים בשעון ישראל ('YYYY-MM-DD' /
# 'YYYY-MM'), כי המכסה של Arbox נספרת לפי חודש קלנדרי
class ArboxUsageRepository:
    def __init__(self, conn):
        self.conn = conn

    def add(self, day, source, count=1):
        self.conn.execute(
            "INSERT INTO arbox_api_usage (day, source, count) VALUES (?, ?, ?) "
            "ON CONFLICT(day, source) DO UPDATE SET count = count + excluded.count",
            (day, source, count),
        )
        self.conn.commit()

    def month_total(self, month):
        row = self.conn.execute(
            "SELECT COALESCE(SUM(count), 0) FROM arbox_api_usage WHERE day LIKE ?", (f"{month}-%",)
        ).fetchone()
        return int(row[0])

    def month_by_source(self, month):
        rows = self.conn.execute(
            "SELECT source, SUM(count) FROM arbox_api_usage WHERE day LIKE ? GROUP BY source "
            "ORDER BY SUM(count) DESC",
            (f"{month}-%",),
        ).fetchall()
        return [{"source": r[0], "label": SOURCE_LABELS.get(r[0], r[0]), "count": int(r[1])} for r in rows]

    # שורה לכל יום בחודש שיש בו בקשות, עם פילוח לפי מקור - לטבלה היומית בעמוד השימוש
    def month_daily(self, month):
        rows = self.conn.execute(
            "SELECT day, source, count FROM arbox_api_usage WHERE day LIKE ? ORDER BY day DESC",
            (f"{month}-%",),
        ).fetchall()
        days = {}
        for day, source, count in rows:
            entry = days.setdefault(day, {"day": day, "total": 0, "by_source": {}})
            entry["total"] += int(count)
            entry["by_source"][source] = entry["by_source"].get(source, 0) + int(count)
        return list(days.values())

    # מסמנת שהתראה על סף נתון נשלחה החודש. מחזירה True רק בפעם הראשונה - כך כל סף מתריע פעם אחת
    def claim_alert(self, month, threshold):
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO arbox_usage_alerts (month, threshold, sent_at) VALUES (?, ?, ?)",
            (month, threshold, datetime.datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return cursor.rowcount == 1
