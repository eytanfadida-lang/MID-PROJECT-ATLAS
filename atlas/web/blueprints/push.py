from flask import Blueprint, jsonify, request

from atlas.core.auth import admin_required, current_user
from atlas.data.context import get_repos
from atlas.services import web_push

# הרשמה לקבלת התראות דחיפה על הודעות חדשות מלקוחות (ראו atlas/services/web_push.py). למנהלת בלבד -
# אלה הודעות של לקוחות אמיתיות. הדפדפן מבצע את ההרשמה (static/push.js) ושולח לכאן את פרטי המנוי;
# הבקשות הן טפסים רגילים (לא JSON) כדי שאימות ה-CSRF הקיים יחול עליהן בלי שינוי
bp = Blueprint("push", __name__, url_prefix="/push")


@bp.route("/public-key")
@admin_required
def public_key():
    if not web_push.is_available():
        return jsonify(available=False, key=None)
    return jsonify(available=True, key=web_push.get_public_key())


@bp.route("/subscribe", methods=["POST"])
@admin_required
def subscribe():
    endpoint = request.form.get("endpoint", "").strip()
    p256dh = request.form.get("p256dh", "").strip()
    auth = request.form.get("auth", "").strip()
    # שירותי הדחיפה כולם ב-https; ערך אחר הוא שגיאה/ניסיון לשלוח בקשות שרת לכתובת שרירותית
    if not endpoint.startswith("https://") or not p256dh or not auth or len(endpoint) > 2000:
        return jsonify(ok=False, error="פרטי מנוי לא תקינים"), 400
    user = current_user() or {}
    get_repos().push_subscriptions.upsert(
        endpoint, p256dh, auth, username=user.get("username"), user_agent=request.headers.get("User-Agent", "")[:300]
    )
    return jsonify(ok=True)


@bp.route("/unsubscribe", methods=["POST"])
@admin_required
def unsubscribe():
    endpoint = request.form.get("endpoint", "").strip()
    removed = get_repos().push_subscriptions.delete_by_endpoint(endpoint) if endpoint else False
    return jsonify(ok=True, removed=removed)


# התראת בדיקה: נשלחת לכל המכשירים הרשומים, כדי שאפשר יהיה לוודא מיד שההתראות מגיעות לטלפון
@bp.route("/test", methods=["POST"])
@admin_required
def send_test():
    if not web_push.is_available():
        return jsonify(ok=False, error="ספריית ההתראות לא מותקנת בשרת"), 503
    repos = get_repos()
    if repos.push_subscriptions.count() == 0:
        return jsonify(ok=False, error="אין מכשירים רשומים להתראות"), 400
    payload = {
        "title": "בדיקת התראות ✓",
        "body": "ההתראות עובדות. כך יופיעו כאן הודעות חדשות מלקוחות.",
        "tag": "push-test",
        "force": True,  # מוצגת גם כשהאפליקציה פתוחה (ראו sw.js) - אחרת לא רואים שהיא עובדת
        "url": "/bot-conversations/",
        "unread": 0,
    }
    result = web_push.send_to_all(repos, payload)
    return jsonify(ok=result["sent"] > 0, **result)
