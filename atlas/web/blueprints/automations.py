import re

from flask import Blueprint, render_template, redirect, url_for, flash, abort, request, jsonify

from atlas.data.context import get_repos
from atlas.core.auth import admin_required
from atlas.automations.engine import SCHEDULE_TYPES, DYNAMIC_AUDIENCE_SOURCES
from atlas.integrations.whatsapp import bot as whatsapp_bot
from atlas.services.automation_recipient_bulk_import import import_recipients_from_file

# עמוד ניהול למנוע האוטומציות (ראו atlas/automations/engine.py) - טבלה אחת מאוחדת (לא
# רשימה+עמוד פרטים נפרד): כל שורה כוללת עריכת תוכן/תזמון/נמענים inline (מורחבת/מוסתרת
# ב-<details>, בלי JS מעבר לפעלה/כיבוי שדות התזמון בטופס היצירה/עריכה - ראו list.html).
# אוטומציות מבוססות-אירוע (כמו "הרשמה לשיעור ניסיון") עדיין מוגדרות בקוד בלבד (seed ב-
# atlas/data/automation_db.py). אוטומציות מתוזמנות (trigger_type="scheduled") נוצרות ונערכות
# לגמרי דרך הממשק. בלאקליסט הוא גלובלי (משותף לכל האוטומציות) - עמוד נפרד, לא פר-שורה
bp = Blueprint("automations", __name__, url_prefix="/automations")

_WEEKDAY_LABELS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]

# שולפת תבניות וואטסאפ מאושרות (מ-Meta בלבד, ראו atlas/web/blueprints/whatsapp_templates.py -
# אין שמירה מקומית) לשימוש כ"תוכן הודעה" באוטומציה, במקום טקסט חופשי - עוקף את חלון 24
# השעות (ראו _send_template_action ב-engine.py). נכשלת בשקט לרשימה ריקה (לא WABA ID מוגדר,
# או שגיאת רשת) - עמוד האוטומציות לא אמור "להישבר" בגלל זה, רק לא להציג אפשרות תבנית
def _get_approved_templates():
    config = whatsapp_bot.CUSTOMER_BOT
    if not whatsapp_bot.load_waba_id(config):
        return []
    try:
        templates = whatsapp_bot.list_message_templates(config)
    except Exception:
        return []
    enriched = []
    for t in templates:
        if t.get("status") != "APPROVED":
            continue
        body_text = next(
            (c.get("text", "") for c in t.get("components", []) if c.get("type") == "BODY"), ""
        )
        enriched.append({
            "name": t.get("name"), "language": t.get("language"), "body_text": body_text,
            "placeholder_count": len(set(re.findall(r"\{\{(\d+)\}\}", body_text))),
        })
    return enriched


# שני הסניפים הפיזיים היחידים של העסק (מאומת מול location_name בכל קריאות Arbox לאורך הפרויקט -
# אין endpoint ב-Arbox שמחזיר "רשימת סניפים" בפני עצמה, אז קבוע כאן בקוד). בשימוש לבחירה מרובה
# בטופס "לקוחות פעילים" (ראו _parse_schedule_form) - ואם תתווסף אוטומציה נוספת שצריכה סינון
# לפי סניף, ראוי לשלוף מכאן ולא לשכפל את הרשימה
LOCATIONS = ["קרית מוצקין", "טירת הכרמל"]

# קיבוץ אוטומציות לקטגוריות בעמוד הרשימה (כל קטגוריה היא <details> מתקפל, ראו list.html) -
# אותו רעיון כמו הקטגוריות ב-Upgrade360, לא זהה להן (שם לכל הודעה יש קטגוריה משלה ידנית,
# כאן נגזר אוטומטית מ-audience_source/trigger_type כדי שלא נצטרך לתחזק את זה ידנית בכל
# אוטומציה חדשה). סדר ה-dict קובע את סדר הקטגוריות בעמוד
_CATEGORY_LABELS = {
    "reminders": "תזכורות",
    "retention": "שימור ושיחזור לקוחות",
    "broadcast": "הודעות כלליות",
    "manual": "רשימה ידנית",
    "immediate": "הודעות מיידיות (מבוססות אירוע)",
}
_REMINDER_AUDIENCE_SOURCES = (
    "arbox_birthday", "arbox_membership_expiring", "arbox_expiring_sessions", "arbox_trial_reminder",
    "arbox_attendance_milestone",
)
_RETENTION_AUDIENCE_SOURCES = (
    "arbox_churned", "arbox_lost_leads", "arbox_converted_leads", "arbox_trial_no_show",
)


def _automation_category(automation):
    if automation["trigger_type"] != "scheduled":
        return "immediate"
    audience_source = automation["trigger_config"].get("audience_source")
    if audience_source in _REMINDER_AUDIENCE_SOURCES:
        return "reminders"
    if audience_source in _RETENTION_AUDIENCE_SOURCES:
        return "retention"
    if audience_source == "arbox_active_members":
        return "broadcast"
    return "manual"


# מקבצת אוטומציות לקטגוריות לפי _automation_category, בסדר הקבוע ב-_CATEGORY_LABELS -
# מחזירה רק קטגוריות שיש בהן בפועל אוטומציה אחת לפחות (לא מציגים קטגוריות ריקות)
def _group_by_category(automations):
    grouped = {key: [] for key in _CATEGORY_LABELS}
    for automation in automations:
        grouped[_automation_category(automation)].append(automation)
    return {
        key: {"rows": _subgroup_by_name(items), "count": len(items)}
        for key, items in grouped.items() if items
    }


# שם שנגמר ב-"- N ימים" (למשל "לקוחות שעזבו - 14 ימים") - כמה אוטומציות עם אותה תחילית
# (אותו "משפחת" תנאי, days_since שונה - ראו _resolve_churn_recipients/_resolve_lost_leads_
# recipients/_resolve_converted_leads_recipients) מקובצות יחד לתת-תפריט מתקפל אחד בתוך
# הקטגוריה, במקום שורה נפרדת לכל אחת - ראו list.html, automationsToggleGroup
_NAME_VARIANT_SUFFIX_RE = re.compile(r"^(.*) - \d+ ימים$")


# הופכת רשימת אוטומציות (בתוך קטגוריה אחת) לרשימת "שורות לרינדור" - שורת אוטומציה רגילה
# (kind="automation", group_id=None) או, כשיש 2+ אוטומציות עם אותה תחילית שם, כותרת קבוצה
# אחת (kind="group_header") ואחריה שורות החברות (group_id משותף, מתחילות hidden). שומרת על
# סדר "פעם ראשונה שנראתה" - לא ממיינת מחדש
def _subgroup_by_name(automations):
    groups = {}
    order = []
    seen_prefixes = set()
    for automation in automations:
        match = _NAME_VARIANT_SUFFIX_RE.match(automation["name"])
        prefix = match.group(1) if match else None
        if prefix:
            groups.setdefault(prefix, []).append(automation)
            if prefix not in seen_prefixes:
                seen_prefixes.add(prefix)
                order.append(("group", prefix))
        else:
            order.append(("single", automation))

    rows = []
    group_counter = 0
    for kind, value in order:
        if kind == "single":
            rows.append({"kind": "automation", "automation": value, "group_id": None})
            continue
        items = groups[value]
        if len(items) < 2:
            rows.append({"kind": "automation", "automation": items[0], "group_id": None})
            continue
        group_counter += 1
        group_id = f"group-{group_counter}"
        rows.append({"kind": "group_header", "name": value, "count": len(items), "group_id": group_id})
        for automation in items:
            rows.append({"kind": "automation", "automation": automation, "group_id": group_id})
    return rows


# מחלצת את ימי השבוע הנבחרים הן מ-request.form (MultiDict, כמה ערכים תחת אותו שם שדה -
# "weekdays") והן מ-trigger_config שכבר נשמר ב-DB (dict רגיל, כבר שמור כרשימת int) - כדי
# שתיבות הסימון בטופס יוצגו נכון גם בשגיאת ולידציה (מ-request.form) וגם בעריכה (מה-DB)
def _extract_weekdays(form):
    if hasattr(form, "getlist"):
        return [int(value) for value in form.getlist("weekdays") if value.isdigit()]
    return form.get("weekdays") or []


# אותו אידיום בדיוק כמו _extract_weekdays - נחוצה כי request.form (MultiDict, מכמה checkbox-ים
# תחת אותו name) ו-trigger_config שכבר נשמר (dict רגיל, רשימה פשוטה) נקראים אחרת
def _extract_membership_types(form):
    if hasattr(form, "getlist"):
        return form.getlist("membership_types")
    return form.get("membership_types") or []


def _extract_locations(form):
    if hasattr(form, "getlist"):
        return form.getlist("locations")
    return form.get("locations") or []


def _extract_param_templates(form):
    if hasattr(form, "getlist"):
        return form.getlist("param_templates")
    return form.get("param_templates") or []


# בונה את action_config של שלב "שליחת הודעה" מהטופס - משותף ליצירה (new_automation) ועריכה
# (edit_step), כדי לא לשכפל את הלוגיקה. מחזירה (action_config, error). מצב "template" מדלג
# על ערכים ריקים ב-param_templates (לא כל תבנית משתמשת בכל 5 השדות הקבועים בטופס)
def _build_message_action_config(form):
    mode = form.get("mode", "text")
    if mode == "template":
        template_name = form.get("template_name", "").strip()
        if not template_name:
            return None, "יש לבחור תבנית מאושרת."
        template_language = form.get("template_language", "he").strip() or "he"
        param_templates = [value.strip() for value in _extract_param_templates(form) if value.strip()]
        return {
            "mode": "template", "template_name": template_name,
            "template_language": template_language, "param_templates": param_templates,
        }, None

    text_template = form.get("text_template", "").strip()
    if not text_template:
        return None, "לא ניתן לשמור הודעה ריקה."
    return {"mode": "text", "text_template": text_template}, None


# בונה trigger_config מתוך טופס לפי schedule_type שנבחר - בשימוש גם ביצירה וגם בעריכה.
# מחזירה (trigger_config, error) - error לא None אם משהו חסר/לא תקין. "הורדה" (stage) היא
# אופציונלית - שלב מוקדם שבו "נועלים" את רשימת הנמענים (אחרי סינון בלאקליסט), לפני שהשליחה
# בפועל קורית בזמן המאוחר יותר - ראו atlas/automations/engine.py §_compute_schedule_instants.
# כשלא מוגדרת, הורדה=שליחה (ברירת המחדל, שליחה מיידית בלי שלב ביניים)
def _parse_schedule_form(form):
    # "יום הולדת (Arbox)" הוא תמיד תזמון יומי (בודקים כל יום מי חוגג/ת) - לא מציגים את
    # בורר schedule_type הרגיל בטופס, רק שעה + סינון קהל (פעילים/לא פעילים/הכל)
    if form.get("audience_source") == "arbox_birthday":
        time_of_day = form.get("time_of_day", "").strip() or "09:00"
        audience_status = form.get("audience_status", "all")
        if audience_status not in ("all", "active", "inactive"):
            audience_status = "all"
        return {
            "schedule_type": "daily", "time_of_day": time_of_day,
            "audience_source": "arbox_birthday", "audience_status": audience_status,
        }, None

    # "סיום מנוי מתקרב (Arbox)" - גם היא תמיד תזמון יומי (בודקים כל יום מי המנוי שלה
    # מסתיים עוד X ימים), עם שעה + מספר ימים מראש במקום סינון קהל
    if form.get("audience_source") == "arbox_membership_expiring":
        time_of_day = form.get("time_of_day", "").strip() or "09:00"
        try:
            days_before = int(form.get("days_before", "5"))
        except ValueError:
            days_before = 5
        days_before = min(max(days_before, 0), 90)
        return {
            "schedule_type": "daily", "time_of_day": time_of_day,
            "audience_source": "arbox_membership_expiring", "days_before": days_before,
        }, None

    # "לקוחות שעזבו (Arbox)" - גם היא תמיד תזמון יומי (בודקים כל יום מי שהמנוי שלה פג בדיוק
    # לפני X ימים), עם שעה + מספר ימים מאז. כדי לשלוח כמה הודעות בטווחים שונים (14/35 יום
    # וכו', כמו ב-Upgrade360) - יוצרים כמה אוטומציות נפרדות עם days_since שונה
    if form.get("audience_source") == "arbox_churned":
        time_of_day = form.get("time_of_day", "").strip() or "09:00"
        try:
            days_since = int(form.get("days_since", "14"))
        except ValueError:
            days_since = 14
        days_since = min(max(days_since, 1), 365)
        return {
            "schedule_type": "daily", "time_of_day": time_of_day,
            "audience_source": "arbox_churned", "days_since": days_since,
        }, None

    # "מתעניינים אבודים (Arbox)" - גם היא תמיד תזמון יומי (בודקים כל יום מי שהליד שלה סומן
    # אבוד בדיוק לפני X ימים), עם שעה + מספר ימים מאז. כמה הודעות בטווחים שונים (7/14/21/28
    # יום כמו ב-Upgrade360) - כמה אוטומציות נפרדות, אותו דפוס כמו arbox_churned
    if form.get("audience_source") == "arbox_lost_leads":
        time_of_day = form.get("time_of_day", "").strip() or "09:00"
        try:
            days_since = int(form.get("days_since", "7"))
        except ValueError:
            days_since = 7
        days_since = min(max(days_since, 1), 365)
        return {
            "schedule_type": "daily", "time_of_day": time_of_day,
            "audience_source": "arbox_lost_leads", "days_since": days_since,
        }, None

    # "מתעניינים חדשים שהומרו (Arbox)" - גם היא תמיד תזמון יומי (בודקים כל יום מי שהליד שלה
    # הומר ללקוחה בדיוק לפני X ימים), עם שעה + מספר ימים מאז. כמה הודעות בטווחים שונים
    # (3/14 יום כמו ב-Upgrade360) - כמה אוטומציות נפרדות, אותו דפוס כמו arbox_churned
    if form.get("audience_source") == "arbox_converted_leads":
        time_of_day = form.get("time_of_day", "").strip() or "09:00"
        try:
            days_since = int(form.get("days_since", "3"))
        except ValueError:
            days_since = 3
        days_since = min(max(days_since, 1), 365)
        return {
            "schedule_type": "daily", "time_of_day": time_of_day,
            "audience_source": "arbox_converted_leads", "days_since": days_since,
        }, None

    # "נגמרת הכרטיסייה (Arbox)" - גם תמיד תזמון יומי (בודקים כל יום כמה ניקובים נותרו), עם
    # שעה + סף ניקובים + תקופת "שקט" (לא לשלוח שוב למי שכבר נשלח לה בטווח הזה - ראו
    # has_recent_execution/_resolve_expiring_sessions_recipients - sessions_left לא "מתקדם"
    # אוטומטית מיום ליום כמו תאריך, אז בלי ההגנה הזו היינו שולחים כל יום
    if form.get("audience_source") == "arbox_expiring_sessions":
        time_of_day = form.get("time_of_day", "").strip() or "09:00"
        try:
            sessions_left = int(form.get("sessions_left", "1"))
        except ValueError:
            sessions_left = 1
        sessions_left = min(max(sessions_left, 0), 20)
        try:
            resend_cooldown_days = int(form.get("resend_cooldown_days", "14"))
        except ValueError:
            resend_cooldown_days = 14
        resend_cooldown_days = min(max(resend_cooldown_days, 1), 90)
        return {
            "schedule_type": "daily", "time_of_day": time_of_day,
            "audience_source": "arbox_expiring_sessions",
            "sessions_left": sessions_left, "resend_cooldown_days": resend_cooldown_days,
        }, None

    # "תזכורת שיעור ניסיון (Arbox)" - גם תמיד תזמון יומי (בודקים כל יום את שיעורי הניסיון
    # שמתוזמנים מחר/היום). locations אופציונלי - ריק = כל הסניפים, אחרת סינון מדויק (אותו
    # LOCATIONS כמו ב-arbox_active_members, ראו _resolve_trial_reminder_recipients)
    if form.get("audience_source") == "arbox_trial_reminder":
        time_of_day = form.get("time_of_day", "").strip() or "09:00"
        reminder_timing = form.get("reminder_timing", "day_before")
        if reminder_timing not in ("day_before", "same_day"):
            reminder_timing = "day_before"
        time_filter = form.get("time_filter", "before")
        if time_filter not in ("before", "after"):
            time_filter = "before"
        try:
            before_hour = int(form.get("before_hour", "12"))
        except ValueError:
            before_hour = 12
        before_hour = min(max(before_hour, 0), 23)
        return {
            "schedule_type": "daily", "time_of_day": time_of_day,
            "audience_source": "arbox_trial_reminder", "reminder_timing": reminder_timing,
            "time_filter": time_filter, "before_hour": before_hour,
            "locations": form.getlist("locations"),
        }, None

    # "מתעניינות שלא הגיעו לשיעור ניסיון (Arbox)" - גם היא תמיד תזמון יומי, אבל בניגוד
    # לכל האוטומציות הדינמיות למעלה (שבודקות "בדיוק יום X אחורה"), כאן יש חלון רחב
    # (window_days, ברירת מחדל 90) כי "לא הגיעה" יכול "להיתקע" בלי להיפתר מעצמו ביום
    # ספציפי - ולכן גם resend_cooldown_days כמו ב-arbox_expiring_sessions, כדי לא לשלוח
    # שוב בכל הרצה לאותה מתעניינת (ראו _resolve_trial_no_show_recipients ב-engine.py)
    if form.get("audience_source") == "arbox_trial_no_show":
        time_of_day = form.get("time_of_day", "").strip() or "09:00"
        try:
            window_days = int(form.get("window_days", "90"))
        except ValueError:
            window_days = 90
        window_days = min(max(window_days, 1), 365)
        try:
            resend_cooldown_days = int(form.get("resend_cooldown_days", "90"))
        except ValueError:
            resend_cooldown_days = 90
        resend_cooldown_days = min(max(resend_cooldown_days, 1), 365)
        return {
            "schedule_type": "daily", "time_of_day": time_of_day,
            "audience_source": "arbox_trial_no_show",
            "window_days": window_days, "resend_cooldown_days": resend_cooldown_days,
        }, None

    # "ברכת מילסטון על נוכחות (Arbox)" - גם תמיד תזמון יומי (בודקים כל יום מי הגיעה
    # **אתמול** לשיעור עגול - ראו _resolve_attendance_milestone_recipients). הספירה
    # "מעכשיו קדימה" בלבד (ראו arbox_entrance_count_db.py)
    if form.get("audience_source") == "arbox_attendance_milestone":
        time_of_day = form.get("time_of_day", "").strip() or "09:00"
        try:
            milestone_interval = int(form.get("milestone_interval", "10"))
        except ValueError:
            milestone_interval = 10
        milestone_interval = min(max(milestone_interval, 1), 1000)
        return {
            "schedule_type": "daily", "time_of_day": time_of_day,
            "audience_source": "arbox_attendance_milestone", "milestone_interval": milestone_interval,
        }, None

    trigger_config, error = _parse_generic_schedule(form)
    if error:
        return None, error

    # "לקוחות פעילים (Arbox)" - בניגוד לשלוש האוטומציות הדינמיות למעלה (שתמיד יומי), זו
    # משתמשת בתזמון הרגיל/גמיש (כבר נותח למעלה) - פשוט מוסיפים עליו audience_source וסינון
    # אופציונלי לפי סוג מנוי/סניף. ראו _resolve_active_members_recipients ב-engine.py
    if form.get("audience_source") == "arbox_active_members":
        trigger_config["audience_source"] = "arbox_active_members"
        trigger_config["membership_types"] = form.getlist("membership_types")
        trigger_config["locations"] = form.getlist("locations")

    return trigger_config, None


# תזמון "רגיל" (לא קהל דינמי שתמיד יומי) - משותף לרשימה ידנית ול"לקוחות פעילים (Arbox)"
# (ראו למעלה) - שתיהן נותנות למשתמש לבחור בעצמו חד-פעמי/יומי/שבועי/חודשי
def _parse_generic_schedule(form):
    schedule_type = form.get("schedule_type", "")
    if schedule_type not in SCHEDULE_TYPES:
        return None, "סוג תזמון לא תקין."

    if schedule_type == "once":
        run_at = form.get("run_at", "").strip()
        if not run_at:
            return None, "יש לבחור תאריך ושעה לשליחה."
        trigger_config = {"schedule_type": "once", "run_at": run_at}
        stage_at = form.get("stage_at", "").strip()
        if stage_at:
            if stage_at >= run_at:
                return None, "זמן ה'הורדה' (שלב הכנת הרשימה) חייב להיות לפני זמן השליחה."
            trigger_config["stage_at"] = stage_at
        return trigger_config, None

    time_of_day = form.get("time_of_day", "").strip() or "09:00"
    stage_time = form.get("stage_time", "").strip()
    if stage_time and stage_time >= time_of_day:
        return None, "זמן ה'הורדה' (שלב הכנת הרשימה) חייב להיות לפני זמן השליחה."

    if schedule_type == "daily":
        trigger_config = {"schedule_type": "daily", "time_of_day": time_of_day}

    elif schedule_type == "weekly":
        weekdays = [int(value) for value in form.getlist("weekdays") if value.isdigit()]
        if not weekdays:
            return None, "יש לבחור לפחות יום אחד בשבוע."
        trigger_config = {"schedule_type": "weekly", "time_of_day": time_of_day, "weekdays": weekdays}

    elif schedule_type == "monthly":
        try:
            day_of_month = int(form.get("day_of_month", "1"))
        except ValueError:
            day_of_month = 1
        day_of_month = min(max(day_of_month, 1), 31)
        trigger_config = {
            "schedule_type": "monthly", "time_of_day": time_of_day, "day_of_month": day_of_month,
        }
    else:
        return None, "סוג תזמון לא תקין."

    if stage_time:
        trigger_config["stage_time"] = stage_time
    return trigger_config, None


# עמוד יחיד מאוחד - לכל אוטומציה נטענים גם השלבים וגם (לאוטומציות מתוזמנות) הנמענים
# וההרצות האחרונות, כדי שהכל יוצג inline באותה טבלה בלי ניווט לעמוד נפרד
@bp.route("/")
@admin_required
def list_automations():
    repos = get_repos()
    automations = repos.automations.get_all()
    for automation in automations:
        automation["steps"] = repos.automations.get_steps(automation["id"])
        full = repos.automations.get_by_id(automation["id"])
        automation["trigger_config"] = full["trigger_config"]
        automation["last_run_at"] = full["last_run_at"]
        is_manual_audience = (
            automation["trigger_type"] == "scheduled"
            and automation["trigger_config"].get("audience_source") not in DYNAMIC_AUDIENCE_SOURCES
        )
        automation["recipients"] = (
            repos.automations.get_recipients(automation["id"]) if is_manual_audience else None
        )
        automation["executions"] = repos.automations.get_recent_executions(automation["id"], limit=10)
        automation["message_history"] = (
            repos.automations.get_step_history(automation["steps"][0]["id"]) if automation["steps"] else []
        )
    return render_template(
        "automations/list.html", grouped_automations=_group_by_category(automations),
        category_labels=_CATEGORY_LABELS, weekday_labels=_WEEKDAY_LABELS,
        membership_types=repos.arbox_member_cache.get_distinct_membership_types(), locations=LOCATIONS,
        approved_templates=_get_approved_templates(),
    )


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new_automation():
    repos = get_repos()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        trigger_config, error = _parse_schedule_form(request.form)
        action_config, msg_error = _build_message_action_config(request.form)

        if not name:
            error = error or "יש למלא שם."
        error = error or msg_error
        if error:
            flash(error, "error")
            return render_template(
                "automations/new.html", weekday_labels=_WEEKDAY_LABELS, form=request.form,
                selected_weekdays=_extract_weekdays(request.form),
                selected_membership_types=_extract_membership_types(request.form),
                selected_locations=_extract_locations(request.form),
                param_templates_list=_extract_param_templates(request.form),
                membership_types=repos.arbox_member_cache.get_distinct_membership_types(), locations=LOCATIONS,
                approved_templates=_get_approved_templates(),
            )

        automation_id = repos.automations.create_automation(name, "scheduled", trigger_config)
        repos.automations.add_step(
            automation_id, step_order=1, delay_minutes=0, action_type="send_whatsapp_message",
            action_config=action_config,
        )
        flash(f"האוטומציה '{name}' נוצרה בהצלחה. עכשיו אפשר להוסיף נמענים.", "success")
        return redirect(url_for("automations.list_automations", _anchor=f"automation-{automation_id}"))

    return render_template(
        "automations/new.html", weekday_labels=_WEEKDAY_LABELS, form={}, selected_weekdays=[],
        selected_membership_types=[], selected_locations=[], param_templates_list=[],
        membership_types=repos.arbox_member_cache.get_distinct_membership_types(), locations=LOCATIONS,
        approved_templates=_get_approved_templates(),
    )


def _back_to_list(automation_id):
    return redirect(url_for("automations.list_automations", _anchor=f"automation-{automation_id}"))


@bp.route("/<int:automation_id>/schedule/edit", methods=["POST"])
@admin_required
def edit_schedule(automation_id):
    repos = get_repos()
    automation = repos.automations.get_by_id(automation_id)
    if automation is None or automation["trigger_type"] != "scheduled":
        abort(404)

    trigger_config, error = _parse_schedule_form(request.form)
    if error:
        flash(error, "error")
        return _back_to_list(automation_id)
    repos.automations.update_schedule(automation_id, trigger_config)
    flash("התזמון עודכן בהצלחה.", "success")
    return _back_to_list(automation_id)


# הפעלה/כיבוי מהירים של יום בודד ישירות מתצוגת-הסיכום בכרטיס (עיגולי הימים, ראו .auto-days
# ב-list.html - שם היא תצוגה בלבד, role="img") - בלי לפתוח את כרטיס העריכה המלא ולשלוח טופס
# שלם. קוראת fetch, מחזירה JSON. שומרת על שאר trigger_config (time_of_day וכו') כמו שהוא -
# משנה רק את weekdays/schedule_type. "daily" מטופל כ"כל 7 הימים דלוקים" (תואם את ההצגה
# ב-list.html) - הסרת יום הופכת את זה ל-weekly עם שאר הימים. לא מאפשרת להשאיר רשימה ריקה
# (אין טעם באוטומציה שלא שולחת באף יום) - הקליק האחרון שהיה מכבה את כל הימים נדחה
@bp.route("/<int:automation_id>/toggle-weekday/<int:day>", methods=["POST"])
@admin_required
def toggle_weekday(automation_id, day):
    repos = get_repos()
    automation = repos.automations.get_by_id(automation_id)
    if automation is None or automation["trigger_type"] != "scheduled" or day not in range(7):
        abort(404)

    trigger_config = dict(automation["trigger_config"])
    schedule_type = trigger_config.get("schedule_type")
    if schedule_type not in ("weekly", "daily"):
        abort(404)

    if schedule_type == "daily":
        current_days = list(range(7))
    else:
        current_days = trigger_config.get("weekdays") or [trigger_config.get("weekday", 0)]
    current_days = set(current_days)

    if day in current_days:
        if len(current_days) == 1:
            return jsonify(ok=False, error="לא ניתן לכבות את היום האחרון שנשאר פעיל."), 400
        current_days.discard(day)
    else:
        current_days.add(day)

    trigger_config["schedule_type"] = "weekly"
    trigger_config["weekdays"] = sorted(current_days)
    trigger_config.pop("weekday", None)
    repos.automations.update_schedule(automation_id, trigger_config)
    return jsonify(ok=True, weekdays=sorted(current_days))


# עדכון מהיר של שעת השליחה ישירות מתיבת "שליחה HH:MM" בתצוגת-הסיכום בכרטיס - בלי לפתוח את
# כרטיס העריכה המלא. אותו עקרון כמו toggle_weekday: שומרת על שאר trigger_config כמו שהוא,
# משנה רק time_of_day. בודקת עקביות מול stage_time קיים (אם יש) - אותו כלל כמו בטופס המלא
# (_parse_schedule_form): זמן ה"הורדה" חייב להיות לפני זמן השליחה
@bp.route("/<int:automation_id>/set-time", methods=["POST"])
@admin_required
def set_time(automation_id):
    repos = get_repos()
    automation = repos.automations.get_by_id(automation_id)
    if automation is None or automation["trigger_type"] != "scheduled":
        abort(404)

    trigger_config = dict(automation["trigger_config"])
    if trigger_config.get("schedule_type") not in ("weekly", "daily", "monthly"):
        abort(404)

    time_of_day = request.form.get("time_of_day", "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", time_of_day or ""):
        return jsonify(ok=False, error="פורמט שעה לא תקין."), 400

    stage_time = trigger_config.get("stage_time")
    if stage_time and stage_time >= time_of_day:
        return jsonify(ok=False, error="זמן ה'הורדה' הקיים מאוחר/שווה לשעת השליחה החדשה - יש לעדכן דרך עריכת התזמון המלאה."), 400

    trigger_config["time_of_day"] = time_of_day
    repos.automations.update_schedule(automation_id, trigger_config)
    return jsonify(ok=True, time_of_day=time_of_day)


@bp.route("/<int:automation_id>/recipients/add", methods=["POST"])
@admin_required
def add_recipient(automation_id):
    repos = get_repos()
    automation = repos.automations.get_by_id(automation_id)
    if automation is None or automation["trigger_type"] != "scheduled":
        abort(404)

    phone = request.form.get("phone", "").strip()
    full_name = request.form.get("full_name", "").strip()
    if not phone:
        flash("יש להזין מספר טלפון.", "error")
        return _back_to_list(automation_id)

    repos.automations.add_recipient(automation_id, phone, full_name)
    flash("הנמען נוסף בהצלחה.", "success")
    return _back_to_list(automation_id)


# ייבוא נמענים בכמות מקובץ CSV/Excel (עמודות "שם מלא"/"טלפון", או full_name/phone) - אותו
# דפוס בדיוק כמו ייבוא לידים (leads.py), ראו atlas/services/automation_recipient_bulk_import.py
@bp.route("/<int:automation_id>/recipients/import", methods=["POST"])
@admin_required
def import_recipients(automation_id):
    repos = get_repos()
    automation = repos.automations.get_by_id(automation_id)
    if automation is None or automation["trigger_type"] != "scheduled":
        abort(404)

    uploaded_file = request.files.get("file")
    if not uploaded_file or not uploaded_file.filename:
        flash("יש לבחור קובץ.", "error")
        return _back_to_list(automation_id)

    if not uploaded_file.filename.lower().endswith((".csv", ".xlsx", ".xls")):
        flash("סוג קובץ לא נתמך. יש להעלות CSV או Excel (.xlsx).", "error")
        return _back_to_list(automation_id)

    try:
        result = import_recipients_from_file(uploaded_file, repos, automation_id)
    except Exception as exc:
        flash(f"שגיאה בקריאת הקובץ: {exc}", "error")
        return _back_to_list(automation_id)

    if "error" in result:
        flash(result["error"], "error")
        return _back_to_list(automation_id)

    flash(f"יובאו {result['created']} נמענים מתוך {result['total_rows']} שורות בקובץ.", "success")
    for message in result["skipped"][:10]:
        flash(message, "error")

    return _back_to_list(automation_id)


@bp.route("/<int:automation_id>/recipients/<int:recipient_id>/delete", methods=["POST"])
@admin_required
def remove_recipient(automation_id, recipient_id):
    repos = get_repos()
    automation = repos.automations.get_by_id(automation_id)
    if automation is None or automation["trigger_type"] != "scheduled":
        abort(404)
    repos.automations.remove_recipient(recipient_id)
    flash("הנמען הוסר.", "success")
    return _back_to_list(automation_id)


# בלאקליסט גלובלי - עמוד נפרד (לא פר-אוטומציה), ראו atlas/data/automation_db.py
@bp.route("/blacklist")
@admin_required
def blacklist():
    entries = get_repos().automations.get_global_blacklist()
    return render_template("automations/blacklist.html", entries=entries)


@bp.route("/blacklist/add", methods=["POST"])
@admin_required
def add_to_blacklist():
    phone = request.form.get("phone", "").strip()
    full_name = request.form.get("full_name", "").strip()
    if not phone:
        flash("יש להזין מספר טלפון.", "error")
        return redirect(url_for("automations.blacklist"))
    get_repos().automations.add_to_global_blacklist(phone, full_name)
    flash("המספר נוסף לבלאקליסט.", "success")
    return redirect(url_for("automations.blacklist"))


@bp.route("/blacklist/<int:blacklist_id>/delete", methods=["POST"])
@admin_required
def remove_from_blacklist(blacklist_id):
    get_repos().automations.remove_from_global_blacklist(blacklist_id)
    flash("המספר הוסר מהבלאקליסט.", "success")
    return redirect(url_for("automations.blacklist"))


@bp.route("/<int:automation_id>/steps/<int:step_id>/edit", methods=["POST"])
@admin_required
def edit_step(automation_id, step_id):
    repos = get_repos()
    automation = repos.automations.get_by_id(automation_id)
    if automation is None:
        abort(404)
    step = repos.automations.get_step(step_id)
    if step is None or step["automation_id"] != automation_id:
        abort(404)

    try:
        delay_minutes = int(request.form.get("delay_minutes", "0"))
    except ValueError:
        delay_minutes = 0
    delay_minutes = max(0, delay_minutes)

    action_config, error = _build_message_action_config(request.form)
    if error:
        flash(error, "error")
        return _back_to_list(automation_id)

    if action_config["mode"] == "template":
        repos.automations.update_step_template(
            step_id, action_config["template_name"], action_config["template_language"],
            action_config["param_templates"], delay_minutes,
        )
        flash("השלב עודכן בהצלחה (תבנית מאושרת).", "success")
    else:
        repos.automations.update_step(step_id, action_config["text_template"], delay_minutes)
        flash("השלב עודכן בהצלחה.", "success")
    return _back_to_list(automation_id)


@bp.route("/<int:automation_id>/toggle", methods=["POST"])
@admin_required
def toggle_automation(automation_id):
    repos = get_repos()
    automation = repos.automations.get_by_id(automation_id)
    if automation is None:
        abort(404)
    repos.automations.toggle_enabled(automation_id)
    new_state = "כבויה" if automation["enabled"] else "פעילה"
    flash(f"האוטומציה '{automation['name']}' עכשיו {new_state}.", "success")
    return _back_to_list(automation_id)
