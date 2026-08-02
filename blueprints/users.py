import sqlite3

from flask import Blueprint, render_template, request, redirect, url_for, flash

from db_context import get_repos
from auth import admin_required, current_user
from view_utils import to_records
import roles

bp = Blueprint("users", __name__, url_prefix="/users")


@bp.route("/")
@admin_required
def list_users():
    df = get_repos().users.get_all()
    return render_template("users/list.html", users=to_records(df))


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
            flash(f"User '{username}' created successfully (role: {role}).", "success")
            return redirect(url_for("users.list_users"))
        except sqlite3.IntegrityError:
            flash(f"Username '{username}' already exists.", "error")

    return render_template("users/new.html", roles=[roles.ADMIN, roles.USER])


@bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_user(user_id):
    user = get_repos().users.get_by_id(user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("users.list_users"))

    current_session_user = current_user()
    if current_session_user and current_session_user.get("id") == user_id:
        flash("You cannot modify your own account from here.", "error")
        return redirect(url_for("users.list_users"))

    if request.method == "POST":
        role = request.form.get("role", user["role"]).strip()
        password = request.form.get("password", "").strip()
        permissions = [
            permission
            for permission in request.form.getlist("permissions")
            if permission
        ]

        if role:
            get_repos().users.update_role(user_id, role)
        if password:
            get_repos().users.update_password(user_id, password)
        get_repos().users.update_permissions(user_id, permissions)

        flash(f"User '{user['username']}' updated successfully.", "success")
        return redirect(url_for("users.list_users"))

    return render_template("users/edit.html", user=user, roles=[roles.ADMIN, roles.USER])


@bp.route("/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    user = get_repos().users.get_by_id(user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("users.list_users"))

    current_session_user = current_user()
    if current_session_user and current_session_user.get("id") == user_id:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("users.list_users"))

    admins = get_repos().users.get_all()
    admin_count = sum(1 for _, row in admins.iterrows() if row["role"] == roles.ADMIN)
    if user["role"] == roles.ADMIN and admin_count <= 1:
        flash("At least one admin account must remain.", "error")
        return redirect(url_for("users.list_users"))

    get_repos().users.delete(user_id)
    flash(f"User '{user['username']}' deleted successfully.", "success")
    return redirect(url_for("users.list_users"))
