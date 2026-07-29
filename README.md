# Appointment Manager

CLI אפליקציה לניהול תורים (appointments) עבור לקוחות וחנויות, מגובה ב-SQLite.

## מבנה הפרויקט

הקוד מפוצל לפי אחריות, כל מחלקה בקובץ נפרד:

| קובץ | מחלקה | אחריות |
|---|---|---|
| `db.py` | `AppointmentDB` | פתיחת חיבור ל-SQLite ויצירת הטבלה `appointments` אם לא קיימת |
| `appointment_input.py` | `AppointmentInput` | איסוף קלט מהמשתמש (שם, טלפון, חנות, ובנפרד תאריך/שעה לצורך עדכון) וולידציה של הפורמט |
| `appointment_repository.py` | `AppointmentRepository` | כל הגישה לנתונים (CRUD), מבוססת על **pandas** |
| `availability.py` | `AvailabilityService` | חישוב הימים/השעות הפנויים לשבוע הקרוב, על בסיס התורים התפוסים ב-repository |
| `menu.py` | `Menu` | לולאת התפריט הראשי ב-CLI וניתוב הבחירות של המשתמש לפעולות המתאימות (כולל מעבר לתפריט ה-CRM) |
| `lead_db.py` | `LeadDB` | פתיחת חיבור ל-SQLite ויצירת הטבלה `leads` אם לא קיימת (טבלה נפרדת מ-`appointments`) |
| `lead_input.py` | `LeadInput` | איסוף קלט ליצירת/עדכון ליד, כולל תפריטי בחירה לסטטוס ולערוץ |
| `lead_repository.py` | `LeadRepository` | כל הגישה לנתונים (CRUD) מול טבלת `leads` |
| `lead_menu.py` | `LeadMenu` | תפריט המשנה של ה-CRM (הוספה/עדכון/מחיקה/הצגה/סינון לידים) |
| `customer_db.py` | `CustomerDB` | פתיחת חיבור ל-SQLite ויצירת הטבלאות `customers` ו-`invoices` אם לא קיימות |
| `customer_input.py` | `CustomerInput` | איסוף קלט ליצירת לקוח חדש (שם/טלפון/אימייל/כתובת) וסכום חשבונית |
| `customer_repository.py` | `CustomerRepository` | כל הגישה לנתונים (CRUD) מול טבלת `customers` |
| `invoice_repository.py` | `InvoiceRepository` | יצירת חשבוניות וקריאה שלהן לפי לקוח, מול טבלת `invoices` |
| `customer_menu.py` | `CustomerMenu` | תפריט המשנה לניהול לקוחות וחשבוניות (הוספה/הצגה/מחיקה/קישור תור/חשבונית/היסטוריה) |
| `id_sequence.py` | `IdSequence` | מקצה מזהים משותפים ל-`id_client` (תורים) ול-`id` (לקוחות), כדי שלעולם לא יתנגשו |
| `password_hashing.py` | — | חישוב ואימות hash מסולסל (PBKDF2 + salt) לסיסמאות משתמשים |
| `user_db.py` | `UserDB` | פתיחת חיבור ל-SQLite ויצירת הטבלה `users` אם לא קיימת |
| `user_repository.py` | `UserRepository` | יצירת משתמשים (עם סיסמה מסולסלת) ואימות שם משתמש+סיסמה מול טבלת `users` |
| `login_service.py` | `LoginService` | זרימת ההתחברות האינטראקטיבית ב-CLI (עד 3 ניסיונות) בתחילת ההרצה |
| `roles.py` | — | קבועי התפקידים האפשריים: `admin`, `user` |
| `seed_users.py` | — | סקריפט חד-פעמי (מריצים ידנית, לא חלק מהתפריט) ליצירת חשבון admin וחשבונות משתמש רגילים |
| `rest_app.py` | — | נקודת הכניסה: דורשת התחברות, ואז מרכיבה את כל האובייקטים (תורים + CRM + לקוחות/חשבוניות) ומריצה את התפריט |

### זרימת הרצה

```
rest_app.py
  ├─ AppointmentDB()                  # פותח חיבור + יוצר טבלת appointments
  │   └─ AppointmentRepository(conn)
  │       └─ AvailabilityService(repository)
  ├─ LeadDB()                         # פותח חיבור (לאותו appointments.db) + יוצר טבלת leads
  │   └─ LeadRepository(conn)
  │       └─ LeadMenu(repository, appointment_repository)     # תפריט משנה של ה-CRM
  ├─ CustomerDB()                     # פותח חיבור (לאותו appointments.db) + יוצר טבלאות customers ו-invoices
  │   ├─ CustomerRepository(conn)
  │   └─ InvoiceRepository(conn)
  │       └─ CustomerMenu(customer_repository, appointment_repository, invoice_repository, id_sequence)   # תפריט משנה ללקוחות/חשבוניות
  ├─ IdSequence(db.conn)   # נוצר אחרי ששתי הטבלאות כבר קיימות, כדי להיזרע נכון (ראו הסבר למטה)
  └─ Menu(repository, availability, lead_menu, customer_menu, id_sequence).run()   # לולאת התפריט עד שהמשתמש בוחר "Exit"
```

## סכמת הנתונים

טבלת `appointments` (ב-`appointments.db`):

| עמודה | תיאור |
|---|---|
| `id_client` | מזהה ייחודי של התור (Primary Key) |
| `name_of_client` | שם הלקוח |
| `phone_client` | טלפון הלקוח |
| `name_of_store` | שם החנות |
| `appointment_date` | תאריך התור (`YYYY-MM-DD`) |
| `appointment_time` | שעת התור (`HH:MM`) |
| `created_datetime_stamp` | חותמת זמן של יצירת/עדכון הרשומה |
| `customer_id` | מפתח זר אופציונלי לטבלת `customers` (`NULL` כל עוד התור לא קושר ללקוח) |

טבלת `leads` (באותו קובץ `appointments.db`, לגמרי נפרדת מטבלת `appointments`):

| עמודה | תיאור |
|---|---|
| `id` | מזהה ייחודי של הליד (Primary Key, אוטומטי) |
| `full_name` | שם מלא |
| `phone` | טלפון |
| `status` | סטטוס הליד (ראה רשימה למטה) |
| `channel` | ערוץ/מקור ההפניה (ראה רשימה למטה) |
| `assigned_user` | משתמש מטפל |
| `routings_count` | מספר ניתובים (ברירת מחדל 1 ביצירה) |
| `sms_count` | מספר הודעות SMS שנשלחו (ברירת מחדל 0 ביצירה) |
| `notes` | הערות חופשיות |
| `created_datetime_stamp` | חותמת זמן יצירת הליד |
| `last_updated_datetime_stamp` | חותמת זמן העדכון האחרון |

ערכי `status` האפשריים: New, In progress, Received info about the trainings, Received info about VIP, Not relevant, Became a client.

ערכי `channel` האפשריים: Manual channel, General VIP, VIP 1.3.26, Facebook.

(תפריט ה-CRM כולו באנגלית - נמנעים מבעיית התצוגה של הערות/טקסט עברי בעורך הקוד, ראו הסבר למעלה)

## תפריט ה-CRM (ניהול לידים)

נגיש מהתפריט הראשי דרך "Manage leads (CRM)":

```
1. Add new lead
2. Update lead
3. Delete lead
4. Show all leads
5. Filter by status
6. Search by phone
7. Convert lead to client
8. Back to main menu
```

עדכון ליד עובד באותו עיקרון כמו עדכון תור: קודם בוחרים איזה שדה לשנות (Name/Phone/Status/Channel/Assigned user/Notes), רואים את הערך הנוכחי, ואז מזינים את הערך החדש (עבור Status ו-Channel מוצג תפריט בחירה קבוע).

## המרת ליד ללקוח (Convert lead to client)

פעולה שיוצרת רשומת לקוח **ישירות בטבלת `appointments`** (מזהה לקוח, שם, טלפון וסניף), ללא תאריך/שעה משויכים עדיין (`appointment_date`/`appointment_time` נשארים ריקים - `None`):

1. מזינים את מזהה הליד להמרה.
2. בוחרים סניף (Mozkin / Tirat Carmel).
3. `id_client` של הלקוח החדש נוצר אוטומטית (ראו "מזהים משותפים" למטה).
4. הליד עצמו מתעדכן אוטומטית לסטטוס "Became a client".

לאחר מכן ניתן לקבוע לו תור בפועל (תאריך/שעה) דרך "Update appointment" הרגיל בתפריט הראשי.

טבלת `customers` (באותו קובץ `appointments.db`):

| עמודה | תיאור |
|---|---|
| `id` | מזהה ייחודי של הלקוח (Primary Key, אוטומטי) |
| `name` | שם |
| `phone` | טלפון |
| `email` | אימייל |
| `address` | כתובת |

טבלת `invoices` (חשבוניות מס, קושרות ל-`customers`):

| עמודה | תיאור |
|---|---|
| `invoice_number` | מספר חשבונית ייחודי (Primary Key, אוטומטי - מספר רץ) |
| `customer_id` | מפתח זר ל-`customers` |
| `amount` | סכום החשבונית |
| `invoice_date` | תאריך יצירת החשבונית (אוטומטי - היום) |
| `membership_type` | סוג המנוי שנרכש (ראו "סוגי מנוי" למטה), או `NULL` עבור חשבונית רגילה שלא נוצרה מרכישת מנוי |

### סוגי מנוי (Membership plans)

נמכרים ללקוח דרך "Purchase membership for customer" בתפריט הלקוחות/חשבוניות. לכל סוג מחיר קבוע, ורכישה יוצרת חשבונית אוטומטית בסכום המתאים:

| סוג מנוי | מחיר |
|---|---|
| GOLD MEMBERSHIP | 350 |
| MASTER MEMBERSHIP | 450 |
| VIP LIFESTYLE | 850 |

הרשימה מוגדרת ב-`MEMBERSHIP_PLANS` בקובץ `customer_input.py`.

## תפריט ניהול לקוחות וחשבוניות (Customers & Invoices)

נגיש מהתפריט הראשי דרך "Manage customers & invoices":

```
1. Add new customer
2. Show all customers
3. Delete customer
4. Link appointment to customer
5. Create invoice for customer
6. View customer history (appointments + invoices)
7. Purchase membership for customer
8. Back to main menu
```

- **רכישת מנוי** — מזינים מזהה לקוח, בוחרים אחד משלושת סוגי המנוי (ראו "סוגי מנוי" למעלה), והמערכת יוצרת עבורו חשבונית אוטומטית במחיר הקבוע של אותו סוג.
- **קישור תור ללקוח** — פעולה נפרדת (לא חלק מ-"Create appointment" הרגיל): מזינים `id_client` של תור קיים ומזהה לקוח קיים, והתור מתעדכן עם `customer_id`.
- **יצירת חשבונית** — מזינים מזהה לקוח וסכום; מספר החשבונית ותאריך היצירה נקבעים אוטומטית.
- **היסטוריית לקוח** — מציגה את כל התורים המקושרים ואת כל החשבוניות של אותו לקוח.
- **מחיקת לקוח** — חסומה אם ללקוח יש תורים ו/או חשבוניות משויכים, כדי לא לאבד היסטוריה.

## שימוש ב-pandas ב-Repository

`AppointmentRepository` משתמש ב-pandas לכל הקריאות והכתיבה של רשומה חדשה:

- **קריאה** (`get_all`, `get_today`, `get_by_phone`, `exists`) — דרך `pd.read_sql_query`, ומחזירה `DataFrame`.
- **יצירה** (`create`) — בונה `DataFrame` של שורה אחת וכותבת אותה עם `DataFrame.to_sql(..., if_exists="append")`.
- **עדכון/מחיקה** (`update`, `delete`) — נשארו כ-SQL גולמי דרך `sqlite3`, כי pandas לא תומך ב-`UPDATE`/`DELETE` ישירות על טבלה קיימת.

## בחירת תור פנוי ביצירת תור (Create appointment)

בבחירת "Create appointment", לפני איסוף הפרטים של הלקוח, המערכת מסננת את התור הפנוי בשני שלבים, עד 6 אופציות בכל שלב:

1. **יום בשבוע** — עד 6 ימים מתוך 7 הימים הקרובים שיש בהם לפחות שעה פנויה אחת (ללא שישי-שבת).
2. **שעה** — לאחר בחירת היום, עד 6 השעות הפנויות באותו יום (מתוך 09:00–17:00, כל שעה עגולה).

- **שעות פעילות:** 09:00–18:00, סלוט מלא כל שעה עגולה.
- **זמינות:** משותפת לכל החנויות — סלוט שתפוס בחנות אחת לא מוצג כפנוי גם עבור חנות אחרת.
- רק אחרי שתי הבחירות (יום ואז שעה) ממשיכים למילוי שם/טלפון/חנות.
- `id_client` של התור החדש נוצר אוטומטית ולא מוקלד ידנית (ראו "מזהים משותפים" למטה).

## מזהים משותפים בין תורים ללקוחות (IdSequence)

`id_client` של תור חדש (ב-Create appointment, ובהמרת ליד ללקוח) ו-`id` של לקוח חדש (ב-Add new customer) **נוצרים אוטומטית משני מקורות שונים, אבל מרצף מספרים אחד ומשותף**:

- `IdSequence` שומרת רצף אוטומטי (`id_sequence` table) ומחלקת ממנו כל מזהה חדש - כך שלעולם לא ייווצרו שני מזהים זהים, גם אם אחד שייך לתור והשני ללקוח.
- בהרצה הראשונה על מסד נתונים קיים, ה-`IdSequence` סורקת את המזהים הגבוהים ביותר שכבר קיימים (הן ב-`id_client` המספריים והן ב-`id` של לקוחות) וממשיכה מהמספר שאחריהם - כך שמזהים ישנים שהוקלדו ידנית (למשל בגרסה קודמת של האפליקציה) לא יתנגשו עם מזהים חדשים.
- כתוצאה מכך, המשתמש כבר לא מקליד `id_client` ידנית ביצירת תור או בהמרת ליד ללקוח - הכל אוטומטי.

## תפריט האפליקציה (ראשי)

```
1. Create appointment
2. Update appointment
3. Delete appointment
4. Get all appointments
5. Get today's appointments
6. Get appointments by phone
7. Manage leads (CRM)
8. Manage customers & invoices
9. Exit
```

## משתמשים והרשאות (Login)

לפני שהתפריט הראשי נפתח, `rest_app.py` דורש התחברות: שם משתמש + סיסמה (הסיסמה מוקלדת עם `getpass`, ולכן לא מוצגת על המסך), עד 3 ניסיונות - אם כולם נכשלים האפליקציה נסגרת.

טבלת `users` (באותו קובץ `appointments.db`):

| עמודה | תיאור |
|---|---|
| `id` | מזהה ייחודי (Primary Key, אוטומטי) |
| `username` | שם משתמש (ייחודי) |
| `password_hash` / `salt` | הסיסמה נשמרת מסולסלת (PBKDF2-HMAC-SHA256, 200,000 איטרציות) ולעולם לא בטקסט גלוי |
| `role` | `admin` או `user` |

**הרשאות:** כל משתמש מחובר (admin או user) יכול לבצע את כל הפעולות בתפריטים - הוספה, עדכון, צפייה, חשבוניות, מנויים וכו'. **מחיקה** (של תור / ליד / לקוח) חסומה למשתמשים עם role `user`, ומתאפשרת רק ל-`admin`.

### יצירת המשתמשים הראשונים

אין דרך ליצור משתמשים דרך התפריט (כדי לא ליצור בעיית "ביצה ותרנגולת" - צריך admin כדי ליצור משתמשים, אבל אין עדיין אף משתמש). לכן יצירת החשבון הראשוני נעשית בסקריפט נפרד, מריצים פעם אחת לפני ההרצה הראשונה של האפליקציה:

```bash
python seed_users.py
```

הסקריפט מבקש קודם ליצור את חשבון ה-admin (שם משתמש + סיסמה), ולאחר מכן מאפשר להוסיף כמה שמשתמשים רגילים שרוצים (role `user`), אחד אחרי השני, עד שמזינים שם משתמש ריק. אפשר להריץ אותו שוב בכל שלב כדי להוסיף עוד משתמשים - שם משתמש שכבר קיים פשוט ידולג עליו.

## התקנה והרצה

```bash
pip install pandas
python seed_users.py   # פעם ראשונה בלבד - יצירת admin ומשתמשים רגילים
python rest_app.py
```

מריץ את הקובץ יוצר (אם לא קיים) קובץ `appointments.db` בתיקיית הפרויקט.

## רעיונות להמשך

- הוצאת פורמט הפלט של הרשומות ל-JSON מסודר (עם `indent`) כתחליף/הוספה להדפסת ה-DataFrame.
- הוספת בדיקות (tests) ל-`AppointmentRepository` ול-`AppointmentInput` בנפרד, בעזרת DB זמני (`:memory:`).
