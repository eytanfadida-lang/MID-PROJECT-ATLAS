from flask import Blueprint, render_template, abort

from atlas.data.context import get_repos
from atlas.core.auth import admin_required

# עמוד לצפייה בהיסטוריית השיחות של בוט הלקוחות בוואטסאפ - למנהלת העסק בלבד
# (שיחות עם לקוחות אמיתיות, מידע רגיש). נתונים מ-customer_bot_messages (ראו
# customer_bot_message_repository.py), נרשם בכל הודעה נכנסת/יוצאת ב-webhooks.py
bp = Blueprint("bot_conversations", __name__, url_prefix="/bot-conversations")


@bp.route("/")
@admin_required
def list_conversations():
    conversations = get_repos().customer_bot_messages.get_conversation_summaries()
    return render_template("bot_conversations/list.html", conversations=conversations)


@bp.route("/<phone>")
@admin_required
def view_conversation(phone):
    messages = get_repos().customer_bot_messages.get_by_phone(phone)
    if not messages:
        abort(404)
    return render_template("bot_conversations/detail.html", phone=phone, messages=messages)
