from flask import Flask, redirect, render_template, url_for, session

import roles
import db_context
from auth import load_secret_key, generate_csrf_token, validate_csrf, current_user
from view_utils import role_badge_class, format_lead_datetime, whatsapp_link, to_records

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

app.jinja_env.globals["role_badge_class"] = role_badge_class
app.jinja_env.filters["format_lead_datetime"] = format_lead_datetime
app.jinja_env.filters["whatsapp_link"] = whatsapp_link


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

    repos = db_context.get_repos()
    appointments = repos.appointments.get_all()
    today_appointments = repos.appointments.get_today()
    leads = repos.leads.get_all()
    customers = repos.customers.get_all()

    recent_appointments = to_records(appointments.head(5)) if not appointments.empty else []
    recent_leads = to_records(leads.head(5)) if not leads.empty else []
    recent_customers = to_records(customers.head(5)) if not customers.empty else []

    return render_template(
        "dashboard.html",
        appointments_count=len(appointments),
        today_count=len(today_appointments),
        leads_count=len(leads),
        customers_count=len(customers),
        recent_appointments=recent_appointments,
        recent_leads=recent_leads,
        recent_customers=recent_customers,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
