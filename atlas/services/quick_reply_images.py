import base64
import binascii
import re
import uuid

from atlas.paths import PROJECT_ROOT

# תמונות של "תגובות מהירות" - נשמרות כקבצים סטטיים (כמו קבצים מצורפים בשיחות), כך שגם עמוד
# השיחות וגם תוסף הוואטסאפ מורידים אותן מאותה כתובת. רק סוגי תמונה נפוצים, עד 5MB
IMAGES_DIR = PROJECT_ROOT / "atlas" / "web" / "static" / "uploads" / "quick-replies"
URL_PREFIX = "/static/uploads/quick-replies/"
MAX_BYTES = 5 * 1024 * 1024
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


class ImageError(ValueError):
    pass


def save_image(data, mime_type):
    ext = EXTENSIONS.get((mime_type or "").lower())
    if not ext:
        raise ImageError("אפשר לצרף רק תמונה (JPG, PNG, WEBP או GIF)")
    if not data:
        raise ImageError("קובץ התמונה ריק")
    if len(data) > MAX_BYTES:
        raise ImageError("התמונה גדולה מדי (עד 5MB)")
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    (IMAGES_DIR / name).write_bytes(data)
    return URL_PREFIX + name


# תמונה שהגיעה כ-data URL (מהתוסף, שמדבר עם השרת ב-JSON בלבד)
def save_data_url(data_url):
    match = re.match(r"^data:([\w/+.-]+);base64,(.*)$", data_url or "", re.S)
    if not match:
        raise ImageError("קובץ התמונה לא תקין")
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        raise ImageError("קובץ התמונה לא תקין")
    return save_image(data, match.group(1))


# מוחקת תמונה ישנה (אחרי החלפה/הסרה/מחיקת התגובה). מתעלמת מכל מה שלא נמצא בתיקייה שלנו
def delete_image(url):
    if not url or not url.startswith(URL_PREFIX):
        return
    name = url[len(URL_PREFIX):]
    if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|png|webp|gif)", name):
        return
    try:
        (IMAGES_DIR / name).unlink()
    except OSError:
        pass


# שמירת תגובה מהירה עם שינוי תמונה אופציונלי - משותף לעמוד השיחות ולתוסף. new_image: פונקציה שמחזירה
# כתובת תמונה חדשה (או None אם לא צורפה), remove: להסיר את התמונה הקיימת. מחזירה (ok, שגיאה)
def save_reply(repos, reply_id, title, body, category, favorite, new_image=None, remove=False):
    old_url = repos.quick_replies.get_image_url(reply_id) if reply_id else ""
    if reply_id and old_url is None:
        return False, "התגובה לא נמצאה"
    try:
        image_url = new_image() if new_image else None
    except ImageError as exc:
        return False, str(exc)
    final_url = image_url or ("" if remove else old_url)
    if not body and not final_url:
        return False, "צריך לכתוב את טקסט ההודעה או לצרף תמונה"
    title = title or (body.splitlines()[0][:40] if body else "תמונה")
    if reply_id:
        repos.quick_replies.update(reply_id, title, body, category, favorite)
    else:
        reply_id = repos.quick_replies.create(title, body, category, favorite)
    if final_url != old_url:
        repos.quick_replies.set_image(reply_id, final_url)
        delete_image(old_url)
    return True, None


def delete_reply(repos, reply_id):
    delete_image(repos.quick_replies.get_image_url(reply_id))
    repos.quick_replies.delete(reply_id)
