from flask import Blueprint, abort, jsonify, request

from atlas.data.context import get_repos
from atlas.data.repositories.linked_whatsapp_repository import STATUSES
from atlas.services import gateway_auth, linked_whatsapp
from atlas.services.phone_utils import normalize_phone

# ה-API שתהליך חיבור הוואטסאפ (תיקיית gateway/) מדבר איתו. לא לדפדפן ולא למשתמשים: מוגן בטוקן סודי משותף
# (gateway_auth), ופטור מאימות CSRF כמו /tasks/ (ראו validate_csrf) כי אין session. התהליך:
#   GET  /gateway/accounts            - שולף מה המנהלת ביקשה + הודעות שממתינות לשליחה (וזה גם "הדופק" שלו)
#   POST /gateway/accounts/<id>/state - מדווח סטטוס / QR / מספר מחובר
#   POST /gateway/accounts/<id>/messages - מדווח הודעות שהתקבלו (או נשלחו מהטלפון)
#   POST /gateway/accounts/<id>/receipts - מדווח עדכוני "נמסרה/נקראה"
#   POST /gateway/outbox/<id>/result  - מדווח אם שליחת הודעה מהתור הצליחה
#   POST /gateway/accounts/<id>/groups - מדווח את רשימת הקבוצות של החשבון
#   POST /gateway/group-jobs/<id>/result - מדווח תוצאת הוספה לקבוצה (added/already/invited/failed)
bp = Blueprint("gateway", __name__, url_prefix="/gateway")


@bp.before_request
def require_token():
    if not gateway_auth.is_valid_header(request.headers.get("Authorization")):
        abort(401)


@bp.route("/accounts")
def accounts():
    repos = get_repos()
    repos.linked_whatsapp.touch_gateway()
    for job in repos.linked_whatsapp.expire_stale_group_jobs():
        _log_group_job(repos, job, "failed", "לא התקבלה תשובה מהחיבור - ייתכן שההוספה לא בוצעה")
    # poll_ms: כל כמה זמן התהליך אמור לפנות שוב - מהר כשיש פעילות, איטי כשהכל שקט (חוסך בקשות לשרת)
    return jsonify(
        accounts=[
            {"id": a["id"], "label": a["label"], "desired": a["desired"], "status": a["status"]}
            for a in repos.linked_whatsapp.get_all()
        ],
        outbox=repos.linked_whatsapp.take_pending(),
        group_jobs=repos.linked_whatsapp.take_pending_group_jobs(),
        poll_ms=repos.linked_whatsapp.poll_interval_ms(),
    )


@bp.route("/accounts/<int:account_id>/state", methods=["POST"])
def report_state(account_id):
    repos = get_repos()
    repos.linked_whatsapp.touch_gateway()
    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    if status != "deleted" and status not in STATUSES:
        return jsonify(ok=False, error="סטטוס לא תקין"), 400
    if repos.linked_whatsapp.get(account_id) is None:
        # נמחק בינתיים בממשק - לא שגיאה, התהליך פשוט יפסיק לנהל אותו
        return jsonify(ok=True, known=False)
    try:
        repos.linked_whatsapp.apply_state(
            account_id, status,
            qr_image=payload.get("qr_image"), qr_ttl=payload.get("qr_ttl"),
            phone=payload.get("phone"), error=payload.get("error"),
        )
    except ValueError:
        return jsonify(ok=False, error="נתון לא תקין"), 400
    return jsonify(ok=True, known=True)


@bp.route("/accounts/<int:account_id>/messages", methods=["POST"])
def report_messages(account_id):
    repos = get_repos()
    repos.linked_whatsapp.touch_gateway()
    if repos.linked_whatsapp.get(account_id) is None:
        return jsonify(ok=True, known=False)
    payload = request.get_json(silent=True) or {}
    accepted, skipped = linked_whatsapp.ingest(repos, account_id, payload.get("messages"))
    return jsonify(ok=True, known=True, accepted=accepted, skipped=skipped)


@bp.route("/accounts/<int:account_id>/receipts", methods=["POST"])
def report_receipts(account_id):
    repos = get_repos()
    repos.linked_whatsapp.touch_gateway()
    payload = request.get_json(silent=True) or {}
    return jsonify(ok=True, applied=linked_whatsapp.apply_receipts(repos, payload.get("updates")))


@bp.route("/outbox/<int:outbox_id>/result", methods=["POST"])
def report_send_result(outbox_id):
    repos = get_repos()
    repos.linked_whatsapp.touch_gateway()
    payload = request.get_json(silent=True) or {}
    known = repos.linked_whatsapp.complete(
        outbox_id, ok=bool(payload.get("ok")), wamid=str(payload.get("wamid") or "")[:128] or None, error=payload.get("error")
    )
    return jsonify(ok=True, known=known)


@bp.route("/accounts/<int:account_id>/groups", methods=["POST"])
def report_groups(account_id):
    repos = get_repos()
    repos.linked_whatsapp.touch_gateway()
    if repos.linked_whatsapp.get(account_id) is None:
        return jsonify(ok=True, known=False)
    payload = request.get_json(silent=True) or {}
    groups = payload.get("groups")
    if not isinstance(groups, list):
        return jsonify(ok=False, error="רשימה לא תקינה"), 400
    repos.linked_whatsapp.replace_groups(account_id, groups[:500])
    return jsonify(ok=True, known=True)


GROUP_RESULT_LABELS = {
    "added": "נוספה לקבוצה",
    "already": "כבר חברה בקבוצה",
    "invited": "ההגדרות שלה חוסמות הוספה - נשלח לה קישור הצטרפות לקבוצה",
    "failed": "ההוספה לקבוצה נכשלה",
}


@bp.route("/group-jobs/<int:job_id>/result", methods=["POST"])
def report_group_job_result(job_id):
    repos = get_repos()
    repos.linked_whatsapp.touch_gateway()
    payload = request.get_json(silent=True) or {}
    result = payload.get("result")
    if result not in GROUP_RESULT_LABELS:
        result = "failed"
    error = payload.get("error")
    job = repos.linked_whatsapp.complete_group_job(job_id, result=result, error=error)
    if job is None:
        return jsonify(ok=True, known=False)
    _log_group_job(repos, job, result, error)
    return jsonify(ok=True, known=True)


# רושמת את התוצאה האמיתית של ההוספה ביומן "הרצות אחרונות" של האוטומציה שביקשה אותה
def _log_group_job(repos, job, result, error=None):
    if not job.get("automation_id"):
        return
    detail = GROUP_RESULT_LABELS.get(result, GROUP_RESULT_LABELS["failed"])
    if error and result == "failed":
        detail += f": {str(error)[:200]}"
    repos.automations.log_execution(
        job["automation_id"], normalize_phone(job["to_digits"]) or job["to_digits"],
        "failed" if result == "failed" else "success", "whatsapp_linked_group", detail,
        due_action_id=job["due_action_id"],
    )
