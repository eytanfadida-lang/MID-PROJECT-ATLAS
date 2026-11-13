from functools import wraps

from flask import abort, g, request

from atlas.data.context import get_repos

PREFIX = "Bearer "


# הרשאת טוקן פר-משתמש לתוסף ה-Chrome (atlas/web/blueprints/extension_api.py) - בניגוד ל-
# atlas/services/gateway_auth.py (טוקן סודי אחד משותף, בלי זיהוי משתמש), כאן כל עובדת
# מתחברת בנפרד (שם משתמש+סיסמה מול /api/extension/login) ומקבלת טוקן אישי ששמור ב-
# api_tokens (ראו atlas/data/repositories/api_token_repository.py). שם g.api_user בהצלחה
def token_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith(PREFIX):
            abort(401)
        raw_token = header[len(PREFIX):].strip()
        if not raw_token:
            abort(401)

        user = get_repos().api_tokens.get_user_by_token(raw_token)
        if user is None:
            abort(401)
        g.api_user = user
        return view(*args, **kwargs)

    return wrapped
