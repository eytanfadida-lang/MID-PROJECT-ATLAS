import json
import sqlite3

from atlas.data.db import DB_FILE

# אוטומציה ראשונה שנזרעת אם הטבלה ריקה - אישור הרשמה לשיעור ניסיון. tenant_id קבוע ל-1 כרגע
# (עסק יחיד), אבל קיים בכל הטבלאות מהיום הראשון כדי שמעבר עתידי למוצר רב-עסקים לא ידרוש שינוי סכמה
_DEFAULT_TRIAL_TEXT_TEMPLATE = (
    "היי {full_name}! 🌸 שיעור הניסיון שלך ב{session_name} אושר - "
    "{date} בשעה {start_time}, {location_name}. מחכים לך!"
)

# אוטומציית webhook אמיתית מ-Arbox (ראו atlas/web/webhooks.py, arbox_webhook) - יורה על *כל*
# הזמנת שיעור ניסיון ב-Arbox בלי קשר למקור (כולל הזמנה ידנית של הצוות, לא רק מהבוט שלנו -
# בניגוד ל-trial_booked). שמות המשתנים תואמים בדיוק ל-payload האמיתי שנלכד ואומת מול Arbox:
# name, event_name, date (DD/MM/YYYY!), time, location_name, coach
_DEFAULT_ARBOX_TRIAL_CLASS_TEXT_TEMPLATE = (
    "היי {name}! 🌸 שיעור הניסיון שלך ב{event_name} אושר - "
    "{date} בשעה {time}, {location_name}. מחכים לך!"
)

# מצב תבנית מאושרת (לא טקסט חופשי) - כי האוטומציה הזו יורה גם על הזמנות שהצוות מזין ישירות
# ב-Arbox בלי שום אינטראקציה עם הבוט, כך שהלקוחה כמעט תמיד **מחוץ** לחלון 24 השעות (ראו
# _is_within_whatsapp_window) - טקסט חופשי פשוט לא היה נשלח במקרים האלה. לא קיימת תבנית
# מתאימה בין 56 התבניות הקיימות מאפגרייד (כולן שיווקיות/לא קשורות). הגרסה הראשונה
# ("trial_class_confirmed", 5 פרמטרים צמודים בלי תיוג) נדחתה ע"י מטא (INVALID_FORMAT) -
# "trial_class_confirmed_v2" (כל שדה מתויג בשורה נפרדת) הוגשה ב-2026-10-14 במקומה - האוטומציה
# נשארת כבויה עד שהיא תאושר בפועל
_DEFAULT_ARBOX_TRIAL_CLASS_ACTION_CONFIG = {
    "mode": "template",
    "template_name": "trial_class_confirmed_v2",
    "template_language": "he",
    "param_templates": ["{name}", "{event_name}", "{date}", "{time}", "{location_name}"],
}

# אוטומציית webhook אמיתית מ-Arbox להקפאת מנוי (ראו atlas/web/webhooks.py, arbox_webhook +
# _enrich_arbox_webhook_context שם ממירה start_date/end_date מ-YYYY-MM-DD ל-DD-MM-YYYY).
# שמות המשתנים תואמים בדיוק ל-payload האמיתי שנלכד ואומת מול Arbox: first_name,
# membership_type_name, start_date, end_date. מצב תבנית מאותה סיבה כמו arbox_trial_class -
# הקפאה יכולה להיעשות ע"י הצוות ישירות ב-Arbox בלי אינטראקציה עם הבוט
_ARBOX_MEMBERSHIP_HOLD_ACTION_CONFIG = {
    "mode": "template",
    "template_name": "membership_hold_confirmed",
    "template_language": "he",
    "param_templates": ["{first_name}", "{membership_type_name}", "{start_date}", "{end_date}"],
}

# אוטומציית webhook אמיתית מ-Arbox לרכישה (ראו atlas/web/webhooks.py, arbox_webhook +
# _enrich_arbox_webhook_context שם גוזרת first_name מ-"name", כי אין שדה נפרד ב-payload).
# יורה על **כל** רכישה (גם פריט קטן בקנטינה, לא רק מנוי - מאומת מול payload אמיתי: "membership_
# type_type": "item" למוצר), ולכן {membership_type} הוא שם הפריט/המנוי הספציפי שנרכש בפועל -
# זה מה ש"מבדיל" בין מנוי למוצר בהודעה (לא שדה נפרד "מנוי/מוצר"), לפי בקשת המשתמשת
_ARBOX_PURCHASE_ACTION_CONFIG = {
    "mode": "template",
    "template_name": "purchase_confirmed",
    "template_language": "he",
    "param_templates": ["{first_name}", "{membership_type}", "{price}"],
}

# אוטומציית webhook אמיתית מ-Arbox להוראת קבע שנכשלה (credit_refusal) - name הוא שם מלא
# (כמו purchase, אין first_name נפרד ב-payload - נגזר ב-_enrich_arbox_webhook_context).
# המשתמשת בחרה הודעה פשוטה עם {first_name} בלבד, למרות שה-payload האמיתי מכיל גם amount/
# card_ends/reason/transaction_attempts_failed - נשארים זמינים ב-context למקרה שתרצה להוסיף
# אותם בעתיד, פשוט לא נמצאים ב-param_templates הנוכחי
_ARBOX_CREDIT_REFUSAL_ACTION_CONFIG = {
    "mode": "template",
    "template_name": "credit_refusal_notice",
    "template_language": "he",
    "param_templates": ["{first_name}"],
}

# קמפיין חד-פעמי: הזמנת לקוחות VIP LIFESTYLE לטיפול ניסיון ב-MATRIX ROLL (ראו שיחה עם
# המשתמשת, 2026-10-18) - לא "קהל חדש" אמיתי, רק שימוש ב-arbox_active_members הקיים עם סינון
# membership_types לארבעת הווריאנטים האמיתיים של VIP LIFESTYLE (מאומת מול הקאש המקומי -
# 2 סניפים × רגיל/הוראת קבע). schedule_type="once" בלי run_at (ראו _compute_schedule_instants
# ב-engine.py) - בכוונה, כדי שלא תישלח במקרה - המשתמשת תקבע תאריך/שעה בעצמה דרך עריכת התזמון
# לפני שתפעיל, בדיוק כמו "תפריטים - שירז" שנוצרה באותו אופן דרך הממשק
_VIP_ROLLER_TRIAL_TRIGGER_CONFIG = {
    "schedule_type": "once",
    "audience_source": "arbox_active_members",
    "membership_types": [
        'VIP LIFESTYLE - טירת כרמל', 'VIP LIFESTYLE - טירת כרמל הו"ק',
        'VIP LIFESTYLE - קרית מוצקין', 'VIP LIFESTYLE - קרית מוצקין הו"ק',
    ],
    "locations": [],
}
_VIP_ROLLER_TRIAL_ACTION_CONFIG = {
    "mode": "template",
    "template_name": "vip_roller_trial_invite",
    "template_language": "he",
    "param_templates": ["{first_name}"],
}

# אוטומציית "חזרה" למתעניינות שלא הגיעו לשיעור ניסיון (ראו arbox_trial_no_show ב-engine.py) -
# נזרעת פעם אחת לבקשת המשתמשת (2026-10-14), עם הנוסח המדויק שהיא נתנה. מצב תבנית (לא טקסט)
# מאותה סיבה כמו arbox_trial_class - קהל שכמעט תמיד מחוץ לחלון 24 השעות. "trial_no_show_winback"
# הוגשה לאישור מטא (MARKETING) באותו תאריך - נזרעת כבויה עד שתאושר ותיבדק
_TRIAL_NO_SHOW_TEMPLATE_NAME = "trial_no_show_winback"
_TRIAL_NO_SHOW_ACTION_CONFIG = {
    "mode": "template",
    "template_name": _TRIAL_NO_SHOW_TEMPLATE_NAME,
    "template_language": "he",
    "param_templates": ["{first_name}"],
}

# אוטומציית "ברכת מילסטון על נוכחות" (ראו arbox_attendance_milestone ב-engine.py) - נזרעת
# פעם אחת לבקשת המשתמשת (2026-10-16), עם הנוסח המדויק שהיא נתנה. מצב תבנית מאותה סיבה כמו
# שאר האוטומציות היומיות - שולחת למחרת (לא באותו יום), אז הלקוחה כמעט תמיד מחוץ לחלון 24
# השעות. "attendance_milestone" הוגשה לאישור מטא (MARKETING) באותו תאריך - נזרעת כבויה
# עד שתאושר ותיבדק
_ATTENDANCE_MILESTONE_TEMPLATE_NAME = "attendance_milestone"
_ATTENDANCE_MILESTONE_ACTION_CONFIG = {
    "mode": "template",
    "template_name": _ATTENDANCE_MILESTONE_TEMPLATE_NAME,
    "template_language": "he",
    "param_templates": ["{first_name}", "{class_name}", "{staff_member}", "{visit_count}"],
}

# מהגרת את 8 האוטומציות שהועתקו מאפגרייד360 (לקוחות שעזבו/מתעניינים אבודים/מתעניינים
# שהומרו) ממצב טקסט למצב תבנית, אחרי שהתבניות המקבילות הוגשו ואושרו ע"י מטא (2026-10-16) -
# אותה סיבה כמו שאר המיגרציות למעלה: קהל שכמעט תמיד מחוץ לחלון 24 השעות. (old_config,
# new_config) לכל אוטומציה - התוכן המקורי הועתק *בדיוק* מה-DB עצמו (לא הוקלד מחדש) כדי
# שההשוואה בהמשך (רק אם איש לא ערך את ההודעה) תהיה מדויקת לחלוטין. churned (14/35 ימים)
# חולקות אותו נוסח בדיוק, ולכן גם אותה תבנית - שתי הכניסות הראשונות כאן
_UPGRADE360_TEXT_TO_TEMPLATE_MIGRATIONS = [
    (
        {'mode': 'text', 'text_template': 'היי {full_name} התגעגענו😊\nשמנו לב שהמנוי שלך הסתיים לפני {days_since}, ורק רציתי להזכיר לך כמה טוב הרגשת כשהיית בתוך שגרה.\nאת חוזרת לעצמך, מקבלת אנרגיה וביטחון, והגוף מגיב מהר כשנכנסים שוב למסלול.\nאנחנו יודעות, החלק הכי קשה באימון הוא לא הסט האחרון של הסקוואטים... אלא הרגע הזה שצריך להחליט ללבוש בגדי ספורט ולצאת מהבית.\nמה את אומרת , רלוונטי שנרשום אותך לאימון השבוע?'},
        {'mode': 'template', 'template_name': 'churned_winback', 'template_language': 'he', 'param_templates': ['{full_name}', '{days_since}']},
    ),
    (
        {'mode': 'text', 'text_template': 'היי {full_name} התגעגענו😊\nשמנו לב שהמנוי שלך הסתיים לפני {days_since}, ורק רציתי להזכיר לך כמה טוב הרגשת כשהיית בתוך שגרה.\nאת חוזרת לעצמך, מקבלת אנרגיה וביטחון, והגוף מגיב מהר כשנכנסים שוב למסלול.\nאנחנו יודעות, החלק הכי קשה באימון הוא לא הסט האחרון של הסקוואטים... אלא הרגע הזה שצריך להחליט ללבוש בגדי ספורט ולצאת מהבית.\nמה את אומרת , רלוונטי שנרשום אותך לאימון השבוע?'},
        {'mode': 'template', 'template_name': 'churned_winback', 'template_language': 'he', 'param_templates': ['{full_name}', '{days_since}']},
    ),
    (
        {'mode': 'text', 'text_template': 'היי {full_name}? מה שלומך ?🥰\nראינו שהתעניינת אצלנו לאחרונה בסטודיו ולא נרשמת! לכן שולחים לך במתנה 3 כללי ברזל *לבחירת הסטודיו המושלם עבורך*🤩\n*כלל ברזל 1: יחס אישי*- יש לבחור את הסטודיו שתרגישי בו בבית! זה יגרום לך להתמיד לטווח הארוך ויהפוך את חווית האימון למהנה הרבה יותר! מקום עם מעטפת שלמה גם מעבר לאימונים שיתנו לך את כל הכלים על מנת להצליח.\n*כלל ברזל 2: מקצועיות*- לבחור את הסטודיו שבו יהיו מאמנות מקצועיות עם ידע וניסיון, שידעו להתאים את רמת הקושי באימון אלייך בצורה נכונה על מנת למקסם תוצאות ובעיקר כדי להימנע מפציעות מיותרות!\n*כלל ברזל 3: המטרות שלך*- לפני שתרשמי יש לחשוב מה המטרה שלך ?! ומה את רוצה להכניס לשגרת האימונים שלך?\nיש להירשם לסטודיו שייתן מענה על הצרכים האישיים שלך מכל הבחינות! \n*לסיכום* יש המון סטודיואים, לכל אחד יש את הייחודיות שלו ויש לבחור את המקום המושלם עבורך!\n*בהצלחה*  \nנשמח לראות אותך אצלנו 💪🏾 צוות סטודיו אפרת רוזנברג 💕'},
        {'mode': 'template', 'template_name': 'lost_lead_7d', 'template_language': 'he', 'param_templates': ['{full_name}']},
    ),
    (
        {'mode': 'text', 'text_template': 'היי {full_name} מה נשמע❤️\n*כמה פעמים רצית להתחיל להתאמן וזה לא יצא לפועל?*\nמניסיון של מעל 10 שנים בתחום הכושר אנחנו יודעים כמה קשה לעשות את הצעד הראשון ולכן רוצים לתת לך *3 טיפים* להצליח להתחיל!\n💥 *טיפ 1*:*פשוט להתחיל*- בלי לחשוב פעמיים ובלי לחכות לאחרי החגים/חופש גדול או כל תירוץ אחר! הכי פשוט שיש- להרים טלפון להירשם ולהגיע!\n💥 *טיפ 2*:*להפסיק לספר לעצמך סיפורים*- אנחנו שומעים המון את האמרות הבאות: "זה לא מתאים לי ,קודם ארזה כמה קילו ואכנס לכושר ואז ארשם לסטודיו"- ההפך הוא הנכון! נרשמים לסטודיו על מנת להשיג את הדברים הללו והסטודיו ילווה אותך יד ביד בצורה איכותית נכונה ומבוקרת!\n*טיפ 3: לא לחכות לחבר/ה*- מסכימים לגמרי שיותר כיף להתאמן עם חברים! אבל אין לתלות את התחלת התהליך שלכם בחבר/ה שלכם!\nלהיפך תתחילו בלעדיהם ותראו שהם יצטרפו אליכם במהרה!\n*אז אם עדיין לא התחלת זה הזמן*❤️'},
        {'mode': 'template', 'template_name': 'lost_lead_14d', 'template_language': 'he', 'param_templates': ['{full_name}']},
    ),
    (
        {'mode': 'text', 'text_template': 'היי {full_name}❤️\n*כמה חשוב זה לעשות ספורט ולשמור על אורח חיים בריא!*\nלכן שולחים לך *3 כללי ברזל* לראיית תוצאות והתדמה באימונים💪🏻\n💥 *כלל ברזל 1*:\nיש לקבוע את האימונים מראש! \nיש לשריין לעצמך את האימונים שיש לבצע ובנוסף להגדיר אותם ביומן האישי ממש כמו פגישה שקבעת!\nלא רואים סיבה לבטל פגישה שהיא נטו השקעה בך ובגוף שלך!\n💥 *כלל ברזל 2*-\nגיוון האימונים שמבצעים!\nיש מלא סוגים שונים של אימונים וכל אימון הוא עולם ומלואו עם יתרונות שונים, שילוב נכון של סוגי אימונים ישרת אותך לתוצאות איכותיות יותר, לגיוון שיגרום לך להתמיד לאורך זמן וגם לניהול עומסים נכון שימנע לך פציעות!\n💥 *כלל ברזל 3*:\nהצבת מטרות שאותן רוצים להשיג!\nמטרות שיתנו לך דרייב ומוטיבציה להתמיד ולהגשים אותן!\nתמיד לזכור! גם מסע ארוך מתחיל בצעד אחד קטן והגשמת מטרה אחת קטנה!\n*בהצלחה* ❤️'},
        {'mode': 'template', 'template_name': 'lost_lead_21d', 'template_language': 'he', 'param_templates': ['{full_name}']},
    ),
    (
        {'mode': 'text', 'text_template': 'היי {full_name} מה נשמע❤️\nמכיוון שהתעניינת אצלנו בעבר אנחנו נותנים במתנה *ל10 הנרשמים הראשונים עד סוף החודש חודש ראשון ב50 אחוז הנחה*🥳\nנשמח לראותך אצלנו בסטודיו וביחד אתך להשיג את כל המטרות שלך💪🏻\nבמידה ורלוונטי יש לשלוח לנו הודעה למספר הזה או להתקשר❤️'},
        {'mode': 'template', 'template_name': 'lost_lead_28d', 'template_language': 'he', 'param_templates': ['{full_name}']},
    ),
    (
        {'mode': 'text', 'text_template': 'היי {full_name} ❤️ מה שלומך?\n\n*רצינו לעצור רגע ולהגיד לך שאנחנו שמחות שבחרת בעצמך והצטרפת אלינו לסטודיו.* אנחנו יודעות שהתחלות יכולות להיות מרגשות ומאתגרות, לכן חשוב לנו שתרגישי כאן בבית מהרגע הראשון.\nיש לנו 3 טיפים חשובים:\n\n🎯*רק את מול עצמך:* אל תסתכלי לצדדים. המטרה היא להיות טובה יותר מהגרסה של עצמך מאתמול.\n🔥*אל תעצרי כשקצת תפוס:* ההתחלה מאתגרת, אבל זה סימן שהגוף משתנה. עוד רגע וזה הופך להנאה.\n🗣️*דברי איתנו:* אנחנו כאן לכל שאלה, קושי או שיתוף. יחד נגיע ליעדים שלך!.\n\nמחכות לך באימון הקרוב עם המון אהבה,\nצוות סטודיו אפרת רוזנברג 💕\n\n*נשמח שתצטרפי לקבוצת העדכונים והטיפים שלנו:*\nסניף מוצקין: https://chat.whatsapp.com/IA7DoKI3dX70CLkQUP2tLQ\nסניף טירת כרמל: https://chat.whatsapp.com/3bVaTsRYw7XJYB4d0Kqyix'},
        {'mode': 'template', 'template_name': 'converted_3d', 'template_language': 'he', 'param_templates': ['{full_name}']},
    ),
    (
        {'mode': 'text', 'text_template': 'היי {full_name}❤️\nשולחים לך 3 כללי ברזל לראיית תוצאות והתמדה באימונים בסטודיו💪🏻\n💥 *כלל ברזל 1*:\nלהשתדל לקבוע את האימונים מראש!\nלוז האימונים מעודכן תמיד באפליקציה, יש לשריין לעצמך את האימונים שהכי בא לך להגיע אליהם ובנוסף להגדיר אותם ביומן האישי ממש כמו פגישה שקבעת!\nלא רואים סיבה לבטל פגישה שהיא נטו השקעה בך ובגוף שלך!\n💥 *כלל ברזל 2*-\nגיוון האימונים אליהם נרשמים!\nהסטודיו מציע סוגים שונים של אימונים שכל אחד מהם הוא עולם ומלואו עם יתרונות שונים, שילוב נכון של סוגי האימונים ישרת אותך לתוצאות איכותיות יותר, לגיוון שיגרום לך להתמיד לאורך זמן וגם לניהול עומסים נכון שימנע לך פציעות!\n💥 *כלל ברזל 3*:\nהצבת מטרות שאותן רוצים להשיג!\nמטרות שיתנו לך דרייב ומוטיבציה להתמיד ולהגשים אותן!\nתמיד לזכור! גם מסע ארוך מתחיל בצעד אחד קטן והגשמת מטרה אחת קטנה!\n*בהצלחה* ❤️'},
        {'mode': 'template', 'template_name': 'converted_14d', 'template_language': 'he', 'param_templates': ['{full_name}']},
    ),
]


# אחראית על החיבור למסד הנתונים ועל יצירת טבלאות מנוע האוטומציות - automations (הגדרת "מתי
# לעשות מה"), automation_steps (הפעולות המסודרות של כל אוטומציה, עם השהייה אופציונלית),
# due_actions (תור הפעולות הממתינות/שבוצעו - גם פעולה מיידית עוברת דרך הטבלה הזו, לא רק
# מושהות), automation_executions (יומן ביקורת קבוע, לצפייה/דיבוג - ראו customer_bot_message_db.py
# לאותו אידיום בדיוק)
class AutomationDB:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.conn = self._connect()

    def _connect(self):
        conn = sqlite3.connect(self.db_file)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS automations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_config TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_automations_trigger ON automations(trigger_type, enabled)"
        )
        self._ensure_automations_columns(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                automation_id INTEGER NOT NULL,
                step_order INTEGER NOT NULL,
                delay_minutes INTEGER NOT NULL DEFAULT 0,
                action_type TEXT NOT NULL,
                action_config TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_automation_steps_automation ON automation_steps(automation_id)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS due_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 1,
                automation_id INTEGER NOT NULL,
                step_id INTEGER NOT NULL,
                target_phone TEXT NOT NULL,
                target_lead_id INTEGER,
                context TEXT,
                run_after TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                claimed_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_due_actions_status_run_after ON due_actions(status, run_after)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                due_action_id INTEGER,
                automation_id INTEGER NOT NULL,
                target_phone TEXT NOT NULL,
                status TEXT NOT NULL,
                channel TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            )
        """)
        self._ensure_execution_columns(conn)
        # רשימת נמענים ידנית - לאוטומציות מתוזמנות (trigger_type='scheduled', למשל סקר/תזכורת
        # תקופתית) שלא קשורות לאירוע ספציפי של לקוח/ליד בודד, ולכן אין להן "phone" שמגיע
        # מנקודת חיבור כמו trial_booked - מי שמקבל אותן נבחר ידנית מראש דרך הממשק
        conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_recipients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                automation_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                full_name TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_automation_recipients_automation "
            "ON automation_recipients(automation_id)"
        )
        # רשימת החרגה גלובלית (לא פר-אוטומציה - אותה רשימה משותפת לכל האוטומציות המתוזמנות
        # בחשבון, בהתאם לדפוס שראינו ב-Upgrade360) - מספרים שלעולם לא יקבלו שום הודעה
        # מתוזמנת, גם אם הם ברשימת הנמענים (automation_recipients) של אוטומציה כלשהי -
        # נבדקת ב-process_scheduled_automations בזמן ה"הורדה"/שליחה
        conn.execute("""
            CREATE TABLE IF NOT EXISTS global_blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 1,
                phone TEXT NOT NULL,
                full_name TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_global_blacklist_unique "
            "ON global_blacklist(tenant_id, phone)"
        )
        # היסטוריית תוכן הודעה פר-step - רשומה חדשה בכל שמירה בפועל (ראו update_step
        # ב-automation_repository.py), כדי שאפשר יהיה "לחזור" לנוסח שנשלח בעבר (למשל
        # ברשימת תפוצה כללית שמשתנה מדי שבוע - ראו list.html) בלי להקליד אותו מחדש
        conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_message_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                step_id INTEGER NOT NULL,
                text_template TEXT NOT NULL,
                saved_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_automation_message_history_step "
            "ON automation_message_history(step_id)"
        )
        self._seed_default_automation(conn)
        self._seed_arbox_trial_class_automation(conn)
        self._seed_arbox_membership_hold_automation(conn)
        self._seed_arbox_purchase_automation(conn)
        self._seed_arbox_credit_refusal_automation(conn)
        self._seed_vip_roller_trial_automation(conn)
        self._seed_trial_no_show_automation(conn)
        self._seed_trial_no_show_winback_manual_campaign(conn)
        self._seed_attendance_milestone_automation(conn)
        self._migrate_upgrade360_automations_to_templates(conn)
        return conn

    # מיגרציה קלה: מוסיפה את last_run_at אם עוד לא קיימת - מתי לאחרונה אוטומציה מתוזמנת
    # (trigger_type='scheduled') הופעלה בפועל, כדי שלא תופעל פעמיים לאותה הזדמנות (ראו
    # atlas/automations/engine.py, process_scheduled_automations)
    @staticmethod
    def _ensure_automations_columns(conn):
        columns = {row[1] for row in conn.execute("PRAGMA table_info(automations)").fetchall()}
        if "last_run_at" not in columns:
            conn.execute("ALTER TABLE automations ADD COLUMN last_run_at TEXT")

    # wamid: מזהה ההודעה שהוחזר מוואטסאפ בזמן השליחה - מפתח לקישור חזרה לעדכוני סטטוס משלוח
    # (webhook נפרד, ראו extract_status_updates ב-whatsapp/bot.py). delivery_status:
    # sent/delivered/read/failed, מתעדכן ע"י אותו webhook - None עד עדכון ראשון/להרצות ישנות
    @staticmethod
    def _ensure_execution_columns(conn):
        columns = {row[1] for row in conn.execute("PRAGMA table_info(automation_executions)").fetchall()}
        new_columns = {"wamid": "TEXT", "delivery_status": "TEXT"}
        for name, column_type in new_columns.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE automation_executions ADD COLUMN {name} {column_type}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_automation_executions_wamid ON automation_executions(wamid)"
        )

    # זורעת אוטומציה ברירת-מחדל אחת (אישור שיעור ניסיון) רק אם טבלת automations ריקה -
    # אותו אידיום בדיוק כמו DEFAULT_STATUSES ב-atlas/data/lead_db.py
    @staticmethod
    def _seed_default_automation(conn):
        import datetime

        has_rows = conn.execute("SELECT COUNT(*) FROM automations").fetchone()[0]
        if has_rows:
            return
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            "INSERT INTO automations (tenant_id, name, trigger_type, trigger_config, enabled, "
            "created_at, updated_at) VALUES (1, ?, ?, NULL, 1, ?, ?)",
            ("אישור הרשמה לשיעור ניסיון", "trial_booked", now, now),
        )
        automation_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO automation_steps (automation_id, step_order, delay_minutes, action_type, "
            "action_config) VALUES (?, 1, 0, 'send_whatsapp_message', ?)",
            (automation_id, json.dumps({"mode": "text", "text_template": _DEFAULT_TRIAL_TEXT_TEMPLATE})),
        )
        conn.commit()

    # זורעת את אוטומציית ה-webhook arbox_trial_class אם עוד לא קיימת (בדיקה לפי trigger_type
    # ספציפי, לא "הטבלה ריקה" כמו _seed_default_automation - כי trial_booked כבר קיימת אצל
    # רוב המשתמשים, אז הטבלה כבר לא ריקה). נזרעת **כבויה** (enabled=0) בכוונה - פעילה יחד
    # עם trial_booked תגרום לשתי הודעות אישור כשההזמנה דרך הבוט (ראו התוכנית/השיחה עם אפרת
    # לגבי ההחלטה אם לכבות את trial_booked הישנה) - המשתמש צריך להפעיל ידנית אחרי שמחליטים.
    # אם היא כבר קיימת - מהגרת אותה ממצב טקסט (ברירת המחדל הישנה) למצב תבנית, אבל **רק** אם
    # איש לא ערך אותה בינתיים (עדיין בדיוק הטקסט המקורי) - כדי לא לדרוס עריכה ידנית של המשתמש
    @staticmethod
    def _seed_arbox_trial_class_automation(conn):
        import datetime

        row = conn.execute(
            "SELECT id FROM automations WHERE trigger_type = 'arbox_trial_class'"
        ).fetchone()
        if row:
            automation_id = row[0]
            step_row = conn.execute(
                "SELECT id, action_config FROM automation_steps WHERE automation_id = ?",
                (automation_id,),
            ).fetchone()
            if step_row:
                step_id, action_config_json = step_row
                # משווים כ-dict מפוענח, לא כמחרוזת - ה-JSON המקורי שנשמר כאן (מהגרסה
                # הראשונה של _seed_arbox_trial_class_automation, לפני התוספת הזו) נשמר בלי
                # ensure_ascii=False (ברירת המחדל), אז מופיע ב-DB עם \uXXXX ולא עברית
                # גולמית - השוואת מחרוזות ישירה מול json.dumps(..., ensure_ascii=False) החדש
                # שלנו **אף פעם לא הייתה תואמת**, והמיגרציה לא רצה בפועל על אף התקנה קיימת
                # (התגלה אחרי שבדקנו ישירות מול פרודקשן וראינו שהיא נשארה בלי שינוי)
                try:
                    current_config = json.loads(action_config_json)
                except (ValueError, TypeError):
                    current_config = None
                unmigrated_text_default = {"mode": "text", "text_template": _DEFAULT_ARBOX_TRIAL_CLASS_TEXT_TEMPLATE}
                # "trial_class_confirmed" (בלי _v2) נדחתה ע"י מטא (INVALID_FORMAT) אחרי
                # שהמיגרציה הראשונה הזו כבר רצה על חלק מהמשתמשים - מהגרים גם אותם לגרסה
                # החדשה, שוב רק אם איש לא ערך את הפרמטרים בינתיים
                rejected_template_default = dict(
                    _DEFAULT_ARBOX_TRIAL_CLASS_ACTION_CONFIG, template_name="trial_class_confirmed"
                )
                if current_config in (unmigrated_text_default, rejected_template_default):
                    conn.execute(
                        "UPDATE automation_steps SET action_config = ? WHERE id = ?",
                        (json.dumps(_DEFAULT_ARBOX_TRIAL_CLASS_ACTION_CONFIG, ensure_ascii=False), step_id),
                    )
                    conn.commit()
            return
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            "INSERT INTO automations (tenant_id, name, trigger_type, trigger_config, enabled, "
            "created_at, updated_at) VALUES (1, ?, ?, NULL, 0, ?, ?)",
            ("אישור שיעור ניסיון (Arbox webhook)", "arbox_trial_class", now, now),
        )
        automation_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO automation_steps (automation_id, step_order, delay_minutes, action_type, "
            "action_config) VALUES (?, 1, 0, 'send_whatsapp_message', ?)",
            (automation_id, json.dumps(_DEFAULT_ARBOX_TRIAL_CLASS_ACTION_CONFIG, ensure_ascii=False)),
        )
        conn.commit()

    # זורעת פעם אחת את אוטומציית webhook הקפאת מנוי (ראו _ARBOX_MEMBERSHIP_HOLD_ACTION_CONFIG
    # למעלה) - אותו דפוס בדיוק כמו _seed_arbox_trial_class_automation (trigger_type ייעודי,
    # לא נבדקת/נזרעת דרך trigger_config.audience_source)
    @staticmethod
    def _seed_arbox_membership_hold_automation(conn):
        import datetime

        exists = conn.execute(
            "SELECT 1 FROM automations WHERE trigger_type = 'arbox_membership_hold'"
        ).fetchone()
        if exists:
            return
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            "INSERT INTO automations (tenant_id, name, trigger_type, trigger_config, enabled, "
            "created_at, updated_at) VALUES (1, ?, ?, NULL, 0, ?, ?)",
            ("אישור הקפאת מנוי (Arbox webhook)", "arbox_membership_hold", now, now),
        )
        automation_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO automation_steps (automation_id, step_order, delay_minutes, action_type, "
            "action_config) VALUES (?, 1, 0, 'send_whatsapp_message', ?)",
            (automation_id, json.dumps(_ARBOX_MEMBERSHIP_HOLD_ACTION_CONFIG, ensure_ascii=False)),
        )
        conn.commit()

    # זורעת פעם אחת את אוטומציית webhook הרכישה (ראו _ARBOX_PURCHASE_ACTION_CONFIG למעלה) -
    # אותו דפוס בדיוק כמו _seed_arbox_membership_hold_automation
    @staticmethod
    def _seed_arbox_purchase_automation(conn):
        import datetime

        exists = conn.execute(
            "SELECT 1 FROM automations WHERE trigger_type = 'arbox_purchase'"
        ).fetchone()
        if exists:
            return
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            "INSERT INTO automations (tenant_id, name, trigger_type, trigger_config, enabled, "
            "created_at, updated_at) VALUES (1, ?, ?, NULL, 0, ?, ?)",
            ("אישור רכישה (Arbox webhook)", "arbox_purchase", now, now),
        )
        automation_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO automation_steps (automation_id, step_order, delay_minutes, action_type, "
            "action_config) VALUES (?, 1, 0, 'send_whatsapp_message', ?)",
            (automation_id, json.dumps(_ARBOX_PURCHASE_ACTION_CONFIG, ensure_ascii=False)),
        )
        conn.commit()

    # זורעת פעם אחת את אוטומציית webhook הוראת הקבע שנכשלה (ראו _ARBOX_CREDIT_REFUSAL_ACTION_
    # CONFIG למעלה) - אותו דפוס בדיוק כמו שאר אוטומציות ה-webhook
    @staticmethod
    def _seed_arbox_credit_refusal_automation(conn):
        import datetime

        exists = conn.execute(
            "SELECT 1 FROM automations WHERE trigger_type = 'arbox_credit_refusal'"
        ).fetchone()
        if exists:
            return
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            "INSERT INTO automations (tenant_id, name, trigger_type, trigger_config, enabled, "
            "created_at, updated_at) VALUES (1, ?, ?, NULL, 0, ?, ?)",
            ("הודעה על הוראת קבע שנכשלה (Arbox webhook)", "arbox_credit_refusal", now, now),
        )
        automation_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO automation_steps (automation_id, step_order, delay_minutes, action_type, "
            "action_config) VALUES (?, 1, 0, 'send_whatsapp_message', ?)",
            (automation_id, json.dumps(_ARBOX_CREDIT_REFUSAL_ACTION_CONFIG, ensure_ascii=False)),
        )
        conn.commit()

    # זורעת פעם אחת את קמפיין הפינוק ל-VIP LIFESTYLE (ראו _VIP_ROLLER_TRIAL_*_CONFIG למעלה).
    # בדיקת קיום לפי שם (לא audience_source - "arbox_active_members" כבר משותף לאוטומציות
    # אחרות, כמו "תפריטים - שירז") - קמפיין חד-פעמי, לא "קהל" כללי לזיהוי
    @staticmethod
    def _seed_vip_roller_trial_automation(conn):
        import datetime

        exists = conn.execute(
            "SELECT 1 FROM automations WHERE name = ?", ("פינוק VIP - טיפול ניסיון רולר",)
        ).fetchone()
        if exists:
            return
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            "INSERT INTO automations (tenant_id, name, trigger_type, trigger_config, enabled, "
            "created_at, updated_at) VALUES (1, ?, 'scheduled', ?, 0, ?, ?)",
            ("פינוק VIP - טיפול ניסיון רולר", json.dumps(_VIP_ROLLER_TRIAL_TRIGGER_CONFIG, ensure_ascii=False), now, now),
        )
        automation_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO automation_steps (automation_id, step_order, delay_minutes, action_type, "
            "action_config) VALUES (?, 1, 0, 'send_whatsapp_message', ?)",
            (automation_id, json.dumps(_VIP_ROLLER_TRIAL_ACTION_CONFIG, ensure_ascii=False)),
        )
        conn.commit()

    # זורעת פעם אחת את אוטומציית "לא הגיעו לשיעור ניסיון" (ראו _TRIAL_NO_SHOW_ACTION_CONFIG
    # למעלה) - בדיקת קיום לפי audience_source בתוך trigger_config (לא trigger_type, כי זו
    # trigger_type="scheduled" רגילה כמו כל קהל דינמי אחר, לא סוג ייעודי כמו arbox_trial_class)
    @staticmethod
    def _seed_trial_no_show_automation(conn):
        import datetime

        rows = conn.execute(
            "SELECT trigger_config FROM automations WHERE trigger_type = 'scheduled'"
        ).fetchall()
        for (trigger_config_json,) in rows:
            try:
                if json.loads(trigger_config_json or "{}").get("audience_source") == "arbox_trial_no_show":
                    return
            except (ValueError, TypeError):
                continue

        now = datetime.datetime.now().isoformat(timespec="seconds")
        trigger_config = {
            "schedule_type": "daily", "time_of_day": "09:00",
            "audience_source": "arbox_trial_no_show", "window_days": 90, "resend_cooldown_days": 90,
        }
        cursor = conn.execute(
            "INSERT INTO automations (tenant_id, name, trigger_type, trigger_config, enabled, "
            "created_at, updated_at) VALUES (1, ?, 'scheduled', ?, 0, ?, ?)",
            ("מתעניינות שלא הגיעו לניסיון - חזרה", json.dumps(trigger_config, ensure_ascii=False), now, now),
        )
        automation_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO automation_steps (automation_id, step_order, delay_minutes, action_type, "
            "action_config) VALUES (?, 1, 0, 'send_whatsapp_message', ?)",
            (automation_id, json.dumps(_TRIAL_NO_SHOW_ACTION_CONFIG, ensure_ascii=False)),
        )
        conn.commit()

    # זורעת פעם אחת קמפיין חד-פעמי (לבקשת המשתמשת, 2026-10-19) לרשימה ידנית וקבועה של 42
    # מתעניינות שלא הגיעו לשיעור/טיפול ניסיון ב-3 החודשים האחרונים (21/07-19/10), **לא**
    # כולל מי שהניסיון האחרון שלהן היה ב-3 הימים האחרונים (16-19/10, הוחרגו במפורש לבקשתה).
    # נוסח אישי משלה (לא נוסח ה-trial_no_show_winback הקיים) - הוגש כתבנית חדשה "trial_no_
    # show_invite" לאישור מטא (MARKETING) ב-19/10, ממתינה לאישור (PENDING) בזמן הזריעה הזו.
    # רשימה ידנית קפואה (automation_recipients), לא audience_source דינמי, כי זה קמפיין
    # חד-פעמי לרשימה שסוננה ידנית, לא ריצה חוזרת. בדיקת קיום לפי שם (קמפיין ספציפי, לא קהל כללי)
    @staticmethod
    def _seed_trial_no_show_winback_manual_campaign(conn):
        import datetime

        name = "חזרה לניסיון - שליחה ידנית 19.10.26"
        exists = conn.execute("SELECT 1 FROM automations WHERE name = ?", (name,)).fetchone()
        if exists:
            return

        recipients = [
            ("0542688309", "דלית אוסטר"),
            ("0533411220", "מרים עווד"),
            ("0504000741", "שילת אטיאס"),
            ("0525707812", "לירון בנטוב"),
            ("0508253813", "ליטל שני"),
            ("0508331775", "סטלה בייצר"),
            ("0542601242", "מלי שרבקוב"),
            ("0506204297", "שלומית יפתח"),
            ("0508445561", "סמדר פז"),
            ("0527333413", "ענבר"),
            ("0525833395", "לורין אלוז"),
            ("0548313830", "נטלי כהן"),
            ("0524820380", "אורלי בן אורי"),
            ("0527525782", "הדס חיה הרוש"),
            ("0547703889", "מלי יהודה"),
            ("0527220212", "מורן אסף"),
            ("0526663062", "אמה יהושוע"),
            ("0507640412", "איריס מרקוביץ"),
            ("0523060566", "שרית אלקובי"),
            ("0545601743", "אור סלמן"),
            ("0549900123", "סברינה אסאדו"),
            ("0527567672", "ליה דימטרייב"),
            ("0542685528", "שחף אוברס"),
            ("0543411068", "תהילה שושן"),
            ("0528162451", "חגית אלמליח"),
            ("0529536178", "צופית פניוילוב"),
            ("0544349755", "מישל גנרלוב"),
            ("0529579145", "אגם סוויסה"),
            ("0508789171", "אלמוג תוכמה"),
            ("0537337879", "שירן סיסו"),
            ("0528985258", "שיראל סויסה"),
            ("0525824646", "נעמי"),
            ("0584267188", "עינב שגב"),
            ("0526140219", "Maytehila"),
            ("0505802662", "עדי אליאנה גביש"),
            ("0523728558", "אתי בן שטרית"),
            ("0527365117", "מיטל בר סיני"),
            ("0542815833", "לימור אנקרי"),
            ("0526265132", "קרן לייבל"),
            ("0549912838", "לימור ברבר"),
            ("0529929199", "מאור שיטרית"),
            ("0528308846", "אורי חלי"),
        ]

        action_config = {
            "mode": "template",
            "template_name": "trial_no_show_invite",
            "template_language": "he",
            "param_templates": ["{first_name}"],
        }
        now = datetime.datetime.now().isoformat(timespec="seconds")
        trigger_config = {"schedule_type": "once", "run_at": "2026-10-19T18:40"}
        cursor = conn.execute(
            "INSERT INTO automations (tenant_id, name, trigger_type, trigger_config, enabled, "
            "created_at, updated_at) VALUES (1, ?, 'scheduled', ?, 0, ?, ?)",
            (name, json.dumps(trigger_config, ensure_ascii=False), now, now),
        )
        automation_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO automation_steps (automation_id, step_order, delay_minutes, action_type, "
            "action_config) VALUES (?, 1, 0, 'send_whatsapp_message', ?)",
            (automation_id, json.dumps(action_config, ensure_ascii=False)),
        )
        for phone, full_name in recipients:
            conn.execute(
                "INSERT INTO automation_recipients (automation_id, phone, full_name, created_at) "
                "VALUES (?, ?, ?, ?)",
                (automation_id, phone, full_name, now),
            )
        conn.commit()

    # זורעת פעם אחת את אוטומציית "ברכת מילסטון על נוכחות" (ראו _ATTENDANCE_MILESTONE_
    # ACTION_CONFIG למעלה) - אותו דפוס בדיוק כמו _seed_trial_no_show_automation
    @staticmethod
    def _seed_attendance_milestone_automation(conn):
        import datetime

        rows = conn.execute(
            "SELECT trigger_config FROM automations WHERE trigger_type = 'scheduled'"
        ).fetchall()
        for (trigger_config_json,) in rows:
            try:
                if json.loads(trigger_config_json or "{}").get("audience_source") == "arbox_attendance_milestone":
                    return
            except (ValueError, TypeError):
                continue

        now = datetime.datetime.now().isoformat(timespec="seconds")
        trigger_config = {
            "schedule_type": "daily", "time_of_day": "09:00",
            "audience_source": "arbox_attendance_milestone", "milestone_interval": 10,
        }
        cursor = conn.execute(
            "INSERT INTO automations (tenant_id, name, trigger_type, trigger_config, enabled, "
            "created_at, updated_at) VALUES (1, ?, 'scheduled', ?, 0, ?, ?)",
            ("ברכת מילסטון על נוכחות", json.dumps(trigger_config, ensure_ascii=False), now, now),
        )
        automation_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO automation_steps (automation_id, step_order, delay_minutes, action_type, "
            "action_config) VALUES (?, 1, 0, 'send_whatsapp_message', ?)",
            (automation_id, json.dumps(_ATTENDANCE_MILESTONE_ACTION_CONFIG, ensure_ascii=False)),
        )
        conn.commit()

    # מיישמת את _UPGRADE360_TEXT_TO_TEMPLATE_MIGRATIONS - סורקת את כל האוטומציות המתוזמנות
    # הקיימות, ומחליפה action_config רק לשורה שתוכנה תואם *בדיוק* לטקסט המקורי הלא-ערוך (אותו
    # עיקרון כמו שאר המיגרציות למעלה - משווה dict מפוענח, לא מחרוזת גולמית, כדי לא להיתקע
    # שוב על ensure_ascii). לא תלויה ב-id/שם - עובדת על כל אוטומציה מתאימה שנמצא, כולל אם
    # נוספו/שוכפלו עוד כאלה בעתיד
    @staticmethod
    def _migrate_upgrade360_automations_to_templates(conn):
        rows = conn.execute(
            "SELECT s.id, s.action_config FROM automation_steps s "
            "JOIN automations a ON a.id = s.automation_id WHERE a.trigger_type = 'scheduled'"
        ).fetchall()
        for step_id, action_config_json in rows:
            try:
                current_config = json.loads(action_config_json)
            except (ValueError, TypeError):
                continue
            for old_config, new_config in _UPGRADE360_TEXT_TO_TEMPLATE_MIGRATIONS:
                if current_config == old_config:
                    conn.execute(
                        "UPDATE automation_steps SET action_config = ? WHERE id = ?",
                        (json.dumps(new_config, ensure_ascii=False), step_id),
                    )
                    conn.commit()
                    break

    def close(self):
        self.conn.close()
