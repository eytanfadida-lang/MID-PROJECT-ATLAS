import json
import sqlite3

from atlas.data.db import DB_FILE

# אוטומציה ראשונה שנזרעת אם הטבלה ריקה - אישור הרשמה לשיעור ניסיון. tenant_id קבוע ל-1 כרגע
# (עסק יחיד), אבל קיים בכל הטבלאות מהיום הראשון כדי שמעבר עתידי למוצר רב-עסקים לא ידרוש שינוי סכמה
_DEFAULT_TRIAL_TEXT_TEMPLATE = (
    "היי {full_name}! 🌸 שיעור הניסיון שלך ב{session_name} אושר - "
    "{date} בשעה {start_time}, {location_name}. מחכים לך!"
)


# אחראית על החיבור למסד הנתונים ועל יצירת טבלאות מנוע האוטומציות - automations (הגדרת "מתי
# לעשות מה"), automation_steps (הפעולות המסודרות של כל אוטומציה, עם השהייה אופציונלית),
# due_actions (תור הפעולות הממתינות/שבוצעו - גם פעולה מיידית עוברת דרך הטבלה הזו, לא רק
# מושהות), automation_executions (יומן ביקורת קבוע, לצפייה/דיבוג - ראו customer_bot_message_db.py
# לאותו אידיום בדיוק)
class AutomationDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS automations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_config TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_automations_trigger ON automations(trigger_type, enabled)"
        )
        self._ensure_automations_columns(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                automation_id INTEGER NOT NULL,
                step_order INTEGER NOT NULL,
                delay_minutes INTEGER NOT NULL DEFAULT 0,
                action_type TEXT NOT NULL,
                action_config TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_automation_steps_automation ON automation_steps(automation_id)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS due_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 1,
                automation_id INTEGER NOT NULL,
                step_id INTEGER NOT NULL,
                target_phone TEXT NOT NULL,
                target_lead_id INTEGER,
                context TEXT,
                run_after TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                claimed_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_due_actions_status_run_after ON due_actions(status, run_after)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                due_action_id INTEGER,
                automation_id INTEGER NOT NULL,
                target_phone TEXT NOT NULL,
                status TEXT NOT NULL,
                channel TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            )
        """)
        # רשימת נמענים ידנית - לאוטומציות מתוזמנות (trigger_type='scheduled', למשל סקר/תזכורת
        # תקופתית) שלא קשורות לאירוע ספציפי של לקוח/ליד בודד, ולכן אין להן "phone" שמגיע
        # מנקודת חיבור כמו trial_booked - מי שמקבל אותן נבחר ידנית מראש דרך הממשק
        conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_recipients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                automation_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                full_name TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_automation_recipients_automation "
            "ON automation_recipients(automation_id)"
        )
        # רשימת החרגה גלובלית (לא פר-אוטומציה - אותה רשימה משותפת לכל האוטומציות המתוזמנות
        # בחשבון, בהתאם לדפוס שראינו ב-Upgrade360) - מספרים שלעולם לא יקבלו שום הודעה
        # מתוזמנת, גם אם הם ברשימת הנמענים (automation_recipients) של אוטומציה כלשהי -
        # נבדקת ב-process_scheduled_automations בזמן ה"הורדה"/שליחה
        conn.execute("""
            CREATE TABLE IF NOT EXISTS global_blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 1,
                phone TEXT NOT NULL,
                full_name TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_global_blacklist_unique "
            "ON global_blacklist(tenant_id, phone)"
        )
        self._seed_default_automation(conn)
        return conn

    # מיגרציה קלה: מוסיפה את last_run_at אם עוד לא קיימת - מתי לאחרונה אוטומציה מתוזמנת
    # (trigger_type='scheduled') הופעלה בפועל, כדי שלא תופעל פעמיים לאותה הזדמנות (ראו
    # atlas/automations/engine.py, process_scheduled_automations)
    @staticmethod
    def _ensure_automations_columns(conn):
        columns = {row[1] for row in conn.execute("PRAGMA table_info(automations)").fetchall()}
        if "last_run_at" not in columns:
            conn.execute("ALTER TABLE automations ADD COLUMN last_run_at TEXT")

    # זורעת אוטומציה ברירת-מחדל אחת (אישור שיעור ניסיון) רק אם טבלת automations ריקה -
    # אותו אידיום בדיוק כמו DEFAULT_STATUSES ב-atlas/data/lead_db.py
    @staticmethod
    def _seed_default_automation(conn):
        import datetime

        has_rows = conn.execute("SELECT COUNT(*) FROM automations").fetchone()[0]
        if has_rows:
            return
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            "INSERT INTO automations (tenant_id, name, trigger_type, trigger_config, enabled, "
            "created_at, updated_at) VALUES (1, ?, ?, NULL, 1, ?, ?)",
            ("אישור הרשמה לשיעור ניסיון", "trial_booked", now, now),
        )
        automation_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO automation_steps (automation_id, step_order, delay_minutes, action_type, "
            "action_config) VALUES (?, 1, 0, 'send_whatsapp_message', ?)",
            (automation_id, json.dumps({"mode": "text", "text_template": _DEFAULT_TRIAL_TEXT_TEMPLATE})),
        )
        conn.commit()

    def close(self):
        self.conn.close()
