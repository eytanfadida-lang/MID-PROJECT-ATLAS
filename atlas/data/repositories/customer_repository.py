import pandas as pd

TABLE_NAME = "customers"


# אחראית על כל הגישה לנתונים (CRUD) מול טבלת customers
class CustomerRepository:
    def __init__(self, conn):
        self.conn = conn

    # יוצרת לקוח חדש עם מזהה נתון מראש (מגיע מ-IdSequence המשותף עם התורים)
    def create(self, customer, customer_id):
        self.conn.execute(
            f"INSERT INTO {TABLE_NAME} (id, name, phone, email, address) VALUES (?, ?, ?, ?, ?)",
            (customer_id, customer["name"], customer["phone"], customer["email"], customer["address"]),
        )
        self.conn.commit()

    # מחזירה את כל הלקוחות כ-DataFrame
    def get_all(self):
        return pd.read_sql_query(f"SELECT * FROM {TABLE_NAME}", self.conn)

    # מחזירה לקוח לפי מזהה, או None אם לא נמצא
    def get_by_id(self, customer_id):
        df = pd.read_sql_query(
            f"SELECT * FROM {TABLE_NAME} WHERE id = ?", self.conn, params=(customer_id,)
        )
        if df.empty:
            return None
        return df.iloc[0].to_dict()

    # מוחקת לקוח לפי מזהה, ומחזירה האם נמחקה רשומה בפועל.
    # האחריות לוודא שאין לקוח זה תורים/חשבוניות משויכים היא על הקורא (Menu)
    def delete(self, customer_id):
        cursor = self.conn.execute(f"DELETE FROM {TABLE_NAME} WHERE id = ?", (customer_id,))
        self.conn.commit()
        return cursor.rowcount > 0
