import os
import secrets
import threading
import time
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for, session

import roles
import db_context
from arbox_sync import sync_arbox_clients
from auth import load_secret_key, generate_csrf_token, validate_csrf, current_user
from view_utils import role_badge_class, format_lead_datetime, whatsapp_link, to_records

from blueprints.auth import bp as auth_bp
from blueprints.appointments import bp as appointments_bp
from blueprints.leads import bp as leads_bp
from blueprints.customers import bp as customers_bp
from blueprints.users import bp as users_bp

# אין אישור על תמיכת Arbox ב-webhook, לכן זו קירוב בפולינג תדיר (לא טריגר אמיתי בזמן אמת)
ARBOX_SYNC_INTERVAL_SECONDS = 300
ARBOX_AUTO_SYNC_ENABLED = True

# טוקן להפעלת סנכרון Arbox דרך HTTP (למשל משירות cron חיצוני, בסביבות אירוח בלי background thread/Scheduled Tasks)
ARBOX_SYNC_TOKEN_FILE = Path(".arbox_sync_token")

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


# בודקת מ-Arbox את כל מי שהפך ללקוח, ומעדכנת סטטוס ללידים קיימים אצלנו בלבד (לא מייבאת/יוצרת לידים חדשים)
def _run_arbox_sync_loop():
    while True:
        try:
            with app.app_context():
                result = sync_arbox_clients(db_context.get_repos())
            if result.get("skipped"):
                print(f"[Arbox sync] skipped: {result.get('reason')}")
            else:
                print(
                    f"[Arbox sync] updated {result['updated_to_converted']} leads to 'הפך ללקוח', "
                    f"{result['already_converted']} already converted, "
                    f"{result['not_found']} not found in leads, "
                    f"{result['no_phone']} without phone "
                    f"(fetched {result['total_fetched']} clients from Arbox)"
                )
        except Exception as exc:
            print(f"[Arbox sync] failed: {exc}")
        time.sleep(ARBOX_SYNC_INTERVAL_SECONDS)


def start_arbox_sync_scheduler():
    threading.Thread(target=_run_arbox_sync_loop, daemon=True).start()


def load_arbox_sync_token():
    if not ARBOX_SYNC_TOKEN_FILE.exists():
        return None
    token = ARBOX_SYNC_TOKEN_FILE.read_text().strip()
    return token or None


# מפעילה סנכרון Arbox דרך HTTP, מאובטחת בטוקן סודי (לא session/login) - מיועדת לשירות
# cron חיצוני שקורא לכתובת הזו על בסיס קבוע, בסביבות אירוח בלי background thread משלנו
@app.route("/tasks/arbox-sync")
def trigger_arbox_sync():
    expected_token = load_arbox_sync_token()
    provided_token = request.args.get("token", "")
    if not expected_token or not secrets.compare_digest(provided_token, expected_token):
        abort(403)

    result = sync_arbox_clients(db_context.get_repos())
    return jsonify(result)


if __name__ == "__main__":
    DEBUG_MODE = True
    # ב-debug=True ה-reloader מריץ גם תהליך "צג" נוסף; מפעילים את הלולאה רק בתהליך העבודה בפועל
    if ARBOX_AUTO_SYNC_ENABLED and (not DEBUG_MODE or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        start_arbox_sync_scheduler()
    app.run(host="127.0.0.1", port=5000, debug=DEBUG_MODE)
