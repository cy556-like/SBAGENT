import unittest
import sys
import types

sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))

from app.auth.permissions import full_kb_admin_usernames, is_full_kb_admin
from app.config import settings


class KnowledgeBasePermissionTests(unittest.TestCase):
    def setUp(self):
        self.original = settings.FULL_KB_ADMIN_USERNAMES

    def tearDown(self):
        settings.FULL_KB_ADMIN_USERNAMES = self.original

    def test_default_full_admin_is_always_retained(self):
        settings.FULL_KB_ADMIN_USERNAMES = ""
        self.assertTrue(is_full_kb_admin("adminsubao"))

    def test_feishu_user_can_be_granted_full_access(self):
        settings.FULL_KB_ADMIN_USERNAMES = "adminsubao,fs_梅琴_54b7b5dcf1"
        self.assertIn("fs_梅琴_54b7b5dcf1", full_kb_admin_usernames())
        self.assertTrue(is_full_kb_admin("fs_梅琴_54b7b5dcf1"))


if __name__ == "__main__":
    unittest.main()
