"""
MoviePilot 智能体工具注册（延迟导入，宿主无 Agent 能力时自动降级）。

工具通过闭包持有插件实例，运行时直接复用插件的凭据、上游客户端与缓存，
不依赖 PluginManager 反查。MoviePilotTool 的导入放在工厂函数内：
宿主缺少 app.agent 能力时 get_agent_tools 返回空列表，插件其余功能不受影响。
"""

from typing import Any, Dict, List, Optional, Type


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

    class _CheckinInput(_ExplainInput):
        """签到工具输入。"""
        pass

    class WorkBuddyCreditsTool(MoviePilotTool):
        """查询 WorkBuddy 账号剩余积分/额度。"""

        name: str = "workbuddy_query_credits"
        description: str = (
            "查询当前登录的 WorkBuddy（CodeBuddy）账号剩余积分与资源包明细。"
            "当用户询问 WorkBuddy/CodeBuddy 额度、积分余额、用量或到期时间时使用。"
        )
        args_schema: Type[BaseModel] = _ExplainInput

        def get_tool_message(self, **kwargs) -> Optional[str]:
            return "正在查询 WorkBuddy 剩余积分…"

        async def run(self, explanation: str = "", **kwargs) -> str:
            try:
                summary = await plugin.agent_credits_summary()
                return summary
            except Exception as error:  # noqa: BLE001
                return f"查询 WorkBuddy 积分失败：{error}"

    class WorkBuddyCheckinTool(MoviePilotTool):
        """立即执行 WorkBuddy 每日福利签到。"""

        name: str = "workbuddy_daily_checkin"
        description: str = (
            "立即执行 WorkBuddy（CodeBuddy）每日福利签到，领取赠送积分。"
            "当用户要求签到、领每日福利、补签时使用。"
        )
        args_schema: Type[BaseModel] = _CheckinInput

        def get_tool_message(self, **kwargs) -> Optional[str]:
            return "正在执行 WorkBuddy 每日签到…"

        async def run(self, explanation: str = "", **kwargs) -> str:
            try:
                return await plugin.agent_checkin()
            except Exception as error:  # noqa: BLE001
                return f"WorkBuddy 签到失败：{error}"

    class WorkBuddyModelsTool(MoviePilotTool):
        """列出 WorkBuddy 当前可用模型。"""

        name: str = "workbuddy_list_models"
        description: str = (
            "列出 WorkBuddy（CodeBuddy）当前可用的模型（模型 ID、上下文窗口、"
            "积分倍率）。当用户询问 WorkBuddy 有哪些模型、模型价格或选型时使用。"
        )
        args_schema: Type[BaseModel] = _ExplainInput

        def get_tool_message(self, **kwargs) -> Optional[str]:
            return "正在读取 WorkBuddy 模型列表…"

        async def run(self, explanation: str = "", **kwargs) -> str:
            try:
                return plugin.agent_models_summary()
            except Exception as error:  # noqa: BLE001
                return f"读取 WorkBuddy 模型列表失败：{error}"

    return [WorkBuddyCreditsTool, WorkBuddyCheckinTool, WorkBuddyModelsTool]
