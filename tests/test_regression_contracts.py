"""Low-dependency regression contracts for critical SBAGENT isolation paths."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class RegressionContracts(unittest.TestCase):
    def test_model_selection_is_user_scoped_and_authenticated(self):
        config = read("app/config.py")
        routes = read("app/api/routes.py")
        self.assertIn("def get_user_model(username", config)
        self.assertIn("def set_user_model(username", config)
        self.assertIn("ContextVar", config)
        self.assertIn("async def get_models(username: str = Depends(require_auth))", routes)
        self.assertIn("async def set_model(req: ModelSetRequest, username: str = Depends(require_auth))", routes)

    def test_knowledge_read_endpoints_require_authentication(self):
        routes = read("app/api/routes.py")
        self.assertIn("async def search_api(req: SearchRequest", routes)
        self.assertIn("async def download_document(filename: str", routes)
        self.assertGreaterEqual(routes.count("username: str = Depends(require_auth)"), 10)

    def test_frontend_has_race_guards_and_safe_markdown(self):
        app_js = read("app/static/js/app.js")
        self.assertIn("renderSafeMarkdown", app_js)
        self.assertIn("DOMPurify.sanitize", app_js)
        self.assertIn("const targetAgentId = currentAgentId", app_js)
        self.assertIn("requestedAgentId !== currentAgentId", app_js)
        self.assertIn("fetchAllChatsForUser", app_js)
        self.assertIn("agentActiveChatIds:${currentUser}", app_js)

    def test_pwa_brand_and_cache_are_sbagent(self):
        manifest = read("app/static/manifest.json")
        service_worker = read("app/static/sw.js")
        self.assertIn("速豹 AI智能体平台", manifest)
        self.assertIn("sbagent-static-v1.2.0", service_worker)
        self.assertNotIn("jlagent-static", service_worker)

    def test_three_chen_workspaces_share_one_knowledge_base(self):
        app_js = read("app/static/js/app.js")
        storage = read("app/agent/storage.py")
        rag = read("app/rag/document.py")
        core = read("app/agent/core.py")

        for workspace_id in (
            "project-development-quality-agent",
            "quality-system-agent",
            "measurement-laboratory-agent",
        ):
            self.assertIn(workspace_id, app_js)
            self.assertIn(workspace_id, storage)

        self.assertIn("agent_id.endswith(_CHEN_TEACHER_WORKSPACE_AGENT_SUFFIX)", rag)
        self.assertIn("return CHEN_TEACHER_AGENT_ID", rag)
        self.assertIn("agent_id.endswith(DIGITAL_CHEN_AGENT_SUFFIX)", core)

    def test_auto_model_quota_failover_is_ordered_and_silent(self):
        config = read("app/config.py")
        routes = read("app/api/routes.py")
        core = read("app/agent/core.py")

        glm_pos = config.index('"glm-5.2"', config.index("AUTO_MODEL_FALLBACK_CHAIN"))
        mimo_pos = config.index('"mimo-v2.5-pro"', glm_pos)
        kimi_pos = config.index('"kimi-k3"', mimo_pos)
        self.assertLess(glm_pos, mimo_pos)
        self.assertLess(mimo_pos, kimi_pos)
        self.assertIn("is_model_quota_error", routes)
        self.assertIn("selected_model == AUTO_MODEL_ID", routes)
        self.assertIn("has_next and not emitted_token and is_quota_event", routes)
        self.assertIn("if has_next and not emitted_token and is_model_quota_error(exc)", routes)
        self.assertNotIn("yield {\"type\": \"model_switch\"", routes)
        self.assertIn("MiMo 未配置 MIMO_API_KEY", core)


if __name__ == "__main__":
    unittest.main()
