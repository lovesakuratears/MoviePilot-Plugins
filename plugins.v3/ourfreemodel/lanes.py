"""
免费车道 HTTP 客户端：OpenCode 免密车道与 Kilo 免费池。

移植自 dsh-our-free-model 的 src/upstream.js / src/kilo.js 出网部分（MIT）。
只负责发请求与错误映射；线协议的规整与解析在 translate.py / wire.py。

HTTP 客户端使用宿主共享环境的 HTTPX2（自管 AsyncClient），纯逻辑测试
环境回退 httpx。
"""

from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from .catalog import LANE_KILO, LANE_OPENCODE
from .wire import gateway_headers

try:
    import httpx2 as _httpx
except ImportError:  # 纯逻辑测试环境回退
    import httpx as _httpx  # type: ignore

#: OpenCode 免密车道基址（源仓库 2026-10-14 迁移后的现行端点）。
OPENCODE_BASE = "https://opencode.ai"

#: Kilo 免费池基址。
KILO_BASE = "https://api.kilo.ai/api/gateway"

LISTING_TIMEOUT = 15.0
TURN_TIMEOUT = 300.0
KILO_UA = "moviepilot-ourfreemodel"


class LaneError(Exception):
    """车道请求失败（携带分类与上游消息）。"""

    def __init__(self, message: str, kind: str = "server", status: int = 0, retry_after: Optional[float] = None):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after


def classify_http_error(status: int, text: str, retry_after: Optional[float] = None) -> LaneError:
    """HTTP 失败 → 分类错误（kind 对齐 OpenAI error.type 词汇）。"""
    snippet = (text or "")[:300] or f"HTTP {status}"
    lowered = snippet.lower()
    if status in (401, 403):
        if "region" in lowered:
            return LaneError(snippet, kind="region_restricted", status=status)
        return LaneError(snippet, kind="unauthorized", status=status, retry_after=retry_after)
    if status == 404:
        return LaneError(snippet, kind="not_found", status=status)
    if status == 429:
        return LaneError(snippet, kind="rate_limit", status=status, retry_after=retry_after)
    if status == 400:
        return LaneError(snippet, kind="invalid_request", status=status)
    if status >= 500:
        return LaneError(snippet, kind="server", status=status, retry_after=retry_after)
    return LaneError(snippet, kind="server", status=status)


class _StreamHandle:
    """一次流式响应的持有者：逐条产出 SSE data 载荷。"""

    def __init__(self, response: Any) -> None:
        self.response = response

    async def iter_data(self) -> AsyncIterator[str]:
        """产出 ``data:`` 后的载荷字符串（含 `[DONE]`，注释行与空行跳过）。"""
        buffer = ""
        async for chunk in self.response.aiter_bytes():
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.rstrip("\r")
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    yield line[5:].strip()
        tail = buffer.strip()
        if tail.startswith("data:"):
            yield tail[5:].strip()

    async def aclose(self) -> None:
        try:
            await self.response.aclose()
        except Exception:  # noqa: BLE001
            pass


class LaneClient:
    """
    车道客户端。整个插件共享一个实例；每次调用显式传入会话信号。

    可注入 ``http_client``（测试用）；缺省按需建短连接。
    """

    def __init__(self, http_client: Optional[Any] = None) -> None:
        self._client = http_client

    async def _get_client(self) -> Any:
        if self._client is None:
            self._client = _httpx.AsyncClient(
                timeout=_httpx.Timeout(TURN_TIMEOUT, connect=15.0),
                follow_redirects=False,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    # -- 模型清单 ---------------------------------------------------------

    async def fetch_opencode_listing(self) -> List[str]:
        """GET 免密车道模型清单，返回原始 id 列表。"""
        client = await self._get_client()
        try:
            response = await client.get(
                f"{OPENCODE_BASE}/inference/v1/models",
                headers={"accept": "application/json"},
                timeout=LISTING_TIMEOUT,
            )
        except Exception as error:  # noqa: BLE001
            raise LaneError(f"模型清单请求失败：{error}", kind="transport") from error
        if response.status_code != 200:
            raise classify_http_error(response.status_code, response.text)
        try:
            payload = response.json()
        except ValueError as error:
            raise LaneError("模型清单不是合法 JSON", kind="server") from error
        from .catalog import parse_listing  # 延迟导入保持模块边界
        return parse_listing(payload)

    async def fetch_kilo_listing(self) -> List[Dict[str, Any]]:
        """GET Kilo 模型清单，返回原始行列表（含 isFree 标记）。"""
        client = await self._get_client()
        try:
            response = await client.get(
                f"{KILO_BASE}/models",
                headers={"accept": "application/json", "user-agent": KILO_UA},
                timeout=LISTING_TIMEOUT,
            )
        except Exception as error:  # noqa: BLE001
            raise LaneError(f"Kilo 清单请求失败：{error}", kind="transport") from error
        if response.status_code != 200:
            raise classify_http_error(response.status_code, response.text)
        try:
            payload = response.json()
        except ValueError as error:
            raise LaneError("Kilo 清单不是合法 JSON", kind="server") from error
        if isinstance(payload, dict):
            rows = payload.get("data") or payload.get("models") or []
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []
        return [row for row in rows if isinstance(row, dict)]

    # -- 聊天流 -----------------------------------------------------------

    async def open_chat_stream(
        self,
        lane: str,
        payload: Dict[str, Any],
        session_id: str = "",
        model_id: str = "",
    ) -> _StreamHandle:
        """
        POST 一轮聊天并返回流句柄（SSE 或单 JSON，由上层按形状解析）。

        :param lane: ``opencode`` / ``kilo``
        :param payload: 目标线协议请求体（translate.build_payload 产物）
        :param session_id: 已解析的上游会话 ID（免密车道指纹头使用）
        """
        client = await self._get_client()
        if lane == LANE_KILO:
            url = f"{KILO_BASE}/chat/completions"
            headers = {
                "content-type": "application/json",
                "accept": "text/event-stream",
                "user-agent": KILO_UA,
            }
        else:
            from .wire import endpoint_for
            url = f"{OPENCODE_BASE}{endpoint_for(model_id or payload.get('model'))}"
            stream = payload.get("stream") is not False
            headers = gateway_headers(session_id, stream=stream)
        try:
            request = client.build_request("POST", url, headers=headers, json=payload)
            response = await client.send(request, stream=True)
        except Exception as error:  # noqa: BLE001
            raise LaneError(f"聊天请求失败：{error}", kind="transport") from error
        if response.status_code != 200:
            try:
                text = (await response.aread()).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                text = ""
            await response.aclose()
            retry_after = None
            raw_retry = response.headers.get("retry-after")
            if raw_retry:
                try:
                    retry_after = float(raw_retry) * 1000.0
                except ValueError:
                    retry_after = None
            raise classify_http_error(response.status_code, text, retry_after=retry_after)
        return _StreamHandle(response)

    async def fetch_chat_completion(
        self,
        lane: str,
        payload: Dict[str, Any],
        session_id: str = "",
        model_id: str = "",
    ) -> Tuple[List[str], Optional[str]]:
        """
        非流式请求便捷入口：返回 (SSE data 载荷列表, 末尾形状提示)。

        上游一律按流式请求（免密车道只放行 stream），这里内部收集全部载荷。
        """
        handle = await self.open_chat_stream(lane, payload, session_id, model_id)
        events: List[str] = []
        try:
            async for data in handle.iter_data():
                events.append(data)
        finally:
            await handle.aclose()
        return events, None
