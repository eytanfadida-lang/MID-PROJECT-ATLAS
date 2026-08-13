# Available status values for a lead, as they appear in the original CRM system
STATUSES = [
    "חדש",
    "בטיפול",
    "קיבל מידע על ההדרכות",
    "קיבל מידע על VIP",
    "לא רלוונטי",
    "הפך ללקוח",
    "ליד כפול",
]

# Available channel (referral source) values for a lead
CHANNELS = [
    "ערוץ ידני",
    "VIP כללי",
    "VIP 1.3.26",
    "פייסבוק",
    "Arbox",
    "Google Ads",
    "דף נחיתה",
]


# אחראית על איסוף קלט מהמשתמש ליצירת/עדכון ליד, כולל תפריטי בחירה לסטטוס ולערוץ
class LeadInput:
    # אוספת את פרטי הליד החדש - שם, טלפון, ערוץ ומשתמש מטפל. הסטטוס ההתחלתי הוא תמיד "New"
    @staticmethod
    def collect_new_lead():
        try:
            full_name = input("Full name: ")
            phone = input("Phone: ")
            channel = LeadInput.choose_channel()
            if channel is None:
                return None
            assigned_user = input("Assigned user: ")
            notes = input("Notes (optional): ")
            return {
                "full_name": full_name,
                "phone": phone,
                "status": STATUSES[0],
                "channel": channel,
                "assigned_user": assigned_user,
                "notes": notes,
            }
        except Exception:
            print("error")
        return None

    # מציגה ללקוח/נציג את רשימת הסטטוסים ומחזירה את הסטטוס שנבחר
    @staticmethod
    def choose_status():
        return LeadInput._choose_from(STATUSES, "Choose a status:")

    # מציגה את רשימת הערוצים ומחזירה את הערוץ שנבחר
    @staticmethod
    def choose_channel():
        return LeadInput._choose_from(CHANNELS, "Choose a channel:")

    @staticmethod
    def _choose_from(options, title):
        print(title)
        for i, option in enumerate(options, start=1):
            print(f"{i}. {option}")

        try:
            choice = int(input("Enter your choice: "))
        except ValueError:
            print("Invalid input. Please enter a number.")
            return None

        if choice < 1 or choice > len(options):
            print("Invalid choice.")
            return None

        return options[choice - 1]
