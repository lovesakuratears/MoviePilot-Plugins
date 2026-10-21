"""
EnhancedAgent 桥接端点。

本文件是插件唯一允许引用 MoviePilot 内部实现的模块，负责把内置 Agent
会话接口与 SSE 流式对话暴露给插件前端（Vue 联邦组件）。其余插件文件
不得直接 import app.* 内部模块。
"""

import threading
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.api.dependencies.auth import get_current_active_user
from app.api.endpoints import agent as agent_endpoints
from app.api.principal import ApiPrincipal
from app.application import agent as agent_application
from app.application.messaging.chat import (
    get_configured_agent_chat_persistence,
    get_configured_agent_chat_service,
)
from app.schemas.agent import AgentChatDisplaySaveRequest
from app.schemas.message import AgentWebChatRequest

# 一次性 SSE 票据有效期（秒）
TICKET_TTL_SECONDS = 120

_tickets: Dict[str, Dict[str, Any]] = {}
_tickets_lock = threading.Lock()


def clear_tickets() -> None:
    """
    清空全部未使用的 SSE 票据（插件停用/重载时调用）。
    """
    with _tickets_lock:
        _tickets.clear()


def _prune_tickets_locked() -> None:
    """
    清理过期票据；调用方需持有票据锁。
    """
    now = time.monotonic()
    expired = [key for key, item in _tickets.items() if item["expires_at"] <= now]
    for key in expired:
        _tickets.pop(key, None)


def _pop_ticket(ticket: str) -> ApiPrincipal:
    """
    校验并消费一次性 SSE 票据，返回签发票据时的身份。

    :param ticket: 票据标识
    :return: 签发时记录的用户身份
    :raises HTTPException: 票据不存在或已过期时返回 401
    """
    with _tickets_lock:
        _prune_tickets_locked()
        item = _tickets.pop(ticket, None)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="票据无效或已过期",
        )
    return item["principal"]


async def issue_sse_ticket(
    current_user: ApiPrincipal = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    签发一次性短时效 SSE 票据，供浏览器以无凭据 POST 消费流式对话。

    :param current_user: 当前登录用户
    :return: 票据与有效期
    """
    ticket = uuid.uuid4().hex
    with _tickets_lock:
        _prune_tickets_locked()
        _tickets[ticket] = {
            "principal": current_user,
            "expires_at": time.monotonic() + TICKET_TTL_SECONDS,
        }
    return {"success": True, "data": {"ticket": ticket, "expires_in": TICKET_TTL_SECONDS}}


async def web_agent_stream(
    payload: AgentWebChatRequest,
    request: Request,
    ticket: str = Query(..., description="sse_ticket 签发的一次性票据"),
) -> StreamingResponse:
    """
    以票据鉴权转发内置 Agent 的 SSE 流式对话。

    :param payload: 对话请求（文本、会话标识、选择项等）
    :param request: 当前请求，用于断线检测与语言识别
    :param ticket: 一次性票据
    :return: SSE 事件流
    """
    principal = _pop_ticket(ticket)
    return await agent_endpoints._web_agent_stream_impl(
        payload,
        request,
        current_user=principal,
    )


async def list_sessions(
    current_user: ApiPrincipal = Depends(get_current_active_user),
    page: int = 1,
    count: int = 30,
) -> Any:
    """
    获取当前用户可访问的 Agent 历史会话列表。

    :param current_user: 当前登录用户
    :param page: 页码
    :param count: 每页数量
    :return: 会话摘要列表
    """
    return await agent_endpoints.list_agent_chat_sessions(
        current_user=current_user,
        service=get_configured_agent_chat_service(),
        page=page,
        count=count,
    )


async def get_session(
    session_id: str,
    current_user: ApiPrincipal = Depends(get_current_active_user),
) -> Any:
    """
    获取一条 Agent 历史会话详情（含展示消息与处理中状态）。

    :param session_id: 会话标识
    :param current_user: 当前登录用户
    :return: 会话详情
    """
    return await agent_endpoints.get_agent_chat_session(
        session_id,
        current_user=current_user,
        service=get_configured_agent_chat_service(),
    )


async def save_session_display(
    session_id: str,
    payload: AgentChatDisplaySaveRequest,
    current_user: ApiPrincipal = Depends(get_current_active_user),
) -> Any:
    """
    保存前端聚合后的展示消息快照（可携带会话标题）。

    :param session_id: 会话标识
    :param payload: 展示消息保存请求
    :param current_user: 当前登录用户
    :return: 保存后的会话摘要
    """
    return await agent_endpoints.save_agent_chat_display(
        session_id,
        payload,
        current_user=current_user,
        service=get_configured_agent_chat_service(),
        persistence=get_configured_agent_chat_persistence(),
    )


async def delete_session(
    session_id: str,
    current_user: ApiPrincipal = Depends(get_current_active_user),
) -> Any:
    """
    删除一条 Agent 历史会话。

    :param session_id: 会话标识
    :param current_user: 当前登录用户
    :return: 删除结果
    """
    return await agent_endpoints.delete_agent_chat_session(
        session_id,
        current_user=current_user,
        service=get_configured_agent_chat_service(),
    )


async def stop_session(
    session_id: str,
    current_user: ApiPrincipal = Depends(get_current_active_user),
) -> Any:
    """
    停止指定会话正在执行的任务。

    :param session_id: 会话标识
    :param current_user: 当前登录用户
    :return: 停止结果
    """
    return await agent_endpoints.stop_web_agent_session_task(
        session_id,
        current_user=current_user,
        service=get_configured_agent_chat_service(),
    )


async def sessions_busy(
    session_ids: list[str] = Body(default_factory=list, embed=True),
    current_user: ApiPrincipal = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    批量查询会话是否有正在执行的任务，供会话列表展示运行态。

    :param session_ids: 会话标识列表
    :param current_user: 当前登录用户
    :return: 会话标识到运行态的映射
    """
    manager = agent_application.get_running_agent_manager()
    busy = {
        session_id: bool(manager and manager.is_session_busy(session_id))
        for session_id in session_ids
    }
    return {"success": True, "data": {"busy": busy}}
