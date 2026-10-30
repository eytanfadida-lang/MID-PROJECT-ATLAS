import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from atlas.core.auth import admin_required
from atlas.data.context import get_repos
from atlas.integrations.whatsapp import bot as whatsapp_bot

# עמוד "אינטגרציות" (למנהלת בלבד): חשבונות וואטסאפ רשמיים (Meta Cloud API, להצגה בלבד) וחשבונות "לא רשמיים"
# שמחוברים כמכשיר מקושר באמצעות QR (כמו WhatsApp Web). החיבור עצמו רץ בתהליך נפרד (gateway/) -
# כאן רק מבקשים ממנו לחבר/לנתק ומציגים את הסטטוס וה-QR שהוא מדווח (ראו blueprints/gateway.py)
bp = Blueprint("integrations", __name__, url_prefix="/integrations")

MAX_LABEL_LENGTH = 40

STATUS_LABELS = {
    "starting": "מתחבר...",
    "waiting_qr": "ממתין לסריקה",
    "connected": "מחובר",
    "disconnected": "מנותק",
    "logged_out": "הוסר מהטלפון - צריך לחבר מחדש",
    "error": "שגיאה בחיבור",
}


def _qr_remaining_seconds(account):
    """כמה שניות נשארו עד שה-QR הנוכחי מתחלף (None אם אין QR)."""
    if account["status"] != "waiting_qr" or not account["qr_updated_at"] or not account["qr_ttl"]:
        return None
    age = (datetime.datetime.now() - datetime.datetime.fromisoformat(account["qr_updated_at"])).total_seconds()
    return max(0, int(account["qr_ttl"] - age))


def _public_state(account, repos):
    return {
        "id": account["id"],
        "label": account["label"],
        "status": account["status"],
        "status_label": STATUS_LABELS.get(account["status"], account["status"]),
        "desired": account["desired"],
        "phone": account["phone"],
        "error": account["error"],
        "qr_image": account["qr_image"] if account["status"] == "waiting_qr" else None,
        "qr_remaining": _qr_remaining_seconds(account),
        "gateway_online": repos.linked_whatsapp.is_gateway_online(),
    }


@bp.route("/")
@admin_required
def index():
    repos = get_repos()
    accounts = repos.linked_whatsapp.get_all()
    official = [{"label": label, "phone_number_id": pid} for pid, label in whatsapp_bot.CUSTOMER_BOT_NUMBER_LABELS.items()]
    return render_template(
        "integrations/index.html",
        accounts=accounts,
        official_numbers=official,
        status_labels=STATUS_LABELS,
        gateway_online=repos.linked_whatsapp.is_gateway_online(),
    )


# יצירת חשבון חדש והתחלת חיבור (המודל קורא לזה בשליחת השם). מחזיר JSON כדי שהמודל יעבור ישר למסך ה-QR
@bp.route("/whatsapp/new", methods=["POST"])
@admin_required
def create_account():
    label = request.form.get("label", "").strip()
    if not label or len(label) > MAX_LABEL_LENGTH:
        return jsonify(ok=False, error=f"יש להזין שם עד {MAX_LABEL_LENGTH} תווים"), 400
    account_id = get_repos().linked_whatsapp.create(label)
    return jsonify(ok=True, id=account_id)


# מצב נוכחי לרענון המודל/הכרטיסים (נשאל כל ~2 שניות כשהמודל פתוח)
@bp.route("/whatsapp/<int:account_id>/state")
@admin_required
def account_state(account_id):
    repos = get_repos()
    account = repos.linked_whatsapp.get(account_id)
    if account is None:
        return jsonify(ok=False), 404
    return jsonify(ok=True, **_public_state(account, repos))


@bp.route("/whatsapp/<int:account_id>/connect", methods=["POST"])
@admin_required
def connect(account_id):
    repos = get_repos()
    if repos.linked_whatsapp.get(account_id) is None:
        return jsonify(ok=False), 404
    repos.linked_whatsapp.set_desired(account_id, "connect")
    return jsonify(ok=True)


@bp.route("/whatsapp/<int:account_id>/disconnect", methods=["POST"])
@admin_required
def disconnect(account_id):
    repos = get_repos()
    if repos.linked_whatsapp.get(account_id) is None:
        flash("החשבון לא נמצא", "error")
    else:
        repos.linked_whatsapp.set_desired(account_id, "disconnect")
        flash("החשבון מתנתק. אפשר לחבר אותו שוב בלי סריקה חדשה", "success")
    return redirect(url_for("integrations.index"))


@bp.route("/whatsapp/<int:account_id>/rename", methods=["POST"])
@admin_required
def rename(account_id):
    label = request.form.get("label", "").strip()
    repos = get_repos()
    if repos.linked_whatsapp.get(account_id) is None or not label or len(label) > MAX_LABEL_LENGTH:
        flash("שם לא תקין", "error")
    else:
        repos.linked_whatsapp.rename(account_id, label)
        flash("השם עודכן", "success")
    return redirect(url_for("integrations.index"))


# מחיקה: אם התהליך פועל - מבקשים ממנו להתנתק מהוואטסאפ ולמחוק את ההתחברות, והשורה נמחקת כשהוא מאשר.
# אם הוא לא פועל (אין מי שיאשר) - מוחקים את השורה מיד; ההתחברות בטלפון תישאר ב"מכשירים מקושרים" ואפשר להסיר אותה משם
@bp.route("/whatsapp/<int:account_id>/delete", methods=["POST"])
@admin_required
def delete(account_id):
    repos = get_repos()
    account = repos.linked_whatsapp.get(account_id)
    if account is None:
        flash("החשבון לא נמצא", "error")
    elif repos.linked_whatsapp.is_gateway_online():
        repos.linked_whatsapp.set_desired(account_id, "delete")
        flash("החשבון נמחק, והוא יוסר מהרשימה תוך שניות", "success")
    else:
        repos.linked_whatsapp.delete(account_id)
        flash("החשבון הוסר מהרשימה. שירות החיבור לא פועל, ולכן כדאי להסיר את המכשיר גם בטלפון: הגדרות ← מכשירים מקושרים", "success")
    return redirect(url_for("integrations.index"))
