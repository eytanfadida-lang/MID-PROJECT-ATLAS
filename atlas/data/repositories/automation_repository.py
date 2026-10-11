import datetime
import json


# אחראית על מנוע האוטומציות - automations/automation_steps (הגדרה), due_actions (תור ביצוע,
# גם לפעולות מיידיות וגם מושהות - ראו automation_db.py) ו-automation_executions (יומן ביקורת
# קבוע). הלוגיקה עצמה (fire_trigger/process_due_action) נמצאת ב-atlas/automations/engine.py -
# המחלקה הזו רק DB access
class AutomationRepository:
    def __init__(self, conn):
        self.conn = conn

    # אוטומציות מופעלות התואמות סוג טריגר נתון, tenant אחד (כרגע תמיד 1) - ראו §Context
    # בתוכנית לגבי הכנה ל-multi-tenant
    def get_enabled_by_trigger(self, trigger_type, tenant_id=1):
        rows = self.conn.execute(
            "SELECT id, name, trigger_config FROM automations "
            "WHERE trigger_type = ? AND tenant_id = ? AND enabled = 1",
            (trigger_type, tenant_id),
        ).fetchall()
        return [
            {"id": row[0], "name": row[1], "trigger_config": json.loads(row[2]) if row[2] else {}}
            for row in rows
        ]

    def get_step(self, step_id):
        row = self.conn.execute(
            "SELECT id, automation_id, step_order, delay_minutes, action_type, action_config "
            "FROM automation_steps WHERE id = ?",
            (step_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "automation_id": row[1],
            "step_order": row[2],
            "delay_minutes": row[3],
            "action_type": row[4],
            "action_config": json.loads(row[5]) if row[5] else {},
        }

    # שומרת רשומת היסטוריה (automation_message_history) בכל פעם שהנוסח בפועל משתנה - לא בכל
    # שמירה (למשל שינוי רק ב-delay_minutes, או שליחת הטופס בלי שינוי בפועל, לא יוצרים רעש).
    # מאפשרת "לחזור" לנוסח קודם (ראו get_step_history + restore בבלופרינט) - שימושי בעיקר
    # לאוטומציות ששולחות תוכן משתנה מדי פעם (כמו רשימת תפוצה כללית, arbox_active_members)
    def update_step(self, step_id, text_template, delay_minutes):
        step = self.get_step(step_id)
        action_config = dict(step["action_config"]) if step else {}
        previous_text = action_config.get("text_template")
        action_config["mode"] = "text"
        action_config["text_template"] = text_template
        self.conn.execute(
            "UPDATE automation_steps SET delay_minutes = ?, action_config = ? WHERE id = ?",
            (delay_minutes, json.dumps(action_config, ensure_ascii=False), step_id),
        )
        if text_template != previous_text:
            self.conn.execute(
                "INSERT INTO automation_message_history (step_id, text_template, saved_at) VALUES (?, ?, ?)",
                (step_id, text_template, datetime.datetime.now().isoformat(timespec="seconds")),
            )
        self.conn.commit()

    # מצב "תבנית מאושרת" (ראו atlas/automations/engine.py, _send_template_action) - שולח
    # דרך תבנית קבועה שאושרה מראש ב-Meta במקום טקסט חופשי, אז עוקף את חלון 24 השעות.
    # param_templates: רשימת מחרוזות-תבנית קטנות (כל אחת מרונדרת בנפרד עם .format(**context),
    # בדיוק כמו text_template הרגיל) שממלאות את {{1}},{{2}} וכו' של התבנית המאושרת, לפי הסדר.
    # אין היסטוריית הודעות למצב הזה (התוכן קבוע מראש ב-Meta, אין "לחזור" לנוסח קודם)
    def update_step_template(self, step_id, template_name, template_language, param_templates, delay_minutes):
        action_config = {
            "mode": "template",
            "template_name": template_name,
            "template_language": template_language,
            "param_templates": param_templates,
        }
        self.conn.execute(
            "UPDATE automation_steps SET delay_minutes = ?, action_config = ? WHERE id = ?",
            (delay_minutes, json.dumps(action_config, ensure_ascii=False), step_id),
        )
        self.conn.commit()

    def get_step_history(self, step_id, limit=20):
        rows = self.conn.execute(
            "SELECT id, text_template, saved_at FROM automation_message_history "
            "WHERE step_id = ? ORDER BY id DESC LIMIT ?",
            (step_id, limit),
        ).fetchall()
        return [{"id": row[0], "text_template": row[1], "saved_at": row[2]} for row in rows]

    def get_steps(self, automation_id):
        rows = self.conn.execute(
            "SELECT id, step_order, delay_minutes, action_type, action_config FROM automation_steps "
            "WHERE automation_id = ? ORDER BY step_order",
            (automation_id,),
        ).fetchall()
        return [
            {
                "id": row[0],
                "step_order": row[1],
                "delay_minutes": row[2],
                "action_type": row[3],
                "action_config": json.loads(row[4]) if row[4] else {},
            }
            for row in rows
        ]

    def insert_due_action(self, tenant_id, automation_id, step_id, target_phone, context,
                           run_after, target_lead_id=None):
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cursor = self.conn.execute(
            "INSERT INTO due_actions (tenant_id, automation_id, step_id, target_phone, "
            "target_lead_id, context, run_after, status, attempts, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)",
            (tenant_id, automation_id, step_id, target_phone, target_lead_id,
             json.dumps(context, ensure_ascii=False), run_after, now),
        )
        self.conn.commit()
        return self.get_due_action(cursor.lastrowid)

    def get_due_action(self, due_action_id):
        row = self.conn.execute(
            "SELECT id, tenant_id, automation_id, step_id, target_phone, target_lead_id, "
            "context, run_after, status, attempts FROM due_actions WHERE id = ?",
            (due_action_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "tenant_id": row[1],
            "automation_id": row[2],
            "step_id": row[3],
            "target_phone": row[4],
            "target_lead_id": row[5],
            "context": json.loads(row[6]) if row[6] else {},
            "run_after": row[7],
            "status": row[8],
            "attempts": row[9],
        }

    # UPDATE מותנה (WHERE status='pending') - מגן מפני ביצוע כפול אם כמה הרצות חופפות
    # (רלוונטי בעיקר ל-poller העתידי, לא בשימוש ב-MVP הנוכחי שמבצע סינכרונית)
    def claim_due_action(self, due_action_id):
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cursor = self.conn.execute(
            "UPDATE due_actions SET status = 'claimed', claimed_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (now, due_action_id),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def mark_sent(self, due_action_id):
        self.conn.execute("UPDATE due_actions SET status = 'sent' WHERE id = ?", (due_action_id,))
        self.conn.commit()

    def mark_failed(self, due_action_id):
        self.conn.execute(
            "UPDATE due_actions SET status = 'failed', attempts = attempts + 1 WHERE id = ?",
            (due_action_id,),
        )
        self.conn.commit()

    # נסרקת ע"י /tasks/automations-run (poller) - פעולות שהגיע זמנן ועדיין pending
    def get_due(self, limit=50):
        now = datetime.datetime.now().isoformat(timespec="seconds")
        rows = self.conn.execute(
            "SELECT id, tenant_id, automation_id, step_id, target_phone, target_lead_id, "
            "context, run_after, status, attempts FROM due_actions "
            "WHERE status = 'pending' AND run_after <= ? ORDER BY run_after LIMIT ?",
            (now, limit),
        ).fetchall()
        return [
            {
                "id": row[0], "tenant_id": row[1], "automation_id": row[2], "step_id": row[3],
                "target_phone": row[4], "target_lead_id": row[5],
                "context": json.loads(row[6]) if row[6] else {},
                "run_after": row[7], "status": row[8], "attempts": row[9],
            }
            for row in rows
        ]

    # שורות שנתפסו (claimed) ע"י הרצה שככל הנראה לא סיימה (תהליך נפל וכו') - במקום לנסות
    # שוב לנצח בלי בקרה, מסמנים כנכשל במפורש בהרצה הבאה (ראו §4 בתוכנית)
    def reclaim_stale_claims(self, stale_after_minutes=10):
        threshold = (
            datetime.datetime.now() - datetime.timedelta(minutes=stale_after_minutes)
        ).isoformat(timespec="seconds")
        rows = self.conn.execute(
            "SELECT id, automation_id, target_phone FROM due_actions "
            "WHERE status = 'claimed' AND claimed_at < ?",
            (threshold,),
        ).fetchall()
        for row in rows:
            self.mark_failed(row[0])
        return [{"id": row[0], "automation_id": row[1], "target_phone": row[2]} for row in rows]

    def log_execution(self, automation_id, target_phone, status, channel, detail, due_action_id=None):
        self.conn.execute(
            "INSERT INTO automation_executions (due_action_id, automation_id, target_phone, "
            "status, channel, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (due_action_id, automation_id, target_phone, status, channel, detail,
             datetime.datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    # בשימוש ע"י resolver-ים דינמיים שצריכים cooldown אנטי-ספאם (כרגע רק
    # _resolve_expiring_sessions_recipients ב-engine.py - ראו שם למה) - בודקת אם כבר נשלחה
    # בהצלחה הודעה מהאוטומציה הזו לטלפון הזה בטווח הימים האחרון
    def has_recent_execution(self, automation_id, phone, since_days, status="success"):
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=since_days)).isoformat(timespec="seconds")
        row = self.conn.execute(
            "SELECT 1 FROM automation_executions WHERE automation_id = ? AND target_phone = ? "
            "AND status = ? AND created_at >= ? LIMIT 1",
            (automation_id, phone, status, cutoff),
        ).fetchone()
        return row is not None

    # --- קריאה/עריכה לממשק הניהול (עמוד "אוטומציות") ---

    def get_all(self, tenant_id=1):
        rows = self.conn.execute(
            "SELECT id, name, trigger_type, enabled, created_at, trigger_config FROM automations "
            "WHERE tenant_id = ? ORDER BY id",
            (tenant_id,),
        ).fetchall()
        automations = []
        for row in rows:
            automation_id = row[0]
            success_count, failed_count = self.conn.execute(
                "SELECT "
                "SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) "
                "FROM automation_executions WHERE automation_id = ?",
                (automation_id,),
            ).fetchone()
            trigger_type = row[2]
            trigger_config = json.loads(row[5]) if row[5] else {}
            # ל-audience_source דינמי (נגזר חי מ-Arbox בכל הרצה - ראו DYNAMIC_AUDIENCE_SOURCES
            # ב-atlas/automations/engine.py, מקור האמת לרשימה הזו) אין "רשימה" קבועה לספור -
            # מוצג "-" (None) בדיוק כמו אוטומציה מבוססת-אירוע. מוכפל כאן במתכוון (לא מייבאים
            # את engine.py לשכבת ה-repository) - אם מוסיפים audience_source דינמי חדש, לעדכן גם כאן
            is_manual_audience = (
                trigger_type == "scheduled"
                and trigger_config.get("audience_source") not in (
                    "arbox_birthday", "arbox_membership_expiring", "arbox_expiring_sessions",
                    "arbox_active_members", "arbox_trial_reminder", "arbox_churned",
                )
            )
            expected_recipient_count = None
            if is_manual_audience:
                recipients_count, blacklist_count = self.conn.execute(
                    "SELECT "
                    "(SELECT COUNT(*) FROM automation_recipients WHERE automation_id = ?), "
                    "(SELECT COUNT(*) FROM automation_recipients r "
                    " JOIN global_blacklist b ON b.phone = r.phone "
                    " WHERE r.automation_id = ? AND b.tenant_id = ?)",
                    (automation_id, automation_id, tenant_id),
                ).fetchone()
                expected_recipient_count = (recipients_count or 0) - (blacklist_count or 0)
            automations.append({
                "id": automation_id,
                "name": row[1],
                "trigger_type": trigger_type,
                "enabled": bool(row[3]),
                "created_at": row[4],
                "trigger_config": trigger_config,
                "success_count": success_count or 0,
                "failed_count": failed_count or 0,
                "expected_recipient_count": expected_recipient_count,
            })
        return automations

    def get_by_id(self, automation_id, tenant_id=1):
        row = self.conn.execute(
            "SELECT id, name, trigger_type, enabled, created_at, trigger_config, last_run_at "
            "FROM automations WHERE id = ? AND tenant_id = ?",
            (automation_id, tenant_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0], "name": row[1], "trigger_type": row[2],
            "enabled": bool(row[3]), "created_at": row[4],
            "trigger_config": json.loads(row[5]) if row[5] else {},
            "last_run_at": row[6],
        }

    # --- יצירה/עריכה של אוטומציות מתוזמנות (trigger_type='scheduled') דרך הממשק ---

    def create_automation(self, name, trigger_type, trigger_config, tenant_id=1):
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cursor = self.conn.execute(
            "INSERT INTO automations (tenant_id, name, trigger_type, trigger_config, enabled, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (tenant_id, name, trigger_type, json.dumps(trigger_config, ensure_ascii=False), now, now),
        )
        self.conn.commit()
        return cursor.lastrowid

    def add_step(self, automation_id, step_order, delay_minutes, action_type, action_config):
        self.conn.execute(
            "INSERT INTO automation_steps (automation_id, step_order, delay_minutes, action_type, "
            "action_config) VALUES (?, ?, ?, ?, ?)",
            (automation_id, step_order, delay_minutes, action_type,
             json.dumps(action_config, ensure_ascii=False)),
        )
        self.conn.commit()

    def update_schedule(self, automation_id, trigger_config):
        now = datetime.datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            "UPDATE automations SET trigger_config = ?, updated_at = ? WHERE id = ?",
            (json.dumps(trigger_config, ensure_ascii=False), now, automation_id),
        )
        self.conn.commit()

    # אוטומציות מתוזמנות מופעלות (לא מבוססות-אירוע) - נסרקות ע"י process_scheduled_automations
    def get_scheduled_automations(self, tenant_id=1):
        rows = self.conn.execute(
            "SELECT id, name, trigger_config, last_run_at FROM automations "
            "WHERE trigger_type = 'scheduled' AND tenant_id = ? AND enabled = 1",
            (tenant_id,),
        ).fetchall()
        return [
            {
                "id": row[0], "name": row[1],
                "trigger_config": json.loads(row[2]) if row[2] else {},
                "last_run_at": row[3],
            }
            for row in rows
        ]

    def update_last_run(self, automation_id, when):
        self.conn.execute("UPDATE automations SET last_run_at = ? WHERE id = ?", (when, automation_id))
        self.conn.commit()

    # --- רשימת נמענים ידנית (לאוטומציות מתוזמנות בלבד) ---

    def add_recipient(self, automation_id, phone, full_name):
        now = datetime.datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT INTO automation_recipients (automation_id, phone, full_name, created_at) "
            "VALUES (?, ?, ?, ?)",
            (automation_id, phone, full_name, now),
        )
        self.conn.commit()

    def remove_recipient(self, recipient_id):
        self.conn.execute("DELETE FROM automation_recipients WHERE id = ?", (recipient_id,))
        self.conn.commit()

    def get_recipients(self, automation_id):
        rows = self.conn.execute(
            "SELECT id, phone, full_name FROM automation_recipients WHERE automation_id = ? ORDER BY id",
            (automation_id,),
        ).fetchall()
        return [{"id": row[0], "phone": row[1], "full_name": row[2]} for row in rows]

    # --- בלאקליסט גלובלי (משותף לכל האוטומציות המתוזמנות, לא פר-אוטומציה - ראו automation_db.py) ---

    def add_to_global_blacklist(self, phone, full_name=None, tenant_id=1):
        now = datetime.datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT OR IGNORE INTO global_blacklist (tenant_id, phone, full_name, created_at) "
            "VALUES (?, ?, ?, ?)",
            (tenant_id, phone, full_name, now),
        )
        self.conn.commit()

    def remove_from_global_blacklist(self, blacklist_id):
        self.conn.execute("DELETE FROM global_blacklist WHERE id = ?", (blacklist_id,))
        self.conn.commit()

    def get_global_blacklist(self, tenant_id=1):
        rows = self.conn.execute(
            "SELECT id, phone, full_name FROM global_blacklist WHERE tenant_id = ? ORDER BY id",
            (tenant_id,),
        ).fetchall()
        return [{"id": row[0], "phone": row[1], "full_name": row[2]} for row in rows]

    def toggle_enabled(self, automation_id):
        now = datetime.datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            "UPDATE automations SET enabled = 1 - enabled, updated_at = ? WHERE id = ?",
            (now, automation_id),
        )
        self.conn.commit()

    def get_recent_executions(self, automation_id, limit=50):
        rows = self.conn.execute(
            "SELECT id, target_phone, status, channel, detail, created_at FROM automation_executions "
            "WHERE automation_id = ? ORDER BY id DESC LIMIT ?",
            (automation_id, limit),
        ).fetchall()
        return [
            {
                "id": row[0], "target_phone": row[1], "status": row[2],
                "channel": row[3], "detail": row[4], "created_at": row[5],
            }
            for row in rows
        ]
