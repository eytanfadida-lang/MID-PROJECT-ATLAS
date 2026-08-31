import json
import secrets

from flask import Blueprint, abort, jsonify, request

from atlas.paths import secret
from atlas.data import context as db_context
from atlas.integrations.arbox.sync import sync_arbox_clients, apply_arbox_users_to_leads
from atlas.integrations.google import lead_forms as google_leads
from atlas.integrations import landing_page as landing_page_leads
from atlas.integrations.meta import lead_ads as meta_leads
from atlas.integrations.whatsapp import bot as whatsapp_bot
from atlas.integrations.whatsapp import admin_assistant as crm_assistant
from atlas.settings import CHANNELS

# כל נקודות הקצה החיצוניות (webhooks + cron endpoints) שאין להן session/login - כל אחת
# מאומתת בטוקן/חתימה משלה. הועברו לכאן מ-atlas/factory.py, בלי שינוי בכתובות (url_prefix
# משחזר בדיוק את אותם נתיבי /tasks/... כמו קודם)
bp = Blueprint("webhooks", __name__, url_prefix="/tasks")

# טוקן להפעלת סנכרון Arbox דרך HTTP (למשל משירות cron חיצוני, בסביבות אירוח בלי background thread/Scheduled Tasks)
ARBOX_SYNC_TOKEN_FILE = secret(".arbox_sync_token")


def load_arbox_sync_token():
    if not ARBOX_SYNC_TOKEN_FILE.exists():
        return None
    token = ARBOX_SYNC_TOKEN_FILE.read_text().strip()
    return token or None


# מפעילה סנכרון Arbox דרך HTTP, מאובטחת בטוקן סודי (לא session/login) - מיועדת לשירות
# cron חיצוני שקורא לכתובת הזו על בסיס קבוע, בסביבות אירוח בלי background thread משלנו
@bp.route("/arbox-sync")
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
@bp.route("/arbox-sync-data", methods=["POST"])
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
@bp.route("/google-leads-webhook", methods=["POST"])
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
@bp.route("/landing-page-lead", methods=["POST"])
def landing_page_lead():
    expected_token = landing_page_leads.load_token()
    provided_token = request.args.get("token", "")
    if not expected_token or not secrets.compare_digest(provided_token, expected_token):
        abort(403)

    data = request.get_json(silent=True) or request.form.to_dict() or {}
    print(f"[Landing page lead] raw payload: {data}", flush=True)
    # שומרים גם לקובץ debug מקומי - print() לא תמיד נראה מיד בלוג של WSGI (buffering),
    # קל יותר פשוט לקרוא את הקובץ הזה ישירות אחרי בדיקה
    secret(".last_landing_page_payload.json").write_text(
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
@bp.route("/meta-leads-webhook", methods=["GET", "POST"])
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
    secret(".last_meta_payload.json").write_text(
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
# בפועל למרות שההגדרות תקינות) - מוגנת בטוקן, מיועדת להפעלה תקופתית (למשל כל 5 דקות
# דרך GitHub Actions, בדיוק כמו trigger_arbox_sync)
@bp.route("/meta-leads-poll")
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
@bp.route("/whatsapp-webhook", methods=["GET", "POST"])
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
    secret(".last_whatsapp_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    from_number, text = whatsapp_bot.extract_incoming_message(payload)
    if not from_number or not text:
        return jsonify({"status": "ignored"})

    allowed_numbers = whatsapp_bot.load_allowed_numbers()
    if from_number not in allowed_numbers:
        print(f"[WhatsApp webhook] ignoring message from unauthorized number: {from_number}", flush=True)
        return jsonify({"status": "ignored", "reason": "unauthorized"})

    repos = db_context.get_repos()
    statuses = repos.lead_statuses.get_names()
    try:
        reply_text = crm_assistant.answer_question(repos, statuses, from_number, text)
    except Exception as exc:
        print(f"[WhatsApp webhook] assistant failed: {exc}", flush=True)
        reply_text = "אירעה שגיאה בעיבוד הבקשה, נסה שוב מאוחר יותר."

    whatsapp_bot.send_text_message(from_number, reply_text)
    return jsonify({"status": "ok"})
