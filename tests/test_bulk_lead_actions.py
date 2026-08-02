import sqlite3
import unittest

from lead_repository import LeadRepository


class LeadRepositoryBulkActionsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute(
            '''
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
                last_updated_datetime_stamp TEXT
            )
            '''
        )
        self.conn.commit()
        self.repo = LeadRepository(self.conn)

    def test_bulk_status_update_and_delete(self):
        first_id = self.repo.create({
            'full_name': 'אייל',
            'phone': '0501111111',
            'status': 'חדש',
            'channel': 'ערוץ ידני',
            'assigned_user': '',
            'notes': '',
        })
        second_id = self.repo.create({
            'full_name': 'נועה',
            'phone': '0502222222',
            'status': 'חדש',
            'channel': 'ערוץ ידני',
            'assigned_user': '',
            'notes': '',
        })

        self.repo.bulk_update_status([first_id, second_id], 'בטיפול')
        first = self.repo.get_by_id(first_id)
        second = self.repo.get_by_id(second_id)
        self.assertEqual(first['status'], 'בטיפול')
        self.assertEqual(second['status'], 'בטיפול')

        self.repo.bulk_delete([second_id])
        self.assertIsNone(self.repo.get_by_id(second_id))
        self.assertIsNotNone(self.repo.get_by_id(first_id))


if __name__ == '__main__':
    unittest.main()
