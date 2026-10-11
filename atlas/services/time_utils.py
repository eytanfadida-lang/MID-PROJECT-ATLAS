import datetime
from zoneinfo import ZoneInfo

# כל שעון-קיר שמוזן בטפסי האוטומציות (time_of_day, run_at, stage_at וכו') מתכוון לשעון ישראל -
# אבל datetime.datetime.now() על השרת (PythonAnywhere) הוא UTC, לא שעון ישראל. מאומת בפועל:
# הושוו חותמות זמן אמיתיות (synced_at של arbox_member_cache מול זמן ריצת ה-GitHub Action
# שיצר אותן, ו-last_run_at של אוטומציה מתוזמנת מול השעה שבה היא אמורה הייתה לרוץ) - שניהם
# תאמו UTC בדיוק, לא שעון ישראל. התוצאה: בלי ההמרה כאן, אוטומציה שהוגדרה ל-"18:30" נשלחת
# בפועל סביב 21:30 בישראל (קיץ, UTC+3) או 20:30 (חורף, UTC+2).
#
# שאר המערכת ממשיכה לאחסן/להשוות תאריכים כ-naive UTC בדיוק כמו היום (אין צורך לגעת בשום
# מקום אחר) - שתי הפונקציות כאן רק ממירות בגבול הנכון: זמן-קיר-ישראלי שהוזן בטופס -> UTC
# naive לאחסון/השוואה מול due_actions.run_after/datetime.now() הקיימים, ולהפך בשביל "מה
# התאריך/יום-בשבוע היום בישראל" (לדוחות Arbox/בדיקות weekday - ראו engine.py)
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")


def utc_now_to_israel(utc_naive_now):
    """datetime.datetime.now() של השרת (naive, בפועל UTC) -> datetime מודע לאזור-זמן בישראל."""
    return utc_naive_now.replace(tzinfo=datetime.timezone.utc).astimezone(ISRAEL_TZ)


def israel_naive_to_utc_naive(israel_naive_dt):
    """datetime נאיבי שמייצג שעון-קיר ישראלי (בדיוק כמו מה שמוזן בטופס) -> naive UTC תואם
    למה ש-datetime.datetime.now() מחזיר בשרת, כדי שהשוואות קיימות (run_after <= now()) ימשיכו
    לעבוד בלי שינוי בשום מקום אחר."""
    aware_israel = israel_naive_dt.replace(tzinfo=ISRAEL_TZ)
    return aware_israel.astimezone(datetime.timezone.utc).replace(tzinfo=None)
