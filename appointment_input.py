import datetime

BRANCHES = ["Mozkin", "Tirat Carmel"]


# אחראית על איסוף קלט מהמשתמש ועל ולידציה של הפורמט שלו
class AppointmentInput:
    # אוספת פרטי לקוח בלבד (שם, טלפון, סניף) - בשימוש בזרימת יצירת תור,
    # שבה התאריך והשעה כבר נבחרו מתוך רשימת התורים הפנויים
    @staticmethod
    def collect_client_details():
        try:
            name_of_client = input("enter your name")
            phone_client = input("enter your phone")
            name_of_store = AppointmentInput.choose_branch()
            if name_of_store is None:
                return None
            return {
                "name_of_client": name_of_client,
                "phone_client": phone_client,
                "name_of_store": name_of_store,
            }
        except Exception:
            print("error")
        return None

    # מציגה ללקוח את רשימת הסניפים ומחזירה את הסניף שנבחר
    @staticmethod
    def choose_branch():
        print("Choose a branch:")
        for i, branch in enumerate(BRANCHES, start=1):
            print(f"{i}. {branch}")

        try:
            choice = int(input("Enter your choice: "))
        except ValueError:
            print("Invalid input. Please enter a number.")
            return None

        if choice < 1 or choice > len(BRANCHES):
            print("Invalid choice.")
            return None

        return BRANCHES[choice - 1]

    # אוספת את כל שדות התור כולל תאריך ושעה שהוקלדו ידנית -
    # בשימוש בזרימת עדכון תור קיים
    @staticmethod
    def collect_fields():
        try:
            name_of_client = input("enter your name")
            phone_client = input("enter your phone")
            name_of_store = input("enter store name")
            appointment_date = datetime.datetime.strptime(input("enter date"), "%Y-%m-%d")
            appointment_time = datetime.datetime.strptime(input("what is the time?"), "%H:%M")
            return {
                "name_of_client": name_of_client,
                "phone_client": phone_client,
                "name_of_store": name_of_store,
                "appointment_date": appointment_date,
                "appointment_time": appointment_time,
            }
        except ValueError:
            print("Invalid format")
        except Exception:
            print("error")
        return None
