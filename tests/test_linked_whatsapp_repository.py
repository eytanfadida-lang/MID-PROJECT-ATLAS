import datetime
import sqlite3
import unittest

from atlas.data.linked_whatsapp_db import LinkedWhatsAppDB
from atlas.data.repositories.linked_whatsapp_repository import (
    GATEWAY_ONLINE_WITHIN_SECONDS,
    LinkedWhatsAppRepository,
)

PNG = "data:image/png;base64,iVBORw0KGgo="


class LinkedWhatsAppRepositoryTests(unittest.TestCase):
    def setUp(self):
        # אותה יצירת טבלאות כמו באפליקציה, על מסד זמני בזיכרון
        db = LinkedWhatsAppDB(":memory:")
        self.conn = db.conn
        self.repo = LinkedWhatsAppRepository(self.conn)

    def test_create_starts_as_connect_request(self):
        account_id = self.repo.create("מספר משני")
        account = self.repo.get(account_id)
        self.assertEqual((account["label"], account["status"], account["desired"]), ("מספר משני", "starting", "connect"))

    def test_qr_is_stored_only_while_waiting_and_cleared_otherwise(self):
        account_id = self.repo.create("a")
        self.repo.apply_state(account_id, "waiting_qr", qr_image=PNG, qr_ttl=60)
        account = self.repo.get(account_id)
        self.assertEqual((account["qr_image"], account["qr_ttl"]), (PNG, 60))
        self.repo.apply_state(account_id, "connected", phone="972501234567")
        account = self.repo.get(account_id)
        self.assertEqual((account["qr_image"], account["phone"], account["status"]), (None, "972501234567", "connected"))
        self.assertIsNotNone(account["connected_at"])

    def test_phone_survives_a_reconnect_without_phone(self):
        account_id = self.repo.create("a")
        self.repo.apply_state(account_id, "connected", phone="972501234567")
        self.repo.apply_state(account_id, "disconnected")
        self.repo.apply_state(account_id, "connected")
        self.assertEqual(self.repo.get(account_id)["phone"], "972501234567")

    def test_rejects_unsafe_or_oversized_qr_and_unknown_status(self):
        account_id = self.repo.create("a")
        with self.assertRaises(ValueError):
            self.repo.apply_state(account_id, "waiting_qr", qr_image="http://evil/x.png")
        with self.assertRaises(ValueError):
            self.repo.apply_state(account_id, "waiting_qr", qr_image=PNG + "A" * 50000)
        with self.assertRaises(ValueError):
            self.repo.apply_state(account_id, "exploded")
        with self.assertRaises(ValueError):
            self.repo.set_desired(account_id, "explode")

    def test_error_text_is_truncated(self):
        account_id = self.repo.create("a")
        self.repo.apply_state(account_id, "error", error="e" * 500)
        self.assertEqual(len(self.repo.get(account_id)["error"]), 300)

    def test_deleted_report_removes_the_row(self):
        account_id = self.repo.create("a")
        self.repo.apply_state(account_id, "deleted")
        self.assertIsNone(self.repo.get(account_id))

    def test_connect_does_not_wipe_a_showing_qr_but_resets_dead_states(self):
        account_id = self.repo.create("a")
        self.repo.apply_state(account_id, "waiting_qr", qr_image=PNG, qr_ttl=20)
        self.repo.set_desired(account_id, "connect")
        self.assertEqual(self.repo.get(account_id)["qr_image"], PNG)

        self.repo.apply_state(account_id, "logged_out")
        self.repo.set_desired(account_id, "connect")
        account = self.repo.get(account_id)
        self.assertEqual((account["status"], account["error"], account["qr_image"]), ("starting", None, None))

    def test_disconnect_keeps_connected_status_until_the_gateway_reports(self):
        account_id = self.repo.create("a")
        self.repo.apply_state(account_id, "connected", phone="1")
        self.repo.set_desired(account_id, "disconnect")
        account = self.repo.get(account_id)
        self.assertEqual((account["desired"], account["status"]), ("disconnect", "connected"))

    def test_gateway_heartbeat(self):
        self.assertFalse(self.repo.is_gateway_online())
        self.assertIsNone(self.repo.gateway_seconds_since_seen())
        self.repo.touch_gateway()
        self.assertTrue(self.repo.is_gateway_online())
        old = (datetime.datetime.now() - datetime.timedelta(seconds=GATEWAY_ONLINE_WITHIN_SECONDS + 5)).isoformat(timespec="seconds")
        self.conn.execute("UPDATE linked_whatsapp_gateway SET seen_at = ?", (old,))
        self.assertFalse(self.repo.is_gateway_online())
        self.repo.touch_gateway()
        self.assertTrue(self.repo.is_gateway_online())

    def test_rename_and_delete(self):
        account_id = self.repo.create("a")
        self.repo.rename(account_id, "b")
        self.assertEqual(self.repo.get(account_id)["label"], "b")
        self.assertTrue(self.repo.delete(account_id))
        self.assertFalse(self.repo.delete(account_id))


if __name__ == "__main__":
    unittest.main()
