from customer_input import CustomerInput
import roles


# תפריט המשנה לניהול לקוחות וחשבוניות מס: הוספה, צפייה, מחיקה, קישור תור,
# יצירת חשבונית וצפייה בהיסטוריה
class CustomerMenu:
    def __init__(self, customer_repository, appointment_repository, invoice_repository, id_sequence, current_user):
        self.customer_repository = customer_repository
        self.appointment_repository = appointment_repository
        self.invoice_repository = invoice_repository
        self.id_sequence = id_sequence
        self.current_user = current_user

    def run(self):
        while True:
            if not self._show_menu():
                break

    def _show_menu(self):
        print(
            "\nCustomers & Invoices:\n"
            "1. Add new customer\n"
            "2. Show all customers\n"
            "3. Delete customer\n"
            "4. Link appointment to customer\n"
            "5. Create invoice for customer\n"
            "6. View customer history (appointments + invoices)\n"
            "7. Purchase membership for customer\n"
            "8. Back to main menu"
        )
        try:
            choice = int(input("Enter your choice: "))
            if choice == 1:
                self._add_customer()
            elif choice == 2:
                self._list_customers()
            elif choice == 3:
                self._delete_customer()
            elif choice == 4:
                self._link_appointment()
            elif choice == 5:
                self._create_invoice()
            elif choice == 6:
                self._view_history()
            elif choice == 7:
                self._purchase_membership()
            elif choice == 8:
                return False
            else:
                print("Invalid choice.")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except Exception as e:
            print("Error:", e)
        return True

    def _add_customer(self):
        customer = CustomerInput.collect_new_customer()
        if customer is None:
            return

        customer_id = self.id_sequence.next_id()
        self.customer_repository.create(customer, customer_id)
        print(f"Customer created successfully (id: {customer_id}).")

    def _list_customers(self):
        self._print_rows(self.customer_repository.get_all(), "No customers yet.")

    # מוחקת לקוח, אך חוסמת את המחיקה אם יש לו תורים או חשבוניות משויכים
    def _delete_customer(self):
        if self.current_user["role"] != roles.ADMIN:
            print("Only an admin can delete customers.")
            return

        customer_id = self._read_id("Enter the id of the customer to delete: ")
        if customer_id is None:
            return

        if self.customer_repository.get_by_id(customer_id) is None:
            print("Customer not found.")
            return

        has_appointments = not self.appointment_repository.get_by_customer_id(customer_id).empty
        has_invoices = not self.invoice_repository.get_by_customer(customer_id).empty
        if has_appointments or has_invoices:
            print("Cannot delete: this customer has linked appointments or invoices.")
            return

        self.customer_repository.delete(customer_id)
        print("Customer deleted successfully.")

    def _link_appointment(self):
        id_client = input("Enter the appointment id (id_client) to link: ")
        if self.appointment_repository.get_by_id(id_client) is None:
            print("Appointment not found.")
            return

        customer_id = self._read_id("Enter the customer id to link to: ")
        if customer_id is None:
            return

        if self.customer_repository.get_by_id(customer_id) is None:
            print("Customer not found.")
            return

        self.appointment_repository.link_customer(id_client, customer_id)
        print("Appointment linked to customer successfully.")

    def _create_invoice(self):
        customer_id = self._read_id("Enter the customer id: ")
        if customer_id is None:
            return

        if self.customer_repository.get_by_id(customer_id) is None:
            print("Customer not found.")
            return

        amount = CustomerInput.collect_invoice_amount()
        if amount is None:
            return

        invoice_number = self.invoice_repository.create(customer_id, amount)
        print(f"Invoice created successfully (invoice number: {invoice_number}).")

    # מוכרת ללקוח אחד מתוך שלושת סוגי המנוי (מחיר קבוע לכל סוג), ויוצרת עבורו חשבונית תואמת
    def _purchase_membership(self):
        customer_id = self._read_id("Enter the customer id: ")
        if customer_id is None:
            return

        if self.customer_repository.get_by_id(customer_id) is None:
            print("Customer not found.")
            return

        plan = CustomerInput.choose_membership_plan()
        if plan is None:
            return

        plan_name, price = plan
        invoice_number = self.invoice_repository.create(customer_id, price, plan_name)
        print(f"{plan_name} purchased successfully (invoice number: {invoice_number}, amount: {price}).")

    def _view_history(self):
        customer_id = self._read_id("Enter the customer id: ")
        if customer_id is None:
            return

        if self.customer_repository.get_by_id(customer_id) is None:
            print("Customer not found.")
            return

        print("Appointments:")
        self._print_rows(
            self.appointment_repository.get_by_customer_id(customer_id),
            "No appointments for this customer.",
        )

        print("Invoices:")
        self._print_rows(
            self.invoice_repository.get_by_customer(customer_id),
            "No invoices for this customer.",
        )

    @staticmethod
    def _read_id(prompt):
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
