import datetime
import json

from appointment_input import AppointmentInput
import roles

UPDATABLE_FIELDS = [
    ("name_of_client", "Name"),
    ("phone_client", "Phone"),
    ("name_of_store", "Branch"),
    ("appointment_date", "Date"),
    ("appointment_time", "Time"),
]


class Menu:
    def __init__(self, repository, availability, lead_menu, customer_menu, id_sequence, current_user):
        self.repository = repository
        self.availability = availability
        self.lead_menu = lead_menu
        self.customer_menu = customer_menu
        self.id_sequence = id_sequence
        self.current_user = current_user

    def run(self):
        while True:
            if not self._show_menu():
                break

    def _show_menu(self):
        print("1. Create_appointment\n 2. Update_appointment\n 3. Delete appointment\n 4. Get_all_appointments\n  5. Get today's appointments\n 6. Get appointments by phone\n 7. Manage leads (CRM)\n 8. Manage customers & invoices\n 9. Exit")
        try:
            choice = int(input("Enter your choice: "))
            if choice == 1:
                self._create_appointment()
            elif choice == 2:
                self._update_appointment()
            elif choice == 3:
                self._delete_appointment()
            elif choice == 4:
                self._get_all_appointments()
            elif choice == 5:
                self._get_today_appointments()
            elif choice == 6:
                self._get_phone_appointments()
            elif choice == 7:
                self.lead_menu.run()
            elif choice == 8:
                self.customer_menu.run()
            elif choice == 9:
                print("Goodbye!")
                return False
            else:
                print("Invalid choice.")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except Exception as e:
            print("Error:", e)
        return True

    def _create_appointment(self):
        slot = self._choose_slot()
        if slot is None:
            return

        details = AppointmentInput.collect_client_details()
        if details is None:
            return

        appointment_date, appointment_time = slot
        appointment = {
            "id_client": str(self.id_sequence.next_id()),
            "created_datetime_stamp": datetime.datetime.now(),
            "name_of_client": details["name_of_client"],
            "phone_client": details["phone_client"],
            "name_of_store": details["name_of_store"],
            "appointment_date": datetime.datetime.strptime(appointment_date, "%Y-%m-%d"),
            "appointment_time": datetime.datetime.strptime(appointment_time, "%H:%M"),
        }
        print(self._format_appointment(appointment))
        self.repository.create(appointment)

    def _choose_slot(self):
        day = self._choose_day()
        if day is None:
            return None

        hour = self._choose_hour(day)
        if hour is None:
            return None

        return day, hour

    def _choose_day(self):
        days = self.availability.get_available_days()
        if not days:
            print("No available days in the upcoming week.")
            return None

        print("Available days for the upcoming week:")
        for i, day in enumerate(days, start=1):
            print(f"{i}. {day}")

        try:
            choice = int(input("Choose a day number: "))
        except ValueError:
            print("Invalid input. Please enter a number.")
            return None

        if choice < 1 or choice > len(days):
            print("Invalid choice.")
            return None

        return days[choice - 1]

    def _choose_hour(self, day):
        hours = self.availability.get_available_hours(day)
        if not hours:
            print("No available times for this day.")
            return None

        print(f"Available times on {day}:")
        for i, hour in enumerate(hours, start=1):
            print(f"{i}. {hour}")

        try:
            choice = int(input("Choose a time number: "))
        except ValueError:
            print("Invalid input. Please enter a number.")
            return None

        if choice < 1 or choice > len(hours):
            print("Invalid choice.")
            return None

        return hours[choice - 1]

    def _update_appointment(self):
        id_client = input("Enter the id of the appointment to update: ")
        current = self.repository.get_by_id(id_client)
        if current is None:
            print("Appointment not found.")
            return

        field_key = self._choose_field_to_update()
        if field_key is None:
            return

        new_value = self._prompt_new_value(field_key, current[field_key])
        if new_value is None:
            return

        fields = {
            "name_of_client": current["name_of_client"],
            "phone_client": current["phone_client"],
            "name_of_store": current["name_of_store"],
            "appointment_date": (
                datetime.datetime.strptime(current["appointment_date"], "%Y-%m-%d")
                if current["appointment_date"] else None
            ),
            "appointment_time": (
                datetime.datetime.strptime(current["appointment_time"], "%H:%M")
                if current["appointment_time"] else None
            ),
        }
        fields[field_key] = new_value

        self.repository.update(id_client, fields)
        print("Appointment updated successfully.")

    # מציגה את רשימת השדות הניתנים לשינוי ומחזירה את מפתח השדה שנבחר
    def _choose_field_to_update(self):
        print("What would you like to change?")
        for i, (_, label) in enumerate(UPDATABLE_FIELDS, start=1):
            print(f"{i}. {label}")

        try:
            choice = int(input("Enter your choice: "))
        except ValueError:
            print("Invalid input. Please enter a number.")
            return None

        if choice < 1 or choice > len(UPDATABLE_FIELDS):
            print("Invalid choice.")
            return None

        return UPDATABLE_FIELDS[choice - 1][0]

    # מציגה את הערך הנוכחי של השדה שנבחר ומבקשת את הערך החדש
    def _prompt_new_value(self, field_key, current_value):
        print(f"Current value: {current_value}")
        try:
            if field_key == "name_of_store":
                return AppointmentInput.choose_branch()
            if field_key == "appointment_date":
                return datetime.datetime.strptime(input("Enter new date (YYYY-MM-DD): "), "%Y-%m-%d")
            if field_key == "appointment_time":
                return datetime.datetime.strptime(input("Enter new time (HH:MM): "), "%H:%M")
            return input("Enter new value: ")
        except ValueError:
            print("Invalid format")
            return None

    def _delete_appointment(self):
        if self.current_user["role"] != roles.ADMIN:
            print("Only an admin can delete appointments.")
            return

        id_client = input("Enter the id of the appointment to delete: ")
        if self.repository.delete(id_client):
            print("Appointment deleted successfully.")
        else:
            print("Appointment not found.")

    def _get_all_appointments(self):
        print("All appointments:")
        self._print_rows(self.repository.get_all(), "No appointments yet.")

    def _get_today_appointments(self):
        self._print_rows(self.repository.get_today(), "No appointments for today.")

    def _get_phone_appointments(self):
        phone = input("enter your phone: ")
        self._print_rows(self.repository.get_by_phone(phone), "No appointments found for this phone number.")

    @staticmethod
    def _print_rows(df, empty_message):
        if df.empty:
            print(empty_message)
            return
        print(df.to_string(index=False))

    @staticmethod
    def _format_appointment(appointment):
        printable = {
            **appointment,
            "appointment_date": appointment["appointment_date"].date().isoformat(),
            "appointment_time": appointment["appointment_time"].strftime("%H:%M"),
            "created_datetime_stamp": appointment["created_datetime_stamp"].isoformat(timespec="minutes"),
        }
        return json.dumps(printable, indent=2, ensure_ascii=False)
