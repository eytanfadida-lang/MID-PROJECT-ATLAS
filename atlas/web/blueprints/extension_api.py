import datetime

from flask import Blueprint, abort, g, jsonify, render_template, request

from atlas.services import quick_reply_images
from atlas.core import roles
from atlas.core.api_auth import token_required
from atlas.data.context import get_repos
from atlas.integrations.arbox import client as arbox_client
from atlas.web.blueprints.bot_conversations import (
    QUICK_REPLY_BODY_MAX, QUICK_REPLY_TITLE_MAX, _DEFAULT_BRANCHES, _age, _customer_info, get_arbox_profile_link,
)
from atlas.settings import BRANCHES
from atlas.services.phone_utils import normalize_phone

# ה-API שתוסף ה-Chrome (שמתלבש על web.whatsapp.com, ראו תוכנית הבנייה) מדבר איתו. כל עובדת
# מתחברת פעם אחת עם שם המשתמש/סיסמה שלה מה-CRM (/login), ומקבלת טוקן אישי ששמור ב-
# api_tokens (ראו atlas/core/api_auth.py, atlas/data/repositories/api_token_repository.py) -
# בלי session/עוגיית דפדפן, כי זו בקשה ממקור אחר (chrome-extension://) ולא מהאתר עצמו.
# פטור מ-CSRF באותו אופן כמו /tasks/ ו-/gateway/ (ראו atlas/core/auth.py validate_csrf)
bp = Blueprint("extension_api", __name__, url_prefix="/api/extension")

LEAD_CHANNEL_DEFAULT = "וואטסאפ"
TAG_MAX = 40
TASK_TITLE_MAX = 200

ARBOX_ROLE_LABELS = {
    "lead": "ליד ב-Arbox",
    "staffMember": "צוות",
    "aggregatorMember": "מנוי אגרגטור (FreeFit וכד')",
}


def _payload():
    return request.get_json(silent=True) or {}


def _username():
    return g.api_user["username"]


def _is_admin():
    return g.api_user.get("role") == roles.ADMIN


def _phone_or_400(raw):
    phone = normalize_phone(raw or "")
    if not phone:
        abort(400, description="מספר טלפון לא תקין")
    return phone


def _lead_or_404(repos, lead_id):
    lead = repos.leads.get_by_id(lead_id)
    if lead is None:
        abort(404)
    return lead


def _branch_name(location_id):
    branches = {**_DEFAULT_BRANCHES, **{str(k): v for k, v in arbox_client.load_location_branch_map().items()}}
    return branches.get(str(location_id or ""))


@bp.errorhandler(400)
def _bad_request(error):
    return jsonify(ok=False, error=getattr(error, "description", None) or "בקשה לא תקינה"), 400


@bp.errorhandler(403)
def _forbidden(error):
    return jsonify(ok=False, error="רק מנהלת יכולה לשנות את זה"), 403


@bp.errorhandler(404)
def _not_found(error):
    return jsonify(ok=False, error="לא נמצא"), 404


# מדיניות הפרטיות של התוסף - עמוד ציבורי (בלי התחברות), כי חנות Chrome דורשת קישור אליו בטופס הפרסום
@bp.route("/privacy", methods=["GET"])
def privacy():
    return render_template("extension_privacy.html")


@bp.route("/login", methods=["POST"])
def login():
    payload = _payload()
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


# נתונים קבועים שהתוסף צריך לבחירות (סטטוסים וצבעים, משתמשות לשיוך נציגה, סניפים, תגיות קיימות)
# - נטען פעם אחת ולא בכל החלפת שיחה
@bp.route("/meta", methods=["GET"])
@token_required
def meta():
    repos = get_repos()
    colors = repos.lead_statuses.get_color_map()
    return jsonify(
        ok=True,
        username=_username(),
        is_admin=_is_admin(),
        statuses=[{"name": name, "color": colors.get(name, "#999")} for name in repos.lead_statuses.get_names()],
        users=sorted(repos.users.get_all()["username"].tolist()),
        branches=BRANCHES,
        tag_names=repos.contact_extras.get_all_tag_names(),
    )


# כרטיס איש הקשר המלא לפי מספר טלפון. סדר העדיפויות של המקור (מבוצע בתוסף): לקוחה ב-Arbox,
# אחרת משתמשת Arbox שאינה לקוחה (ליד/צוות/אגרגטור), אחרת ליד ב-CRM. phone לא חייב להיות כבר
# בפורמט מקומי - מנורמל כאן (ראו phone_utils.normalize_phone)
@bp.route("/lookup", methods=["GET"])
@token_required
def lookup():
    phone = _phone_or_400(request.args.get("phone"))
    repos = get_repos()
    # אותו "כרטיס לקוחה" כמו בחלונית עמוד שיחות הבוט (שם, סניף, גיל, הוראת קבע, חוב, מונה ביקורים)
    # - כדי שהתוסף והעמוד הפנימי יציגו בדיוק את אותו מידע ולא יתפצלו
    customer = _customer_info(repos, phone)

    arbox_contact = None
    if not customer["member"]:
        arbox_contact = repos.arbox_contact_cache.get_by_phone(phone)
        if arbox_contact:
            arbox_contact.update(
                full_name=f"{arbox_contact['first_name']} {arbox_contact['last_name']}".strip(),
                role_label=ARBOX_ROLE_LABELS.get(arbox_contact["role"], arbox_contact["role"]),
                branch=_branch_name(arbox_contact.get("location_id")),
                age=_age(arbox_contact["birthday"]) if arbox_contact.get("birthday") else None,
            )

    extras = repos.contact_extras
    return jsonify(
        ok=True,
        phone=phone,
        lead=customer["lead"],
        customer=customer,
        membership=customer["member"],
        arbox_contact=arbox_contact,
        status_colors=repos.lead_statuses.get_color_map(),
        branches=BRANCHES,
        recent_visits=repos.arbox_visit_cache.get_recent_by_phone(phone),
        tags=extras.get_tags(phone),
        tasks=extras.get_tasks(phone),
        activity=extras.get_activity(phone),
    )


# --- לידים ---

@bp.route("/leads", methods=["POST"])
@token_required
def create_lead():
    payload = _payload()
    phone = _phone_or_400(payload.get("phone"))
    repos = get_repos()
    statuses = repos.lead_statuses.get_names()
    branch = payload.get("branch") if payload.get("branch") in BRANCHES else BRANCHES[0]
    lead = {
        "full_name": (payload.get("full_name") or "").strip(),
        "phone": phone,
        "status": statuses[0] if statuses else "",
        "channel": LEAD_CHANNEL_DEFAULT,
        "branch": branch,
        "assigned_user": _username(),
        "notes": "",
    }
    lead_id = repos.leads.create(lead)
    repos.contact_extras.log(phone, f"נוצר ליד ב-CRM (סניף {branch})", _username())
    return jsonify(ok=True, lead_id=lead_id, lead=repos.leads.get_by_id(lead_id))


@bp.route("/leads/<int:lead_id>/status", methods=["POST"])
@token_required
def update_lead_status(lead_id):
    status = _payload().get("status", "")
    repos = get_repos()
    lead = _lead_or_404(repos, lead_id)
    if status not in repos.lead_statuses.get_names():
        return jsonify(ok=False, error="סטטוס לא קיים"), 400
    if status != lead.get("status"):
        repos.leads.update_field(lead_id, "status", status)
        repos.contact_extras.log(
            normalize_phone(lead["phone"]) or lead["phone"],
            f"סטטוס שונה: {lead.get('status') or '-'} ← {status}",
            _username(),
        )
    return jsonify(ok=True, lead=repos.leads.get_by_id(lead_id))


@bp.route("/leads/<int:lead_id>/assign", methods=["POST"])
@token_required
def assign_lead(lead_id):
    assigned_user = (_payload().get("assigned_user") or "").strip()
    repos = get_repos()
    lead = _lead_or_404(repos, lead_id)
    if assigned_user and assigned_user not in repos.users.get_all()["username"].tolist():
        return jsonify(ok=False, error="משתמשת לא קיימת"), 400
    if assigned_user != (lead.get("assigned_user") or ""):
        repos.leads.update_field(lead_id, "assigned_user", assigned_user)
        repos.contact_extras.log(
            normalize_phone(lead["phone"]) or lead["phone"],
            f"נציג/ה: {assigned_user or 'ללא'}",
            _username(),
        )
    return jsonify(ok=True, lead=repos.leads.get_by_id(lead_id))


# "הוספת הערה" - leads.notes הוא שדה טקסט בודד (לא רשימה), אז מצרפים שורה מתוארכת בראש
# הטקסט הקיים במקום להחליף אותו. פורמט תואם למה שעובדת תזהה כ"יומן הערות" גם בלי טבלה נפרדת
@bp.route("/leads/<int:lead_id>/notes", methods=["POST"])
@token_required
def add_lead_note(lead_id):
    note_text = (_payload().get("note") or "").strip()
    if not note_text:
        return jsonify(ok=False, error="הערה ריקה"), 400

    repos = get_repos()
    lead = _lead_or_404(repos, lead_id)
    timestamp = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    new_entry = f"[{timestamp} - {_username()}] {note_text}"
    existing_notes = (lead.get("notes") or "").strip()
    merged_notes = f"{new_entry}\n\n{existing_notes}" if existing_notes else new_entry

    repos.leads.update_field(lead_id, "notes", merged_notes)
    repos.contact_extras.log(normalize_phone(lead["phone"]) or lead["phone"], "נוספה הערה", _username())
    return jsonify(ok=True, lead=repos.leads.get_by_id(lead_id))


# הקישור לכרטיס של איש הקשר במערכת הניהול של Arbox (נשלף מ-Arbox בפעם הראשונה ונשמר - ראו
# get_arbox_profile_link). נקרא רק בלחיצה על הכפתור, לא בכל החלפת שיחה
@bp.route("/contacts/<phone>/arbox-profile", methods=["GET"])
@token_required
def arbox_profile_link(phone):
    link = get_arbox_profile_link(_phone_or_400(phone))
    if not link:
        return jsonify(ok=False, error="לא נמצא כרטיס ב-Arbox למספר הזה"), 404
    return jsonify(ok=True, link=link)


# --- תגיות (לפי טלפון - עובד גם ללקוחה שאין לה ליד) ---

@bp.route("/contacts/<phone>/tags", methods=["POST"])
@token_required
def add_tag(phone):
    phone = _phone_or_400(phone)
    tag = (_payload().get("tag") or "").strip()[:TAG_MAX]
    if not tag:
        return jsonify(ok=False, error="תגית ריקה"), 400
    repos = get_repos()
    if repos.contact_extras.add_tag(phone, tag):
        repos.contact_extras.log(phone, f"נוספה תגית: {tag}", _username())
    return jsonify(ok=True, tags=repos.contact_extras.get_tags(phone))


@bp.route("/contacts/<phone>/tags/remove", methods=["POST"])
@token_required
def remove_tag(phone):
    phone = _phone_or_400(phone)
    tag = (_payload().get("tag") or "").strip()
    repos = get_repos()
    if repos.contact_extras.remove_tag(phone, tag):
        repos.contact_extras.log(phone, f"הוסרה תגית: {tag}", _username())
    return jsonify(ok=True, tags=repos.contact_extras.get_tags(phone))


# --- משימות ---

@bp.route("/contacts/<phone>/tasks", methods=["POST"])
@token_required
def add_task(phone):
    phone = _phone_or_400(phone)
    payload = _payload()
    title = (payload.get("title") or "").strip()[:TASK_TITLE_MAX]
    if not title:
        return jsonify(ok=False, error="משימה ריקה"), 400
    due_date = (payload.get("due_date") or "").strip() or None
    if due_date:
        try:
            datetime.date.fromisoformat(due_date)
        except ValueError:
            return jsonify(ok=False, error="תאריך לא תקין"), 400

    repos = get_repos()
    repos.contact_extras.add_task(phone, title, due_date, _username())
    repos.contact_extras.log(phone, f"נוספה משימה: {title}", _username())
    return jsonify(ok=True, tasks=repos.contact_extras.get_tasks(phone))


@bp.route("/tasks/<int:task_id>/toggle", methods=["POST"])
@token_required
def toggle_task(task_id):
    repos = get_repos()
    task = repos.contact_extras.get_task(task_id)
    if task is None:
        abort(404)
    done = not task["done"]
    repos.contact_extras.set_task_done(task_id, done)
    repos.contact_extras.log(
        task["phone"], f"{'הושלמה' if done else 'נפתחה מחדש'} משימה: {task['title']}", _username()
    )
    return jsonify(ok=True, tasks=repos.contact_extras.get_tasks(task["phone"]))


@bp.route("/tasks/<int:task_id>/delete", methods=["POST"])
@token_required
def delete_task(task_id):
    repos = get_repos()
    task = repos.contact_extras.get_task(task_id)
    if task is None:
        abort(404)
    repos.contact_extras.delete_task(task_id)
    repos.contact_extras.log(task["phone"], f"נמחקה משימה: {task['title']}", _username())
    return jsonify(ok=True, tasks=repos.contact_extras.get_tasks(task["phone"]))


# --- תגובות מהירות (אותה ספרייה כמו בעמוד שיחות הבוט, ראו bot_conversations.py) ---

def _quick_replies_payload(repos):
    return jsonify(
        ok=True,
        replies=repos.quick_replies.get_all(),
        categories=repos.quick_replies.get_categories(),
        can_edit=_is_admin(),
    )


# עריכה של הספרייה המשותפת (יצירה/עריכה/מחיקה/מועדפים/קטגוריות) - רק למנהלת, כמו בעמוד שיחות
# הבוט (שם admin_required). עובדת רגילה יכולה להשתמש בתגובות, לא לשנות אותן לכולן
def _require_admin():
    if not _is_admin():
        abort(403)


@bp.route("/quick-replies", methods=["GET"])
@token_required
def quick_replies():
    return _quick_replies_payload(get_repos())


@bp.route("/quick-replies/save", methods=["POST"])
@token_required
def save_quick_reply():
    _require_admin()
    payload = _payload()
    title = (payload.get("title") or "").strip()[:QUICK_REPLY_TITLE_MAX]
    body = (payload.get("body") or "").strip()[:QUICK_REPLY_BODY_MAX]
    category = (payload.get("category") or "").strip()[:QUICK_REPLY_TITLE_MAX]
    favorite = bool(payload.get("favorite"))
    # התוסף שולח תמונה חדשה כ-data URL (התקשורת איתו היא JSON בלבד)
    image_data = payload.get("image_data")
    new_image = (lambda: quick_reply_images.save_data_url(image_data)) if image_data else None

    repos = get_repos()
    reply_id = payload.get("id")
    ok, error = quick_reply_images.save_reply(
        repos, int(reply_id) if reply_id else None, title, body, category, favorite,
        new_image=new_image, remove=bool(payload.get("remove_image")),
    )
    if not ok:
        return jsonify(ok=False, error=error), 400
    return _quick_replies_payload(repos)


@bp.route("/quick-replies/<int:reply_id>/favorite", methods=["POST"])
@token_required
def favorite_quick_reply(reply_id):
    _require_admin()
    repos = get_repos()
    repos.quick_replies.set_favorite(reply_id, bool(_payload().get("favorite")))
    return _quick_replies_payload(repos)


@bp.route("/quick-replies/<int:reply_id>/delete", methods=["POST"])
@token_required
def delete_quick_reply(reply_id):
    _require_admin()
    repos = get_repos()
    quick_reply_images.delete_reply(repos, reply_id)
    return _quick_replies_payload(repos)


@bp.route("/quick-replies/categories", methods=["POST"])
@token_required
def add_quick_reply_category():
    _require_admin()
    name = (_payload().get("name") or "").strip()[:QUICK_REPLY_TITLE_MAX]
    if not name:
        return jsonify(ok=False, error="צריך שם לקטגוריה"), 400
    repos = get_repos()
    repos.quick_replies.add_category(name)
    return _quick_replies_payload(repos)
