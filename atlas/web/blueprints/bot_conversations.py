import datetime
import re
from pathlib import Path

from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash, abort, jsonify
from werkzeug.utils import secure_filename

from atlas.data.context import get_repos
from atlas.core.auth import admin_required
from atlas.services import linked_whatsapp
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
def _with_number_labels(conversations, repos=None):
    labels = {}
    for conversation in conversations:
        number_id = conversation.get("bot_phone_number_id")
        if number_id not in labels:
            linked_label = linked_whatsapp.label_for(repos, number_id) if repos is not None else None
            labels[number_id] = (
                linked_label or whatsapp_bot.describe_phone_number_id(number_id),
                linked_whatsapp.account_id_of(number_id) is not None,
            )
        conversation["bot_phone_label"], conversation["is_linked"] = labels[number_id]
    return conversations


# מעשירה כל שיחה בפרטי הלקוחה מהקאש המקומי של Arbox (arbox_member_cache, ראו
# atlas/data/repositories/arbox_member_cache_repository.py - מתעדכן תדיר ע"י /tasks/arbox-sync,
# אין כאן קריאה חיה ל-Arbox בטעינת העמוד). כל השדות None אם המספר לא נמצא בקאש (למשל ליד
# שעוד לא הפך ללקוחה ב-Arbox, או מספר שגוי) - הטמפלט נופל חזרה למספר הטלפון/מסתיר את השדות.
# הקאש והשהיות הבוט נשלפים בשאילתה אחת לכל הרשימה (לא שאילתה לכל שיחה)
def _with_names(conversations, repos):
    members = repos.arbox_member_cache.get_many_by_phone([c["phone"] for c in conversations])
    paused = repos.customer_bot_messages.paused_phones()
    for conversation in conversations:
        member = members.get(conversation["phone"])
        full_name = f"{member['first_name']} {member['last_name']}".strip() if member else ""
        conversation["full_name"] = full_name or None
        conversation["membership_type_name"] = (member or {}).get("membership_type_name") or None
        conversation["membership_start_date"] = (member or {}).get("membership_start_date") or None
        conversation["membership_end_date"] = (member or {}).get("membership_end_date") or None
        conversation["debt"] = (member or {}).get("debt") or None
        conversation["cancelled"] = bool((member or {}).get("cancelled")) if member else False
        # active=None כשאין בכלל התאמה בקאש (לא "לא פעיל") - כדי שהטמפלט יבדיל בין "לא מופיעה
        # ב-Arbox" לבין "מופיעה אבל המנוי שלה לא פעיל כרגע"
        conversation["active"] = bool(member["active"]) if member else None
        conversation["synced_at"] = (member or {}).get("synced_at") or None
        conversation["bot_paused"] = conversation["phone"] in paused
    return conversations


# המספרים (רשמי/מקושר) שבהם יש שיחות - לבורר "סנן לפי מספר" ברשימה (מוצג רק כשיש יותר ממספר אחד)
def _number_labels(conversations):
    return sorted({c["bot_phone_label"] for c in conversations})


@bp.route("/")
@admin_required
def list_conversations():
    repos = get_repos()
    conversations = _with_names(
        _with_number_labels(repos.customer_bot_messages.get_conversation_summaries(), repos), repos
    )
    return render_template(
        "bot_conversations/index.html", conversations=conversations, active_phone=None, messages=None,
        active_conversation=None, signature=repos.customer_bot_messages.get_state_signature(),
        number_labels=_number_labels(conversations),
    )


# חתימת המצב הנוכחית של כל השיחות - העמוד בודק אותה כל כמה שניות ורענן את עצמו רק כשהיא
# משתנה (ראו הסקריפט ב-bot_conversations/index.html). שאילתה זולה, בלי חיפוש בקאש Arbox
@bp.route("/_state")
@admin_required
def poll_state():
    return jsonify(signature=get_repos().customer_bot_messages.get_state_signature())


# הופכת שיחה ל"לא נקראה" (למשל כדי לחזור אליה אחר כך). נקראת גם מהרשימה (fetch, מחזירה JSON)
# וגם מכפתור בראש השיחה (טופס רגיל, חוזרת לרשימה - לא לשיחה עצמה, אחרת פתיחתה הייתה מסמנת
# אותה מיד כנקראת שוב)
@bp.route("/<phone>/mark-unread", methods=["POST"])
@admin_required
def mark_unread(phone):
    done = get_repos().customer_bot_messages.mark_unread(phone)
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=done)
    if not done:
        flash("אי אפשר לסמן כלא נקרא - הלקוחה עוד לא כתבה בשיחה הזו.", "error")
    return redirect(url_for("bot_conversations.list_conversations"))


# מוחקת הודעה מהיומן שבממשק (מחיקה רכה, ראו delete_message בריפוזיטורי). חשוב: לא מוחקת
# אותה מוואטסאפ של הלקוחה - ל-Cloud API אין אפשרות למחוק הודעה שכבר נשלחה. נקראת ב-fetch מהעמוד
# (מחזירה כמה הודעות נשארו בשיחה, כדי שהעמוד יחזור לרשימה אם נמחקה האחרונה)
@bp.route("/<phone>/messages/<int:message_id>/delete", methods=["POST"])
@admin_required
def delete_message(phone, message_id):
    remaining = get_repos().customer_bot_messages.delete_message(phone, message_id)
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=remaining is not None, remaining=remaining or 0)
    if remaining is None:
        flash("ההודעה לא נמצאה או שכבר נמחקה.", "error")
    elif remaining == 0:
        return redirect(url_for("bot_conversations.list_conversations"))
    return redirect(url_for("bot_conversations.view_conversation", phone=phone))


# עורכת את טקסט ההודעה ביומן בממשק (תיעוד מקומי, ראו edit_message בריפוזיטורי) - אי אפשר
# לשנות בפועל הודעה שכבר נשלחה/התקבלה בוואטסאפ (אין API למטא לכך, גם לא ל-WhatsApp Cloud API
# שהבוט שלנו משתמש בו - עריכת הודעות היא תכונה של אפליקציית הצרכנים בלבד). לכן, רק להודעות
# **יוצאות** (direction='out', מה שאנחנו שלחנו) - שולחים בנוסף הודעת "תיקון" אמיתית חדשה
# ללקוחה (בועה נפרדת, לא מחליפה את המקורית), כדי שהיא בכל זאת תראה את השינוי. להודעות
# **נכנסות** (מה שהלקוחה כתבה) אין שום שליחה - רק עריכת התיעוד אצלנו (אין טעם "לתקן" אותה)
@bp.route("/<phone>/messages/<int:message_id>/edit", methods=["POST"])
@admin_required
def edit_message(phone, message_id):
    new_body = (request.form.get("body") or "").strip()
    repos = get_repos()
    message = repos.customer_bot_messages.get_by_id(phone, message_id)
    ok = bool(new_body) and bool(message) and repos.customer_bot_messages.edit_message(phone, message_id, new_body)

    if ok and message["direction"] == "out" and linked_whatsapp.account_id_of(message["bot_phone_number_id"]) is not None:
        # חשבון מקושר: הודעת "תיקון" נשלחת דרך התור, כמו כל הודעה יוצאת משם
        linked_whatsapp.queue_outgoing(
            repos, linked_whatsapp.account_id_of(message["bot_phone_number_id"]), phone, f"תיקון להודעה הקודמת:\n{new_body}"
        )
    elif ok and message["direction"] == "out":
        whatsapp_phone = to_whatsapp_format(phone)
        if whatsapp_phone:
            try:
                correction_text = f"תיקון להודעה הקודמת:\n{new_body}"
                response = whatsapp_bot.send_text_message(
                    whatsapp_bot.CUSTOMER_BOT, whatsapp_phone, correction_text,
                    phone_number_id=message["bot_phone_number_id"],
                )
                repos.customer_bot_messages.log(
                    phone, "out", correction_text, message["bot_phone_number_id"],
                    wamid=whatsapp_bot.extract_wamid(response),
                )
            except Exception as exc:
                print(f"[bot_conversations] edit correction send failed: {exc}", flush=True)

    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=ok)
    if not ok:
        flash("לא ניתן לערוך את ההודעה - היא לא נמצאה, כבר נמחקה, או שהטקסט ריק.", "error")
    return redirect(url_for("bot_conversations.view_conversation", phone=phone))


# משהה/מפעילה מחדש את הבוט לשיחה הזו (ראו set_bot_paused בריפוזיטורי) - כשמושהה, הבוט
# ממשיך לתעד הודעות נכנסות ביומן (כדי שהשיחה תישאר שלמה) אבל לא שולח שום תגובה אוטומטית,
# כולל לא ה-fallback הרגיל של "אני יכול לקרוא רק טקסט" (ראו whatsapp_customer_webhook)
@bp.route("/<phone>/bot-pause", methods=["POST"])
@admin_required
def toggle_bot_pause(phone):
    repos = get_repos()
    paused = not repos.customer_bot_messages.is_bot_paused(phone)
    repos.customer_bot_messages.set_bot_paused(phone, paused)
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True, paused=paused)
    return redirect(url_for("bot_conversations.view_conversation", phone=phone))


# הקשר התבנית של פאנל השיחה הפתוחה (כותרת, הודעות, שדה תשובה) - משותף לעמוד המלא ולקטע (fragment)
def _thread_context(repos, phone, messages, active_conversation):
    latest_number_id = repos.customer_bot_messages.get_latest_bot_phone_number_id(phone)
    active_bot_label = linked_whatsapp.label_for(repos, latest_number_id) or whatsapp_bot.describe_phone_number_id(latest_number_id)
    # שיחה דרך חשבון מקושר שלא מחובר כרגע - התבנית מציגה אזהרה במקום שדה כתיבה פעיל
    linked_id = linked_whatsapp.account_id_of(latest_number_id)
    active_linked = repos.linked_whatsapp.get(linked_id) if linked_id is not None else None
    linked_unavailable = None
    if linked_id is not None:
        if active_linked is None:
            linked_unavailable = "החשבון שדרכו התנהלה השיחה נמחק, ולכן אי אפשר לענות כאן."
        elif active_linked["status"] != "connected":
            linked_unavailable = "החשבון שדרכו התנהלה השיחה לא מחובר כרגע. אפשר לחבר אותו מחדש בעמוד האינטגרציות."
    return dict(
        active_phone=phone, messages=messages, active_bot_label=active_bot_label,
        active_conversation=active_conversation, linked_unavailable=linked_unavailable,
    )


@bp.route("/<phone>")
@admin_required
def view_conversation(phone):
    repos = get_repos()
    # לסמן כ"נקרא" לפני שמביאים את רשימת השיחות - כדי שהשיחה הנוכחית כבר תוצג כנקראת
    # ברשימה בצד, בלי לחכות לרענון הבא.
    # בקשת רענון אוטומטי (poll=1) מסמנת כנקרא רק אם הלשונית באמת גלויה (visible=1) - אחרת
    # הודעה שהגיעה בזמן שהמנהלת בלשונית אחרת הייתה מסומנת כנקראת בלי שראתה אותה
    is_poll = request.args.get("poll") == "1"
    if not is_poll or request.args.get("visible") == "1":
        repos.customer_bot_messages.mark_read(phone)
    messages = repos.customer_bot_messages.get_by_phone(phone)
    if not messages:
        abort(404)

    # fragment=1: פתיחת שיחה מתוך הרשימה בלי לטעון את כל הדף - מחזירה רק את פאנל השיחה (בלי שליפת כל
    # הרשימה), והחתימה הנוכחית בכותרת כדי שהרענון האוטומטי לא יטען שוב מיותר
    if request.args.get("fragment") == "1":
        summaries = _with_names(_with_number_labels(repos.customer_bot_messages.get_conversation_summaries(phone), repos), repos)
        html = render_template(
            "bot_conversations/_thread.html",
            **_thread_context(repos, phone, messages, summaries[0] if summaries else None),
        )
        response = current_app.response_class(html, mimetype="text/html")
        response.headers["X-Chat-Signature"] = repos.customer_bot_messages.get_state_signature()
        return response

    conversations = _with_names(
        _with_number_labels(repos.customer_bot_messages.get_conversation_summaries(), repos), repos
    )
    active_conversation = next((c for c in conversations if c["phone"] == phone), None)
    return render_template(
        "bot_conversations/index.html",
        conversations=conversations,
        signature=repos.customer_bot_messages.get_state_signature(),
        number_labels=_number_labels(conversations),
        **_thread_context(repos, phone, messages, active_conversation),
    )


# שומרת את הקובץ שהועלה גם מקומית (תחת static/uploads, כדי שהתמונה/קובץ יוצגו בתוך
# בועת הצ'אט שלנו) וגם ב-Meta (media_id, דרוש כדי לשלוח את הקובץ בפועל בוואטסאפ)
def _save_upload_locally(phone, uploaded_file):
    phone_dir = UPLOADS_DIR / phone
    phone_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    # שמות קבצים בעברית מתאפסים לגמרי ע"י secure_filename (כולל הנקודה והסיומת) -
    # שומרים את הסיומת בנפרד כדי שהקובץ יישאר ניתן לפתיחה (ראו גם webhooks.py)
    safe_name = secure_filename(uploaded_file.filename or "")
    if not safe_name or "." not in safe_name:
        extension = re.sub(r"[^A-Za-z0-9.]", "", Path(uploaded_file.filename or "").suffix)
        safe_name = f"attachment{extension}" if extension else (safe_name or "attachment")
    stored_name = f"{timestamp}_{safe_name}"
    uploaded_file.save(phone_dir / stored_name)
    return f"/static/uploads/{phone}/{stored_name}"


# שולחת הודעה ידנית ללקוח ישירות מהממשק (השתלטות ידנית על שיחה, למשל אחרי
# request_human_callback) - לא עוברת דרך ה-LLM, ולכן גם לא נכנסת להיסטוריה הקצרה
# שהבוט משתמש בה (customer_assistant.py). זה בסדר - התיעוד המלא נשאר כאן, ביומן הקבוע.
# תומכת גם בצירוף תמונה/קובץ (נשלח כ-caption על גבי המדיה אם יש גם טקסט וגם קובץ)
# הממשק שולח את התשובה ברקע (fetch, ראו bot_conversations/index.html) כדי שהבועה תופיע מיד ולא
# נחכה לשרתי מטא ולטעינה מחדש של כל העמוד - אז מחזירים JSON. בלי fetch (דפדפן בלי JS) ההתנהגות
# הישנה נשמרת: הודעת flash וחזרה לשיחה
def _reply_failed(phone, message, status=400):
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=False, error=message[:300]), status
    flash(message, "error")
    return redirect(url_for("bot_conversations.view_conversation", phone=phone))


@bp.route("/<phone>/reply", methods=["POST"])
@admin_required
def reply(phone):
    body = request.form.get("body", "").strip()
    uploaded_file = request.files.get("attachment")
    has_attachment = bool(uploaded_file and uploaded_file.filename)

    if not body and not has_attachment:
        return _reply_failed(phone, "יש להזין תוכן הודעה או לצרף קובץ.")

    repos = get_repos()
    # עונה מאותו מספר שבו התנהלה השיחה עד כה - רלוונטי מרגע שכמה מספרים מחוברים
    bot_phone_number_id = repos.customer_bot_messages.get_latest_bot_phone_number_id(phone)

    # שיחה דרך חשבון "לא רשמי" (מכשיר מקושר): ההודעה נכנסת לתור, והתהליך שמחזיק את החיבור שולח אותה
    # (עד כמה שניות). נתיב נפרד לגמרי מה-API הרשמי, כולל מספרים זרים שלא עוברים נרמול ישראלי
    linked_id = linked_whatsapp.account_id_of(bot_phone_number_id)
    if linked_id is not None:
        attachment_url = attachment_mime = attachment_name = None
        if has_attachment:
            attachment_mime = uploaded_file.content_type or "application/octet-stream"
            attachment_name = uploaded_file.filename
            if len(uploaded_file.read()) > linked_whatsapp.MAX_ATTACHMENT_BYTES:
                return _reply_failed(phone, "הקובץ גדול מדי (עד 10MB).")
            uploaded_file.seek(0)
            attachment_url = _save_upload_locally(phone, uploaded_file)
        queued, result = linked_whatsapp.queue_outgoing(
            repos, linked_id, phone, body, attachment_url, attachment_mime, attachment_name
        )
        if not queued:
            return _reply_failed(phone, result, status=409)
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify(ok=True)
        return redirect(url_for("bot_conversations.view_conversation", phone=phone))

    whatsapp_phone = to_whatsapp_format(phone)
    if not whatsapp_phone:
        return _reply_failed(phone, "מספר טלפון לא תקין לשליחה.")
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
            response = whatsapp_bot.send_media_message(
                bot_config, whatsapp_phone, media_id, media_type,
                phone_number_id=bot_phone_number_id, caption=body or None,
            )
        else:
            response = whatsapp_bot.send_text_message(
                bot_config, whatsapp_phone, body, phone_number_id=bot_phone_number_id
            )
    except Exception as exc:
        return _reply_failed(phone, f"שליחת ההודעה נכשלה: {exc}", status=502)

    log_body = body or ("📎 " + uploaded_file.filename if has_attachment else "")
    wamid = whatsapp_bot.extract_wamid(response)
    repos.customer_bot_messages.log(phone, "out", log_body, bot_phone_number_id, attachment_url, wamid=wamid)
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True)
    return redirect(url_for("bot_conversations.view_conversation", phone=phone))
