from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from atlas.data.context import get_repos

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        role = get_repos().users.authenticate(username, password)
        if role is None:
            flash("שם משתמש או סיסמה שגויים.", "error")
            return render_template("login.html", username=username)

        user = get_repos().users.get_by_username(username)
        session["user"] = {
            "id": user["id"],
            "username": username,
            "role": role,
            "permissions": user.get("permissions", []),
        }
        return redirect(url_for("appointments.list_appointments"))

    return render_template("login.html", username="")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
