"""
EnhancedAgent：内置 Agent 的侧边栏全页入口插件。

提供「AI助手增强」全页路由（Vue 联邦组件），承载流式对话、工具卡片与
多会话管理；会话能力复用内置 Agent 的会话接口，插件自身不复制业务逻辑。
"""

from typing import Any, Dict, List, Optional, Tuple

from app.sdk.plugin import _PluginBase

from . import bridge


class EnhancedAgent(_PluginBase):
    """内置 Agent 全页入口与多会话增强插件。"""

    plugin_name = "AI助手增强"
    plugin_desc = "为内置 Agent 提供侧边栏全页入口：流式对话、工具卡片与多会话管理。"
    plugin_version = "1.0.0"
    plugin_label = "智能助手"
    plugin_author = "lovesakuratears"
    plugin_config_prefix = "enhancedagent_"
    plugin_order = 50
    auth_level = 1

    _enabled = False

    def init_plugin(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        生效配置信息并清理遗留的流式票据。

        :param config: 配置信息字典
        """
        self.stop_service()
        self._enabled = bool((config or {}).get("enabled"))

    def get_state(self) -> bool:
        """
        获取插件启用状态。
        """
        return self._enabled

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """
        声明插件使用 Vue 联邦组件渲染。
        """
        return "vue", "dist/assets"

    def get_sidebar_nav(self) -> List[Dict[str, Any]]:
        """
        声明插件在主界面左侧导航栏中的全页入口。
        """
        if not self.get_state():
            return []
        return [
            {
                "nav_key": "main",
                "title": "AI助手增强",
                "icon": "mdi-robot-happy",
                "section": "start",
                "permission": "manage",
                "order": 5,
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        """
        返回插件 API 列表（桥接内置 Agent 会话与流式对话）。
        """
        return [
            {
                "path": "/sse_ticket",
                "endpoint": bridge.issue_sse_ticket,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "签发流式对话票据",
                "description": "签发一次性短时效票据，供浏览器以无凭据 POST 消费 SSE 流。",
            },
            {
                "path": "/stream",
                "endpoint": bridge.web_agent_stream,
                "methods": ["POST"],
                "allow_anonymous": True,
                "summary": "流式对话（票据鉴权）",
                "description": "以一次性票据鉴权转发内置 Agent 的 SSE 流式对话。",
            },
            {
                "path": "/sessions",
                "endpoint": bridge.list_sessions,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取历史会话列表",
                "description": "获取当前用户可访问的 Agent 历史会话摘要。",
            },
            {
                "path": "/sessions/{session_id}",
                "endpoint": bridge.get_session,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取会话详情",
                "description": "获取一条历史会话详情，含展示消息与处理中状态。",
            },
            {
                "path": "/sessions/{session_id}/display",
                "endpoint": bridge.save_session_display,
                "methods": ["PUT"],
                "auth": "bear",
                "summary": "保存展示消息快照",
                "description": "保存前端聚合后的展示消息，可携带会话标题。",
            },
            {
                "path": "/sessions/{session_id}",
                "endpoint": bridge.delete_session,
                "methods": ["DELETE"],
                "auth": "bear",
                "summary": "删除会话",
                "description": "删除一条历史会话。",
            },
            {
                "path": "/sessions/{session_id}/stop",
                "endpoint": bridge.stop_session,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "停止会话任务",
                "description": "停止指定会话正在执行的任务。",
            },
            {
                "path": "/sessions_busy",
                "endpoint": bridge.sessions_busy,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "批量查询会话运行态",
                "description": "批量查询会话是否有正在执行的任务。",
            },
        ]

    def get_form(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        返回插件配置表单与默认配置；vue 模式下表单由 Config 组件渲染。
        """
        return [], {"enabled": True}

    def get_page(self) -> Optional[List[Dict[str, Any]]]:
        """
        vue 模式下详情页由远程 Page 组件渲染。
        """
        return []

    def stop_service(self) -> None:
        """
        停止插件服务并清理未使用的流式票据。
        """
        bridge.clear_tickets()
