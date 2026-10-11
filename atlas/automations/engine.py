import datetime

from atlas.integrations.arbox import client as arbox_client
from atlas.integrations.whatsapp import bot as whatsapp_bot
from atlas.services import time_utils
from atlas.services.phone_utils import normalize_phone, to_whatsapp_format

CHANNEL_WHATSAPP_CLOUD_API = "whatsapp_cloud_api"


# נקראת מנקודת חיבור אחת (למשל book_trial_class) ברגע שאירוע עסקי קרה בפועל - אין Event
# Bus במערכת (ראו תוכנית), אז זו קריאה מפורשת, לא מנוי/פרסום. phone תמיד בפורמט מקומי
# (0501234567, כמו בכל שאר המערכת - ראו normalize_phone), לא בפורמט וואטסאפ הבינלאומי
def fire_trigger(repos, trigger_type, context, phone, lead_id=None, tenant_id=1):
    automations = repos.automations.get_enabled_by_trigger(trigger_type, tenant_id=tenant_id)
    for automation in automations:
        _fire_automation_steps(repos, automation["id"], context, phone, lead_id, tenant_id)


# משותפת לשני המקורות האפשריים ליצירת due_actions: אירוע חד-פעמי (fire_trigger, נמען יחיד
# מנקודת חיבור כמו book_trial_class) ואוטומציה מתוזמנת (process_scheduled_automations, כמה
# נמענים מרשימה ידנית) - שתיהן בסופו של דבר "לכל step של האוטומציה הזו, ליצור due_action אחד".
# run_after אופציונלי: דריסה למועד שליחה מדויק (למשל שלב "הורדה" מוקדם מה"שליחה" בפועל
# באוטומציה מתוזמנת - ראו process_scheduled_automations) - כשלא מסופק, מחושב מ-delay_minutes
# של ה-step כרגיל (ברירת המחדל, בשימוש ע"י fire_trigger)
def _fire_automation_steps(repos, automation_id, context, phone, lead_id=None, tenant_id=1,
                            run_after=None):
    for step in repos.automations.get_steps(automation_id):
        step_run_after = run_after or (
            datetime.datetime.now() + datetime.timedelta(minutes=step["delay_minutes"])
        ).isoformat(timespec="seconds")
        due_action = repos.automations.insert_due_action(
            tenant_id=tenant_id,
            automation_id=automation_id,
            step_id=step["id"],
            target_phone=phone,
            context=context,
            run_after=step_run_after,
            target_lead_id=lead_id,
        )
        # אם הגיע הזמן כבר עכשיו (המקרה הרגיל: run_after=now+0) - מבוצע מייד, סינכרונית, באותה
        # בקשה, בלי לחכות ל-poller. אם run_after בעתיד (השהייה, או שלב "שליחה" מאוחר יותר
        # מ"הורדה") - נשאר 'pending' בטבלה ל-/tasks/automations-run (process_due_actions)
        if datetime.datetime.fromisoformat(due_action["run_after"]) <= datetime.datetime.now():
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

    scheduled_fired = process_scheduled_automations(repos)
    return {"processed": processed, "reclaimed_stale": len(stale), "scheduled_fired": scheduled_fired}


SCHEDULE_TYPES = ("once", "daily", "weekly", "monthly")


def _parse_time_of_day(value, default_hour=9, default_minute=0):
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
        return hour, minute
    except (ValueError, AttributeError, TypeError):
        return default_hour, default_minute


# מחשבת שני מועדים ל"היום" (או ליחיד, ל-once) לפי trigger_config: stage_instant (מתי "נועלים"
# את רשימת הנמענים - שלב "הורדה", תמיד <= send) ו-send_instant (מתי בפועל נשלחת ההודעה).
# אם אין stage_time מוגדר, שני המועדים זהים (שליחה מיידית בלי שלב הורדה נפרד - ברירת המחדל).
# מחזירה (None, None) אם האוטומציה הזו בכלל לא אמורה לרוץ היום (יום בשבוע/חודש לא תואם).
#
# now מגיע naive-UTC (datetime.datetime.now() של השרת - ראו time_utils.py). כל הערכים
# שהמשתמש הזין בטופס (time_of_day/run_at/stage_at/stage_time, וגם יום-בשבוע/יום-בחודש
# שנגזרים מהתאריך "היום") מתכוונים לשעון ישראל - ממירים ל/מ-UTC naive רק כאן, כדי שהערך
# המוחזר (וכל מה שמשתמש בו בהמשך - due_actions.run_after, השוואות מול datetime.now()) יישאר
# UTC naive עקבי עם שאר המערכת, בלי לשנות שום דבר מחוץ לגבול הזה
def _compute_schedule_instants(trigger_config, now):
    now_local = time_utils.utc_now_to_israel(now)
    schedule_type = trigger_config.get("schedule_type")

    if schedule_type == "once":
        run_at = trigger_config.get("run_at")
        if not run_at:
            return None, None
        try:
            send_instant = time_utils.israel_naive_to_utc_naive(datetime.datetime.fromisoformat(run_at))
        except ValueError:
            return None, None
        stage_at = trigger_config.get("stage_at")
        if stage_at:
            try:
                stage_instant = time_utils.israel_naive_to_utc_naive(datetime.datetime.fromisoformat(stage_at))
                return stage_instant, send_instant
            except ValueError:
                pass
        return send_instant, send_instant

    if schedule_type == "weekly":
        # weekdays: רשימת ימים (0=שני...6=ראשון, תואם datetime.weekday()) - weekday יחיד
        # (ישן, לפני שדרוג לבחירה מרובה) עדיין נתמך לתאימות לאחור
        weekdays = trigger_config.get("weekdays")
        if weekdays is None:
            weekdays = [trigger_config.get("weekday", 0)]
        if now_local.weekday() not in weekdays:
            return None, None
    elif schedule_type == "monthly":
        if now_local.day != trigger_config.get("day_of_month", 1):
            return None, None
    elif schedule_type != "daily":
        return None, None

    hour, minute = _parse_time_of_day(trigger_config.get("time_of_day"))
    send_instant_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=None)
    send_instant = time_utils.israel_naive_to_utc_naive(send_instant_local)

    stage_time = trigger_config.get("stage_time")
    if stage_time:
        s_hour, s_minute = _parse_time_of_day(stage_time, default_hour=hour, default_minute=minute)
        stage_instant_local = now_local.replace(hour=s_hour, minute=s_minute, second=0, microsecond=0, tzinfo=None)
        stage_instant = time_utils.israel_naive_to_utc_naive(stage_instant_local)
    else:
        stage_instant = send_instant

    return stage_instant, send_instant


# שולפת את מי שיום ההולדת שלו/שלה חל היום (לפי יום-בחודש, לא שנה - ראו fetch_arbox_birthdays),
# ישירות מ-Arbox בכל הרצה (לא רשימה סטטית כמו הנמענים הידניים). מחזירה (recipients, error) -
# error לא None אם שליפת Arbox נכשלה (כדי לתעד כישלון במקום לדלג בשקט). חתימה אחידה
# (repos, automation, now) לכל פונקציות ה-resolver - ראו _AUDIENCE_RESOLVERS - גם כשלא כולן
# צריכות בפועל את repos (כאן ו-ב-_resolve_membership_expiring_recipients לא בשימוש)
def _resolve_birthday_recipients(repos, automation, now):
    trigger_config = automation["trigger_config"]
    api_key = arbox_client.load_arbox_api_key()
    if not api_key:
        return [], "שגיאה טכנית בגישה ל-Arbox (אין מפתח API)"

    today = time_utils.utc_now_to_israel(now).date().isoformat()
    try:
        people = arbox_client.fetch_arbox_birthdays(api_key, today, today)
    except Exception as exc:
        return [], f"שליפת ימי הולדת מ-Arbox נכשלה: {exc}"

    audience_status = trigger_config.get("audience_status", "all")
    recipients = []
    for person in people:
        if audience_status != "all" and person.get("status") != audience_status:
            continue
        phone = normalize_phone(person.get("phone"))
        if not phone:
            continue
        recipients.append({
            "phone": phone,
            "full_name": person.get("full_name") or person.get("first_name") or "",
            "age": person.get("age"),
        })
    return recipients, None


# שולפת מי שהמנוי שלה עומד להסתיים בעוד trigger_config["days_before"] ימים (ברירת מחדל 5,
# תואם "הגדר שליחה עבור X ימים לפני סיום המנוי" ב-Upgrade360) - ישירות מ-Arbox בכל הרצה.
# בניגוד ל-birthdayReport, ההתאמה כאן היא לפי תאריך סיום ממשי (end_date), לא יום-בחודש חוזר.
# מדלגת על מנויים שכבר בוטלו (cancelled=yes) - אין טעם להזכיר לחדש מנוי שכבר מבוטל
def _resolve_membership_expiring_recipients(repos, automation, now):
    trigger_config = automation["trigger_config"]
    api_key = arbox_client.load_arbox_api_key()
    if not api_key:
        return [], "שגיאה טכנית בגישה ל-Arbox (אין מפתח API)"

    days_before = trigger_config.get("days_before", 5)
    target_date = (time_utils.utc_now_to_israel(now).date() + datetime.timedelta(days=days_before)).isoformat()
    try:
        memberships = arbox_client.fetch_arbox_expiring_memberships(api_key, target_date, target_date)
    except Exception as exc:
        return [], f"שליפת מנויים שעומדים להסתיים מ-Arbox נכשלה: {exc}"

    recipients = []
    for membership in memberships:
        if membership.get("cancelled") == "yes":
            continue
        phone = normalize_phone(membership.get("phone"))
        if not phone:
            continue
        recipients.append({
            "phone": phone,
            "full_name": membership.get("full_name") or membership.get("first_name") or "",
            "membership_type_name": membership.get("membership_type_name") or "",
            "end_date": membership.get("end_date") or "",
            "days_left": days_before,
        })
    return recipients, None


# שולפת את מי שנותרו לה X ניקובים בכרטיסייה (ברירת מחדל 1, תואם "הגדר שליחה עבור 1 ניקובים
# שנותרו" ב-Upgrade360, מזהה "InvalidTicketReport" שם) - ישירות מ-Arbox בכל הרצה.
# expiringSessionsReport, בניגוד לשני הדוחות למעלה, מחזיר שורות עם *כל* טווח sessions_left
# (מאומת מול ה-API) - הסינון לסף המדויק נעשה כאן, לא ע"י הדוח עצמו. בניגוד ליום-הולדת/סיום-
# מנוי (שנפתרים אוטומטית למחרת כי התאריך המתאים עבר), sessions_left יכול להישאר תקוע על 1
# ימים רבים אם הלקוחה לא מגיעה - בלי הגנה היינו שולחים לה את אותה הודעה כל יום. לכן כאן יש
# cooldown מפורש (has_recent_execution) שמדלג על מי שכבר קיבלה הודעה מהאוטומציה הזו בטווח
# הימים האחרון (resend_cooldown_days, ברירת מחדל 14) - זו הסיבה היחידה ש-resolver הזה צריך
# גם את repos (האחרים לא), ומוגדר ככה (repos, automation, now) לאחידות
def _resolve_expiring_sessions_recipients(repos, automation, now):
    trigger_config = automation["trigger_config"]
    api_key = arbox_client.load_arbox_api_key()
    if not api_key:
        return [], "שגיאה טכנית בגישה ל-Arbox (אין מפתח API)"

    sessions_left_threshold = trigger_config.get("sessions_left", 1)
    cooldown_days = trigger_config.get("resend_cooldown_days", 14)
    today = time_utils.utc_now_to_israel(now).date().isoformat()
    try:
        rows = arbox_client.fetch_arbox_expiring_sessions(api_key, today, today)
    except Exception as exc:
        return [], f"שליפת כרטיסיות שעומדות להסתיים מ-Arbox נכשלה: {exc}"

    seen_phones = set()
    recipients = []
    for row in rows:
        if row.get("sessions_left") != sessions_left_threshold:
            continue
        if row.get("cancelled") == "yes":
            continue
        phone = normalize_phone(row.get("phone"))
        if not phone or phone in seen_phones:
            continue  # אותה לקוחה יכולה להופיע כמה פעמים (כמה כרטיסיות נפרדות) - שולחים פעם אחת
        if repos.automations.has_recent_execution(automation["id"], phone, cooldown_days):
            continue
        seen_phones.add(phone)
        recipients.append({
            "phone": phone,
            "full_name": row.get("full_name") or row.get("first_name") or "",
            "membership_type_name": row.get("membership_type_name") or "",
            "sessions_left": row.get("sessions_left"),
        })
    return recipients, None


# "רשימת תפוצה כללית" ללקוחות פעילים - בניגוד לשלושת הקודמים (שתמיד תזמון יומי, בודקים תנאי
# עסקי יומיומי), זו משתמשת בתזמון הרגיל/גמיש שהמשתמש בוחר (חד-פעמי/יומי/שבועי/חודשי, בדיוק
# כמו "רשימה ידנית" - ראו _parse_schedule_form) כי היא מיועדת לשידור כללי מתוזמן (למשל כל יום
# רביעי), לא לבדיקת תנאי. סינון אופציונלי לפי סוג מנוי ו/או סניף (membership_types/locations -
# שתיהן רשימות שמות מדויקים שנבחרו בתיבת סימון מרובה בטופס, ראו _schedule_fields.html - לא
# substring, exact match על ערכי enum ידועים מראש - LOCATIONS בבלופרינט/הקאש המקומי בהתאמה).
# בניגוד ל-Upgrade360 (שם אפשר לערוך את תוכן ההודעה אד-הוק בכל הרצה, ראו צילום מסך) - כאן יש
# תבנית קבועה לאוטומציה (כמו כל אוטומציה אחרת), ניתנת לעריכה בכל עת לפני ההרצה הבאה (וגם
# לשחזור מהיסטוריה - ראו automation_message_history), לא פר-הרצה
def _resolve_active_members_recipients(repos, automation, now):
    trigger_config = automation["trigger_config"]
    api_key = arbox_client.load_arbox_api_key()
    if not api_key:
        return [], "שגיאה טכנית בגישה ל-Arbox (אין מפתח API)"

    today = time_utils.utc_now_to_israel(now).date().isoformat()
    try:
        memberships = arbox_client.fetch_arbox_active_memberships_report(api_key, today, today)
    except Exception as exc:
        return [], f"שליפת לקוחות פעילים מ-Arbox נכשלה: {exc}"

    membership_types_filter = set(trigger_config.get("membership_types") or [])
    locations_filter = set(trigger_config.get("locations") or [])

    seen_phones = set()
    recipients = []
    for membership in memberships:
        if membership_types_filter and (membership.get("membership_type_name") or "") not in membership_types_filter:
            continue
        if locations_filter and (membership.get("location_name") or "") not in locations_filter:
            continue
        phone = normalize_phone(membership.get("phone"))
        if not phone or phone in seen_phones:
            continue  # אותה לקוחה יכולה להופיע כמה פעמים (כמה מנויים פעילים בו-זמנית)
        seen_phones.add(phone)
        recipients.append({
            "phone": phone,
            "full_name": membership.get("full_name") or membership.get("first_name") or "",
            "membership_type_name": membership.get("membership_type_name") or "",
            "location_name": membership.get("location_name") or "",
        })
    return recipients, None


# תזכורת לשיעור ניסיון שמתוזמן מחר/היום - תואם "תזכורת יום לפני/באותו יום אימוני ניסיון"
# ב-Upgrade360. reminder_timing קובע את התאריך (day_before=מחר, same_day=היום);
# time_filter+before_hour קובעים איזה חלק מהיום (before=עד שעה X, after=החל משעה X - תואם
# "הגדר שליחה עבור אימונים עד/החל מהשעה 12:00" שם). locations אופציונלי (ריק=כל הסניפים) -
# ב-Upgrade360 כל סניף הוא הודעה נפרדת (כתובת/וויז שונים בטקסט) - כאן זה נפתר ע"י יצירת
# אוטומציה נפרדת לכל סניף עם locations=[סניף אחד], לא ע"י תמיכה מיוחדת בנוסח רב-סניפי
def _resolve_trial_reminder_recipients(repos, automation, now):
    trigger_config = automation["trigger_config"]
    api_key = arbox_client.load_arbox_api_key()
    if not api_key:
        return [], "שגיאה טכנית בגישה ל-Arbox (אין מפתח API)"

    days_ahead = 1 if trigger_config.get("reminder_timing") != "same_day" else 0
    target_date = (time_utils.utc_now_to_israel(now).date() + datetime.timedelta(days=days_ahead)).isoformat()
    try:
        classes = arbox_client.fetch_arbox_trial_classes(api_key, target_date, target_date)
    except Exception as exc:
        return [], f"שליפת שיעורי ניסיון מ-Arbox נכשלה: {exc}"

    time_filter = trigger_config.get("time_filter", "before")
    before_hour = trigger_config.get("before_hour", 12)
    locations_filter = set(trigger_config.get("locations") or [])

    seen_phones = set()
    recipients = []
    for cls in classes:
        start_time = cls.get("start_time") or ""
        try:
            start_hour = int(start_time.split(":", 1)[0])
        except (ValueError, IndexError):
            continue
        if time_filter == "after" and start_hour < before_hour:
            continue
        if time_filter != "after" and start_hour >= before_hour:
            continue
        if locations_filter and (cls.get("location_name") or "") not in locations_filter:
            continue
        phone = normalize_phone(cls.get("phone"))
        if not phone or phone in seen_phones:
            continue
        seen_phones.add(phone)
        recipients.append({
            "phone": phone,
            "full_name": cls.get("full_name") or cls.get("first_name") or "",
            "class_name": (cls.get("class_name") or "").strip(),
            "start_time": start_time[:5],
            "location_name": cls.get("location_name") or "",
        })
    return recipients, None


# מיפוי audience_source -> פונקציית שליפה - כל פונקציה מחזירה (recipients, error) כמו
# _resolve_birthday_recipients/_resolve_membership_expiring_recipients למעלה. audience_source
# שלא מופיע כאן (כולל ברירת המחדל "manual") נופל לרשימת הנמענים הידנית (automation_recipients)
_AUDIENCE_RESOLVERS = {
    "arbox_birthday": _resolve_birthday_recipients,
    "arbox_membership_expiring": _resolve_membership_expiring_recipients,
    "arbox_expiring_sessions": _resolve_expiring_sessions_recipients,
    "arbox_active_members": _resolve_active_members_recipients,
    "arbox_trial_reminder": _resolve_trial_reminder_recipients,
}

# נחשף כדי שקוד אחר (הבלופרינט, ה-repository) יוכל לבדוק "האם זו אוטומציה עם קהל דינמי
# מ-Arbox" בלי לשכפל את רשימת ה-audience_source הידועים בכמה מקומות - מקור אמת יחיד
DYNAMIC_AUDIENCE_SOURCES = frozenset(_AUDIENCE_RESOLVERS.keys())


# נקראת מ-process_due_actions (אותו poller, אותה תדירות) - סורקת אוטומציות מתוזמנות
# (trigger_type='scheduled'), ולכל אחת שהגיע זמן ה"הורדה" (נעילת רשימת הנמענים) שלה ועוד לא
# רצה להזדמנות הזו, יוצרת due_actions לכל הנמענים (מרשימה ידנית או מ-Arbox - ראו
# _resolve_recipients) שאינם ברשימת ההחרגה הגלובלית (global_blacklist - משותפת לכל
# האוטומציות, לא פר-אוטומציה), עם זמן שליחה = send_instant (לא בהכרח מייד - ראו
# _fire_automation_steps). לא קשורות ל-fire_trigger/אירוע בודד
def process_scheduled_automations(repos, tenant_id=1):
    now = datetime.datetime.now()
    fired = 0
    blacklisted_phones = {row["phone"] for row in repos.automations.get_global_blacklist(tenant_id=tenant_id)}
    for automation in repos.automations.get_scheduled_automations(tenant_id=tenant_id):
        stage_instant, send_instant = _compute_schedule_instants(automation["trigger_config"], now)
        if stage_instant is None or now < stage_instant:
            continue

        last_run_at = automation.get("last_run_at")
        if last_run_at:
            try:
                if datetime.datetime.fromisoformat(last_run_at) >= stage_instant:
                    continue  # כבר רץ להזדמנות הזו (לא יוצרים כפילות)
            except ValueError:
                pass

        audience_source = automation["trigger_config"].get("audience_source")
        resolver = _AUDIENCE_RESOLVERS.get(audience_source)
        if resolver:
            recipients, error = resolver(repos, automation, now)
            if error:
                repos.automations.log_execution(
                    automation["id"], "-", "failed", CHANNEL_WHATSAPP_CLOUD_API, error,
                )
                continue  # לא מעדכנים last_run_at - ננסה שוב בהרצה הבאה של ה-poller
        else:
            recipients = repos.automations.get_recipients(automation["id"])

        send_after = send_instant.isoformat(timespec="seconds")
        for recipient in recipients:
            if recipient["phone"] in blacklisted_phones:
                continue
            # כל שדה חוץ מ-phone/id הופך אוטומטית לחלק מה-context (שם מלא, גיל, תאריך סיום
            # מנוי וכו' - לפי מה שהרזולבר הרלוונטי מחזיר, בלי רשימת שדות קשיחה כאן). "id" מוחרג
            # כי ב-get_recipients הוא רק המזהה הפנימי של שורת automation_recipients - לא מידע
            # רלוונטי להודעה
            context = {key: value for key, value in recipient.items() if key not in ("phone", "id")}
            _fire_automation_steps(
                repos, automation["id"], context, recipient["phone"], tenant_id=tenant_id,
                run_after=send_after,
            )

        repos.automations.update_last_run(automation["id"], now.isoformat(timespec="seconds"))
        fired += 1
    return fired
