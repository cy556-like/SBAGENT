"""Low-dependency regression contracts for critical SBAGENT isolation paths."""
import ast
import asyncio
import contextlib
import contextvars
import logging
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
        self.assertIn('@router.post("/documents/ocr-word-export"', routes)
        self.assertIn("该扫描PDF仍在OCR/索引中", routes)

    def test_pdf_ocr_word_download_is_available_in_knowledge_base_ui(self):
        app_js = read("app/static/js/app.js")
        self.assertIn("doc-ocr-word-btn", app_js)
        self.assertIn("/api/v1/documents/ocr-word-export", app_js)
        self.assertIn("downloadPdfOcrWord", app_js)

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
        index = read("app/static/index.html")
        main = read("app/main.py")
        self.assertIn("速豹 AI智能体平台", manifest)
        self.assertIn("sbagent-static-${CACHE_VERSION}", service_worker)
        self.assertNotIn("jlagent-static", service_worker)
        self.assertIn("fetch(request, { cache: 'no-cache' })", service_worker)
        self.assertIn("event.respondWith(networkFirst(request))", service_worker)
        self.assertIn("controllerchange", index)
        self.assertIn("updateViaCache: 'none'", index)
        self.assertIn('path == "/static/sw.js"', main)

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

    def test_pdf_loader_has_text_fallback_ocr_and_persistent_cache(self):
        rag = read("app/rag/document.py")
        requirements = read("requirements.txt")

        self.assertIn("def _load_pdf_with_fallback", rag)
        self.assertIn("PyPDFLoader(file_path).load()", rag)
        self.assertIn("import pypdfium2 as pdfium", rag)
        self.assertIn("from rapidocr import RapidOCR", rag)
        self.assertIn(".sbagent-text.json", rag)
        self.assertIn("source_mtime_ns", rag)
        self.assertIn("return _load_pdf_with_fallback(file_path)", rag)
        self.assertIn("pypdfium2", requirements)
        self.assertIn("rapidocr", requirements)
        self.assertIn("onnxruntime", requirements)
        self.assertIn("numpy==1.26.4", requirements)
        self.assertIn("opencv-python==4.11.0.86", requirements)
        self.assertIn("_PDF_OCR_MAX_SCALE = 1.5", rag)
        self.assertIn("_PDF_OCR_CHECKPOINT_PAGES = 10", rag)
        self.assertIn("use_cls=False", rag)
        self.assertIn("PDF OCR单页开始:", rag)
        self.assertIn("PDF OCR单页完成:", rag)
        self.assertIn("def _read_pdf_partial_cache", rag)
        self.assertIn("def _write_pdf_partial_cache", rag)
        self.assertIn("PDF OCR进度:", rag)
        self.assertIn("跳过尚未完成OCR/索引的PDF磁盘兜底搜索", rag)
        self.assertIn('"status": "processing"', rag)
        self.assertIn('docs = _read_pdf_text_cache(file_path)', rag)

    def test_large_pdf_questions_do_not_send_full_book_to_model(self):
        tools = read("app/agent/tools.py")
        prompts = read("app/agent/prompts.py")
        core = read("app/agent/core.py")

        self.assertIn("_MAX_DOCUMENT_TOOL_CHARS = 12000", tools)
        self.assertIn("def _sample_large_document", tools)
        self.assertIn("【大型文档摘要素材】", tools)
        self.assertIn("禁止重复调用本工具", tools)
        self.assertIn("大型PDF问答硬规则", prompts)
        self.assertIn("必须调用 **search_documents_tool**", prompts)
        self.assertIn('"get_document_content_tool": "读取文档内容"', core)

    def test_stream_model_context_does_not_span_async_yield(self):
        routes = read("app/api/routes.py")

        self.assertIn("item = await stream.__anext__()", routes)
        self.assertIn("ContextVar 不能跨 async-generator", routes)
        self.assertIn("yield item", routes)
        unsafe = (
            "with use_model(model_id):\n"
            "                stream = generator_factory()\n"
            "                async for item in stream:"
        )
        self.assertNotIn(unsafe, routes)

    def test_stream_can_be_closed_from_another_asyncio_task(self):
        """Regression for ContextVar token reset from a different Context."""
        routes = read("app/api/routes.py")
        tree = ast.parse(routes)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_stream_with_user_model"
        )
        module = ast.fix_missing_locations(
            ast.Module(body=[function], type_ignores=[])
        )

        active_model = contextvars.ContextVar("test_active_model", default=None)

        @contextlib.contextmanager
        def use_model(model_id):
            token = active_model.set(model_id)
            try:
                yield
            finally:
                active_model.reset(token)

        namespace = {
            "AUTO_MODEL_ID": "auto",
            "_auto_model_candidates": lambda: ("glm", "mimo", "kimi"),
            "get_user_model": lambda _username: "glm",
            "is_model_quota_error": lambda _value: False,
            "logger": logging.getLogger("stream-context-regression"),
            "use_model": use_model,
        }
        exec(compile(module, "routes-stream-test", "exec"), namespace)
        stream_wrapper = namespace["_stream_with_user_model"]

        async def source():
            self.assertEqual(active_model.get(), "glm")
            yield {"type": "token", "content": "OK"}
            await asyncio.Event().wait()

        async def scenario():
            wrapped = stream_wrapper("adminsubao", source)
            first = await wrapped.__anext__()
            self.assertEqual(first["content"], "OK")
            self.assertIsNone(active_model.get())
            # StreamingResponse/客户端断开时，关闭动作可能发生在另一个 Task。
            await asyncio.create_task(wrapped.aclose())
            self.assertIsNone(active_model.get())

        asyncio.run(scenario())

    def test_auto_stream_quota_failover_stays_silent(self):
        routes = read("app/api/routes.py")
        tree = ast.parse(routes)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_stream_with_user_model"
        )
        module = ast.fix_missing_locations(
            ast.Module(body=[function], type_ignores=[])
        )

        active_model = contextvars.ContextVar("test_auto_model", default=None)

        @contextlib.contextmanager
        def use_model(model_id):
            token = active_model.set(model_id)
            try:
                yield
            finally:
                active_model.reset(token)

        namespace = {
            "AUTO_MODEL_ID": "auto",
            "_auto_model_candidates": lambda: ("glm", "mimo", "kimi"),
            "get_user_model": lambda _username: "auto",
            "is_model_quota_error": lambda value: "quota" in str(value).lower(),
            "logger": logging.getLogger("auto-stream-regression"),
            "use_model": use_model,
        }
        exec(compile(module, "routes-auto-test", "exec"), namespace)
        stream_wrapper = namespace["_stream_with_user_model"]

        def source():
            model_id = active_model.get()

            async def events():
                if model_id in {"glm", "mimo"}:
                    yield {"type": "error", "content": "quota exhausted"}
                else:
                    yield {"type": "token", "content": "Kimi OK"}

            return events()

        async def scenario():
            return [
                item
                async for item in stream_wrapper("adminsubao", source)
            ]

        self.assertEqual(
            asyncio.run(scenario()),
            [{"type": "token", "content": "Kimi OK"}],
        )


if __name__ == "__main__":
    unittest.main()
