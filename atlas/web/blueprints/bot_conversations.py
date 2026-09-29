from flask import Blueprint, render_template, redirect, url_for, request, flash, abort

from atlas.data.context import get_repos
from atlas.core.auth import admin_required
from atlas.services.phone_utils import to_whatsapp_format
from atlas.integrations.whatsapp import bot as whatsapp_bot

# עמוד לצפייה בהיסטוריית השיחות של בוט הלקוחות בוואטסאפ - למנהלת העסק בלבד
# (שיחות עם לקוחות אמיתיות, מידע רגיש). נתונים מ-customer_bot_messages (ראו
# customer_bot_message_repository.py), נרשם בכל הודעה נכנסת/יוצאת ב-webhooks.py
bp = Blueprint("bot_conversations", __name__, url_prefix="/bot-conversations")


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


# שולחת הודעה ידנית ללקוח ישירות מהממשק (השתלטות ידנית על שיחה, למשל אחרי
# request_human_callback) - לא עוברת דרך ה-LLM, ולכן גם לא נכנסת להיסטוריה הקצרה
# שהבוט משתמש בה (customer_assistant.py). זה בסדר - התיעוד המלא נשאר כאן, ביומן הקבוע
@bp.route("/<phone>/reply", methods=["POST"])
@admin_required
def reply(phone):
    body = request.form.get("body", "").strip()
    if not body:
        flash("יש להזין תוכן הודעה.", "error")
        return redirect(url_for("bot_conversations.view_conversation", phone=phone))

    whatsapp_phone = to_whatsapp_format(phone)
    if not whatsapp_phone:
        flash("מספר טלפון לא תקין לשליחה.", "error")
        return redirect(url_for("bot_conversations.view_conversation", phone=phone))

    try:
        whatsapp_bot.send_text_message(whatsapp_bot.CUSTOMER_BOT, whatsapp_phone, body)
    except Exception as exc:
        flash(f"שליחת ההודעה נכשלה: {exc}", "error")
        return redirect(url_for("bot_conversations.view_conversation", phone=phone))

    get_repos().customer_bot_messages.log(phone, "out", body)
    return redirect(url_for("bot_conversations.view_conversation", phone=phone))
