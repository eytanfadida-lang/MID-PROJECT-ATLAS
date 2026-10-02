import datetime

import pandas as pd

TABLE_NAME = "invoices"


# אחראית על כל הגישה לנתונים (CRUD) מול טבלת invoices
class InvoiceRepository:
    def __init__(self, conn):
        self.conn = conn

    # יוצרת חשבונית מס חדשה עבור לקוח, עם תאריך אוטומטי (היום), ומחזירה את מספר החשבונית שנוצר
    # membership_type אופציונלי - מוזן כאשר החשבונית נוצרת עבור רכישת מנוי (ראו create_membership)
    def create(self, customer_id, amount, membership_type=None):
        invoice_date = datetime.date.today().isoformat()
        cursor = self.conn.execute(
            f"INSERT INTO {TABLE_NAME} (customer_id, amount, invoice_date, membership_type) VALUES (?, ?, ?, ?)",
            (customer_id, amount, invoice_date, membership_type),
        )
        self.conn.commit()
        return cursor.lastrowid

    # מחזירה את כל החשבוניות של לקוח נתון
    def get_by_customer(self, customer_id):
        return pd.read_sql_query(
            f"SELECT * FROM {TABLE_NAME} WHERE customer_id = ?",
            self.conn,
            params=(customer_id,),
        )
