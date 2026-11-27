import calendar
import datetime
import sqlite3

from flask import Blueprint, render_template, request, redirect, url_for, flash

from atlas.data.context import get_repos
from atlas.core.auth import admin_required, login_required, current_user
from atlas.core.view_utils import to_records
from atlas.core import roles

bp = Blueprint("users", __name__, url_prefix="/users")


# שינוי סיסמה עצמי - בכוונה *לא* דרך edit_user (זה חסום במפורש לעריכת החשבון של עצמך, ראו
# למטה) כדי שלא יהיה אפשר לשנות לעצמך הרשאות/תפקיד דרך "דלת אחורית". דורשת את הסיסמה
# הנוכחית (לא רק session פעיל) כהגנה נוספת - login_required ולא admin_required, כי כל
# משתמש מחובר (לא רק מנהל) צריך להיות מסוגל לשנות את הסיסמה של עצמו
@bp.route("/me/password", methods=["GET", "POST"])
@login_required
def change_my_password():
    session_user = current_user()

    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if get_repos().users.authenticate(session_user["username"], current_password) is None:
            flash("הסיסמה הנוכחית שגויה.", "error")
        elif not new_password:
            flash("יש להזין סיסמה חדשה.", "error")
        elif new_password != confirm_password:
            flash("הסיסמה החדשה ואימות הסיסמה לא תואמים.", "error")
        else:
            get_repos().users.update_password(session_user["id"], new_password)
            flash("הסיסמה עודכנה בהצלחה.", "success")
            return redirect(url_for("index"))

    return render_template("users/change_my_password.html")


@bp.route("/")
@admin_required
def list_users():
    df = get_repos().users.get_all()
    return render_template("users/list.html", users=to_records(df))


# כמה בקשות נשלחו ל-Arbox החודש מתוך המכסה (20,000), לפי מקור ולפי יום - ראו arbox_usage_repository.py
@bp.route("/arbox-usage")
@admin_required
def arbox_usage():
    from atlas.data.repositories.arbox_usage_repository import (
        ALERT_THRESHOLD, BRAKE_THRESHOLD, MONTHLY_LIMIT, SOURCE_LABELS,
    )
    from atlas.services.time_utils import utc_now_to_israel

    now_israel = utc_now_to_israel(datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
    month = now_israel.strftime("%Y-%m")
    usage = get_repos().arbox_usage
    total = usage.month_total(month)
    days_in_month = calendar.monthrange(now_israel.year, now_israel.month)[1]
    # תחזית לסוף החודש לפי קצב הימים שעברו (לא כולל היום, שעוד לא נגמר) - רק אם עבר לפחות יום
    daily = usage.month_daily(month)
    past_days = [d for d in daily if d["day"] < now_israel.date().isoformat()]
    forecast = None
    if past_days:
        past_total = sum(d["total"] for d in past_days)
        remaining_days = days_in_month - now_israel.day + 1  # כולל היום
        forecast = int(past_total + past_total / len(past_days) * remaining_days)
    return render_template(
        "users/arbox_usage.html",
        month=now_israel.strftime("%m/%Y"), total=total, limit=MONTHLY_LIMIT,
        alert=ALERT_THRESHOLD, brake=BRAKE_THRESHOLD, percent=min(100, round(total * 100 / MONTHLY_LIMIT)),
        by_source=usage.month_by_source(month), daily=daily, labels=SOURCE_LABELS, forecast=forecast,
    )


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new_user():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        role = request.form.get("role", roles.USER)
        permissions = [permission for permission in request.form.getlist("permissions") if permission]

        try:
            get_repos().users.create(username, password, role, permissions)
            flash(f"המשתמש '{username}' נוצר בהצלחה (תפקיד: {role}).", "success")
            return redirect(url_for("users.list_users"))
        except sqlite3.IntegrityError:
            flash(f"שם המשתמש '{username}' כבר קיים.", "error")

    return render_template("users/new.html", roles=[roles.ADMIN, roles.USER])


@bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_user(user_id):
    user = get_repos().users.get_by_id(user_id)
    if user is None:
        flash("המשתמש לא נמצא.", "error")
        return redirect(url_for("users.list_users"))

    current_session_user = current_user()
    if current_session_user and current_session_user.get("id") == user_id:
        flash("לא ניתן לערוך את החשבון שלך מכאן.", "error")
        return redirect(url_for("users.list_users"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        role = request.form.get("role", user["role"]).strip()
        password = request.form.get("password", "").strip()
        permissions = [
            permission
            for permission in request.form.getlist("permissions")
            if permission
        ]

        if username and username != user["username"]:
            try:
                get_repos().users.update_username(user_id, username)
            except sqlite3.IntegrityError:
                flash(f"שם המשתמש '{username}' כבר קיים.", "error")
                return render_template("users/edit.html", user=user, roles=[roles.ADMIN, roles.USER])

        if role:
            get_repos().users.update_role(user_id, role)
        if password:
            get_repos().users.update_password(user_id, password)
        get_repos().users.update_permissions(user_id, permissions)

        flash(f"המשתמש '{username or user['username']}' עודכן בהצלחה.", "success")
        return redirect(url_for("users.list_users"))

    return render_template("users/edit.html", user=user, roles=[roles.ADMIN, roles.USER])


@bp.route("/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    user = get_repos().users.get_by_id(user_id)
    if user is None:
        flash("המשתמש לא נמצא.", "error")
        return redirect(url_for("users.list_users"))

    current_session_user = current_user()
    if current_session_user and current_session_user.get("id") == user_id:
        flash("לא ניתן למחוק את החשבון שלך.", "error")
        return redirect(url_for("users.list_users"))

    admins = get_repos().users.get_all()
    admin_count = sum(1 for _, row in admins.iterrows() if row["role"] == roles.ADMIN)
    if user["role"] == roles.ADMIN and admin_count <= 1:
        flash("חייב להישאר לפחות חשבון מנהל אחד.", "error")
        return redirect(url_for("users.list_users"))

    get_repos().users.delete(user_id)
    flash(f"המשתמש '{user['username']}' נמחק בהצלחה.", "success")
    return redirect(url_for("users.list_users"))
