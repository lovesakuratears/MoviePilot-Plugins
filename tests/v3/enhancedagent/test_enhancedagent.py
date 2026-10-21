"""
EnhancedAgent 纯逻辑测试（不依赖宿主 SDK / 网络）。

stub 宿主 fastapi / app.* 之后加载插件包，覆盖：
- SSE 票据：签发、一次性消费、复用拒绝、过期失效、清空
- 插件类：元数据、渲染模式、侧栏导航门控、API 声明、配置表单
运行：python -m unittest discover tests/v3/enhancedagent
"""

import asyncio
import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugins.v3" / "enhancedagent"


# ---------------------------------------------------------------------------
# 宿主 stub：fastapi 与 app.*（bridge.py / __init__.py 的全部外部依赖）
# ---------------------------------------------------------------------------

class _HTTPException(Exception):
    def __init__(self, status_code=500, detail=""):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _install_stubs():
    if "fastapi" in sys.modules:
        return

    def _module(name):
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        return mod

    fastapi = _module("fastapi")

    def _depends(arg):
        return arg

    def _body(default_factory=None, embed=False, **kwargs):
        return None

    def _query(default=..., **kwargs):
        return default

    fastapi.Body = _body
    fastapi.Depends = _depends
    fastapi.HTTPException = _HTTPException
    fastapi.Query = _query
    fastapi.Request = type("Request", (), {})
    fastapi.status = types.SimpleNamespace(HTTP_401_UNAUTHORIZED=401)

    responses = _module("fastapi.responses")
    responses.StreamingResponse = type("StreamingResponse", (), {})
    fastapi.responses = responses

    app = _module("app")

    def _submodule(name):
        parts = name.split(".")
        for i in range(1, len(parts) + 1):
            full = ".".join(parts[:i])
            if full not in sys.modules:
                _module(full)
            if i > 1:
                parent = sys.modules[".".join(parts[: i - 1])]
                setattr(parent, parts[i - 1], sys.modules[full])
        return sys.modules[name]

    api = _submodule("app.api")
    deps = _submodule("app.api.dependencies")
    auth = _submodule("app.api.dependencies.auth")
    auth.get_current_active_user = lambda: None

    endpoints = _submodule("app.api.endpoints")
    agent_endpoints = _submodule("app.api.endpoints.agent")
    for name in (
        "list_agent_chat_sessions",
        "get_agent_chat_session",
        "save_agent_chat_display",
        "delete_agent_chat_session",
        "stop_web_agent_session_task",
    ):
        setattr(agent_endpoints, name, _make_async_stub(name))
    agent_endpoints._web_agent_stream_impl = _make_async_stub("_web_agent_stream_impl")

    principal = _submodule("app.api.principal")
    principal.ApiPrincipal = type("ApiPrincipal", (), {})

    application = _submodule("app.application")
    agent_app = _submodule("app.application.agent")
    agent_app.get_running_agent_manager = lambda: None

    messaging = _submodule("app.application.messaging")
    chat = _submodule("app.application.messaging.chat")
    chat.get_configured_agent_chat_persistence = lambda: None
    chat.get_configured_agent_chat_service = lambda: None

    schemas = _submodule("app.schemas")
    schemas_agent = _submodule("app.schemas.agent")
    schemas_agent.AgentChatDisplaySaveRequest = type("AgentChatDisplaySaveRequest", (), {})
    schemas_message = _submodule("app.schemas.message")
    schemas_message.AgentWebChatRequest = type("AgentWebChatRequest", (), {})

    sdk = _submodule("app.sdk")
    sdk_plugin = _submodule("app.sdk.plugin")
    sdk_plugin._PluginBase = _make_plugin_base()


def _make_async_stub(name):
    async def _stub(*args, **kwargs):
        return {"called": name, "args": args, "kwargs": kwargs}

    return _stub


def _make_plugin_base():
    class _PluginBase:
        def update_config(self, config: dict) -> bool:
            return False

        def save_data(self, key: str, value) -> None:
            pass

        def get_data(self, key: str):
            return None

        def get_data_path(self):
            return Path(".")

    return _PluginBase


def _load_plugin_package():
    """把插件按包加载到 eapure 命名空间（外部依赖已 stub）。"""
    name = "eapure"
    if name in sys.modules:
        return sys.modules[name]
    _install_stubs()
    spec = importlib.util.spec_from_file_location(
        name,
        PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    spec.loader.exec_module(package)
    return package


eapure = _load_plugin_package()
bridge = eapure.bridge
EnhancedAgent = eapure.EnhancedAgent


class TestSseTicket(unittest.TestCase):
    """一次性 SSE 票据生命周期。"""

    def setUp(self):
        bridge.clear_tickets()

    def tearDown(self):
        bridge.clear_tickets()

    def _issue(self):
        return asyncio.run(bridge.issue_sse_ticket(current_user="user-1"))

    def test_issue_returns_ticket(self):
        result = self._issue()
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertTrue(data["ticket"])
        self.assertEqual(data["expires_in"], bridge.TICKET_TTL_SECONDS)
        self.assertIn(data["ticket"], bridge._tickets)

    def test_ticket_consumed_once(self):
        ticket = self._issue()["data"]["ticket"]
        principal = bridge._pop_ticket(ticket)
        self.assertEqual(principal, "user-1")
        self.assertNotIn(ticket, bridge._tickets)
        with self.assertRaises(_HTTPException) as ctx:
            bridge._pop_ticket(ticket)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_unknown_ticket_rejected(self):
        with self.assertRaises(_HTTPException) as ctx:
            bridge._pop_ticket("not-a-ticket")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_expired_ticket_rejected(self):
        ticket = self._issue()["data"]["ticket"]
        bridge._tickets[ticket]["expires_at"] = time.monotonic() - 1
        with self.assertRaises(_HTTPException) as ctx:
            bridge._pop_ticket(ticket)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertNotIn(ticket, bridge._tickets)

    def test_clear_tickets(self):
        self._issue()
        self._issue()
        self.assertEqual(len(bridge._tickets), 2)
        bridge.clear_tickets()
        self.assertEqual(len(bridge._tickets), 0)

    def test_prune_removes_expired_only(self):
        alive = self._issue()["data"]["ticket"]
        dead = self._issue()["data"]["ticket"]
        bridge._tickets[dead]["expires_at"] = time.monotonic() - 1
        with bridge._tickets_lock:
            bridge._prune_tickets_locked()
        self.assertIn(alive, bridge._tickets)
        self.assertNotIn(dead, bridge._tickets)


class TestPluginMeta(unittest.TestCase):
    """插件类元数据与声明。"""

    def test_metadata(self):
        self.assertEqual(EnhancedAgent.plugin_name, "AI 助手")
        self.assertEqual(EnhancedAgent.plugin_version, "1.0.0")
        self.assertEqual(EnhancedAgent.plugin_author, "lovesakuratears")
        self.assertEqual(EnhancedAgent.plugin_config_prefix, "enhancedagent_")
        self.assertEqual(EnhancedAgent.auth_level, 1)

    def test_render_mode(self):
        self.assertEqual(EnhancedAgent.get_render_mode(), ("vue", "dist/assets"))
        self.assertTrue((PLUGIN_DIR / "dist" / "assets" / "remoteEntry.js").exists())

    def test_default_state_disabled_until_init(self):
        plugin = EnhancedAgent()
        self.assertFalse(plugin.get_state())
        self.assertEqual(plugin.get_sidebar_nav(), [])

    def test_init_plugin_enables_and_nav_appears(self):
        plugin = EnhancedAgent()
        plugin.init_plugin({"enabled": True})
        self.assertTrue(plugin.get_state())
        nav = plugin.get_sidebar_nav()
        self.assertEqual(len(nav), 1)
        self.assertEqual(nav[0]["nav_key"], "main")
        self.assertEqual(nav[0]["title"], "AI 助手")
        self.assertEqual(nav[0]["permission"], "manage")

    def test_init_plugin_disabled_hides_nav(self):
        plugin = EnhancedAgent()
        plugin.init_plugin({"enabled": False})
        self.assertFalse(plugin.get_state())
        self.assertEqual(plugin.get_sidebar_nav(), [])

    def test_form_defaults(self):
        form, defaults = EnhancedAgent().get_form()
        self.assertEqual(form, [])
        self.assertEqual(defaults, {"enabled": True})

    def test_api_routes(self):
        routes = {(item["path"], tuple(item["methods"])): item for item in EnhancedAgent().get_api()}
        expected = {
            ("/sse_ticket", ("POST",)),
            ("/stream", ("POST",)),
            ("/sessions", ("GET",)),
            ("/sessions/{session_id}", ("GET",)),
            ("/sessions/{session_id}/display", ("PUT",)),
            ("/sessions/{session_id}", ("DELETE",)),
            ("/sessions/{session_id}/stop", ("POST",)),
            ("/sessions_busy", ("POST",)),
        }
        self.assertEqual(set(routes), expected)
        # SSE 流式接口走票据鉴权（allow_anonymous），其余走宿主 Bearer
        self.assertTrue(routes[("/stream", ("POST",))]["allow_anonymous"])
        self.assertEqual(routes[("/sse_ticket", ("POST",))]["auth"], "bear")
        self.assertEqual(routes[("/sessions", ("GET",))]["auth"], "bear")
        self.assertEqual(routes[("/sessions/{session_id}", ("DELETE",))]["auth"], "bear")


if __name__ == "__main__":
    unittest.main()
