import types
import unittest

from atlas.automations import engine
from atlas.data.linked_whatsapp_db import LinkedWhatsAppDB
from atlas.data.repositories.linked_whatsapp_repository import LinkedWhatsAppRepository

MOTZKIN_JID = "120363000000000001@g.us"
TIRA_JID = "120363000000000002@g.us"


class FakeAutomations:
    def __init__(self):
        self.sent, self.failed, self.logs = [], [], []

    def mark_sent(self, due_action_id):
        self.sent.append(due_action_id)

    def mark_failed(self, due_action_id):
        self.failed.append(due_action_id)

    def log_execution(self, automation_id, target_phone, status, channel, detail, due_action_id=None, wamid=None):
        self.logs.append((status, detail))


# אוטומציית "הצטרפות לקבוצת הסניף": רכישה ב-Arbox -> עבודת הוספה לקבוצה של הסניף הנכון (דרך החשבון המקושר)
class BranchGroupAutomationTests(unittest.TestCase):
    def setUp(self):
        self.linked = LinkedWhatsAppRepository(LinkedWhatsAppDB(":memory:").conn)
        self.account_id = self.linked.create("מספר משני")
        self.linked.replace_groups(self.account_id, [
            {"jid": MOTZKIN_JID, "subject": "מוצקין", "is_admin": True, "size": 40},
            {"jid": TIRA_JID, "subject": "טירה", "is_admin": True, "size": 30},
            {"jid": "not-a-group", "subject": "x"},
        ])
        self.linked.set_branch_group("קרית מוצקין", self.account_id, MOTZKIN_JID, "מוצקין")
        self.linked.set_branch_group("טירת הכרמל", self.account_id, TIRA_JID, "טירה")
        self.automations = FakeAutomations()
        self.repos = types.SimpleNamespace(linked_whatsapp=self.linked, automations=self.automations)

    def run_action(self, context, due_action_id=1):
        due_action = {"id": due_action_id, "automation_id": 7, "target_phone": "0501234567", "context": context}
        engine._add_to_group_action(self.repos, due_action, {"skip_membership_type_types": ["item"]})

    def test_invalid_group_ids_are_not_stored(self):
        self.assertEqual({g["jid"] for g in self.linked.get_groups()}, {MOTZKIN_JID, TIRA_JID})

    def test_membership_goes_to_its_branch_group(self):
        self.run_action({"location": "טירת הכרמל", "membership_type_type": "plan", "first_name": "דנה"})
        jobs = self.linked.take_pending_group_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual((jobs[0]["group_jid"], jobs[0]["to"]), (TIRA_JID, "972501234567"))
        self.assertIn("דנה", jobs[0]["invite_text"])
        self.assertIn("טירת הכרמל", jobs[0]["invite_text"])
        self.assertEqual(self.automations.sent, [1])

    def test_branch_name_variants_match(self):
        self.run_action({"location": "קריית מוצקין", "membership_type_type": "session"})
        self.assertEqual(self.linked.take_pending_group_jobs()[0]["group_jid"], MOTZKIN_JID)
        self.run_action({"location": "טירת כרמל", "membership_type_type": "plan"}, due_action_id=2)
        self.assertEqual(self.linked.take_pending_group_jobs()[0]["group_jid"], TIRA_JID)

    def test_product_purchase_is_skipped(self):
        self.run_action({"location": "קרית מוצקין", "membership_type_type": "item", "membership_type": "בקבוק"})
        self.assertEqual(self.linked.take_pending_group_jobs(), [])
        self.assertEqual(self.automations.logs[0][0], "skipped")

    def test_unknown_branch_fails_with_a_clear_reason(self):
        self.run_action({"location": "חיפה", "membership_type_type": "plan"})
        self.assertEqual(self.linked.take_pending_group_jobs(), [])
        self.assertEqual(self.automations.failed, [1])
        self.assertIn("חיפה", self.automations.logs[0][1])

    def test_job_is_handed_out_once_and_completed_once(self):
        self.run_action({"location": "קרית מוצקין", "membership_type_type": "plan"})
        job = self.linked.take_pending_group_jobs()[0]
        self.assertEqual(self.linked.take_pending_group_jobs(), [])
        self.assertTrue(self.linked.has_pending_outbox())
        done = self.linked.complete_group_job(job["id"], "added")
        self.assertEqual((done["automation_id"], done["due_action_id"]), (7, 1))
        self.assertIsNone(self.linked.complete_group_job(job["id"], "added"))
        self.assertFalse(self.linked.has_pending_outbox())

    def test_clearing_a_branch_removes_its_group(self):
        self.linked.set_branch_group("טירת הכרמל")
        self.assertEqual(set(self.linked.get_branch_groups()), {"קרית מוצקין"})


if __name__ == "__main__":
    unittest.main()
