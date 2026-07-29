import secrets
from functools import wraps
from pathlib import Path

from flask import abort, request, session, redirect, url_for

import roles

SECRET_KEY_FILE = Path(".flask_secret")


# טוענת מפתח session קבוע מקובץ מקומי (יוצרת אותו אם לא קיים), כדי שהפעלה מחדש
# של השרת לא תנתק את כל המשתמשים המחוברים ולא תפיל בקשות בגלל אי-התאמת CSRF
def load_secret_key():
    if SECRET_KEY_FILE.exists():
        return SECRET_KEY_FILE.read_text().strip()

    key = secrets.token_hex(32)
    SECRET_KEY_FILE.write_text(key)
    return key


# מחזירה את טוקן ה-CSRF של ה-session הנוכחי, ויוצרת אחד חדש אם עדיין אין
def generate_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


# מריצה בכל בקשה (before_request): מוודאת שכל POST נושא טוקן CSRF תואם ל-session
def validate_csrf():
    if request.method != "POST":
        return
    token = session.get("csrf_token")
    submitted = request.form.get("csrf_token", "")
    if not token or not secrets.compare_digest(token, submitted):
        abort(400)


def current_user():
    return session.get("user")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("auth.login"))
        if user["role"] != roles.ADMIN:
            abort(403)
        return view(*args, **kwargs)

    return wrapped
