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


MAX_IMAGES = 10


# שמירת תגובה מהירה עם תמונות - משותף לעמוד השיחות ולתוסף. new_images: רשימת פונקציות, כל אחת שומרת
# תמונה חדשה ומחזירה את הכתובת שלה (נוספות בסוף); remove_urls: תמונות קיימות להסרה. מחזירה (ok, שגיאה)
def save_reply(repos, reply_id, title, body, category, favorite, new_images=(), remove_urls=()):
    old_urls = repos.quick_replies.get_image_urls(reply_id) if reply_id else []
    if reply_id and old_urls is None:
        return False, "התגובה לא נמצאה"
    kept = [u for u in old_urls if u not in set(remove_urls)]
    if len(kept) + len(new_images) > MAX_IMAGES:
        return False, f"אפשר לצרף עד {MAX_IMAGES} תמונות לתגובה"
    added = []
    try:
        for save in new_images:
            added.append(save())
    except ImageError as exc:
        for url in added:
            delete_image(url)
        return False, str(exc)
    final = kept + added
    if not body and not final:
        return False, "צריך לכתוב את טקסט ההודעה או לצרף תמונה"
    title = title or (body.splitlines()[0][:40] if body else "תמונות")
    if reply_id:
        repos.quick_replies.update(reply_id, title, body, category, favorite)
    else:
        reply_id = repos.quick_replies.create(title, body, category, favorite)
    if final != old_urls:
        repos.quick_replies.set_images(reply_id, final)
        for url in old_urls:
            if url not in final:
                delete_image(url)
    return True, None


def delete_reply(repos, reply_id):
    for url in repos.quick_replies.get_image_urls(reply_id) or []:
        delete_image(url)
    repos.quick_replies.delete(reply_id)
