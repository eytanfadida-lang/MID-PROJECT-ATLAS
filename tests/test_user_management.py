import sqlite3
import unittest

from atlas.data.repositories.user_repository import UserRepository


class UserRepositoryManagementTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL
            )
        ''')
        self.repo = UserRepository(self.conn)

    def test_update_role_and_password_and_delete(self):
        user_id = self.repo.create('alice', 'old-pass', 'user')

        self.repo.update_role(user_id, 'admin')
        self.repo.update_password(user_id, 'new-pass')

        updated_user = self.repo.get_by_id(user_id)
        self.assertEqual(updated_user['role'], 'admin')
        self.assertNotEqual(updated_user['password_hash'], '')

        self.repo.delete(user_id)
        self.assertIsNone(self.repo.get_by_id(user_id))

    def test_update_permissions_round_trip(self):
        user_id = self.repo.create('bob', 'secret', 'user')

        self.repo.update_permissions(user_id, ['manage_users', 'manage_appointments'])

        updated_user = self.repo.get_by_id(user_id)
        self.assertEqual(updated_user['permissions'], ['manage_users', 'manage_appointments'])


if __name__ == '__main__':
    unittest.main()
