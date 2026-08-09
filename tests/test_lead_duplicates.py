import sqlite3

from lead_repository import LeadRepository


def test_duplicate_phone_marks_new_lead_as_duplicate(tmp_path):
    db_path = tmp_path / "test_leads.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            phone TEXT,
            status TEXT,
            channel TEXT,
            assigned_user TEXT,
            routings_count INTEGER,
            sms_count INTEGER,
            notes TEXT,
            created_datetime_stamp TEXT,
            last_updated_datetime_stamp TEXT,
            branch TEXT
        )
        """
    )
    conn.commit()

    repo = LeadRepository(conn)
    repo.create(
        {
            "full_name": "אייל",
            "phone": "0501234567",
            "status": "חדש",
            "channel": "ערוץ ידני",
            "assigned_user": "",
            "notes": "",
        }
    )
    second_lead_id = repo.create(
        {
            "full_name": "נועה",
            "phone": "0501234567",
            "status": "חדש",
            "channel": "ערוץ ידני",
            "assigned_user": "",
            "notes": "",
        }
    )

    duplicate_rows = repo.get_by_phone("0501234567")
    statuses = duplicate_rows["status"].tolist()

    assert second_lead_id is not None
    assert statuses == ["ליד כפול", "חדש"] or statuses == ["חדש", "ליד כפול"]
