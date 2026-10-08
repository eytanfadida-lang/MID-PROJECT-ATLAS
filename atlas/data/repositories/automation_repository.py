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

    def update_step(self, step_id, text_template, delay_minutes):
        step = self.get_step(step_id)
        action_config = dict(step["action_config"]) if step else {}
        action_config["mode"] = "text"
        action_config["text_template"] = text_template
        self.conn.execute(
            "UPDATE automation_steps SET delay_minutes = ?, action_config = ? WHERE id = ?",
            (delay_minutes, json.dumps(action_config, ensure_ascii=False), step_id),
        )
        self.conn.commit()

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

    # --- קריאה/עריכה לממשק הניהול (עמוד "אוטומציות") ---

    def get_all(self, tenant_id=1):
        rows = self.conn.execute(
            "SELECT id, name, trigger_type, enabled, created_at FROM automations "
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
            automations.append({
                "id": automation_id,
                "name": row[1],
                "trigger_type": row[2],
                "enabled": bool(row[3]),
                "created_at": row[4],
                "success_count": success_count or 0,
                "failed_count": failed_count or 0,
            })
        return automations

    def get_by_id(self, automation_id, tenant_id=1):
        row = self.conn.execute(
            "SELECT id, name, trigger_type, enabled, created_at FROM automations "
            "WHERE id = ? AND tenant_id = ?",
            (automation_id, tenant_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0], "name": row[1], "trigger_type": row[2],
            "enabled": bool(row[3]), "created_at": row[4],
        }

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
