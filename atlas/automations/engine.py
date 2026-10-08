import datetime

from atlas.integrations.whatsapp import bot as whatsapp_bot
from atlas.services.phone_utils import to_whatsapp_format

CHANNEL_WHATSAPP_CLOUD_API = "whatsapp_cloud_api"


# נקראת מנקודת חיבור אחת (למשל book_trial_class) ברגע שאירוע עסקי קרה בפועל - אין Event
# Bus במערכת (ראו תוכנית), אז זו קריאה מפורשת, לא מנוי/פרסום. phone תמיד בפורמט מקומי
# (0501234567, כמו בכל שאר המערכת - ראו normalize_phone), לא בפורמט וואטסאפ הבינלאומי
def fire_trigger(repos, trigger_type, context, phone, lead_id=None, tenant_id=1):
    automations = repos.automations.get_enabled_by_trigger(trigger_type, tenant_id=tenant_id)
    for automation in automations:
        for step in repos.automations.get_steps(automation["id"]):
            run_after = (
                datetime.datetime.now() + datetime.timedelta(minutes=step["delay_minutes"])
            ).isoformat(timespec="seconds")
            due_action = repos.automations.insert_due_action(
                tenant_id=tenant_id,
                automation_id=automation["id"],
                step_id=step["id"],
                target_phone=phone,
                context=context,
                run_after=run_after,
                target_lead_id=lead_id,
            )
            # delay=0 מבוצע מייד, סינכרונית, באותה בקשה - בלי ממתין ל-poller (שעדיין לא קיים,
            # ראו §"מה לא נבנה ב-Phase הזה" בתוכנית). פעולה מושהית נשארת 'pending' בטבלה
            # לשלב הבא (poller עתידי)
            if step["delay_minutes"] == 0:
                process_due_action(repos, due_action)


# מבצעת פעולה אחת בפועל (כרגע רק send_whatsapp_message נתמך) ומתעדת תוצאה - גם בטבלת
# automation_executions (יומן ביקורת ייעודי) וגם, בהצלחה, ב-customer_bot_messages כדי
# שההודעה תופיע בעמוד שיחות בוט הלקוחות הקיים לצד שאר ההתכתבות עם אותה לקוחה. חתימה בכוונה
# לוקחת רק (repos, due_action) - זו אותה פונקציה שגם poller עתידי יקרא לה, לא רק fire_trigger
def process_due_action(repos, due_action):
    if due_action["status"] != "pending":
        return  # כבר טופל (או נתפס ע"י הרצה אחרת) - לא לבצע פעמיים

    repos.automations.claim_due_action(due_action["id"])

    step = repos.automations.get_step(due_action["step_id"])
    action_type = step["action_type"] if step else None
    action_config = step["action_config"] if step else {}

    if action_type != "send_whatsapp_message":
        repos.automations.mark_failed(due_action["id"])
        repos.automations.log_execution(
            due_action["automation_id"], due_action["target_phone"], "failed",
            CHANNEL_WHATSAPP_CLOUD_API, f"סוג פעולה לא נתמך: {action_type}",
            due_action_id=due_action["id"],
        )
        return

    try:
        body = action_config.get("text_template", "").format(**due_action["context"])
    except Exception as exc:
        repos.automations.mark_failed(due_action["id"])
        repos.automations.log_execution(
            due_action["automation_id"], due_action["target_phone"], "failed",
            CHANNEL_WHATSAPP_CLOUD_API, f"שגיאה ברינדור התבנית: {exc}",
            due_action_id=due_action["id"],
        )
        return

    whatsapp_to = to_whatsapp_format(due_action["target_phone"])
    try:
        whatsapp_bot.send_text_message(whatsapp_bot.CUSTOMER_BOT, whatsapp_to, body)
    except Exception as exc:
        repos.automations.mark_failed(due_action["id"])
        repos.automations.log_execution(
            due_action["automation_id"], due_action["target_phone"], "failed",
            CHANNEL_WHATSAPP_CLOUD_API, f"שליחת וואטסאפ נכשלה: {exc}",
            due_action_id=due_action["id"],
        )
        return

    repos.automations.mark_sent(due_action["id"])
    repos.automations.log_execution(
        due_action["automation_id"], due_action["target_phone"], "success",
        CHANNEL_WHATSAPP_CLOUD_API, body, due_action_id=due_action["id"],
    )
    repos.customer_bot_messages.log(due_action["target_phone"], "out", body)


# נקראת מ-/tasks/automations-run (cron חיצוני, GitHub Actions - אין thread רקע בפרודקשן,
# ראו atlas/factory.py). קודם מאפסת claimed שנתקעו (תהליך קודם שלא סיים), ואז מבצעת את כל
# הפעולות שהגיע זמנן. claim_due_action הוא UPDATE מותנה (WHERE status='pending') - אם שתי
# הרצות חופפות, השנייה פשוט לא תצליח לתפוס את מה שהראשונה כבר תפסה (idempotent)
def process_due_actions(repos, limit=50):
    stale = repos.automations.reclaim_stale_claims()
    for row in stale:
        repos.automations.log_execution(
            row["automation_id"], row["target_phone"], "failed",
            CHANNEL_WHATSAPP_CLOUD_API, "נתקע במצב 'claimed' יותר מדי זמן - סומן כנכשל",
        )

    due_actions = repos.automations.get_due(limit=limit)
    processed = 0
    for due_action in due_actions:
        process_due_action(repos, due_action)
        processed += 1
    return {"processed": processed, "reclaimed_stale": len(stale)}
