import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))


class _Message:
    def __init__(self, content=""):
        self.content = content


class _History:
    pass


sys.modules.setdefault("langchain_core", types.ModuleType("langchain_core"))
sys.modules.setdefault(
    "langchain_core.messages",
    types.SimpleNamespace(BaseMessage=_Message, HumanMessage=_Message, AIMessage=_Message),
)
sys.modules.setdefault(
    "langchain_core.chat_history", types.SimpleNamespace(BaseChatMessageHistory=_History)
)
sys.modules.setdefault("langchain_community", types.ModuleType("langchain_community"))
sys.modules.setdefault(
    "langchain_community.chat_message_histories",
    types.SimpleNamespace(ChatMessageHistory=_History),
)

from app.auth.sqm_demo import (
    SQMDemoLoginError,
    authenticate_demo_entry,
    cleanup_expired_demo_data,
    is_demo_chat_id,
    is_demo_username,
)
from app.config import settings


class SQMDemoLoginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        keys = [
            "DATA_DIR",
            "SQM_DEMO_LOGIN_ENABLED",
            "SQM_DEMO_USERNAME",
            "SQM_DEMO_ENTRY_KEY",
            "SQM_DEMO_RETENTION_DAYS",
        ]
        self.original = {key: getattr(settings, key) for key in keys}
        settings.DATA_DIR = self.temp.name
        settings.SQM_DEMO_LOGIN_ENABLED = True
        settings.SQM_DEMO_USERNAME = "jiangxy"
        settings.SQM_DEMO_ENTRY_KEY = "demo-entry-key-for-unit-tests"
        settings.SQM_DEMO_RETENTION_DAYS = 7

    def tearDown(self):
        for key, value in self.original.items():
            setattr(settings, key, value)
        self.temp.cleanup()

    def test_valid_key_resolves_existing_fixed_account(self):
        username, role = authenticate_demo_entry("demo-entry-key-for-unit-tests")
        self.assertEqual("jiangxy", username)
        self.assertEqual("user", role)
        self.assertTrue(is_demo_username(username))
        self.assertTrue(is_demo_chat_id("jiangxy_abcdef12"))

    def test_invalid_or_disabled_key_is_rejected(self):
        with self.assertRaises(SQMDemoLoginError):
            authenticate_demo_entry("wrong")
        settings.SQM_DEMO_LOGIN_ENABLED = False
        with self.assertRaises(SQMDemoLoginError):
            authenticate_demo_entry("demo-entry-key-for-unit-tests")

    def test_old_demo_chat_and_generated_files_are_deleted_only_for_jiangxy(self):
        now = time.time()
        old_time = now - 8 * 86400
        demo_old = "jiangxy_old00001"
        demo_fresh = "jiangxy_new00001"
        normal_old = "admin_old00001"

        users = Path(settings.DATA_DIR) / "users"
        conversations = Path(settings.DATA_DIR) / "conversations"
        exports = Path(settings.DATA_DIR) / "export"
        temp = Path(settings.DATA_DIR) / "temp"
        documents = Path(settings.DATA_DIR) / "documents"
        for path in (users, conversations, exports, temp, documents):
            path.mkdir(parents=True, exist_ok=True)

        (users / "jiangxy_chats.json").write_text(
            json.dumps(
                [
                    {"chat_id": demo_old, "created_at": old_time, "updated_at": old_time},
                    {"chat_id": demo_fresh, "created_at": now, "updated_at": now},
                ]
            ),
            encoding="utf-8",
        )
        (users / "admin_chats.json").write_text(
            json.dumps(
                [{"chat_id": normal_old, "created_at": old_time, "updated_at": old_time}]
            ),
            encoding="utf-8",
        )
        for chat_id in (demo_old, demo_fresh, normal_old):
            (conversations / f"{chat_id}.json").write_text("[]", encoding="utf-8")
            (exports / chat_id).mkdir()
            (exports / chat_id / "result.docx").write_bytes(b"docx")
            (temp / chat_id).mkdir()
            (temp / chat_id / "input.txt").write_text("temp", encoding="utf-8")
        knowledge_file = documents / "knowledge.docx"
        knowledge_file.write_bytes(b"knowledge")

        result = cleanup_expired_demo_data(now=now)
        self.assertEqual(1, result["chats"])
        self.assertFalse((conversations / f"{demo_old}.json").exists())
        self.assertFalse((exports / demo_old).exists())
        self.assertFalse((temp / demo_old).exists())
        self.assertTrue((conversations / f"{demo_fresh}.json").exists())
        self.assertTrue((conversations / f"{normal_old}.json").exists())
        self.assertTrue((exports / normal_old).exists())
        self.assertTrue(knowledge_file.exists())

        remaining = json.loads(
            (users / "jiangxy_chats.json").read_text(encoding="utf-8")
        )
        self.assertEqual([demo_fresh], [chat["chat_id"] for chat in remaining])

    def test_demo_account_uses_seven_day_retention_instead_of_two_chat_cap(self):
        from app.memory.manager import create_chat, list_chats

        for index in range(3):
            create_chat("jiangxy", f"Demo {index}", agent_id="agent-a")
        self.assertEqual(3, len(list_chats("jiangxy")))

        for index in range(3):
            create_chat("normal-user", f"Web {index}", agent_id="agent-a")
        self.assertEqual(2, len(list_chats("normal-user")))

    def test_old_sso_contract_is_removed_and_demo_entry_is_wired(self):
        root = Path(__file__).parents[1]
        routes = (root / "app" / "api" / "routes.py").read_text(encoding="utf-8")
        frontend = (root / "app" / "static" / "js" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('@router.get("/auth/sqm/demo-login"', routes)
        self.assertNotIn('/auth/sqm/tickets', routes)
        self.assertNotIn('/auth/sqm/login', routes)
        self.assertIn("sqm_demo", frontend)
        self.assertNotIn("sqm_sso", frontend)


if __name__ == "__main__":
    unittest.main()
