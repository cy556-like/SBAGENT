import json
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

# The lightweight Codex test runtime does not include python-dotenv. The
# production requirements do; a tiny import stub is enough for these pure unit
# tests because they override all relevant settings explicitly.
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))

from app.auth import feishu_sso
from app.config import settings


class FeishuSSOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = {
            "DATA_DIR": settings.DATA_DIR,
            "FEISHU_APP_ID": settings.FEISHU_APP_ID,
            "FEISHU_APP_SECRET": settings.FEISHU_APP_SECRET,
            "FEISHU_REDIRECT_URI": settings.FEISHU_REDIRECT_URI,
            "FEISHU_ACCOUNT_MAP_JSON": settings.FEISHU_ACCOUNT_MAP_JSON,
            "FULL_KB_ADMIN_USERNAMES": settings.FULL_KB_ADMIN_USERNAMES,
        }
        settings.DATA_DIR = self.temp.name
        settings.FEISHU_APP_ID = "cli_test"
        settings.FEISHU_APP_SECRET = "secret"
        settings.FEISHU_REDIRECT_URI = "https://example.com/api/v1/auth/feishu/callback"
        settings.FEISHU_ACCOUNT_MAP_JSON = ""
        settings.FULL_KB_ADMIN_USERNAMES = "adminsubao"

    def tearDown(self):
        for key, value in self.original.items():
            setattr(settings, key, value)
        self.temp.cleanup()

    def test_state_is_one_time_and_authorize_url_uses_pkce(self):
        state, url = feishu_sso.create_oauth_request("/chat")
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["client_id"], ["cli_test"])
        self.assertEqual(query["redirect_uri"], [settings.FEISHU_REDIRECT_URI])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["state"], [state])
        verifier, next_path = feishu_sso.consume_oauth_state(state)
        self.assertGreater(len(verifier), 30)
        self.assertEqual(next_path, "/chat")
        with self.assertRaises(feishu_sso.FeishuSSOError):
            feishu_sso.consume_oauth_state(state)

    def test_external_next_url_is_rejected(self):
        state, _ = feishu_sso.create_oauth_request("//evil.example/path")
        _, next_path = feishu_sso.consume_oauth_state(state)
        self.assertEqual(next_path, "/")

    def test_sso_marker_is_local_and_preserves_existing_query(self):
        self.assertEqual(
            feishu_sso.with_sso_marker("/workspace?tab=chat"),
            "/workspace?tab=chat&feishu_sso=1",
        )
        self.assertEqual(
            feishu_sso.with_sso_marker("//evil.example/path"),
            "/?feishu_sso=1",
        )

    def test_frontend_keeps_web_and_feishu_sessions_separate(self):
        source = Path(__file__).parents[1].joinpath("app", "static", "js", "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("let authSource = 'web';", source)
        self.assertIn("const preferCookie = options.preferCookie === true;", source)
        self.assertIn("if (!preferCookie && !token) return false;", source)
        self.assertIn("{preferCookie: isFeishuSsoEntry}", source)

    def test_automatic_binding_is_stable_and_user_isolated(self):
        user_a = {"tenant_key": "tenant", "open_id": "ou_a", "name": "张三"}
        user_b = {"tenant_key": "tenant", "open_id": "ou_b", "name": "张三"}
        identity_a1 = feishu_sso.resolve_internal_identity(user_a)
        identity_a2 = feishu_sso.resolve_internal_identity(user_a)
        identity_b = feishu_sso.resolve_internal_identity(user_b)
        self.assertEqual(identity_a1, identity_a2)
        self.assertNotEqual(identity_a1[0], identity_b[0])
        self.assertEqual(identity_a1[1], "user")
        self.assertTrue(Path(self.temp.name, "users", "feishu_sso.sqlite3").exists())

    def test_explicit_mapping_can_bind_an_existing_admin(self):
        settings.FEISHU_ACCOUNT_MAP_JSON = json.dumps(
            {"ou_admin": {"username": "adminsubao", "role": "admin"}}
        )
        identity = feishu_sso.resolve_internal_identity(
            {"tenant_key": "tenant", "open_id": "ou_admin", "name": "管理员"}
        )
        self.assertEqual(identity, ("adminsubao", "admin"))

    def test_full_kb_admin_configuration_promotes_existing_feishu_identity(self):
        settings.FEISHU_ACCOUNT_MAP_JSON = json.dumps(
            {"u_meiqin": {"username": "fs_梅琴_54b7b5dcf1", "role": "user"}}
        )
        settings.FULL_KB_ADMIN_USERNAMES = "adminsubao,fs_梅琴_54b7b5dcf1"
        identity = feishu_sso.resolve_internal_identity(
            {
                "tenant_key": "tenant",
                "user_id": "u_meiqin",
                "open_id": "ou_meiqin",
                "name": "梅琴",
            }
        )
        self.assertEqual(identity, ("fs_梅琴_54b7b5dcf1", "admin"))

    def test_user_id_survives_open_id_change(self):
        first = feishu_sso.resolve_internal_identity(
            {"tenant_key": "tenant", "user_id": "u_stable", "open_id": "ou_old", "name": "张三"}
        )
        second = feishu_sso.resolve_internal_identity(
            {"tenant_key": "tenant", "user_id": "u_stable", "open_id": "ou_new", "name": "张三"}
        )
        self.assertEqual(first, second)

    def test_legacy_open_id_binding_migrates_without_username_change(self):
        legacy = feishu_sso.resolve_internal_identity(
            {"tenant_key": "tenant", "open_id": "ou_legacy", "name": "李四"}
        )
        migrated = feishu_sso.resolve_internal_identity(
            {
                "tenant_key": "tenant",
                "user_id": "u_real",
                "open_id": "ou_legacy",
                "name": "李四",
            }
        )
        self.assertEqual(legacy, migrated)

    def test_existing_legacy_database_is_migrated_in_place(self):
        db_path = Path(self.temp.name, "users", "feishu_sso.sqlite3")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "CREATE TABLE user_bindings(tenant_key TEXT NOT NULL, open_id TEXT NOT NULL, "
                "username TEXT NOT NULL UNIQUE, role TEXT NOT NULL, display_name TEXT NOT NULL, "
                "user_id TEXT NOT NULL, union_id TEXT NOT NULL, updated_at INTEGER NOT NULL, "
                "PRIMARY KEY(tenant_key, open_id))"
            )
            conn.execute(
                "INSERT INTO user_bindings VALUES(?,?,?,?,?,?,?,?)",
                ("tenant", "ou_old", "fs_existing", "user", "王五", "", "", 1),
            )
            conn.commit()
        finally:
            conn.close()
        identity = feishu_sso.resolve_internal_identity(
            {
                "tenant_key": "tenant",
                "user_id": "u_real",
                "open_id": "ou_old",
                "name": "王五",
            }
        )
        self.assertEqual(identity, ("fs_existing", "user"))
        conn = sqlite3.connect(db_path)
        try:
            primary = [
                row[1]
                for row in sorted(
                    (x for x in conn.execute("PRAGMA table_info(user_bindings)") if x[5]),
                    key=lambda x: x[5],
                )
            ]
        finally:
            conn.close()
        self.assertEqual(primary, ["tenant_key", "user_id"])


if __name__ == "__main__":
    unittest.main()
