import sqlite3

from flask import Blueprint, render_template, request, redirect, url_for, flash

from db_context import get_repos
from auth import admin_required
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

        try:
            get_repos().users.create(username, password, role)
            flash(f"User '{username}' created successfully (role: {role}).", "success")
            return redirect(url_for("users.list_users"))
        except sqlite3.IntegrityError:
            flash(f"Username '{username}' already exists.", "error")

    return render_template("users/new.html", roles=[roles.ADMIN, roles.USER])
