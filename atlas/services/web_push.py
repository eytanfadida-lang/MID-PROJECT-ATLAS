import base64
import json
import logging
import os
import re
import sqlite3
import threading
from types import SimpleNamespace

from atlas.data.db import DB_FILE
from atlas.data.repositories.arbox_member_cache_repository import ArboxMemberCacheRepository
from atlas.data.repositories.customer_bot_message_repository import CustomerBotMessageRepository
from atlas.data.repositories.push_subscription_repository import PushSubscriptionRepository
from atlas.paths import secret

logger = logging.getLogger(__name__)

# שירות התראות דחיפה (Web Push) על הודעות חדשות מלקוחות: מקבל "הודעה נכנסת" ושולח התראה לכל מכשיר
# שנרשם (ראו blueprints/push.py). עובד ישירות מול שירותי הדחיפה של הדפדפנים (גוגל/אפל/מיקרוסופט) -
# בלי שרת צד שלישי ובלי עלות. כל שליחה נעשית בתהליכון רקע כדי לא להאט את ה-webhook של וואטסאפ,
# וכל כשל בהתראות נבלע (נרשם בלוג) - התראה שנכשלה אף פעם לא צריכה לפגוע בקבלת הודעה.

# מפתח VAPID פרטי - מזהה את השרת מול שירותי הדחיפה. נוצר אוטומטית בשימוש הראשון ונשמר כקובץ סוד מקומי
# (מחוץ ל-git, ראו .gitignore). אם הקובץ נמחק - נוצר מפתח חדש והמכשירים נרשמים מחדש אוטומטית
VAPID_PRIVATE_KEY_FILE = secret(".vapid_private_key")

# כתובת מזהה שנשלחת לשירותי הדחיפה בתוך ה-VAPID (claim "sub"). בכוונה כתובת האתר ולא אימייל
# אישי - הערך הזה יוצא החוצה לגוגל/אפל. אפשר לדרוס עם משתנה סביבה VAPID_SUBJECT
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "https://eytan1985.pythonanywhere.com")

# האם להציג את תוכן ההודעה (קטע קצר) בהתראה. התראה מופיעה גם במסך נעול - אם לא רוצים שתוכן
# הודעות של לקוחות יהיה גלוי שם, אפשר לשנות ל-False ותוצג רק "הודעה חדשה" עם שם/מספר השולחת
SHOW_MESSAGE_PREVIEW = True
PREVIEW_MAX_CHARS = 90

# כמה זמן שירות הדחיפה ישמור התראה אם המכשיר כבוי/בלי רשת (שניות). הודעה ישנה יותר לא רלוונטית
NOTIFICATION_TTL_SECONDS = 6 * 3600


def _webpush_module():
    """pywebpush נטען בעצמה (lazy) - אם הספרייה עוד לא מותקנת בשרת, האתר ממשיך לעבוד כרגיל בלי התראות."""
    try:
        import pywebpush  # noqa: WPS433
        return pywebpush
    except ImportError:
        return None


def is_available():
    return _webpush_module() is not None


def _ensure_private_key():
    """מחזירה נתיב למפתח הפרטי; יוצרת אותו אם חסר (פעם אחת, בצורה אטומית כדי שכמה תהליכים לא ידרסו זה את זה)."""
    if VAPID_PRIVATE_KEY_FILE.exists():
        return VAPID_PRIVATE_KEY_FILE
    from py_vapid import Vapid

    vapid = Vapid()
    vapid.generate_keys()
    temp_path = VAPID_PRIVATE_KEY_FILE.with_name(VAPID_PRIVATE_KEY_FILE.name + f".{os.getpid()}.tmp")
    vapid.save_key(str(temp_path))
    try:
        # os.link נכשל אם היעד כבר קיים (תהליך אחר הקדים אותנו) - ואז משתמשים במפתח שלו
        os.link(temp_path, VAPID_PRIVATE_KEY_FILE)
    except FileExistsError:
        pass
    except OSError:
        # מערכות קבצים בלי hard links - נופלים להעברה רגילה
        if not VAPID_PRIVATE_KEY_FILE.exists():
            os.replace(temp_path, VAPID_PRIVATE_KEY_FILE)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return VAPID_PRIVATE_KEY_FILE


def get_public_key():
    """המפתח הציבורי בפורמט שהדפדפן מצפה לו (applicationServerKey): base64 בטוח-ל-URL בלי padding."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    vapid = Vapid.from_file(str(_ensure_private_key()))
    raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _preview_text(body, attachment_url):
    if not SHOW_MESSAGE_PREVIEW:
        return "הודעה חדשה"
    text = re.sub(r"\s+", " ", body or "").strip()
    if not text and attachment_url:
        return "📎 קובץ מצורף"
    if not text:
        return "הודעה חדשה"
    return text if len(text) <= PREVIEW_MAX_CHARS else text[: PREVIEW_MAX_CHARS - 1].rstrip() + "…"


def build_incoming_payload(phone, display_name, body, attachment_url, unread_count):
    return {
        "title": display_name or phone,
        "body": _preview_text(body, attachment_url),
        # tag: התראה חדשה מאותה שיחה מחליפה את הקודמת במקום להצטבר ערימה
        "tag": f"chat-{phone}",
        "url": f"/bot-conversations/{phone}",
        "unread": unread_count,
    }


def send_to_subscription(subscription, payload):
    """שולחת התראה למכשיר אחד. מחזירה 'ok' / 'gone' (המנוי פג - צריך למחוק) / 'error'."""
    pywebpush = _webpush_module()
    if pywebpush is None:
        return "error"
    try:
        pywebpush.webpush(
            subscription_info={
                "endpoint": subscription["endpoint"],
                "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=str(_ensure_private_key()),
            # dict חדש בכל קריאה - הספרייה מוסיפה לו שדות (aud/exp)
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=NOTIFICATION_TTL_SECONDS,
            headers={"Urgency": "high"},
            timeout=10,
        )
        return "ok"
    except pywebpush.WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            return "gone"
        logger.warning("push failed (%s): %s", status, exc)
        return "error"
    except Exception as exc:  # noqa: BLE001 - התראה שנכשלה לא אמורה להפיל כלום
        logger.warning("push failed: %s", exc)
        return "error"


def send_to_all(repos, payload):
    """שולחת לכל המנויים; מוחקת מנויים שפגו. מחזירה סיכום {sent, failed, removed}."""
    result = {"sent": 0, "failed": 0, "removed": 0}
    for subscription in repos.push_subscriptions.get_all():
        outcome = send_to_subscription(subscription, payload)
        if outcome == "ok":
            result["sent"] += 1
            repos.push_subscriptions.mark_success(subscription["endpoint"])
        elif outcome == "gone":
            result["removed"] += 1
            repos.push_subscriptions.delete_by_endpoint(subscription["endpoint"])
        else:
            result["failed"] += 1
    return result


def _notify_incoming(phone, body, attachment_url):
    # חיבור ייעודי לתהליכון (sqlite לא משתף חיבורים בין תהליכונים) ורק שלושת המאגרים הדרושים - לא get_repos()
    # המלא, שבונה כל מאגר במערכת (כולל מאגר מזהים שמאתחל את עצמו - נוצרת התנגשות בין כמה התראות במקביל)
    conn = sqlite3.connect(DB_FILE, timeout=10)
    try:
        repos = SimpleNamespace(
            push_subscriptions=PushSubscriptionRepository(conn),
            arbox_member_cache=ArboxMemberCacheRepository(conn),
            customer_bot_messages=CustomerBotMessageRepository(conn),
        )
        if repos.push_subscriptions.count() == 0:
            return
        member = repos.arbox_member_cache.get_by_phone(phone)
        name = f"{member['first_name']} {member['last_name']}".strip() if member else ""
        unread = repos.customer_bot_messages.count_unread_conversations()
        send_to_all(repos, build_incoming_payload(phone, name, body, attachment_url, unread))
    finally:
        conn.close()


def notify_incoming_async(phone, body, attachment_url=None):
    """נקראת על כל הודעה נכנסת מלקוחה (ראו incoming_listeners ב-customer_bot_message_repository)."""
    if not is_available():
        return

    def run():
        try:
            _notify_incoming(phone, body, attachment_url)
        except Exception:  # noqa: BLE001
            logger.exception("incoming-message push notification failed")

    threading.Thread(target=run, daemon=True).start()
