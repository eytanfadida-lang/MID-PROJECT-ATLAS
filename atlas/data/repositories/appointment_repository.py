import datetime
import sqlite3

import pandas as pd

TABLE_NAME = "appointments"


# אחראית על כל הגישה לנתונים (CRUD) מול טבלת appointments, מבוססת על pandas
class AppointmentRepository:
    def __init__(self, conn):
        self.conn = conn

    # בודקת האם כבר קיים תור עם מזהה הלקוח הנתון
    def exists(self, id_client):
        df = pd.read_sql_query(
            f"SELECT id_client FROM {TABLE_NAME} WHERE id_client = ?",
            self.conn,
            params=(id_client,),
        )
        return not df.empty

    # יוצרת רשומת תור חדשה בטבלה
    def create(self, appointment):
        row = pd.DataFrame([{
            "id_client": appointment["id_client"],
            "name_of_client": appointment["name_of_client"],
            "phone_client": appointment["phone_client"],
            "name_of_store": appointment["name_of_store"],
            "appointment_date": appointment["appointment_date"].date().isoformat(),
            "appointment_time": appointment["appointment_time"].strftime("%H:%M"),
            "created_datetime_stamp": appointment["created_datetime_stamp"].isoformat(timespec="minutes"),
        }])
        try:
            row.to_sql(TABLE_NAME, self.conn, if_exists="append", index=False)
        except sqlite3.IntegrityError:
            print("An appointment with this id already exists.")

    # יוצרת רשומת לקוח חדשה ללא תור משויך (ללא תאריך/שעה) - למשל בהמרת ליד ללקוח
    def create_client(self, id_client, name_of_client, phone_client, name_of_store):
        row = pd.DataFrame([{
            "id_client": id_client,
            "name_of_client": name_of_client,
            "phone_client": phone_client,
            "name_of_store": name_of_store,
            "appointment_date": None,
            "appointment_time": None,
            "created_datetime_stamp": datetime.datetime.now().isoformat(timespec="minutes"),
        }])
        try:
            row.to_sql(TABLE_NAME, self.conn, if_exists="append", index=False)
        except sqlite3.IntegrityError:
            print("A client with this id already exists.")

    # מעדכנת תור קיים לפי מזהה הלקוח, ומרעננת את חותמת הזמן.
    # appointment_date/appointment_time יכולים להיות None (לקוח שעדיין ללא תור משויך)
    def update(self, id_client, fields):
        appointment_date = fields["appointment_date"]
        appointment_time = fields["appointment_time"]
        self.conn.execute(
            f"UPDATE {TABLE_NAME} SET name_of_client = ?, phone_client = ?, name_of_store = ?, "
            "appointment_date = ?, appointment_time = ?, created_datetime_stamp = ? WHERE id_client = ?",
            (
                fields["name_of_client"],
                fields["phone_client"],
                fields["name_of_store"],
                appointment_date.date().isoformat() if appointment_date else None,
                appointment_time.strftime("%H:%M") if appointment_time else None,
                datetime.datetime.now().isoformat(timespec="minutes"),
                id_client,
            ),
        )
        self.conn.commit()

    # מחזירה את פרטי התור הקיים לפי מזהה לקוח, או None אם לא נמצא.
    # ערכי NULL (למשל appointment_date/time של לקוח ללא תור עדיין) מוחזרים כ-None ולא כ-NaN
    def get_by_id(self, id_client):
        df = pd.read_sql_query(
            f"SELECT * FROM {TABLE_NAME} WHERE id_client = ?",
            self.conn,
            params=(id_client,),
        )
        if df.empty:
            return None
        row = df.iloc[0]
        return row.where(pd.notna(row), None).to_dict()

    # מוחקת תור לפי מזהה לקוח, ומחזירה האם נמחקה רשומה בפועל
    def delete(self, id_client):
        cursor = self.conn.execute(f"DELETE FROM {TABLE_NAME} WHERE id_client = ?", (id_client,))
        self.conn.commit()
        return cursor.rowcount > 0

    # מחזירה את כל התורים כ-DataFrame
    def get_all(self):
        return pd.read_sql_query(f"SELECT * FROM {TABLE_NAME}", self.conn)

    # מחזירה את התורים של היום הנוכחי
    def get_today(self):
        today = datetime.datetime.now().date().isoformat()
        return pd.read_sql_query(
            f"SELECT * FROM {TABLE_NAME} WHERE appointment_date = ?",
            self.conn,
            params=(today,),
        )

    # מחזירה את התורים לפי מספר טלפון של לקוח
    def get_by_phone(self, phone):
        return pd.read_sql_query(
            f"SELECT * FROM {TABLE_NAME} WHERE phone_client = ?",
            self.conn,
            params=(phone,),
        )

    # מקשרת תור קיים ללקוח קיים בטבלת customers, לפי מזהה הלקוח (customer_id)
    def link_customer(self, id_client, customer_id):
        self.conn.execute(
            f"UPDATE {TABLE_NAME} SET customer_id = ? WHERE id_client = ?",
            (customer_id, id_client),
        )
        self.conn.commit()

    # מחזירה את כל התורים המקושרים ללקוח נתון (customer_id)
    def get_by_customer_id(self, customer_id):
        return pd.read_sql_query(
            f"SELECT * FROM {TABLE_NAME} WHERE customer_id = ?",
            self.conn,
            params=(customer_id,),
        )

    # מחזירה סט של (תאריך, שעה) תפוסים בכל החנויות - משמש לחישוב זמינות
    def get_booked_slots(self):
        df = pd.read_sql_query(
            f"SELECT appointment_date, appointment_time FROM {TABLE_NAME}", self.conn
        )
        return set(zip(df["appointment_date"], df["appointment_time"]))
