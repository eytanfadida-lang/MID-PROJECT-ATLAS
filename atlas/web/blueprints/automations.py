from flask import Blueprint, render_template, redirect, url_for, flash, abort, request

from atlas.data.context import get_repos
from atlas.core.auth import admin_required
from atlas.automations.engine import SCHEDULE_TYPES

# עמוד ניהול למנוע האוטומציות (ראו atlas/automations/engine.py) - רשימה, הפעלה/כיבוי,
# עריכת תוכן/תזמון, ויומן הרצות אחרונות. אוטומציות מבוססות-אירוע (כמו "הרשמה לשיעור ניסיון")
# עדיין מוגדרות בקוד בלבד (seed ב-atlas/data/automation_db.py) - אין להן נקודת חיבור גנרית
# בממשק כי הן תלויות בקוד שמזהה את האירוע. אוטומציות מתוזמנות (trigger_type="scheduled",
# למשל סקר/תזכורת לרשימה נבחרת) כן נוצרות ונערכות לגמרי דרך הממשק - ראו new_automation/edit_schedule
bp = Blueprint("automations", __name__, url_prefix="/automations")

_WEEKDAY_LABELS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


# בונה trigger_config מתוך טופס לפי schedule_type שנבחר - בשימוש גם ביצירה וגם בעריכה.
# מחזירה (trigger_config, error) - error לא None אם משהו חסר/לא תקין
def _parse_schedule_form(form):
    schedule_type = form.get("schedule_type", "")
    if schedule_type not in SCHEDULE_TYPES:
        return None, "סוג תזמון לא תקין."

    if schedule_type == "once":
        run_at = form.get("run_at", "").strip()
        if not run_at:
            return None, "יש לבחור תאריך ושעה."
        return {"schedule_type": "once", "run_at": run_at}, None

    time_of_day = form.get("time_of_day", "").strip() or "09:00"

    if schedule_type == "daily":
        return {"schedule_type": "daily", "time_of_day": time_of_day}, None

    if schedule_type == "weekly":
        try:
            weekday = int(form.get("weekday", "0"))
        except ValueError:
            weekday = 0
        return {"schedule_type": "weekly", "time_of_day": time_of_day, "weekday": weekday}, None

    if schedule_type == "monthly":
        try:
            day_of_month = int(form.get("day_of_month", "1"))
        except ValueError:
            day_of_month = 1
        day_of_month = min(max(day_of_month, 1), 31)
        return {
            "schedule_type": "monthly", "time_of_day": time_of_day, "day_of_month": day_of_month,
        }, None

    return None, "סוג תזמון לא תקין."


@bp.route("/")
@admin_required
def list_automations():
    automations = get_repos().automations.get_all()
    return render_template("automations/list.html", automations=automations)


@bp.route("/<int:automation_id>")
@admin_required
def view_automation(automation_id):
    repos = get_repos()
    automation = repos.automations.get_by_id(automation_id)
    if automation is None:
        abort(404)
    steps = repos.automations.get_steps(automation_id)
    executions = repos.automations.get_recent_executions(automation_id)
    recipients = (
        repos.automations.get_recipients(automation_id)
        if automation["trigger_type"] == "scheduled" else None
    )
    return render_template(
        "automations/detail.html", automation=automation, steps=steps, executions=executions,
        recipients=recipients, weekday_labels=_WEEKDAY_LABELS,
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
            )

        repos = get_repos()
        automation_id = repos.automations.create_automation(name, "scheduled", trigger_config)
        repos.automations.add_step(
            automation_id, step_order=1, delay_minutes=0, action_type="send_whatsapp_message",
            action_config={"mode": "text", "text_template": text_template},
        )
        flash(f"האוטומציה '{name}' נוצרה בהצלחה. עכשיו אפשר להוסיף נמענים.", "success")
        return redirect(url_for("automations.view_automation", automation_id=automation_id))

    return render_template("automations/new.html", weekday_labels=_WEEKDAY_LABELS, form={})


@bp.route("/<int:automation_id>/schedule/edit", methods=["GET", "POST"])
@admin_required
def edit_schedule(automation_id):
    repos = get_repos()
    automation = repos.automations.get_by_id(automation_id)
    if automation is None or automation["trigger_type"] != "scheduled":
        abort(404)

    if request.method == "POST":
        trigger_config, error = _parse_schedule_form(request.form)
        if error:
            flash(error, "error")
            return render_template(
                "automations/edit_schedule.html", automation=automation,
                weekday_labels=_WEEKDAY_LABELS, form=request.form,
            )
        repos.automations.update_schedule(automation_id, trigger_config)
        flash("התזמון עודכן בהצלחה.", "success")
        return redirect(url_for("automations.view_automation", automation_id=automation_id))

    return render_template(
        "automations/edit_schedule.html", automation=automation,
        weekday_labels=_WEEKDAY_LABELS, form=automation["trigger_config"],
    )


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
        return redirect(url_for("automations.view_automation", automation_id=automation_id))

    repos.automations.add_recipient(automation_id, phone, full_name)
    flash("הנמען נוסף בהצלחה.", "success")
    return redirect(url_for("automations.view_automation", automation_id=automation_id))


@bp.route("/<int:automation_id>/recipients/<int:recipient_id>/delete", methods=["POST"])
@admin_required
def remove_recipient(automation_id, recipient_id):
    repos = get_repos()
    automation = repos.automations.get_by_id(automation_id)
    if automation is None or automation["trigger_type"] != "scheduled":
        abort(404)
    repos.automations.remove_recipient(recipient_id)
    flash("הנמען הוסר.", "success")
    return redirect(url_for("automations.view_automation", automation_id=automation_id))


@bp.route("/<int:automation_id>/steps/<int:step_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_step(automation_id, step_id):
    repos = get_repos()
    automation = repos.automations.get_by_id(automation_id)
    if automation is None:
        abort(404)
    step = repos.automations.get_step(step_id)
    if step is None or step["automation_id"] != automation_id:
        abort(404)

    if request.method == "POST":
        text_template = request.form.get("text_template", "").strip()
        try:
            delay_minutes = int(request.form.get("delay_minutes", "0"))
        except ValueError:
            delay_minutes = 0
        delay_minutes = max(0, delay_minutes)

        if not text_template:
            flash("לא ניתן לשמור הודעה ריקה.", "error")
            return render_template(
                "automations/edit_step.html", automation=automation, step=step,
                text_template=text_template, delay_minutes=delay_minutes,
            )

        repos.automations.update_step(step_id, text_template, delay_minutes)
        flash("השלב עודכן בהצלחה.", "success")
        return redirect(url_for("automations.view_automation", automation_id=automation_id))

    return render_template(
        "automations/edit_step.html", automation=automation, step=step,
        text_template=step["action_config"].get("text_template", ""),
        delay_minutes=step["delay_minutes"],
    )


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
    return redirect(url_for("automations.list_automations"))
