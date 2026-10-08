from flask import Blueprint, render_template, redirect, url_for, flash, abort, request

from atlas.data.context import get_repos
from atlas.core.auth import admin_required
from atlas.automations.engine import SCHEDULE_TYPES

# עמוד ניהול למנוע האוטומציות (ראו atlas/automations/engine.py) - טבלה אחת מאוחדת (לא
# רשימה+עמוד פרטים נפרד): כל שורה כוללת עריכת תוכן/תזמון/נמענים inline (מורחבת/מוסתרת
# ב-<details>, בלי JS מעבר לפעלה/כיבוי שדות התזמון בטופס היצירה/עריכה - ראו list.html).
# אוטומציות מבוססות-אירוע (כמו "הרשמה לשיעור ניסיון") עדיין מוגדרות בקוד בלבד (seed ב-
# atlas/data/automation_db.py). אוטומציות מתוזמנות (trigger_type="scheduled") נוצרות ונערכות
# לגמרי דרך הממשק. בלאקליסט הוא גלובלי (משותף לכל האוטומציות) - עמוד נפרד, לא פר-שורה
bp = Blueprint("automations", __name__, url_prefix="/automations")

_WEEKDAY_LABELS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


# מחלצת את ימי השבוע הנבחרים הן מ-request.form (MultiDict, כמה ערכים תחת אותו שם שדה -
# "weekdays") והן מ-trigger_config שכבר נשמר ב-DB (dict רגיל, כבר שמור כרשימת int) - כדי
# שתיבות הסימון בטופס יוצגו נכון גם בשגיאת ולידציה (מ-request.form) וגם בעריכה (מה-DB)
def _extract_weekdays(form):
    if hasattr(form, "getlist"):
        return [int(value) for value in form.getlist("weekdays") if value.isdigit()]
    return form.get("weekdays") or []


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
            and automation["trigger_config"].get("audience_source") != "arbox_birthday"
        )
        automation["recipients"] = (
            repos.automations.get_recipients(automation["id"]) if is_manual_audience else None
        )
        automation["executions"] = repos.automations.get_recent_executions(automation["id"], limit=10)
    return render_template(
        "automations/list.html", automations=automations, weekday_labels=_WEEKDAY_LABELS,
    )


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new_automation():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        text_template = request.form.get("text_template", "").strip()
        trigger_config, error = _parse_schedule_form(request.form)

        if not name or not text_template:
            error = error or "יש למלא שם והודעה."
        if error:
            flash(error, "error")
            return render_template(
                "automations/new.html", weekday_labels=_WEEKDAY_LABELS, form=request.form,
                selected_weekdays=_extract_weekdays(request.form),
            )

        repos = get_repos()
        automation_id = repos.automations.create_automation(name, "scheduled", trigger_config)
        repos.automations.add_step(
            automation_id, step_order=1, delay_minutes=0, action_type="send_whatsapp_message",
            action_config={"mode": "text", "text_template": text_template},
        )
        flash(f"האוטומציה '{name}' נוצרה בהצלחה. עכשיו אפשר להוסיף נמענים.", "success")
        return redirect(url_for("automations.list_automations", _anchor=f"automation-{automation_id}"))

    return render_template(
        "automations/new.html", weekday_labels=_WEEKDAY_LABELS, form={}, selected_weekdays=[],
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

    text_template = request.form.get("text_template", "").strip()
    try:
        delay_minutes = int(request.form.get("delay_minutes", "0"))
    except ValueError:
        delay_minutes = 0
    delay_minutes = max(0, delay_minutes)

    if not text_template:
        flash("לא ניתן לשמור הודעה ריקה.", "error")
        return _back_to_list(automation_id)

    repos.automations.update_step(step_id, text_template, delay_minutes)
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
