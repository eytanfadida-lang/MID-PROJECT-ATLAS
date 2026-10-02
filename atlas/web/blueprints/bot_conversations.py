import datetime

from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from werkzeug.utils import secure_filename

from atlas.data.context import get_repos
from atlas.core.auth import admin_required
from atlas.services.phone_utils import to_whatsapp_format
from atlas.integrations.whatsapp import bot as whatsapp_bot
from atlas.paths import PROJECT_ROOT

# עמוד לצפייה בהיסטוריית השיחות של בוט הלקוחות בוואטסאפ - למנהלת העסק בלבד
# (שיחות עם לקוחות אמיתיות, מידע רגיש). נתונים מ-customer_bot_messages (ראו
# customer_bot_message_repository.py), נרשם בכל הודעה נכנסת/יוצאת ב-webhooks.py
bp = Blueprint("bot_conversations", __name__, url_prefix="/bot-conversations")

UPLOADS_DIR = PROJECT_ROOT / "atlas" / "web" / "static" / "uploads"


# שני הראוטים למטה מציגים את אותו עמוד דו-עמודות (רשימת שיחות מימין, שיחה נבחרת
# משמאל, כמו וואטסאפ עצמו) - view_conversation רק מוסיף לו את השיחה הנבחרת
@bp.route("/")
@admin_required
def list_conversations():
    conversations = get_repos().customer_bot_messages.get_conversation_summaries()
    return render_template(
        "bot_conversations/index.html", conversations=conversations, active_phone=None, messages=None
    )


@bp.route("/<phone>")
@admin_required
def view_conversation(phone):
    repos = get_repos()
    conversations = repos.customer_bot_messages.get_conversation_summaries()
    messages = repos.customer_bot_messages.get_by_phone(phone)
    if not messages:
        abort(404)
    return render_template(
        "bot_conversations/index.html", conversations=conversations, active_phone=phone, messages=messages
    )


# שומרת את הקובץ שהועלה גם מקומית (תחת static/uploads, כדי שהתמונה/קובץ יוצגו בתוך
# בועת הצ'אט שלנו) וגם ב-Meta (media_id, דרוש כדי לשלוח את הקובץ בפועל בוואטסאפ)
def _save_upload_locally(phone, uploaded_file):
    phone_dir = UPLOADS_DIR / phone
    phone_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    safe_name = secure_filename(uploaded_file.filename) or "attachment"
    stored_name = f"{timestamp}_{safe_name}"
    uploaded_file.save(phone_dir / stored_name)
    return f"/static/uploads/{phone}/{stored_name}"


# שולחת הודעה ידנית ללקוח ישירות מהממשק (השתלטות ידנית על שיחה, למשל אחרי
# request_human_callback) - לא עוברת דרך ה-LLM, ולכן גם לא נכנסת להיסטוריה הקצרה
# שהבוט משתמש בה (customer_assistant.py). זה בסדר - התיעוד המלא נשאר כאן, ביומן הקבוע.
# תומכת גם בצירוף תמונה/קובץ (נשלח כ-caption על גבי המדיה אם יש גם טקסט וגם קובץ)
@bp.route("/<phone>/reply", methods=["POST"])
@admin_required
def reply(phone):
    body = request.form.get("body", "").strip()
    uploaded_file = request.files.get("attachment")
    has_attachment = bool(uploaded_file and uploaded_file.filename)

    if not body and not has_attachment:
        flash("יש להזין תוכן הודעה או לצרף קובץ.", "error")
        return redirect(url_for("bot_conversations.view_conversation", phone=phone))

    whatsapp_phone = to_whatsapp_format(phone)
    if not whatsapp_phone:
        flash("מספר טלפון לא תקין לשליחה.", "error")
        return redirect(url_for("bot_conversations.view_conversation", phone=phone))

    repos = get_repos()
    # עונה מאותו מספר שבו התנהלה השיחה עד כה - רלוונטי מרגע שכמה מספרים מחוברים
    bot_phone_number_id = repos.customer_bot_messages.get_latest_bot_phone_number_id(phone)
    bot_config = whatsapp_bot.CUSTOMER_BOT

    attachment_url = None
    try:
        if has_attachment:
            mime_type = uploaded_file.content_type or "application/octet-stream"
            file_bytes = uploaded_file.read()
            attachment_url = _save_upload_locally(phone, uploaded_file)

            media_id = whatsapp_bot.upload_media(
                bot_config, file_bytes, uploaded_file.filename, mime_type, phone_number_id=bot_phone_number_id
            )
            media_type = "image" if mime_type.startswith("image/") else "document"
            whatsapp_bot.send_media_message(
                bot_config, whatsapp_phone, media_id, media_type,
                phone_number_id=bot_phone_number_id, caption=body or None,
            )
        else:
            whatsapp_bot.send_text_message(
                bot_config, whatsapp_phone, body, phone_number_id=bot_phone_number_id
            )
    except Exception as exc:
        flash(f"שליחת ההודעה נכשלה: {exc}", "error")
        return redirect(url_for("bot_conversations.view_conversation", phone=phone))

    log_body = body or ("📎 " + uploaded_file.filename if has_attachment else "")
    repos.customer_bot_messages.log(phone, "out", log_body, bot_phone_number_id, attachment_url)
    return redirect(url_for("bot_conversations.view_conversation", phone=phone))
