from appointment_input import AppointmentInput
from lead_input import LeadInput
import roles

# השדות שניתן לעדכן בליד קיים, ותוויות התצוגה שלהם
LEAD_UPDATABLE_FIELDS = [
    ("full_name", "Name"),
    ("phone", "Phone"),
    ("status", "Status"),
    ("channel", "Channel"),
    ("assigned_user", "Assigned user"),
    ("notes", "Notes"),
]

CONVERTED_STATUS = "Became a client"


# תפריט המשנה של ה-CRM: הוספה, עדכון, מחיקה, הצגה, סינון והמרה ללקוח של לידים
class LeadMenu:
    def __init__(self, repository, appointment_repository, id_sequence, current_user):
        self.repository = repository
        self.appointment_repository = appointment_repository
        self.id_sequence = id_sequence
        self.current_user = current_user

    def run(self):
        while True:
            if not self._show_menu():
                break

    def _show_menu(self):
        print(
            "\nCRM - Manage leads:\n"
            "1. Add new lead\n"
            "2. Update lead\n"
            "3. Delete lead\n"
            "4. Show all leads\n"
            "5. Filter by status\n"
            "6. Search by phone\n"
            "7. Convert lead to client\n"
            "8. Back to main menu"
        )
        try:
            choice = int(input("Enter your choice: "))
            if choice == 1:
                self._add_lead()
            elif choice == 2:
                self._update_lead()
            elif choice == 3:
                self._delete_lead()
            elif choice == 4:
                self._list_all()
            elif choice == 5:
                self._filter_by_status()
            elif choice == 6:
                self._search_by_phone()
            elif choice == 7:
                self._convert_to_client()
            elif choice == 8:
                return False
            else:
                print("Invalid choice.")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except Exception as e:
            print("Error:", e)
        return True

    def _add_lead(self):
        lead = LeadInput.collect_new_lead()
        if lead is None:
            return

        lead_id = self.repository.create(lead)
        print(f"Lead created successfully (id: {lead_id}).")

    def _update_lead(self):
        lead_id = self._read_lead_id("Enter the id of the lead to update: ")
        if lead_id is None:
            return

        current = self.repository.get_by_id(lead_id)
        if current is None:
            print("Lead not found.")
            return

        field_key = self._choose_field_to_update()
        if field_key is None:
            return

        print(f"Current value: {current[field_key]}")
        new_value = self._prompt_new_value(field_key)
        if new_value is None:
            return

        self.repository.update_field(lead_id, field_key, new_value)
        print("Lead updated successfully.")

    # מציגה את רשימת השדות הניתנים לשינוי ומחזירה את מפתח השדה שנבחר
    def _choose_field_to_update(self):
        print("What would you like to change?")
        for i, (_, label) in enumerate(LEAD_UPDATABLE_FIELDS, start=1):
            print(f"{i}. {label}")

        try:
            choice = int(input("Enter your choice: "))
        except ValueError:
            print("Invalid input. Please enter a number.")
            return None

        if choice < 1 or choice > len(LEAD_UPDATABLE_FIELDS):
            print("Invalid choice.")
            return None

        return LEAD_UPDATABLE_FIELDS[choice - 1][0]

    # מבקשת את הערך החדש לשדה שנבחר - סטטוס/ערוץ מציגים תפריט בחירה, שאר השדות קלט חופשי
    def _prompt_new_value(self, field_key):
        if field_key == "status":
            return LeadInput.choose_status()
        if field_key == "channel":
            return LeadInput.choose_channel()
        return input("Enter new value: ")

    # ממירה ליד קיים ללקוח: יוצרת רשומת לקוח בטבלת appointments (ללא תור משויך עדיין)
    # ומעדכנת את סטטוס הליד ל-"Became a client"
    def _convert_to_client(self):
        lead_id = self._read_lead_id("Enter the id of the lead to convert: ")
        if lead_id is None:
            return

        lead = self.repository.get_by_id(lead_id)
        if lead is None:
            print("Lead not found.")
            return

        name_of_store = AppointmentInput.choose_branch()
        if name_of_store is None:
            return

        id_client = str(self.id_sequence.next_id())
        self.appointment_repository.create_client(
            id_client=id_client,
            name_of_client=lead["full_name"],
            phone_client=lead["phone"],
            name_of_store=name_of_store,
        )
        self.repository.update_field(lead_id, "status", CONVERTED_STATUS)
        print(f"Lead converted to client successfully (client id: {id_client}).")

    def _delete_lead(self):
        if self.current_user["role"] != roles.ADMIN:
            print("Only an admin can delete leads.")
            return

        lead_id = self._read_lead_id("Enter the id of the lead to delete: ")
        if lead_id is None:
            return

        if self.repository.delete(lead_id):
            print("Lead deleted successfully.")
        else:
            print("Lead not found.")

    def _list_all(self):
        self._print_rows(self.repository.get_all(), "No leads yet.")

    def _filter_by_status(self):
        status = LeadInput.choose_status()
        if status is None:
            return
        self._print_rows(self.repository.get_by_status(status), "No leads found with this status.")

    def _search_by_phone(self):
        phone = input("Phone: ")
        self._print_rows(self.repository.get_by_phone(phone), "No leads found for this phone number.")

    @staticmethod
    def _read_lead_id(prompt):
        try:
            return int(input(prompt))
        except ValueError:
            print("Invalid input. Please enter a number.")
            return None

    @staticmethod
    def _print_rows(df, empty_message):
        if df.empty:
            print(empty_message)
            return
        print(df.to_string(index=False))
