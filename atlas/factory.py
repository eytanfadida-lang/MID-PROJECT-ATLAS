import gzip
import datetime
import os
import threading
import time

import pandas as pd
from flask import Flask, redirect, render_template, request, send_from_directory, session, url_for

from atlas.core import roles
from atlas.data import context as db_context
from atlas.integrations.arbox.sync import sync_arbox_clients
from atlas.data.repositories.customer_bot_message_repository import incoming_listeners
from atlas.services import gateway_auth, web_push
from atlas.core.auth import load_secret_key, generate_csrf_token, validate_csrf, current_user
from atlas.core.view_utils import (
    role_badge_class,
    format_lead_datetime,
    whatsapp_link,
    to_records,
    collapse_blank_lines,
    day_label,
)

from atlas.web.blueprints.auth import bp as auth_bp
from atlas.web.blueprints.appointments import bp as appointments_bp
from atlas.web.blueprints.leads import bp as leads_bp
from atlas.web.blueprints.customers import bp as customers_bp
from atlas.web.blueprints.users import bp as users_bp
from atlas.web.blueprints.push import bp as push_bp
from atlas.web.blueprints.integrations import bp as integrations_bp
from atlas.web.blueprints.search import bp as search_bp
from atlas.web.blueprints.gateway import bp as gateway_bp
from atlas.web.blueprints.bot_conversations import bp as bot_conversations_bp
from atlas.web.blueprints.automations import bp as automations_bp
from atlas.web.blueprints.whatsapp_templates import bp as whatsapp_templates_bp
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


# גרסת קובץ העיצוב (זמן שינוי) - מצורפת ל-URL של style.css כדי שהדפדפן/הטלפון לא ישתמשו בגרסה ישנה
# מהמטמון אחרי כל עדכון (חשוב במיוחד באפליקציה מותקנת, שמחזיקה מטמון אגרסיבי)
def _static_asset_version(app):
    newest = 0
    for name in ("style.css", "push.js"):
        try:
            newest = max(newest, int(os.path.getmtime(os.path.join(app.static_folder, name))))
        except OSError:
            pass
    return newest


# מספרים שמוצגים כתגיות בסרגל הניווט: שיחות שמחכות לתשובה (למנהלת בלבד - אלה שיחות לקוחות) ולידים בסטטוס
# הראשון ("חדש"). כשל בשאילתה לא צריך להפיל עמוד - פשוט אין תגית
def _nav_counts():
    user = current_user()
    if user is None:
        return {"nav_unread_chats": 0, "nav_new_leads": 0}
    counts = {"nav_unread_chats": 0, "nav_new_leads": 0}
    try:
        repos = db_context.get_repos()
        if user.get("role") == roles.ADMIN:
            counts["nav_unread_chats"] = repos.customer_bot_messages.count_unread_conversations()
        statuses = repos.lead_statuses.get_names()
        if statuses:
            # משתמשת רגילה רואה בעמוד הלידים רק לידים ששויכו אליה - המספר בתגית חייב להתאים לרשימה
            assignee = None if user.get("role") == roles.ADMIN else user.get("username", "")
            counts["nav_new_leads"] = repos.leads.count_by_status(statuses[0], assigned_user=assignee)
    except Exception:  # noqa: BLE001
        pass
    return counts


# מספר הערוצים המוצגים בנפרד בגרף העוגה; השאר מתקבצים ל"אחר" (פחות מ-4 צבעים שאפשר להבדיל ביניהם)
_DASHBOARD_TOP_CHANNELS = 3


def _dashboard_charts(repos, is_admin, username, days):
    """נתוני הגרפים בלוח הבקרה: לידים ותורים ליום ב-`days` הימים האחרונים, וערוצי הלידים באותה תקופה.
    אותו כלל נראות כמו בעמוד הלידים: משתמשת רגילה רואה רק לידים ששויכו אליה."""
    today = datetime.date.today()
    start = today - datetime.timedelta(days=days - 1)
    day_list = [(start + datetime.timedelta(days=i)).isoformat() for i in range(days)]

    leads = repos.leads.get_all()
    if not is_admin and not leads.empty:
        leads = leads[leads["assigned_user"].fillna("") == username]
    lead_days = pd.to_datetime(leads["created_datetime_stamp"], errors="coerce").dt.strftime("%Y-%m-%d") if not leads.empty else pd.Series(dtype=str)
    in_range = leads[lead_days.isin(day_list)] if not leads.empty else leads
    lead_per_day = lead_days[lead_days.isin(day_list)].value_counts().to_dict() if not leads.empty else {}

    appointments = repos.appointments.get_all()
    appt_days = appointments["appointment_date"].astype(str).str[:10] if not appointments.empty else pd.Series(dtype=str)
    appt_per_day = appt_days[appt_days.isin(day_list)].value_counts().to_dict()
    next_week = [(today + datetime.timedelta(days=i)).isoformat() for i in range(7)]

    channel_counts = in_range["channel"].fillna("").replace("", "ללא ערוץ").value_counts() if not in_range.empty else pd.Series(dtype=int)
    channels = [{"name": name, "count": int(count)} for name, count in channel_counts.head(_DASHBOARD_TOP_CHANNELS).items()]
    other = int(channel_counts.iloc[_DASHBOARD_TOP_CHANNELS:].sum()) if len(channel_counts) > _DASHBOARD_TOP_CHANNELS else 0
    if other:
        channels.append({"name": "אחר", "count": other, "other": True})
    total = sum(c["count"] for c in channels)
    for c in channels:
        c["pct"] = round(100 * c["count"] / total, 1) if total else 0

    return {
        "days": day_list,
        "leads": [int(lead_per_day.get(d, 0)) for d in day_list],
        "appointments": [int(appt_per_day.get(d, 0)) for d in day_list],
        "channels": channels,
        "leads_total": int(len(in_range)),
        "week_appointments": int(appt_days.isin(next_week).sum()) if not appointments.empty else 0,
    }


def _dashboard_data(repos, is_admin, username="", days=30):
    """הנתונים ללוח היום: תורי היום לפי שעה, שיחות שמחכות לתשובה (למנהלת), ולידים חדשים."""
    today = repos.appointments.get_today()
    today_records = to_records(today.sort_values("appointment_time")) if not today.empty else []

    waiting = []
    waiting_count = 0
    if is_admin:
        unread = [c for c in repos.customer_bot_messages.get_conversation_summaries() if c["unread"]]
        waiting_count = len(unread)
        for conversation in unread[:5]:
            member = repos.arbox_member_cache.get_by_phone(conversation["phone"])
            name = f"{member['first_name']} {member['last_name']}".strip() if member else ""
            waiting.append({**conversation, "full_name": name or None})

    statuses = repos.lead_statuses.get_names()
    new_leads = repos.leads.get_by_status(statuses[0]) if statuses else None
    if new_leads is not None and not is_admin:
        # אותו כלל כמו בעמוד הלידים: משתמשת רגילה רואה רק לידים ששויכו אליה
        new_leads = new_leads[new_leads["assigned_user"].fillna("") == username]
    new_leads_count = 0 if new_leads is None else len(new_leads)
    new_lead_records = to_records(new_leads.head(5)) if new_leads is not None and not new_leads.empty else []

    chart = _dashboard_charts(repos, is_admin, username, days)

    return {
        "today_appointments": today_records,
        "chart": chart,
        "days": days,
        "week_appointments_count": chart["week_appointments"],
        "waiting_chats": waiting,
        "waiting_count": waiting_count,
        "new_leads": new_lead_records,
        "new_leads_count": new_leads_count,
        "new_status_name": statuses[0] if statuses else "",
    }


# דחיסת gzip לדפי HTML ו-JSON (דף השיחות לבדו ~500KB, ב-gzip כ-10%) - מתעלמת מקבצים סטטיים (נשרתים
# ישירות ע"י השרת) ומתשובות שכבר דחוסות/זרימה. מקטינה משמעותית את זמן הטעינה בטלפון
def _gzip_response(response):
    if (
        response.direct_passthrough
        or response.status_code < 200 or response.status_code >= 300
        or "Content-Encoding" in response.headers
        or "gzip" not in request.headers.get("Accept-Encoding", "")
        or response.mimetype not in ("text/html", "application/json")
    ):
        return
    data = response.get_data()
    if len(data) < 1024:
        return
    response.set_data(gzip.compress(data, compresslevel=5))
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(response.get_data()))
    response.headers.add("Vary", "Accept-Encoding")


def create_app():
    # יוצר/ממגר את כל הטבלאות פעם אחת בזמן יצירת האפליקציה (רץ גם תחת flask run וגם תחת python app.py)
    db_context.bootstrap_databases()
    # טוקן משותף לתהליך חיבור הוואטסאפ (gateway/) - נוצר כבר באתחול, כדי שהתהליך תמיד ימצא אותו
    gateway_auth.get_or_create_token()

    app = Flask(
        __name__,
        template_folder="web/templates",
        static_folder="web/static",
    )
    app.secret_key = load_secret_key()

    # התחברות קבועה: בלי זה ה-session הוא קוקי "זמני" שנמחק כשסוגרים את הדפדפן/האפליקציה, ובאפליקציה
    # מותקנת בטלפון המשתמשת הייתה מתנתקת בכל פתיחה מחדש. עם session קבוע הקוקי נשמר 30 יום, ו-Flask
    # מחדש אותו בכל בקשה (SESSION_REFRESH_EACH_REQUEST) - כלומר "30 ימים מהשימוש האחרון", לא מההתחברות.
    # SameSite=Lax: הקוקי לא נשלח בבקשות חוצות-אתרים (הגנה נוספת מפני CSRF) אבל כן בניווט רגיל לאתר
    app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(days=30)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    @app.before_request
    def keep_logged_in_sessions_persistent():
        # גם מי שכבר מחוברת עם קוקי זמני (לפני העדכון) הופכת לקבועה בבקשה הבאה - בלי להתחבר מחדש
        if session.get("user") is not None and not session.permanent:
            session.permanent = True

    db_context.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(leads_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(bot_conversations_bp)
    app.register_blueprint(push_bp)
    app.register_blueprint(integrations_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(gateway_bp)
    app.register_blueprint(automations_bp)
    app.register_blueprint(whatsapp_templates_bp)
    app.register_blueprint(webhooks_bp)

    app.before_request(validate_csrf)

    # כותרות אבטחה ומטמון לכל תשובה (נבדק בביקורת איכות: לא הוגדרו קודם):
    #  - nosniff / SAMEORIGIN / Referrer-Policy / Permissions-Policy: מניעת הטמעת האתר בדף זר (clickjacking על פעולות מנהל),
    #    ניחוש סוג תוכן, ודליפת כתובות. HSTS רק כשהבקשה הגיעה ב-HTTPS (PythonAnywhere מסיים TLS לפני האפליקציה)
    #  - דפי האפליקציה הם אישיים: "private, no-cache" (לא נשמרים במטמון משותף, ותמיד מאומתים מחדש)
    #  - קבצים סטטיים: עם ?v=<גרסה> (ראו asset_version) - שנה שלמה ו-immutable; גופנים/אייקונים - שבוע;
    #    sw.js והמניפסט תמיד מאומתים מחדש (חייבים להתעדכן מיד)
    @app.after_request
    def add_security_and_cache_headers(response):
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.is_secure or request.headers.get("X-Forwarded-Proto") == "https":
            headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        path = request.path
        if path.startswith("/static/"):
            if path.endswith("/sw.js"):
                headers["Cache-Control"] = "no-cache"
            elif request.args.get("v"):
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif path.rsplit(".", 1)[-1] in ("woff2", "png", "ico", "svg"):
                headers["Cache-Control"] = "public, max-age=604800"
        elif path in ("/sw.js", "/manifest.webmanifest"):
            headers["Cache-Control"] = "no-cache"
        else:
            headers.setdefault("Cache-Control", "private, no-cache")
        _gzip_response(response)
        return response

    app.jinja_env.globals["role_badge_class"] = role_badge_class
    app.jinja_env.filters["format_lead_datetime"] = format_lead_datetime
    app.jinja_env.filters["whatsapp_link"] = whatsapp_link
    app.jinja_env.filters["collapse_blank_lines"] = collapse_blank_lines
    app.jinja_env.filters["day_label"] = day_label

    # התראות דחיפה על הודעה נכנסת חדשה מלקוחה (ראו atlas/services/web_push.py). רושמים פעם אחת
    # לכל תהליך - לא מכפילים אם create_app נקראת שוב (למשל בבדיקות)
    if not any(getattr(fn, "_is_web_push_listener", False) for fn in incoming_listeners):
        def _push_on_incoming(phone, body, attachment_url=None):
            web_push.notify_incoming_async(phone, body, attachment_url)

        _push_on_incoming._is_web_push_listener = True
        incoming_listeners.append(_push_on_incoming)

    @app.context_processor
    def inject_template_globals():
        return {
            "csrf_token": generate_csrf_token(),
            "current_user": current_user(),
            "ROLE_ADMIN": roles.ADMIN,
            "ROLE_USER": roles.USER,
            "asset_version": _static_asset_version(app),
            **_nav_counts(),
        }

    # --- PWA: מאפשר "התקנה" למסך הבית בטלפון. ה-manifest וה-service worker חייבים להיות מוגשים
    # מהשורש (לא מ-/static) כדי שה-scope יכסה את כל האתר; הם ציבוריים (בלי מידע רגיש) ולכן ללא התחברות ---
    @app.route("/manifest.webmanifest")
    def pwa_manifest():
        response = send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.route("/sw.js")
    def pwa_service_worker():
        response = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
        # ה-SW עצמו לא נשמר במטמון - כדי שעדכון שלו ייקלט מיד אחרי פריסה
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    @app.route("/offline")
    def pwa_offline():
        return send_from_directory(app.static_folder, "offline.html", mimetype="text/html")

    @app.route("/")
    def index():
        if current_user() is None:
            return redirect(url_for("auth.login"))

        repos = db_context.get_repos()
        return render_template(
            "dashboard.html",
            **_dashboard_data(
                repos, current_user().get("role") == roles.ADMIN, current_user().get("username", ""),
                days=days if (days := request.args.get("days", type=int)) in (7, 30, 90) else 30,
            ),
        )

    return app
