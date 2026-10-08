import datetime
import json
import mimetypes
import re
import secrets
from pathlib import Path

from flask import Blueprint, abort, jsonify, request
from werkzeug.utils import secure_filename

from atlas.paths import secret
from atlas.data import context as db_context
from atlas.integrations.arbox.sync import sync_arbox_clients, apply_arbox_users_to_leads
from atlas.integrations.google import lead_forms as google_leads
from atlas.integrations import landing_page as landing_page_leads
from atlas.integrations.meta import lead_ads as meta_leads
from atlas.integrations.whatsapp import bot as whatsapp_bot
from atlas.integrations.whatsapp import admin_assistant as crm_assistant
from atlas.integrations.whatsapp import customer_assistant
from atlas.integrations.whatsapp.customer_assistant import OWNER_WHATSAPP_NUMBER, OWNER_ALERT_TEMPLATE_NAME
from atlas.automations import engine as automation_engine
from atlas.services.phone_utils import normalize_phone
from atlas.settings import CHANNELS
from atlas.web.blueprints.bot_conversations import UPLOADS_DIR

# כל נקודות הקצה החיצוניות (webhooks + cron endpoints) שאין להן session/login - כל אחת
# מאומתת בטוקן/חתימה משלה. הועברו לכאן מ-atlas/factory.py, בלי שינוי בכתובות (url_prefix
# משחזר בדיוק את אותם נתיבי /tasks/... כמו קודם)
bp = Blueprint("webhooks", __name__, url_prefix="/tasks")

# שם תבנית וואטסאפ מאושרת (נוצרת ב-WhatsApp Manager, ראו הנחיות) שמודיעה לבעלים על
# קורות חיים חדשים - חייבת תבנית ולא טקסט חופשי כי זו הודעה יזומה מהעסק, לא בהכרח
# בתוך 24 שעות מהודעה אחרונה של הבעלים לבוט הפנימי
CV_NOTIFICATION_TEMPLATE_NAME = "cv_received_notification"


# שומרת קובץ שהתקבל מהלקוח (למשל קורות חיים) תחת static/uploads, באותו מבנה תיקיות
# כמו קבצים שהבעלים מעלה ידנית מהממשק (bot_conversations.py) - כדי שגם אלה יוצגו
# בבועת הצ'אט בעמוד שיחות בוט הלקוחות, לא רק קבצים שנשלחו החוצה
def _save_incoming_document(phone, filename, file_bytes):
    phone_dir = UPLOADS_DIR / phone
    phone_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    # שמות קבצים בעברית (למשל "קורות חיים.pdf") מתאפסים לגמרי ע"י secure_filename
    # (כולל הנקודה והסיומת) - שומרים את הסיומת בנפרד כדי שהקובץ יישאר ניתן לפתיחה
    safe_name = secure_filename(filename or "")
    if not safe_name or "." not in safe_name:
        extension = re.sub(r"[^A-Za-z0-9.]", "", Path(filename or "").suffix)
        safe_name = f"attachment{extension}" if extension else (safe_name or "attachment")
    stored_name = f"{timestamp}_{safe_name}"
    (phone_dir / stored_name).write_bytes(file_bytes)
    return f"/static/uploads/{phone}/{stored_name}"


# תמונה/וידאו שמגיעים מוואטסאפ לא נושאים filename (בניגוד למסמך) - רק mime_type.
# מיפוי ידני לסוגים הנפוצים כי mimetypes.guess_extension לא תמיד עקבי בין סביבות
_MEDIA_EXTENSION_OVERRIDES = {"image/jpeg": ".jpg", "video/mp4": ".mp4", "video/3gpp": ".3gp"}


def _guess_media_extension(mime_type):
    base_mime = (mime_type or "").split(";")[0].strip()
    if base_mime in _MEDIA_EXTENSION_OVERRIDES:
        return _MEDIA_EXTENSION_OVERRIDES[base_mime]
    return mimetypes.guess_extension(base_mime) or ""

# טוקן להפעלת סנכרון Arbox דרך HTTP (למשל משירות cron חיצוני, בסביבות אירוח בלי background thread/Scheduled Tasks)
ARBOX_SYNC_TOKEN_FILE = secret(".arbox_sync_token")


def load_arbox_sync_token():
    if not ARBOX_SYNC_TOKEN_FILE.exists():
        return None
    token = ARBOX_SYNC_TOKEN_FILE.read_text().strip()
    return token or None


# טוקן להפעלת ה-poller של מנוע האוטומציות (atlas/automations/engine.py) - אותו דפוס בדיוק
# כמו arbox-sync: אין thread רקע בפרודקשן, אז cron חיצוני (GitHub Actions) קורא לזה תדיר
AUTOMATIONS_RUN_TOKEN_FILE = secret(".automations_run_token")


def load_automations_run_token():
    if not AUTOMATIONS_RUN_TOKEN_FILE.exists():
        return None
    token = AUTOMATIONS_RUN_TOKEN_FILE.read_text().strip()
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


# מפעילה את ה-poller של מנוע האוטומציות (ביצוע פעולות מושהות שהגיע זמנן) - אותה הגנת
# טוקן בדיוק כמו arbox-sync
@bp.route("/automations-run")
def trigger_automations_run():
    expected_token = load_automations_run_token()
    provided_token = request.args.get("token", "")
    if not expected_token or not secrets.compare_digest(provided_token, expected_token):
        abort(403)

    result = automation_engine.process_due_actions(db_context.get_repos())
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

    arbox_memberships = payload.get("memberships")
    if not isinstance(arbox_memberships, list):
        arbox_memberships = None

    repos = db_context.get_repos()
    repos.arbox_member_cache.replace_all(arbox_users, arbox_memberships)

    schedule = payload.get("schedule")
    from_date = payload.get("schedule_from_date")
    to_date = payload.get("schedule_to_date")
    if isinstance(schedule, list) and from_date and to_date:
        repos.arbox_class_cache.replace_range(from_date, to_date, schedule)

    result = apply_arbox_users_to_leads(repos, arbox_users)
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
    bot_config = whatsapp_bot.ADMIN_BOT

    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token", "")
        challenge = request.args.get("hub.challenge", "")
        expected_token = whatsapp_bot.load_verify_token(bot_config)
        if mode == "subscribe" and expected_token and secrets.compare_digest(token, expected_token):
            return challenge, 200
        abort(403)

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not whatsapp_bot.verify_signature(bot_config, request.get_data(), signature):
        abort(403)

    payload = request.get_json(silent=True) or {}
    print(f"[WhatsApp webhook] raw payload: {payload}", flush=True)
    secret(".last_whatsapp_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    from_number, message_id, message_type, text = whatsapp_bot.extract_incoming_event(payload)
    if not from_number:
        return jsonify({"status": "ignored"})

    repos = db_context.get_repos()

    # מטא שולחת שוב את אותה הודעה אם התגובה שלנו לא הגיעה מהר מספיק - בלי הבדיקה הזו
    # היינו עלולים לענות פעמיים (ובעתיד, לקבוע תור פעמיים) לאותה הודעה בדיוק
    if message_id and repos.whatsapp_state.has_processed(message_id):
        print(f"[WhatsApp webhook] duplicate delivery ignored: {message_id}", flush=True)
        return jsonify({"status": "ignored", "reason": "duplicate"})

    allowed_numbers = whatsapp_bot.load_allowed_numbers()
    if from_number not in allowed_numbers:
        print(f"[WhatsApp webhook] ignoring message from unauthorized number: {from_number}", flush=True)
        return jsonify({"status": "ignored", "reason": "unauthorized"})

    if message_id:
        repos.whatsapp_state.mark_processed(message_id)

    if message_type != "text":
        print(f"[WhatsApp webhook] non-text message ignored ({message_type})", flush=True)
        whatsapp_bot.send_text_message(
            bot_config, from_number, "אני יכול לקרוא כרגע רק הודעות טקסט - אפשר לכתוב לי? 🙏"
        )
        return jsonify({"status": "ignored", "reason": "non_text"})

    statuses = repos.lead_statuses.get_names()
    try:
        reply_text = crm_assistant.answer_question(repos, statuses, from_number, text)
    except Exception as exc:
        print(f"[WhatsApp webhook] assistant failed: {exc}", flush=True)
        reply_text = "אירעה שגיאה בעיבוד הבקשה, נסה שוב מאוחר יותר."

    whatsapp_bot.send_text_message(bot_config, from_number, reply_text)
    return jsonify({"status": "ok"})


# מקבלת הודעות וואטסאפ נכנסות מבוט הלקוחות (מספר נפרד, אפליקציית מטא נפרדת) - כמו
# whatsapp_webhook, אבל בלי רשימת מורשים (זה בוט פונה-לקוחות, לא כלי פנימי)
@bp.route("/whatsapp-customer-webhook", methods=["GET", "POST"])
def whatsapp_customer_webhook():
    bot_config = whatsapp_bot.CUSTOMER_BOT

    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token", "")
        challenge = request.args.get("hub.challenge", "")
        expected_token = whatsapp_bot.load_verify_token(bot_config)
        if mode == "subscribe" and expected_token and secrets.compare_digest(token, expected_token):
            return challenge, 200
        abort(403)

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not whatsapp_bot.verify_signature(bot_config, request.get_data(), signature):
        abort(403)

    payload = request.get_json(silent=True) or {}
    print(f"[WhatsApp customer webhook] raw payload: {payload}", flush=True)
    secret(".last_whatsapp_customer_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    from_number, message_id, message_type, text = whatsapp_bot.extract_incoming_event(payload)
    if not from_number:
        return jsonify({"status": "ignored"})

    # לא בהכרח config.phone_number_id - כמה מספרים יכולים להיות מחוברים לאותה
    # אפליקציה/WABA, וצריך לענות מאותו מספר שהלקוח כתב אליו
    reply_phone_number_id = whatsapp_bot.extract_metadata_phone_number_id(payload) or bot_config.phone_number_id

    repos = db_context.get_repos()

    if message_id and repos.whatsapp_state.has_processed(message_id):
        print(f"[WhatsApp customer webhook] duplicate delivery ignored: {message_id}", flush=True)
        return jsonify({"status": "ignored", "reason": "duplicate"})
    if message_id:
        repos.whatsapp_state.mark_processed(message_id)

    caller_phone = normalize_phone(from_number)

    # מסמך שהתקבל (למשל קורות חיים בתגובה לפנייה בנושא משרה) - מתקבל ונשמר בנפרד
    # מההודעות הלא-טקסטואליות הכלליות למטה, כי כאן יש התנהגות ייעודית: לשמור את
    # הקובץ, להודיע לבעלים, ולהשיב ללקוחה בחום (ולא "אני יודע לקרוא רק טקסט")
    if message_type == "document":
        document_info = text or {}
        sender_name = whatsapp_bot.extract_sender_profile_name(payload)
        attachment_url = None
        try:
            file_bytes, _mime_type = whatsapp_bot.download_media(bot_config, document_info.get("media_id"))
            if file_bytes:
                attachment_url = _save_incoming_document(
                    caller_phone, document_info.get("filename") or "מסמך", file_bytes
                )
        except Exception as exc:
            print(f"[WhatsApp customer webhook] document download failed: {exc}", flush=True)

        repos.customer_bot_messages.log(
            caller_phone,
            "in",
            f"[קובץ: {document_info.get('filename') or 'מסמך'}]",
            reply_phone_number_id,
            attachment_url=attachment_url,
        )

        thank_you_text = "תודה רבה! קיבלתי את הקובץ ואחזור אלייך עם כל הפרטים בהקדם 🙏"
        repos.customer_bot_messages.log(caller_phone, "out", thank_you_text, reply_phone_number_id)
        whatsapp_bot.send_text_message(bot_config, from_number, thank_you_text, phone_number_id=reply_phone_number_id)

        # הודעת תבנית (template) - בניגוד לטקסט חופשי, מגיעה גם אם לא כתבת לבוט הפנימי
        # ב-24 השעות האחרונות (ראו CV_NOTIFICATION_TEMPLATE_NAME). נופלת חזרה לטקסט חופשי
        # רק אם שליחת התבנית נכשלת (למשל לפני שאושרה ב-WhatsApp Manager) - עדיף ניסיון
        # שעלול להיחסם על פני ויתור מוחלט
        try:
            whatsapp_bot.send_template_message(
                whatsapp_bot.ADMIN_BOT,
                OWNER_WHATSAPP_NUMBER,
                CV_NOTIFICATION_TEMPLATE_NAME,
                "he",
                body_params=[sender_name or caller_phone, caller_phone],
            )
        except Exception as exc:
            print(f"[WhatsApp customer webhook] owner template notification failed: {exc}", flush=True)
            owner_notification = (
                f"📄 התקבלו קורות חיים מ-{sender_name or caller_phone} ({caller_phone}).\n"
                f"אפשר לצפות בשיחה בעמוד שיחות בוט הלקוחות."
            )
            try:
                whatsapp_bot.send_text_message(whatsapp_bot.ADMIN_BOT, OWNER_WHATSAPP_NUMBER, owner_notification)
            except Exception as exc2:
                print(f"[WhatsApp customer webhook] owner fallback notification failed: {exc2}", flush=True)

        return jsonify({"status": "ok", "reason": "document_received"})

    # תמונה/וידאו - נשמרים (לצפייה בעמוד שיחות בוט הלקוחות) ומעבירים לבעלים, כי
    # בניגוד לטקסט הבוט לא "רואה" את התוכן ולא יכול להגיב עליו בעצמו
    if message_type in ("image", "video"):
        media_info = text or {}
        sender_name = whatsapp_bot.extract_sender_profile_name(payload)
        kind_label = "תמונה" if message_type == "image" else "סרטון"
        attachment_url = None
        try:
            file_bytes, mime_type = whatsapp_bot.download_media(bot_config, media_info.get("media_id"))
            if file_bytes:
                extension = _guess_media_extension(mime_type or media_info.get("mime_type"))
                attachment_url = _save_incoming_document(
                    caller_phone, f"{message_type}{extension}", file_bytes
                )
        except Exception as exc:
            print(f"[WhatsApp customer webhook] {message_type} download failed: {exc}", flush=True)

        log_body = f"[{kind_label}]"
        if media_info.get("caption"):
            log_body += f" {media_info['caption']}"
        repos.customer_bot_messages.log(
            caller_phone, "in", log_body, reply_phone_number_id, attachment_url=attachment_url
        )

        thank_you_text = f"תודה! קיבלתי את ה{kind_label}, אעביר את זה הלאה ונחזור אלייך בהקדם 🙏"
        repos.customer_bot_messages.log(caller_phone, "out", thank_you_text, reply_phone_number_id)
        whatsapp_bot.send_text_message(bot_config, from_number, thank_you_text, phone_number_id=reply_phone_number_id)

        alert_text = f"התקבל/ה {kind_label} מ-{sender_name or caller_phone} ({caller_phone}) - אפשר לצפות בעמוד שיחות בוט הלקוחות."
        try:
            whatsapp_bot.send_template_message(
                whatsapp_bot.ADMIN_BOT, OWNER_WHATSAPP_NUMBER, OWNER_ALERT_TEMPLATE_NAME, "he",
                body_params=[alert_text],
            )
        except Exception as exc:
            print(f"[WhatsApp customer webhook] owner {message_type} template alert failed: {exc}", flush=True)
            try:
                whatsapp_bot.send_text_message(whatsapp_bot.ADMIN_BOT, OWNER_WHATSAPP_NUMBER, f"📎 {alert_text}")
            except Exception as exc2:
                print(f"[WhatsApp customer webhook] owner {message_type} fallback alert failed: {exc2}", flush=True)

        return jsonify({"status": "ok", "reason": f"{message_type}_received"})

    if message_type != "text":
        fallback_text = "אני יכול לקרוא כרגע רק הודעות טקסט - אפשר לכתוב לי? 🙏"
        repos.customer_bot_messages.log(
            caller_phone, "in", f"[הודעה לא-טקסטואלית: {message_type}]", reply_phone_number_id
        )
        repos.customer_bot_messages.log(caller_phone, "out", fallback_text, reply_phone_number_id)
        whatsapp_bot.send_text_message(bot_config, from_number, fallback_text, phone_number_id=reply_phone_number_id)
        return jsonify({"status": "ignored", "reason": "non_text"})

    sender_name = whatsapp_bot.extract_sender_profile_name(payload)
    repos.customer_bot_messages.log(caller_phone, "in", text, reply_phone_number_id)
    try:
        reply_text = customer_assistant.answer_question(repos, caller_phone, text, sender_name=sender_name)
    except Exception as exc:
        print(f"[WhatsApp customer webhook] assistant failed: {exc}", flush=True)
        reply_text = "אירעה שגיאה בעיבוד הבקשה, נסה שוב מאוחר יותר."

    repos.customer_bot_messages.log(caller_phone, "out", reply_text, reply_phone_number_id)
    whatsapp_bot.send_text_message(bot_config, from_number, reply_text, phone_number_id=reply_phone_number_id)
    return jsonify({"status": "ok"})
