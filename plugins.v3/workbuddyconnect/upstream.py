"""
WorkBuddy 上游 HTTP 客户端：聊天流、令牌刷新、模型目录、积分查询。

线协议的规整与解析在 protocol.py（纯函数），本模块只负责发请求与
错误映射。聊天成功返回原始 SSE 流；失败按 protocol.classify_upstream_error
分类后由调用方映射为 OpenAI 兼容层的 HTTP 状态。

HTTP 客户端使用宿主共享环境的 HTTPX2（自管 AsyncClient）。
"""

import json
from typing import Any, Dict, List, Optional

from . import protocol
from .variants import (
    ENTERPRISE_USAGE_PATH,
    ERROR_BODY_LIMIT,
    JSON_TIMEOUT_MS,
    REFRESH_PATH,
    CLIENT_VERSION,
    variant_for_region,
)

try:
    import httpx2 as _httpx
except ImportError:  # 纯逻辑测试环境回退
    import httpx as _httpx  # type: ignore


class ChatStreamResult:
    """聊天结果：成功持有可流式读取的响应，失败携带分类信息。"""

    def __init__(self, ok: bool, response: Optional[Any] = None,
                 status: int = 0, kind: str = "server", message: str = ""):
        self.ok = ok
        self.response = response
        self.status = status
        self.kind = kind
        self.message = message


class WorkBuddyUpstreamClient:
    """
    上游客户端。整个插件共享一个实例；每次调用显式传入凭据，
    以便刷新后的令牌立即生效。
    """

    def __init__(self, http_client: Optional[Any] = None,
                 chat_identity=None, app_version_getter=None):
        """
        :param http_client: 可注入的 httpx2.AsyncClient（测试用）；缺省按需建短连接
        :param chat_identity: callable(region) -> (client_version, cli_version|None)
        :param app_version_getter: callable() -> str，国际版目录 UA 版本
        """
        self._client = http_client
        self._chat_identity = chat_identity
        self._app_version_getter = app_version_getter
        self.last_catalog: Optional[Dict[str, Any]] = None

    # -- 内部 HTTP ------------------------------------------------------------

    async def _send(self, method: str, url: str, headers: Dict[str, str],
                    body: Optional[str] = None, stream: bool = False,
                    timeout: Optional[float] = None) -> Any:
        """
        发送请求。非流式响应内容已读入内存；流式响应由调用方经 _aclose 释放。
        自管客户端时把 client 挂在响应上，由 _aclose 一并关闭。
        """
        timeout = timeout if timeout is not None else JSON_TIMEOUT_MS / 1000
        if self._client is not None:
            request = self._client.build_request(method, url, headers=headers,
                                                 content=body, timeout=timeout)
            return await self._client.send(request, stream=stream)
        client = _httpx.AsyncClient(timeout=timeout)
        request = client.build_request(method, url, headers=headers, content=body)
        try:
            response = await client.send(request, stream=stream)
        except BaseException:
            await client.aclose()
            raise
        if stream:
            # 流式：连接随响应存活，调用方读完后经 _aclose 关闭
            response._wb_own_client = client  # type: ignore[attr-defined]
        else:
            # 非流式：send 已读完响应，立即释放客户端
            await client.aclose()
        return response

    @staticmethod
    async def _aclose(response: Any) -> None:
        own = getattr(response, "_wb_own_client", None)
        try:
            await response.aclose()
        finally:
            if own is not None:
                await own.aclose()

    def _chat_ua(self, region: str) -> str:
        if self._chat_identity is not None:
            try:
                client_version, cli_version = self._chat_identity(region)
                return protocol.chat_user_agent(region, client_version, cli_version)
            except Exception:  # noqa: BLE001 - 身份解析永不阻塞消息
                pass
        variant = variant_for_region(region)
        return protocol.chat_user_agent(region, variant.fallback_app_version())

    # -- 聊天 -----------------------------------------------------------------

    async def chat_stream(self, credential: Any, body_json: str,
                          default_effort: Optional[str] = None) -> ChatStreamResult:
        """
        POST 聊天端点；成功返回原始 SSE 响应（调用方流式读取并释放）。

        国际版优先 console 路径；仅路由缺失（404/405）或 WAF 拦截页 403
        才回落到共用路径。会话头族在路径回退间保持不变（同一次发送）。
        """
        region = protocol.realm_of(credential)
        variant = variant_for_region(region)
        uid = getattr(credential, "uid", "") or ""
        if region == "global":
            prepared = protocol.prepare_international_chat_body(body_json, default_effort)
        else:
            prepared = protocol.prepare_chat_body(body_json, default_effort)
        prepared = protocol.with_prompt_cache_key(prepared, uid)
        headers = protocol.with_gateway_chat_headers(
            protocol.build_chat_headers(credential, self._chat_ua(region)), prepared,
        )
        last_failure: Optional[Dict[str, Any]] = None
        for path in variant.chat_paths():
            try:
                response = await self._send(
                    "POST", f"{variant.chat_base()}{path}", headers, prepared, stream=True,
                    timeout=600.0,
                )
            except Exception as error:  # noqa: BLE001 - 传输失败可试下一个路径
                last_failure = {"status": 0, "text": f"transport error: {error}"}
                continue
            if response.status_code < 400:
                return ChatStreamResult(True, response=response)
            # 流式响应的错误体必须先读入内存才能取 text
            failure_text = ""
            try:
                await response.aread()
                failure_text = (response.text or "")[:ERROR_BODY_LIMIT]
            except Exception:  # noqa: BLE001
                failure_text = ""
            status = response.status_code
            await self._aclose(response)
            last_failure = {"status": status, "text": failure_text}
            if not protocol.path_fallback_status(status, failure_text):
                break
        failure = last_failure or {"status": 0, "text": "no chat endpoint answered"}
        status = failure["status"]
        kind = "server" if status == 0 else protocol.classify_upstream_error(status, failure["text"])
        return ChatStreamResult(False, status=status, kind=kind, message=failure["text"])

    # -- 信封调用 -------------------------------------------------------------

    async def _envelope_request(self, method: str, url: str, headers: Dict[str, str],
                                body: Optional[str] = None) -> Dict[str, Any]:
        response = await self._send(method, url, headers, body)
        text = response.text or ""
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            raise RuntimeError(
                f"workbuddy 上游返回非 JSON（http {response.status_code}）：{text[:160]}"
            ) from None
        envelope = protocol.read_envelope(parsed)
        if response.status_code >= 400 or envelope["code"] != 0:
            kind = protocol.classify_upstream_error(response.status_code, envelope["msg"] or text)
            raise RuntimeError(
                f"workbuddy 上游 {kind}（http {response.status_code}, code {envelope['code']}）："
                f"{(envelope['msg'] or text)[:160]}"
            )
        return envelope

    # -- 令牌刷新 -------------------------------------------------------------

    async def refresh_token(self, credential: Any) -> Dict[str, Any]:
        """POST 刷新端点；返回 {accessToken, refreshToken?, expiresInSec?, domain?}。"""
        region = protocol.realm_of(credential)
        variant = variant_for_region(region)
        envelope = await self._envelope_request(
            "POST", f"{variant.chat_base()}{REFRESH_PATH}",
            protocol.build_refresh_headers(credential), None,
        )
        data = envelope["data"] if isinstance(envelope["data"], dict) else {}
        access_token = data.get("accessToken") if isinstance(data.get("accessToken"), str) else ""
        if not access_token:
            raise RuntimeError("workbuddy 令牌刷新未返回 accessToken；请重新登录")
        outcome: Dict[str, Any] = {"accessToken": access_token}
        if isinstance(data.get("refreshToken"), str) and data["refreshToken"]:
            outcome["refreshToken"] = data["refreshToken"]
        if isinstance(data.get("expiresIn"), (int, float)) and data["expiresIn"] > 0:
            outcome["expiresInSec"] = data["expiresIn"]
        if isinstance(data.get("domain"), str) and data["domain"]:
            outcome["domain"] = data["domain"]
        return outcome

    # -- 模型目录 -------------------------------------------------------------

    async def fetch_models(self, credential: Any) -> List[Dict[str, Any]]:
        """
        拉取模型目录。国内版走官方 CLI 同款接口；国际版走 App 文档接口
        （按 UA 分流，携带 App 形态 UA）。两种响应形态统一解析。
        """
        region = protocol.realm_of(credential)
        variant = variant_for_region(region)
        international = region == "global"
        app_version = None
        if international and self._app_version_getter is not None:
            try:
                app_version = self._app_version_getter()
            except Exception:  # noqa: BLE001
                app_version = None
        if international:
            app_version = app_version or variant.fallback_app_version()
        headers = {
            "Authorization": f"Bearer {credential.access_token}",
            "Accept": "application/json",
            "Origin": variant.login_origin(),
            "Referer": f"{variant.login_origin()}/",
            "User-Agent": protocol.app_user_agent(app_version) if international else "CLI/2.63.2 CodeBuddy/2.63.2",
        }
        if international:
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["X-Product"] = "SaaS"
        path = "/v3/config" if international else "/console/enterprises/personal/models"
        envelope = await self._envelope_request(
            "GET", f"{variant.chat_base()}{path}", headers,
        )
        # 两种目录形态：标准 {code,msg,data} 信封，或文档直接顶在顶层
        data = envelope["data"] if isinstance(envelope["data"], dict) else {}
        if not data and ("models" in envelope["document"] or "agents" in envelope["document"]):
            data = envelope["document"]
        models = protocol.parse_model_catalog(data, international)
        self.last_catalog = {
            "fetchedAtMs": __import__("time").time() * 1000,
            "source": "workbuddy-ai:app" if international else "workbuddy:cli",
        }
        return models

    # -- 积分/额度 ------------------------------------------------------------

    async def fetch_credits(self, credential: Any) -> Dict[str, Any]:
        """
        聚合剩余积分。国内版企业账号走企业专用接口（个人接口对其返回空
        资源包列表，会渲染成错误的 0 积分）；其余走个人资源包接口。
        """
        region = protocol.realm_of(credential)
        enterprise_id = getattr(credential, "enterprise_id", None) or getattr(credential, "enterpriseId", None)
        if region == "cn" and enterprise_id:
            return await self._fetch_enterprise_credits(credential)
        variant = variant_for_region(region)
        body = protocol.billing_request_body()
        headers = protocol.build_billing_headers(credential)
        last_status = 0
        envelope: Optional[Dict[str, Any]] = None
        for path in variant.billing_meter_paths():
            response = await self._send(
                "POST", f"{variant.billing_base()}{path}", headers, body,
            )
            last_status = response.status_code
            text = response.text or ""
            if response.status_code < 400 or not protocol.path_fallback_status(response.status_code):
                try:
                    parsed = json.loads(text)
                except (ValueError, TypeError):
                    raise RuntimeError(
                        f"workbuddy 计费端点返回非 JSON（http {response.status_code}）：{text[:160]}"
                    ) from None
                envelope = protocol.read_envelope(parsed)
                break
        if envelope is None:
            raise RuntimeError(f"workbuddy 计费端点不可用（http {last_status}）")
        if envelope["code"] != 0:
            kind = protocol.classify_upstream_error(last_status, envelope["msg"])
            raise RuntimeError(f"workbuddy 上游 {kind}（http {last_status}）：{envelope['msg'][:160]}")
        return protocol.parse_personal_credits(envelope["document"])

    async def _fetch_enterprise_credits(self, credential: Any) -> Dict[str, Any]:
        """国内版企业周期额度：身份在请求头，请求体为空对象。"""
        from .variants import CN_BILLING_BASE
        envelope = await self._envelope_request(
            "POST", f"{CN_BILLING_BASE}{ENTERPRISE_USAGE_PATH}",
            protocol.build_billing_headers(credential), "{}",
        )
        return protocol.parse_enterprise_credits(envelope["document"])
