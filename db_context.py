import sqlite3
from types import SimpleNamespace

from flask import g

from db import AppointmentDB, DB_FILE
from appointment_repository import AppointmentRepository
from availability import AvailabilityService
from lead_db import LeadDB
from lead_repository import LeadRepository
from lead_status_repository import LeadStatusRepository
from customer_db import CustomerDB
from customer_repository import CustomerRepository
from invoice_repository import InvoiceRepository
from user_db import UserDB
from user_repository import UserRepository
from id_sequence import IdSequence


# מריצה חד-פעמית באתחול (import-time של app.py): יוצרת/ממגרת את כל הטבלאות,
# באמצעות אותה לוגיקת יצירה שכל *DB Class כבר מכיל, בלי לשנות אותם.
# בטוחה להרצה חוזרת (idempotent) - כל שלב הוא CREATE TABLE IF NOT EXISTS / ALTER מותנה / seed מותנה
def bootstrap_databases():
    for db_class in (AppointmentDB, CustomerDB, LeadDB, UserDB):
        instance = db_class()
        instance.close()

    # נוצר אחרי ש-appointments ו-customers כבר קיימות, כדי להיזרע נכון מהמזהים הקיימים (ראו id_sequence.py)
    conn = sqlite3.connect(DB_FILE)
    IdSequence(conn)
    conn.close()


# פותחת חיבור sqlite3 חדש לבקשה הנוכחית, נשמר על flask.g כדי לא לפתוח כמה פעמים באותה בקשה
def get_conn():
    if "db_conn" not in g:
        g.db_conn = sqlite3.connect(DB_FILE, timeout=10)
    return g.db_conn


# בונה את כל אובייקטי ה-Repository סביב חיבור הבקשה הנוכחית, פעם אחת לבקשה
def get_repos():
    if "repos" not in g:
        conn = get_conn()
        appointments = AppointmentRepository(conn)
        g.repos = SimpleNamespace(
            appointments=appointments,
            availability=AvailabilityService(appointments),
            leads=LeadRepository(conn),
            lead_statuses=LeadStatusRepository(conn),
            customers=CustomerRepository(conn),
            invoices=InvoiceRepository(conn),
            users=UserRepository(conn),
            id_sequence=IdSequence(conn),
        )
    return g.repos


def init_app(app):
    @app.teardown_appcontext
    def close_conn(exception):
        conn = g.pop("db_conn", None)
        if conn is not None:
            conn.close()
