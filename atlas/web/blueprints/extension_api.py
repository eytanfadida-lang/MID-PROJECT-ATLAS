import datetime

from flask import Blueprint, abort, g, jsonify, request

from atlas.core.api_auth import token_required
from atlas.data.context import get_repos
from atlas.settings import BRANCHES
from atlas.services.phone_utils import normalize_phone

# ה-API שתוסף ה-Chrome (שמתלבש על web.whatsapp.com, ראו תוכנית הבנייה) מדבר איתו. כל עובדת
# מתחברת פעם אחת עם שם המשתמש/סיסמה שלה מה-CRM (/login), ומקבלת טוקן אישי ששמור ב-
# api_tokens (ראו atlas/core/api_auth.py, atlas/data/repositories/api_token_repository.py) -
# בלי session/עוגיית דפדפן, כי זו בקשה ממקור אחר (chrome-extension://) ולא מהאתר עצמו.
# פטור מ-CSRF באותו אופן כמו /tasks/ ו-/gateway/ (ראו atlas/core/auth.py validate_csrf)
bp = Blueprint("extension_api", __name__, url_prefix="/api/extension")

LEAD_CHANNEL_DEFAULT = "וואטסאפ"


@bp.route("/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or {}
    username = payload.get("username", "")
    password = payload.get("password", "")

    repos = get_repos()
    role = repos.users.authenticate(username, password)
    if role is None:
        return jsonify(ok=False, error="שם משתמש או סיסמה שגויים"), 401

    user = repos.users.get_by_username(username)
    label = (payload.get("label") or "תוסף וואטסאפ")[:200]
    token = repos.api_tokens.create(user["id"], label=label)
    return jsonify(ok=True, token=token, username=username, role=role)


@bp.route("/logout", methods=["POST"])
@token_required
def logout():
    get_repos().api_tokens.revoke(g.api_user["token_id"])
    return jsonify(ok=True)


# מידע מאוחד על מספר טלפון - ליד/לקוחה (אם קיימים), מנוי מ-Arbox, ביקורים אחרונים, ומפת
# הצבעים של הסטטוסים (כדי שהתוסף יצבע את התגית כמו בטבלת הלידים). phone לא חייב להיות
# כבר בפורמט מקומי - מנורמל כאן (ראו phone_utils.normalize_phone)
@bp.route("/lookup", methods=["GET"])
@token_required
def lookup():
    phone = normalize_phone(request.args.get("phone", ""))
    if not phone:
        return jsonify(ok=False, error="מספר טלפון לא תקין"), 400

    repos = get_repos()
    leads_df = repos.leads.get_by_phone(phone)
    lead = leads_df.iloc[0].to_dict() if not leads_df.empty else None

    return jsonify(
        ok=True,
        phone=phone,
        lead=lead,
        status_colors=repos.lead_statuses.get_color_map(),
        branches=BRANCHES,
        membership=repos.arbox_member_cache.get_details_by_phone(phone),
        recent_visits=repos.arbox_visit_cache.get_recent_by_phone(phone),
    )


@bp.route("/leads", methods=["POST"])
@token_required
def create_lead():
    payload = request.get_json(silent=True) or {}
    phone = normalize_phone(payload.get("phone", ""))
    if not phone:
        return jsonify(ok=False, error="מספר טלפון לא תקין"), 400

    repos = get_repos()
    statuses = repos.lead_statuses.get_names()
    lead = {
        "full_name": payload.get("full_name") or "",
        "phone": phone,
        "status": statuses[0] if statuses else "",
        "channel": payload.get("channel") or LEAD_CHANNEL_DEFAULT,
        "branch": payload.get("branch") or BRANCHES[0],
        "assigned_user": g.api_user["username"],
        "notes": payload.get("notes") or "",
    }
    lead_id = repos.leads.create(lead)
    return jsonify(ok=True, lead_id=lead_id, lead=repos.leads.get_by_id(lead_id))


@bp.route("/leads/<int:lead_id>/status", methods=["POST"])
@token_required
def update_lead_status(lead_id):
    payload = request.get_json(silent=True) or {}
    status = payload.get("status", "")
    repos = get_repos()
    if repos.leads.get_by_id(lead_id) is None:
        abort(404)
    if status not in repos.lead_statuses.get_names():
        return jsonify(ok=False, error="סטטוס לא קיים"), 400

    repos.leads.update_field(lead_id, "status", status)
    return jsonify(ok=True, lead=repos.leads.get_by_id(lead_id))


# "הוספת הערה" - leads.notes הוא שדה טקסט בודד (לא רשימה), אז מצרפים שורה מתוארכת בראש
# הטקסט הקיים במקום להחליף אותו. פורמט תואם למה שעובדת תזהה כ"יומן הערות" גם בלי טבלה נפרדת
@bp.route("/leads/<int:lead_id>/notes", methods=["POST"])
@token_required
def add_lead_note(lead_id):
    payload = request.get_json(silent=True) or {}
    note_text = (payload.get("note") or "").strip()
    if not note_text:
        return jsonify(ok=False, error="הערה ריקה"), 400

    repos = get_repos()
    lead = repos.leads.get_by_id(lead_id)
    if lead is None:
        abort(404)

    timestamp = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    author = g.api_user["username"]
    new_entry = f"[{timestamp} - {author}] {note_text}"
    existing_notes = (lead.get("notes") or "").strip()
    merged_notes = f"{new_entry}\n\n{existing_notes}" if existing_notes else new_entry

    repos.leads.update_field(lead_id, "notes", merged_notes)
    return jsonify(ok=True, lead=repos.leads.get_by_id(lead_id))


# אותה צורת JSON כמו ה-endpoint הפנימי הקיים ב-bot_conversations.py (quick_replies route),
# רק עם הרשאת טוקן במקום session+CSRF - כדי שהתוסף ישתמש באותה ספריית תבניות בדיוק
@bp.route("/quick-replies", methods=["GET"])
@token_required
def quick_replies():
    repos = get_repos()
    return jsonify(
        ok=True,
        replies=repos.quick_replies.get_all(),
        categories=repos.quick_replies.get_categories(),
    )
