MEMBERSHIP_PLANS = [
    ("מנוי זהב", 350),
    ("מנוי מאסטר", 450),
    ("VIP LIFESTYLE", 850),
]


# אחראית על איסוף קלט מהמשתמש ליצירת לקוח חדש, סכום חשבונית ובחירת סוג מנוי
class CustomerInput:
    @staticmethod
    def collect_new_customer():
        try:
            name = input("Name: ")
            phone = input("Phone: ")
            email = input("Email: ")
            address = input("Address: ")
            return {
                "name": name,
                "phone": phone,
                "email": email,
                "address": address,
            }
        except Exception:
            print("error")
        return None

    @staticmethod
    def collect_invoice_amount():
        try:
            return float(input("Amount: "))
        except ValueError:
            print("Invalid amount.")
            return None

    # מציגה את סוגי המנוי הזמינים למכירה עם מחיר קבוע, ומחזירה (name, price) של הבחירה
    @staticmethod
    def choose_membership_plan():
        print("Choose a membership plan:")
        for i, (name, price) in enumerate(MEMBERSHIP_PLANS, start=1):
            print(f"{i}. {name} - {price}")

        try:
            choice = int(input("Enter your choice: "))
        except ValueError:
            print("Invalid input. Please enter a number.")
            return None

        if choice < 1 or choice > len(MEMBERSHIP_PLANS):
            print("Invalid choice.")
            return None

        return MEMBERSHIP_PLANS[choice - 1]
