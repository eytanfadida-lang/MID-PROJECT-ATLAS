import re

# מנרמל מספרי טלפון לצורה קנונית אחת, כדי שאפשר יהיה להשוות מספר שהגיע מוואטסאפ
# (E.164, למשל 972526223432) מול מה ששמור אצלנו ב-CRM (0526223432) ומול Arbox.
#
# הפורמטים שנמצאו בפועל בנתונים האמיתיים (998 לקוחות ב-Arbox + 50 לידים):
#   0526223432        - 10 ספרות, הפורמט הנפוץ
#   052-6223432       - עם מקף
#   526223432         - 9 ספרות, בלי האפס המוביל
#   +972526223432     - E.164 עם פלוס
#   972526223432      - E.164 בלי פלוס (ככה וואטסאפ שולחת)
#   \u2066052...\u2069 - עטוף בתווי כיווניות בלתי-נראים (LRI/PDI) שנדבקו בהעתקה מ-RTL
#
# הפתרון: מוחקים כל מה שאינו ספרה (זה מטפל גם במקפים, גם ברווחים, גם בתווי הכיווניות
# הבלתי-נראים), ואז מאחדים את הקידומת לצורה מקומית אחת: 0XXXXXXXXX

ISRAEL_COUNTRY_CODE = "972"
LOCAL_LENGTH = 10


def normalize_phone(phone):
    """מחזיר צורה קנונית מקומית (0526223432), או "" אם אין מספר תקין לזיהוי."""
    digits = re.sub(r"\D", "", str(phone or ""))
    if not digits:
        return ""

    # 972526223432 / +972526223432 -> 0526223432
    if digits.startswith(ISRAEL_COUNTRY_CODE):
        digits = "0" + digits[len(ISRAEL_COUNTRY_CODE):]
    # 526223432 (בלי אפס מוביל) -> 0526223432
    elif len(digits) == LOCAL_LENGTH - 1 and not digits.startswith("0"):
        digits = "0" + digits

    return digits if len(digits) == LOCAL_LENGTH else ""


def to_whatsapp_format(phone):
    """הופך לצורה שוואטסאפ מצפה לה (972526223432), או "" אם המספר לא תקין."""
    local = normalize_phone(phone)
    if not local:
        return ""
    return ISRAEL_COUNTRY_CODE + local[1:]


def same_phone(a, b):
    """האם שני מספרים הם אותו מספר, בלי קשר לפורמט שבו נשמרו."""
    normalized = normalize_phone(a)
    return bool(normalized) and normalized == normalize_phone(b)
