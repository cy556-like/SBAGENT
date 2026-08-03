import json
import os
import tempfile
import time
import sys
import types
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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

from app.config import settings
from app.auth.sqm_sso import (
    SQMSSOError,
    calculate_signature,
    cleanup_expired_sqm_data,
    consume_login_ticket,
    create_login_ticket,
    is_sqm_chat_id,
    verify_partner_request,
)


class SQMSSOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        keys = [
            "DATA_DIR",
            "SQM_SSO_ENABLED",
            "SQM_SSO_CLIENT_ID",
            "SQM_SSO_SHARED_SECRET",
            "SQM_SSO_PUBLIC_URL",
            "SQM_SSO_TICKET_EXPIRE_SECONDS",
            "SQM_SSO_RETENTION_DAYS",
        ]
        self.original = {key: getattr(settings, key) for key in keys}
        settings.DATA_DIR = self.temp.name
        settings.SQM_SSO_ENABLED = True
        settings.SQM_SSO_CLIENT_ID = "sqm-test"
        settings.SQM_SSO_SHARED_SECRET = "unit-test-secret-not-for-production"
        settings.SQM_SSO_PUBLIC_URL = "https://subao.example"
        settings.SQM_SSO_TICKET_EXPIRE_SECONDS = 60
        settings.SQM_SSO_RETENTION_DAYS = 7

    def tearDown(self):
        for key, value in self.original.items():
            setattr(settings, key, value)
        self.temp.cleanup()

    def _ticket_value(self, response):
        return parse_qs(urlsplit(response["login_url"]).query)["ticket"][0]

    def test_signed_request_is_accepted_once(self):
        raw = b'{"user_id":"u-100","name":"Alice"}'
        timestamp = str(int(time.time()))
        nonce = "nonce-1234567890"
        signature = calculate_signature(timestamp, nonce, raw)
        verify_partner_request(
            client_id="sqm-test",
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
            raw_body=raw,
        )
        with self.assertRaises(SQMSSOError):
            verify_partner_request(
                client_id="sqm-test",
                timestamp=timestamp,
                nonce=nonce,
                signature=signature,
                raw_body=raw,
            )

    def test_user_mapping_is_stable_and_ticket_is_one_time(self):
        first = create_login_ticket("u-100", "Alice")
        username, role = consume_login_ticket(self._ticket_value(first))
        self.assertEqual("user", role)
        self.assertTrue(username.startswith("sqm_Alice_"))
        with self.assertRaises(SQMSSOError):
            consume_login_ticket(self._ticket_value(first))

        second = create_login_ticket("u-100", "Alice Renamed")
        username_again, _ = consume_login_ticket(self._ticket_value(second))
        self.assertEqual(username, username_again)
        self.assertTrue(is_sqm_chat_id(f"{username}_abcdefgh"))

    def test_cleanup_deletes_only_old_sqm_chat_and_generated_files(self):
        response = create_login_ticket("u-200", "SQM User")
        username, _ = consume_login_ticket(self._ticket_value(response))
        now = time.time()
        old_chat = f"{username}_old00001"
        fresh_chat = f"{username}_new00001"
        normal_chat = "admin_old00001"

        users_dir = Path(settings.DATA_DIR) / "users"
        conversations = Path(settings.DATA_DIR) / "conversations"
        exports = Path(settings.DATA_DIR) / "export"
        temp = Path(settings.DATA_DIR) / "temp"
        documents = Path(settings.DATA_DIR) / "documents"
        for path in (users_dir, conversations, exports, temp, documents):
            path.mkdir(parents=True, exist_ok=True)

        old_time = now - 8 * 86400
        (users_dir / f"{username}_chats.json").write_text(
            json.dumps(
                [
                    {"chat_id": old_chat, "created_at": old_time, "updated_at": old_time},
                    {"chat_id": fresh_chat, "created_at": now, "updated_at": now},
                ]
            ),
            encoding="utf-8",
        )
        (users_dir / "admin_chats.json").write_text(
            json.dumps(
                [{"chat_id": normal_chat, "created_at": old_time, "updated_at": old_time}]
            ),
            encoding="utf-8",
        )
        for chat_id in (old_chat, fresh_chat, normal_chat):
            (conversations / f"{chat_id}.json").write_text("[]", encoding="utf-8")
            (exports / chat_id).mkdir()
            (exports / chat_id / "result.docx").write_bytes(b"docx")
            (temp / chat_id).mkdir()
            (temp / chat_id / "input.txt").write_text("temp", encoding="utf-8")
        knowledge_file = documents / "knowledge.docx"
        knowledge_file.write_bytes(b"knowledge")

        result = cleanup_expired_sqm_data(now=now)
        self.assertEqual(1, result["chats"])
        self.assertFalse((conversations / f"{old_chat}.json").exists())
        self.assertFalse((exports / old_chat).exists())
        self.assertFalse((temp / old_chat).exists())
        self.assertTrue((conversations / f"{fresh_chat}.json").exists())
        self.assertTrue((conversations / f"{normal_chat}.json").exists())
        self.assertTrue((exports / normal_chat).exists())
        self.assertTrue(knowledge_file.exists())

        remaining = json.loads(
            (users_dir / f"{username}_chats.json").read_text(encoding="utf-8")
        )
        self.assertEqual([fresh_chat], [chat["chat_id"] for chat in remaining])

    def test_contract_contains_no_department_field(self):
        source = Path(__file__).parents[1].joinpath("app", "api", "routes.py").read_text(
            encoding="utf-8"
        )
        contract = source.split("class SQMTicketRequest", 1)[1].split(
            "class RegisterRequest", 1
        )[0]
        self.assertIn("user_id: str", contract)
        self.assertIn('name: str = ""', contract)
        self.assertNotIn("department", contract.lower())

    def test_sqm_chats_are_retained_until_seven_day_cleanup(self):
        from app.memory.manager import create_chat, list_chats

        response = create_login_ticket("u-300", "History User")
        username, _ = consume_login_ticket(self._ticket_value(response))
        for index in range(3):
            create_chat(username, f"SQM {index}", agent_id="agent-a")
        self.assertEqual(3, len(list_chats(username)))

        for index in range(3):
            create_chat("normal-user", f"Web {index}", agent_id="agent-a")
        self.assertEqual(2, len(list_chats("normal-user")))


if __name__ == "__main__":
    unittest.main()
