import json
import os
import secrets
import threading
import time
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for, session

import roles
import db_context
from arbox_sync import sync_arbox_clients, apply_arbox_users_to_leads
import google_leads
import landing_page_leads
import meta_leads
import whatsapp_bot
from lead_input import CHANNELS
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


# כמו trigger_arbox_sync, אבל מקבלת את רשימת משתמשי Arbox כבר-מוכנה ב-body (POST),
# בלי לגשת בעצמה ל-Arbox. מיועדת לסביבות אירוח שחוסמות גישה יוצאת לדומיין של Arbox -
# GitHub Actions (או כל מקום עם גישה פתוחה) מושך מ-Arbox ודוחף לכאן
@app.route("/tasks/arbox-sync-data", methods=["POST"])
def receive_arbox_sync_data():
    expected_token = load_arbox_sync_token()
    provided_token = request.args.get("token", "")
    if not expected_token or not secrets.compare_digest(provided_token, expected_token):
        abort(403)

    payload = request.get_json(silent=True) or {}
    arbox_users = payload.get("users")
    if not isinstance(arbox_users, list):
        abort(400)

    result = apply_arbox_users_to_leads(db_context.get_repos(), arbox_users)
    return jsonify(result)


# מקבלת ליד חדש מ-Google Ads (Lead Form extension, webhook delivery). האימות הוא לפי
# google_key בתוך ה-JSON עצמו (ככה Google מגדירה את זה, לא header). מדפיסה את ה-payload
# הגולמי ללוג כדי שנוכל לוודא שהשדות באמת נשלפים נכון מול ליד-בדיקה אמיתי מגוגל
@app.route("/tasks/google-leads-webhook", methods=["POST"])
def google_leads_webhook():
    payload = request.get_json(silent=True) or {}
    print(f"[Google leads webhook] raw payload: {payload}")

    expected_key = google_leads.load_webhook_key()
    provided_key = payload.get("google_key", "")
    if not expected_key or not secrets.compare_digest(provided_key, expected_key):
        abort(403)

    if payload.get("is_test"):
        return jsonify({"status": "test_received"})

    full_name, phone = google_leads.extract_lead_fields(payload)
    if not phone:
        print("[Google leads webhook] no phone found in payload, skipping lead creation")
        return jsonify({"status": "ignored", "reason": "no_phone"})

    repos = db_context.get_repos()
    statuses = repos.lead_statuses.get_names()
    lead = {
        "full_name": full_name or "ליד מגוגל",
        "phone": phone,
        "status": statuses[0] if statuses else "",
        "channel": "Google Ads" if "Google Ads" in CHANNELS else CHANNELS[0],
        "assigned_user": "",
        "notes": f"campaign: {payload.get('campaign_name', '')}".strip(),
    }
    lead_id = repos.leads.create(lead)
    return jsonify({"status": "created", "lead_id": lead_id})


# מקבלת ליד מטופס Elementor Pro (Actions After Submit > Webhook) בדף הנחיתה של האתר שלך.
# אימות בטוקן ב-query string (מוגדר בתוך כתובת ה-webhook עצמה בהגדרות הטופס).
# מדפיסה payload גולמי ללוג כדי שנוכל להתאים את שמות השדות לטופס האמיתי
@app.route("/tasks/landing-page-lead", methods=["POST"])
def landing_page_lead():
    expected_token = landing_page_leads.load_token()
    provided_token = request.args.get("token", "")
    if not expected_token or not secrets.compare_digest(provided_token, expected_token):
        abort(403)

    data = request.get_json(silent=True) or request.form.to_dict() or {}
    print(f"[Landing page lead] raw payload: {data}", flush=True)
    # שומרים גם לקובץ debug מקומי - print() לא תמיד נראה מיד בלוג של WSGI (buffering),
    # קל יותר פשוט לקרוא את הקובץ הזה ישירות אחרי בדיקה
    Path(".last_landing_page_payload.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    full_name, phone, email, notes = landing_page_leads.extract_lead_fields(data)
    if not phone:
        print("[Landing page lead] no phone found in payload, skipping lead creation", flush=True)
        return jsonify({"status": "ignored", "reason": "no_phone"})

    repos = db_context.get_repos()
    statuses = repos.lead_statuses.get_names()
    combined_notes = f"{notes}\nאימייל: {email}".strip() if email else notes
    lead = {
        "full_name": full_name or "ליד מדף נחיתה",
        "phone": phone,
        "status": statuses[0] if statuses else "",
        "channel": "דף נחיתה" if "דף נחיתה" in CHANNELS else CHANNELS[0],
        "assigned_user": "",
        "notes": combined_notes,
    }
    lead_id = repos.leads.create(lead)
    return jsonify({"status": "created", "lead_id": lead_id})


# מקבלת לידים מ-Meta (Facebook/Instagram Lead Ads). GET הוא ה-handshake לאימות ה-webhook
# מול Meta (חד-פעמי, כשמגדירים את הכתובת בפאנל שלהם). POST הוא ההתראה עצמה בכל ליד חדש -
# מכילה רק leadgen_id, אז צריך קריאה נוספת ל-Graph API כדי לקבל את הנתונים בפועל
@app.route("/tasks/meta-leads-webhook", methods=["GET", "POST"])
def meta_leads_webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token", "")
        challenge = request.args.get("hub.challenge", "")
        expected_token = meta_leads.load_verify_token()
        if mode == "subscribe" and expected_token and secrets.compare_digest(token, expected_token):
            return challenge, 200
        abort(403)

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not meta_leads.verify_signature(request.get_data(), signature):
        abort(403)

    payload = request.get_json(silent=True) or {}
    print(f"[Meta leads webhook] raw payload: {payload}", flush=True)
    Path(".last_meta_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    repos = db_context.get_repos()
    statuses = repos.lead_statuses.get_names()
    created_count = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "leadgen":
                continue
            leadgen_id = (change.get("value") or {}).get("leadgen_id")
            if not leadgen_id:
                continue
            try:
                lead_data = meta_leads.fetch_lead_data(leadgen_id)
            except Exception as exc:
                print(f"[Meta leads webhook] failed to fetch lead {leadgen_id}: {exc}", flush=True)
                continue
            if not lead_data:
                continue

            full_name, phone, email, extra_answers = meta_leads.extract_lead_fields(lead_data)
            if not phone:
                continue

            lead = {
                "full_name": full_name or "ליד ממטא",
                "phone": phone,
                "status": statuses[0] if statuses else "",
                "channel": "פייסבוק" if "פייסבוק" in CHANNELS else CHANNELS[0],
                "assigned_user": "",
                "notes": meta_leads.build_notes(email, extra_answers),
            }
            repos.leads.create(lead)
            created_count += 1

    return jsonify({"status": "ok", "created": created_count})


# מפעילה משיכה יזומה של לידים חדשים ממטא (חלופה ל-webhook בזמן אמת, שלא סיפק לנו נתונים
# בפועל למרות שההגדרות תקינות) - מוגנת בטוקן, מיועדת להפעלה תקופתית (למשל כל 15 דקות
# דרך GitHub Actions, בדיוק כמו trigger_arbox_sync)
@app.route("/tasks/meta-leads-poll")
def meta_leads_poll():
    expected_token = meta_leads.load_poll_token()
    provided_token = request.args.get("token", "")
    if not expected_token or not secrets.compare_digest(provided_token, expected_token):
        abort(403)

    result = meta_leads.poll_new_leads(db_context.get_repos(), CHANNELS)
    return jsonify(result)


# מקבלת הודעות וואטסאפ נכנסות מהבוט הפנימי (CRM WhaApp Bot). כמו ה-webhook של מטא לידים:
# GET הוא ה-handshake, POST היא ההודעה עצמה. עונה רק למספרים ברשימת המורשים (בעל העסק) -
# זה כלי פנימי לשאילת נתונים, לא בוט ללקוחות
@app.route("/tasks/whatsapp-webhook", methods=["GET", "POST"])
def whatsapp_webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token", "")
        challenge = request.args.get("hub.challenge", "")
        expected_token = whatsapp_bot.load_verify_token()
        if mode == "subscribe" and expected_token and secrets.compare_digest(token, expected_token):
            return challenge, 200
        abort(403)

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not whatsapp_bot.verify_signature(request.get_data(), signature):
        abort(403)

    payload = request.get_json(silent=True) or {}
    print(f"[WhatsApp webhook] raw payload: {payload}", flush=True)
    Path(".last_whatsapp_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    from_number, text = whatsapp_bot.extract_incoming_message(payload)
    if not from_number or not text:
        return jsonify({"status": "ignored"})

    allowed_numbers = whatsapp_bot.load_allowed_numbers()
    if from_number not in allowed_numbers:
        print(f"[WhatsApp webhook] ignoring message from unauthorized number: {from_number}", flush=True)
        return jsonify({"status": "ignored", "reason": "unauthorized"})

    # תשובת הד זמנית, רק כדי לוודא שהצינור עובד מקצה לקצה - תוחלף בקריאה בפועל ל-Claude
    whatsapp_bot.send_text_message(from_number, f"קיבלתי: {text}")
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    DEBUG_MODE = True
    # ב-debug=True ה-reloader מריץ גם תהליך "צג" נוסף; מפעילים את הלולאה רק בתהליך העבודה בפועל
    if ARBOX_AUTO_SYNC_ENABLED and (not DEBUG_MODE or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        start_arbox_sync_scheduler()
    app.run(host="127.0.0.1", port=5000, debug=DEBUG_MODE)
