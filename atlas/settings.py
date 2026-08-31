# קבועים עסקיים שנצרכים ישירות על ידי אפליקציית ה-Flask (app.py + blueprints).
# הועברו לכאן מהמודולים המקוריים של ה-CLI (lead_input.py / appointment_input.py /
# customer_input.py / lead_menu.py), שנמחקו לחלוטין - קוד המסך/תפריט שלהם לא היה
# בשימוש, אבל אפליקציית הווב המשיכה למשוך מהם את הקבועים האלה בלבד

# ערוצי הגעה (מקור ליד) אפשריים
CHANNELS = [
    "ערוץ ידני",
    "VIP כללי",
    "VIP 1.3.26",
    "פייסבוק",
    "Arbox",
    "Google Ads",
    "דף נחיתה",
]

# סניפים
BRANCHES = ["מוצקין", "טירת כרמל"]

# סוגי מנוי למכירה, (שם, מחיר)
MEMBERSHIP_PLANS = [
    ("מנוי זהב", 350),
    ("מנוי מאסטר", 450),
    ("VIP LIFESTYLE", 850),
]

# השדות שניתן לעדכן בליד קיים, ותוויות התצוגה שלהם
LEAD_UPDATABLE_FIELDS = [
    ("full_name", "Name"),
    ("phone", "Phone"),
    ("status", "Status"),
    ("channel", "Channel"),
    ("branch", "Branch"),
    ("assigned_user", "Assigned user"),
    ("notes", "Notes"),
]

# הסטטוס שנכתב לליד כשהוא מומר ללקוח (blueprints/leads.py: convert()).
# תוקן כאן: הערך הקודם היה "Became a client" - מחרוזת אנגלית שלא הייתה קיימת בכלל
# ברשימת הסטטוסים האמיתית בטבלה (כל שאר הסטטוסים בעברית), כך שהמרת ליד ללקוח
# הייתה כותבת סטטוס שאף סינון/צבע לא מזהה. arbox_sync.py כבר השתמש בערך הנכון
# הזה (ARBOX_CONVERTED_STATUS) כשהוא מעדכן לידים שהפכו ללקוחות דרך Arbox
CONVERTED_STATUS = "הפך ללקוח"
