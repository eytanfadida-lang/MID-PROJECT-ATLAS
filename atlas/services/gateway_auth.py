import secrets

from atlas.paths import secret

# טוקן סודי משותף בין האפליקציה לבין תהליך החיבור של הוואטסאפ (תיקיית gateway/). התהליך שולח אותו
# בכותרת Authorization: Bearer, והאפליקציה בודקת אותו ב-blueprints/gateway.py. הקובץ נוצר פעם אחת
# אוטומטית בשורש הפרויקט ואינו נשמר ב-git (ראו .gitignore); התהליך קורא את אותו קובץ
TOKEN_FILE = secret(".gateway_token")


def get_or_create_token():
    if TOKEN_FILE.exists():
        value = TOKEN_FILE.read_text().strip()
        if value:
            return value
    value = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(value)
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass  # מערכות קבצים בלי הרשאות (חלונות) - ממשיכים
    return value


def is_valid_header(authorization_header):
    """האם כותרת Authorization תקפה ('Bearer <token>'). השוואה בזמן קבוע."""
    prefix = "Bearer "
    if not authorization_header or not authorization_header.startswith(prefix):
        return False
    return secrets.compare_digest(authorization_header[len(prefix):].strip(), get_or_create_token())
