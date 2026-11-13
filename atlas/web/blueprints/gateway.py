from flask import Blueprint, abort, jsonify, request

from atlas.data.context import get_repos
from atlas.data.repositories.linked_whatsapp_repository import STATUSES
from atlas.services import gateway_auth, linked_whatsapp

# ה-API שתהליך חיבור הוואטסאפ (תיקיית gateway/) מדבר איתו. לא לדפדפן ולא למשתמשים: מוגן בטוקן סודי משותף
# (gateway_auth), ופטור מאימות CSRF כמו /tasks/ (ראו validate_csrf) כי אין session. התהליך:
#   GET  /gateway/accounts            - שולף מה המנהלת ביקשה + הודעות שממתינות לשליחה (וזה גם "הדופק" שלו)
#   POST /gateway/accounts/<id>/state - מדווח סטטוס / QR / מספר מחובר
#   POST /gateway/accounts/<id>/messages - מדווח הודעות שהתקבלו (או נשלחו מהטלפון)
#   POST /gateway/accounts/<id>/receipts - מדווח עדכוני "נמסרה/נקראה"
#   POST /gateway/outbox/<id>/result  - מדווח אם שליחת הודעה מהתור הצליחה
bp = Blueprint("gateway", __name__, url_prefix="/gateway")


@bp.before_request
def require_token():
    if not gateway_auth.is_valid_header(request.headers.get("Authorization")):
        abort(401)


@bp.route("/accounts")
def accounts():
    repos = get_repos()
    repos.linked_whatsapp.touch_gateway()
    # poll_ms: כל כמה זמן התהליך אמור לפנות שוב - מהר כשיש פעילות, איטי כשהכל שקט (חוסך בקשות לשרת)
    return jsonify(
        accounts=[
            {"id": a["id"], "label": a["label"], "desired": a["desired"], "status": a["status"]}
            for a in repos.linked_whatsapp.get_all()
        ],
        outbox=repos.linked_whatsapp.take_pending(),
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
