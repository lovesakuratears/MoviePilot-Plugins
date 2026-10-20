"""
MoviePilot 智能体工具注册（延迟导入，宿主无 Agent 能力时自动降级）。

工具通过闭包持有插件实例，运行时直接复用插件的目录缓存与配置，
不依赖 PluginManager 反查。MoviePilotTool 的导入放在工厂函数内：
宿主缺少 app.agent 能力时 get_agent_tools 返回空列表，插件其余功能不受影响。
"""

from typing import Any, List, Optional, Type


def build_agent_tools(plugin: Any) -> List[Type]:
    """
    为宿主智能助手构造本插件的工具类列表。

    每个工具类必须继承 MoviePilotTool，并实现 run / get_tool_message。
    """
    try:
        from pydantic import BaseModel, Field  # noqa: PLC0415
        from app.agent.tools.base import MoviePilotTool  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - 宿主无智能体能力时降级
        return []

    class _ExplainInput(BaseModel):
        """工具公共输入：智能体注入的使用说明。"""
        explanation: str = Field(..., description="工具使用说明，说明为什么调用本工具")

    class _SwitchInput(_ExplainInput):
        """切换默认模型的输入。"""
        model_id: str = Field(..., description="要切换到的模型 ID（可用 ourfree_list_models 查询）")

    class OurFreeListModelsTool(MoviePilotTool):
        """列出免费模型车道当前可用模型。"""

        name: str = "ourfree_list_models"
        description: str = (
            "列出「我们的免费模型」插件当前可用的免费模型（模型 ID、车道、上下文窗口、"
            "思考能力、视觉能力）。当用户询问有哪些免费模型、想换模型、或比较模型能力时使用。"
        )
        args_schema: Type[BaseModel] = _ExplainInput

        def get_tool_message(self, **kwargs) -> Optional[str]:
            return "正在读取免费模型列表…"

        async def run(self, explanation: str = "", **kwargs) -> str:
            try:
                return await plugin.agent_models_summary()
            except Exception as error:  # noqa: BLE001
                return f"读取免费模型列表失败：{error}"

    class OurFreeSwitchModelTool(MoviePilotTool):
        """切换插件的默认模型（影响 OpenAI 兼容端点缺省模型）。"""

        name: str = "ourfree_switch_model"
        description: str = (
            "把「我们的免费模型」插件的默认模型切换为指定模型 ID，之后智能助手默认使用该模型。"
            "当用户要求换用某个免费模型、切换到某模型时使用。"
        )
        args_schema: Type[BaseModel] = _SwitchInput

        def get_tool_message(self, **kwargs) -> Optional[str]:
            return "正在切换默认模型…"

        async def run(self, model_id: str = "", explanation: str = "", **kwargs) -> str:
            try:
                return await plugin.agent_switch_model(str(model_id or "").strip())
            except Exception as error:  # noqa: BLE001
                return f"切换默认模型失败：{error}"

    class OurFreeStatusTool(MoviePilotTool):
        """查看免费模型车道状态（目录新鲜度、接入配置）。"""

        name: str = "ourfree_status"
        description: str = (
            "查看「我们的免费模型」插件运行状态：模型目录数量与刷新时间、默认模型、"
            "智能助手接入地址。当用户询问免费模型插件状态、接入方式是否正常时使用。"
        )
        args_schema: Type[BaseModel] = _ExplainInput

        def get_tool_message(self, **kwargs) -> Optional[str]:
            return "正在读取免费模型插件状态…"

        async def run(self, explanation: str = "", **kwargs) -> str:
            try:
                return await plugin.agent_status_summary()
            except Exception as error:  # noqa: BLE001
                return f"读取插件状态失败：{error}"

    return [OurFreeListModelsTool, OurFreeSwitchModelTool, OurFreeStatusTool]
