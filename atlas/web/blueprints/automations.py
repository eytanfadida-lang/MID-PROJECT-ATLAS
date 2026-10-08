from flask import Blueprint, render_template, redirect, url_for, flash, abort, request

from atlas.data.context import get_repos
from atlas.core.auth import admin_required

# עמוד ניהול בסיסי למנוע האוטומציות (ראו atlas/automations/engine.py) - רשימה, הפעלה/כיבוי,
# ויומן הרצות אחרונות לכל אוטומציה. בכוונה בלי בונה-תהליכים ויזואלי - נבנה/נערך רק דרך קוד
# (seed ב-atlas/data/automation_db.py), כי יש כרגע אוטומציה אחת-שתיים לנהל, לא יותר
bp = Blueprint("automations", __name__, url_prefix="/automations")


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
    return render_template(
        "automations/detail.html", automation=automation, steps=steps, executions=executions
    )


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
