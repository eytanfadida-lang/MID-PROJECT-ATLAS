import sqlite3

from atlas.data.db import DB_FILE


# סופרת שיעורים שנוכחה בהם בפועל, מצטבר לכל לקוחה, "מעכשיו קדימה" בלבד (לא היסטוריית
# Arbox המלאה מ-2018 - Arbox לא חושפת "כמה שיעורים בסה"כ" בשום endpoint, רק דוחות לפי
# טווח תאריכים, אז ספירה היסטורית מלאה הייתה דורשת backfill יקר של שנים - הוחלט במפורש
# להתחיל לספור מהיום שהתכונה הופעלה, ראו _resolve_attendance_milestone_recipients
# ב-engine.py). last_counted_date נשמר לצורך דיבוג/תצוגה בלבד, לא לאכיפת אידמפוטנטיות -
# זו באחריות רמת האוטומציה (last_run_at), כי אותה לקוחה יכולה להיספר כמה פעמים באותו
# יום אם הגיעה לכמה שיעורים
class ArboxEntranceCountDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arbox_entrance_counts (
                phone TEXT PRIMARY KEY,
                full_name TEXT,
                visit_count INTEGER NOT NULL DEFAULT 0,
                last_counted_date TEXT
            )
        """)
        return conn

    def close(self):
        self.conn.close()
