import threading
import time

from flask import Flask, redirect, render_template, url_for

from atlas.core import roles
from atlas.data import context as db_context
from atlas.integrations.arbox.sync import sync_arbox_clients
from atlas.core.auth import load_secret_key, generate_csrf_token, validate_csrf, current_user
from atlas.core.view_utils import role_badge_class, format_lead_datetime, whatsapp_link, to_records

from atlas.web.blueprints.auth import bp as auth_bp
from atlas.web.blueprints.appointments import bp as appointments_bp
from atlas.web.blueprints.leads import bp as leads_bp
from atlas.web.blueprints.customers import bp as customers_bp
from atlas.web.blueprints.users import bp as users_bp
from atlas.web.webhooks import bp as webhooks_bp

# אין אישור על תמיכת Arbox ב-webhook, לכן זו קירוב בפולינג תדיר (לא טריגר אמיתי בזמן אמת)
ARBOX_SYNC_INTERVAL_SECONDS = 300
ARBOX_AUTO_SYNC_ENABLED = True


# בודקת מ-Arbox את כל מי שהפך ללקוח, ומעדכנת סטטוס ללידים קיימים אצלנו בלבד (לא מייבאת/יוצרת לידים חדשים)
def _run_arbox_sync_loop(app):
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


# מיועד לשימוש מקומי בלבד (python app.py) - בסביבת אירוח WSGI (PythonAnywhere) אין thread
# רקע לתהליך, ולכן שם משתמשים ב-/tasks/arbox-sync* דרך cron חיצוני (GitHub Actions) במקום
def start_arbox_sync_scheduler(app):
    threading.Thread(target=_run_arbox_sync_loop, args=(app,), daemon=True).start()


def create_app():
    # יוצר/ממגר את כל הטבלאות פעם אחת בזמן יצירת האפליקציה (רץ גם תחת flask run וגם תחת python app.py)
    db_context.bootstrap_databases()

    app = Flask(
        __name__,
        template_folder="web/templates",
        static_folder="web/static",
    )
    app.secret_key = load_secret_key()

    db_context.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(leads_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(webhooks_bp)

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

    return app
