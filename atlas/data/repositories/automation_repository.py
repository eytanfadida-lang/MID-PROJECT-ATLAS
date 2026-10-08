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

    def log_execution(self, automation_id, target_phone, status, channel, detail, due_action_id=None):
        self.conn.execute(
            "INSERT INTO automation_executions (due_action_id, automation_id, target_phone, "
            "status, channel, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (due_action_id, automation_id, target_phone, status, channel, detail,
             datetime.datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()
