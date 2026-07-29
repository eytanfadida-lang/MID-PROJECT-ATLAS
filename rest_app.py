from db import AppointmentDB
from appointment_repository import AppointmentRepository
from availability import AvailabilityService
from lead_db import LeadDB
from lead_repository import LeadRepository
from lead_menu import LeadMenu
from customer_db import CustomerDB
from customer_repository import CustomerRepository
from invoice_repository import InvoiceRepository
from customer_menu import CustomerMenu
from id_sequence import IdSequence
from user_db import UserDB
from user_repository import UserRepository
from login_service import LoginService
from menu import Menu


def main():
    user_db = UserDB()
    user_repository = UserRepository(user_db.conn)

    current_user = LoginService(user_repository).login()
    if current_user is None:
        user_db.close()
        return

    db = AppointmentDB()
    repository = AppointmentRepository(db.conn)
    availability = AvailabilityService(repository)

    lead_db = LeadDB()
    lead_repository = LeadRepository(lead_db.conn)

    customer_db = CustomerDB()
    customer_repository = CustomerRepository(customer_db.conn)
    invoice_repository = InvoiceRepository(customer_db.conn)

    # נוצר אחרי שטבלאות appointments ו-customers כבר קיימות, כדי להיזרע נכון מהמזהים הקיימים
    id_sequence = IdSequence(db.conn)

    lead_menu = LeadMenu(lead_repository, repository, id_sequence, current_user)
    customer_menu = CustomerMenu(customer_repository, repository, invoice_repository, id_sequence, current_user)

    menu = Menu(repository, availability, lead_menu, customer_menu, id_sequence, current_user)
    menu.run()

    db.close()
    lead_db.close()
    customer_db.close()
    user_db.close()


if __name__ == "__main__":
    main()
