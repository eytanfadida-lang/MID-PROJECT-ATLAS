from flask import Blueprint, render_template, redirect, url_for, flash, abort

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
