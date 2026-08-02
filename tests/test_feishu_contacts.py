import asyncio
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))

from app.auth import feishu_contacts, feishu_sso
from app.config import settings


class FakeContactClient:
    async def tenant_token(self):
        return "token"

    async def all_departments(self, token):
        return [
            {
                "department_id": "od_sales",
                "open_department_id": "od_sales",
                "name": "销售部",
                "parent_department_id": "0",
            }
        ]

    async def users_in_department(self, token, department_id):
        if department_id == "0":
            return []
        return [
            {
                "user_id": "u_1",
                "open_id": "ou_1",
                "name": "张三",
                "job_title": "质量工程师",
                "department_ids": ["od_sales"],
                "status": {"is_activated": True},
            }
        ]


class FeishuContactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = {
            "DATA_DIR": settings.DATA_DIR,
            "EMPLOYEES_FILE": settings.EMPLOYEES_FILE,
            "FEISHU_CONTACTS_DB": settings.FEISHU_CONTACTS_DB,
            "FEISHU_APP_ID": settings.FEISHU_APP_ID,
            "FEISHU_APP_SECRET": settings.FEISHU_APP_SECRET,
        }
        settings.DATA_DIR = self.temp.name
        settings.EMPLOYEES_FILE = str(Path(self.temp.name) / "employees.json")
        settings.FEISHU_CONTACTS_DB = ""
        settings.FEISHU_APP_ID = "cli_test"
        settings.FEISHU_APP_SECRET = "secret"

    def tearDown(self):
        for key, value in self.original.items():
            setattr(settings, key, value)
        self.temp.cleanup()

    def test_full_sync_creates_database_and_employee_export(self):
        result = asyncio.run(
            feishu_contacts.run_full_sync(
                tenant_key="tenant", client=FakeContactClient(), source="test"
            )
        )
        self.assertEqual(result["departments"], 1)
        self.assertEqual(result["users"], 1)
        exported = json.loads(Path(settings.EMPLOYEES_FILE).read_text(encoding="utf-8"))
        self.assertEqual(exported[0]["name"], "张三")
        self.assertEqual(exported[0]["department"], "销售部")
        self.assertEqual(feishu_contacts.contact_active_status("tenant", user_id="u_1"), True)

    def test_user_deleted_event_disables_existing_sso_token_identity(self):
        username, _ = feishu_sso.resolve_internal_identity(
            {
                "tenant_key": "tenant",
                "user_id": "u_1",
                "open_id": "ou_1",
                "name": "张三",
            }
        )
        feishu_contacts.upsert_user(
            "tenant", {"user_id": "u_1", "open_id": "ou_1", "name": "张三"}
        )
        feishu_contacts.apply_contact_event(
            "contact.user.deleted_v3",
            "tenant",
            {"event": {"object": {"user_id": "u_1", "open_id": "ou_1"}}},
        )
        self.assertFalse(feishu_sso.is_username_active(username))
        self.assertFalse(feishu_contacts.contact_active_status("tenant", user_id="u_1"))


if __name__ == "__main__":
    unittest.main()
