from flask import Flask, redirect, url_for, session

import roles
import db_context
from auth import load_secret_key, generate_csrf_token, validate_csrf, current_user
from view_utils import status_badge_class, role_badge_class

from blueprints.auth import bp as auth_bp
from blueprints.appointments import bp as appointments_bp
from blueprints.leads import bp as leads_bp
from blueprints.customers import bp as customers_bp
from blueprints.users import bp as users_bp

# יוצר/ממגר את כל הטבלאות פעם אחת בזמן import (רץ גם תחת flask run וגם תחת python app.py)
db_context.bootstrap_databases()

app = Flask(__name__)
app.secret_key = load_secret_key()

db_context.init_app(app)

app.register_blueprint(auth_bp)
app.register_blueprint(appointments_bp)
app.register_blueprint(leads_bp)
app.register_blueprint(customers_bp)
app.register_blueprint(users_bp)

app.before_request(validate_csrf)

app.jinja_env.globals["status_badge_class"] = status_badge_class
app.jinja_env.globals["role_badge_class"] = role_badge_class


@app.context_processor
def inject_template_globals():
    return {
        "csrf_token": generate_csrf_token(),
        "current_user": current_user(),
        "ROLE_ADMIN": roles.ADMIN,
        "ROLE_USER": roles.USER,
    }


@app.route("/")
def index():
    if current_user() is None:
        return redirect(url_for("auth.login"))
    return redirect(url_for("appointments.list_appointments"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
