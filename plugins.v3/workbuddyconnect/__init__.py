"""
WorkBuddy 连接器（MoviePilot V3 插件）。

把 WorkBuddy（国内版）/ WorkBuddy AI（国际版）的模型桥接为 OpenAI 兼容接口，
供 MoviePilot 智能助手（LLM_BASE_URL）直接调用；同时提供登录、额度、
模型目录、每日签到等管理接口与智能体工具。

协议移植自 dsh-workbuddy-connect（MIT）：设备授权登录、令牌自动续期、
聊天流转发（含请求体规整与网关会话头）、模型目录、计费与签到。

接入方式（系统设置 → 智能助手）：
    LLM提供商   openai（OpenAI 兼容）
    LLM基础URL  http://127.0.0.1:3000/api/v1/plugin/WorkBuddyConnect/v1
    LLM API密钥 插件设置页的「访问密钥」
    LLM模型名称 如 glm-5.2（详情页可查看完整模型列表）
"""

import secrets
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 宿主导入：优先 V3 稳定 SDK，回退旧版路径；都不可用时提供离线测试占位
# ---------------------------------------------------------------------------

try:
    from app.sdk.plugin import _PluginBase
except Exception:  # noqa: BLE001
    try:
        from app.plugins import _PluginBase  # type: ignore
    except Exception:  # noqa: BLE001
        class _PluginBase:  # type: ignore
            """离线测试占位基类。"""
            def update_config(self, config: dict) -> bool:
                return False

            def save_data(self, key: str, value: Any) -> None:
                pass

            def get_data(self, key: str) -> Any:
                return None

            def get_data_path(self):
                from pathlib import Path
                return Path(".")

            def post_message(self, **kwargs) -> None:
                pass

try:
    from app.sdk.logging import logger
except Exception:  # noqa: BLE001
    try:
        from app.log import logger  # type: ignore
    except Exception:  # noqa: BLE001
        import logging
        logger = logging.getLogger("workbuddyconnect")  # type: ignore

try:
    from app.sdk.events import Event, eventmanager
except Exception:  # noqa: BLE001
    try:
        from app.core.event import Event, eventmanager  # type: ignore
    except Exception:  # noqa: BLE001
        Event = object  # type: ignore

        class _EventManagerStub:  # type: ignore
            @staticmethod
            def register(_event_type):
                def decorator(func):
                    return func
                return decorator
        eventmanager = _EventManagerStub()  # type: ignore

try:
    from app.schemas.types import EventType
except Exception:  # noqa: BLE001
    class EventType:  # type: ignore
        PluginAction = "PluginAction"

try:
    from app.schemas import NotificationType
except Exception:  # noqa: BLE001
    class NotificationType:  # type: ignore
        Plugin = "Plugin"

from apscheduler.triggers.cron import CronTrigger
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from . import protocol
from .auth import CredentialStore, WorkBuddyCredential
from .catalog import CatalogStore
from .checkin import WorkBuddyCheckInService
from .login import WorkBuddyLoginClient
from .upstream import WorkBuddyUpstreamClient
from .variants import REGION_CN, REGION_GLOBAL, REGION_LABELS, variant_for_region

# ---------------------------------------------------------------------------
# API 响应模型（普通 JSON 端点必须声明具体 response_model）
# ---------------------------------------------------------------------------


class LoginBeginRequest(BaseModel):
    """发起登录请求体。"""
    region: Optional[str] = Field(None, description="区域：cn / global；缺省用插件配置")


class LoginBeginResult(BaseModel):
    """发起登录结果：state 与需要打开的授权链接。"""
    state: str
    authUrl: str
    region: str


class LoginPollRequest(BaseModel):
    """轮询登录请求体。"""
    state: Optional[str] = Field(None, description="待确认的 state；缺省用插件挂起的登录")


class LoginPollResult(BaseModel):
    """轮询登录结果。"""
    status: str = Field(..., description="pending / complete / error")
    message: Optional[str] = None
    nickname: Optional[str] = None
    uid: Optional[str] = None


class CheckinResult(BaseModel):
    """签到结果。"""
    date: str
    status: str = Field(..., description="claimed / already-claimed / no-campaign / error")
    amount: Optional[float] = None
    message: Optional[str] = None


class CatalogRefreshResult(BaseModel):
    """目录刷新结果。"""
    count: int
    source: str
    message: Optional[str] = None


class CreditsPackage(BaseModel):
    """单个资源包额度。"""
    packageName: str
    remain: float
    size: float
    packageEndTime: Optional[str] = None
    unlimited: Optional[bool] = None


class CreditsResult(BaseModel):
    """聚合额度。"""
    total: float = 0
    totalSize: Optional[float] = None
    unlimited: Optional[bool] = None
    cycleResetTime: Optional[str] = None
    accounts: List[CreditsPackage] = Field(default_factory=list)


class SimpleResult(BaseModel):
    """通用结果。"""
    success: bool
    message: Optional[str] = None


class ImportRequest(BaseModel):
    """导入凭据请求体：workbuddy.json 全文。"""
    text: str = Field(..., description="workbuddy.json 文档内容")


class ModelBrief(BaseModel):
    """模型摘要。"""
    id: str
    name: str
    contextWindow: int = 0
    maxTokens: int = 0
    supportsImages: bool = False
    credits: Optional[str] = None
    badges: Optional[List[str]] = None
    free: bool = False
    rateUnknown: Optional[bool] = None


class StatusResult(BaseModel):
    """插件完整状态（详情页数据源）。"""
    enabled: bool
    region: str
    regionLabel: str
    signedIn: bool
    nickname: Optional[str] = None
    uid: Optional[str] = None
    domain: Optional[str] = None
    expiresAtMs: Optional[int] = None
    pendingLogin: Optional[Dict[str, Any]] = None
    catalogSource: str = "builtin"
    models: List[ModelBrief] = Field(default_factory=list)
    credits: Optional[CreditsResult] = None
    lastCheckin: Optional[CheckinResult] = None
    llmBaseUrl: str = ""
    llmApiKey: str = ""
    defaultModel: Optional[str] = None


class WorkBuddyConnect(_PluginBase):
    """WorkBuddy 连接器：模型接入 MoviePilot 智能助手 + 账号管理。"""

    plugin_name = "WorkBuddy连接器"
    plugin_desc = "将 WorkBuddy（国内版）/ WorkBuddy AI（国际版）模型接入智能助手：OpenAI 兼容接口、额度查询、每日签到。"
    plugin_icon = "Workbuddy_A.png"
    plugin_version = "1.0.0"
    plugin_author = "masknull"
    author_url = "https://github.com/masknull/dsh-workbuddy-connect"
    plugin_config_prefix = "workbuddyconnect_"
    plugin_order = 40
    auth_level = 1

    # -- 配置字段 -----------------------------------------------------------
    _enabled: bool = False
    _region: str = REGION_CN
    _api_key: str = ""
    _checkin_enabled: bool = True
    _checkin_hour: int = 10
    _notify: bool = True
    _disabled_models: str = ""
    _client_version: str = ""

    # -- 运行时状态 ---------------------------------------------------------
    _store: Optional[CredentialStore] = None
    _login_client: Optional[WorkBuddyLoginClient] = None
    _upstream: Optional[WorkBuddyUpstreamClient] = None
    _checkin_service: Optional[WorkBuddyCheckInService] = None
    _catalog: Optional[CatalogStore] = None
    _pending_login: Optional[Dict[str, Any]] = None
    _credits_cache: Optional[Dict[str, Any]] = None
    _credits_cached_at: float = 0.0
    _last_checkin: Optional[Dict[str, Any]] = None

    # ==================================================================
    # 生命周期
    # ==================================================================

    def init_plugin(self, config: dict = None) -> None:
        """读取配置并建立本次运行状态；允许重复调用。"""
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._region = REGION_GLOBAL if config.get("region") == REGION_GLOBAL else REGION_CN
        self._api_key = str(config.get("api_key") or "")
        self._checkin_enabled = bool(config.get("checkin_enabled", True))
        try:
            self._checkin_hour = max(0, min(23, int(config.get("checkin_hour") or 10)))
        except (TypeError, ValueError):
            self._checkin_hour = 10
        self._notify = bool(config.get("notify", True))
        self._disabled_models = str(config.get("disabled_models") or "")
        self._client_version = str(config.get("client_version") or "").strip()

        # 访问密钥缺失时生成一个并回写配置（OpenAI 兼容端点的 Bearer 口令）
        if not self._api_key:
            self._api_key = secrets.token_urlsafe(24)
            config["api_key"] = self._api_key
            self.update_config(config)

        variant = variant_for_region(self._region)
        data_path = self.get_data_path()
        state_dir = data_path / "state"
        self._store = CredentialStore(
            path=data_path / variant.auth_filename,
            expected_region=self._region,
            refresh_func=self._refresh_credential,
        )
        self._login_client = WorkBuddyLoginClient()
        self._upstream = WorkBuddyUpstreamClient(
            chat_identity=self._resolve_chat_identity,
            app_version_getter=self._resolve_app_version,
        )
        self._checkin_service = WorkBuddyCheckInService()
        self._catalog = CatalogStore(state_dir, variant.catalog_filename, self._region)

        # 恢复重启前挂起的登录尝试（30 分钟内有效）
        self._pending_login = self.get_data("pending_login")
        if isinstance(self._pending_login, dict):
            created = float(self._pending_login.get("createdAt") or 0)
            if not created or time.time() - created > 1800:
                self._pending_login = None
                self.save_data("pending_login", None)
        self._last_checkin = self.get_data("last_checkin")

        if self._enabled:
            self._start_warmup()

    def get_state(self) -> bool:
        """返回插件是否启用。"""
        return self._enabled

    def stop_service(self) -> None:
        """释放运行时状态；可重复调用。"""
        self._pending_login = None
        self._credits_cache = None

    # ==================================================================
    # 内部：身份与凭证
    # ==================================================================

    def _plugin_id(self) -> str:
        """当前实例 ID（虚拟分身兼容：以类名为准）。"""
        return self.__class__.__name__

    def _resolve_chat_identity(self, region: str) -> Tuple[str, Optional[str]]:
        """聊天 UA 的版本来源：配置覆盖 → 内置回退（无桌面端可读）。"""
        version = self._client_version or variant_for_region(region).fallback_app_version()
        return version, None

    @staticmethod
    def _resolve_app_version() -> str:
        """国际版目录 UA 版本：无桌面端可读，使用内置回退。"""
        return variant_for_region(REGION_GLOBAL).fallback_app_version()

    async def _refresh_credential(self, credential: WorkBuddyCredential) -> Dict[str, Any]:
        """令牌刷新回调（CredentialStore 按需调用）。"""
        return await self._upstream.refresh_token(credential)

    async def _resolve_credential(self) -> WorkBuddyCredential:
        """取可用凭据（自动续期）。"""
        return await self._store.resolve()

    # ==================================================================
    # OpenAI 兼容端点（供 MoviePilot 智能助手 LLM_BASE_URL 接入）
    # ==================================================================

    def _bearer_error(self, message: str, err_type: str = "unauthorized") -> Any:
        return JSONResponse(
            status_code=401,
            content={"error": {"message": message, "type": err_type, "code": err_type}},
        )

    def _check_api_key(self, request: Request) -> Optional[Any]:
        """校验 OpenAI 兼容端点的 Bearer 访问密钥。"""
        header = request.headers.get("authorization", "") or ""
        if not header.lower().startswith("bearer "):
            return self._bearer_error("missing Authorization bearer")
        presented = header[7:].strip()
        if not self._api_key or not secrets.compare_digest(presented, self._api_key):
            return self._bearer_error("invalid api key")
        return None

    def _disabled_set(self) -> set:
        return {item.strip() for item in self._disabled_models.split(",") if item.strip()}

    async def openai_models(self, request: Request) -> Any:
        """GET /v1/models —— OpenAI 协议模型列表。"""
        denied = self._check_api_key(request)
        if denied is not None:
            return denied
        signed_in = self._store.status().get("state") == "signed-in"
        disabled = self._disabled_set()
        models = [
            model for model in self._catalog.current(signed_in=signed_in)
            if model.get("id") not in disabled
        ]
        return JSONResponse(content={
            "object": "list",
            "data": [
                {"id": m.get("id"), "object": "model", "created": 0, "owned_by": "workbuddy"}
                for m in models
            ],
        })

    async def openai_chat_completions(self, request: Request) -> Any:
        """
        POST /v1/chat/completions —— OpenAI 协议聊天。
        请求 stream=true 时透传上游 SSE；否则服务端聚合成 chat.completion JSON。
        """
        denied = self._check_api_key(request)
        if denied is not None:
            return denied

        raw = (await request.body()).decode("utf-8", errors="replace")
        try:
            import json as _json
            body = _json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        model_id = body.get("model") if isinstance(body.get("model"), str) else ""
        wants_stream = body.get("stream") is True

        try:
            credential = await self._resolve_credential()
        except PermissionError as error:
            return JSONResponse(
                status_code=401,
                content={"error": {"message": str(error), "type": "not_signed_in", "code": "not_signed_in"}},
            )

        default_effort = self._catalog.default_effort_for(model_id) if model_id else None
        try:
            result = await self._upstream.chat_stream(credential, raw, default_effort=default_effort)
        except Exception as error:  # noqa: BLE001
            logger.error(f"WorkBuddy 聊天请求失败：{error}")
            return JSONResponse(
                status_code=502,
                content={"error": {"message": str(error), "type": "server", "code": "server"}},
            )

        if not result.ok:
            status = protocol.KIND_STATUS.get(result.kind, 502)
            return JSONResponse(
                status_code=status,
                content={"error": {
                    "message": f"workbuddy upstream {result.kind} (http {result.status}): {result.message[:400]}",
                    "type": result.kind, "code": result.kind,
                }},
            )

        if wants_stream:
            return StreamingResponse(
                self._pipe_sse(result),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # 非流式：服务端聚合 SSE 为 chat.completion
        events: List[str] = []
        buffer = ""
        try:
            async for chunk in result.response.aiter_bytes():
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.rstrip("\r")
                    if line.startswith("data:"):
                        events.append(line[5:].strip())
        finally:
            await self._upstream.aclose(result.response)
        return JSONResponse(content=protocol.aggregate_chat_completion(events, model_id))

    async def _pipe_sse(self, result: Any):
        """把上游 SSE 字节流透传给客户端；上游中断时补 [DONE] 终帧。"""
        saw_done = False
        try:
            async for chunk in result.response.aiter_bytes():
                if b"[DONE]" in chunk:
                    saw_done = True
                yield chunk
        except Exception as error:  # noqa: BLE001
            logger.warning(f"WorkBuddy 上游流中断：{error}")
            if not saw_done:
                yield b": stream interrupted\n\ndata: [DONE]\n\n"
        finally:
            await self._upstream.aclose(result.response)

    # ==================================================================
    # 管理端点（详情页按钮 / 前端调用，走宿主 bear 认证）
    # ==================================================================

    async def api_login_begin(self, payload: Optional[LoginBeginRequest] = None) -> LoginBeginResult:
        """发起设备授权登录，返回授权链接。"""
        region = payload.region if payload and payload.region else self._region
        if region not in (REGION_CN, REGION_GLOBAL):
            region = self._region
        attempt = await self._login_client.begin(region)
        self._pending_login = {
            "state": attempt["state"],
            "authUrl": attempt["authUrl"],
            "region": region,
            "createdAt": time.time(),
        }
        self.save_data("pending_login", self._pending_login)
        return LoginBeginResult(**attempt)

    async def api_login_poll(self, payload: Optional[LoginPollRequest] = None) -> LoginPollResult:
        """轮询一次登录结果；完成即保存凭据。"""
        return await self._poll_pending_login(payload.state if payload else None)

    async def api_status(self) -> StatusResult:
        """插件完整状态。"""
        return self._build_status()

    async def api_checkin(self) -> CheckinResult:
        """立即执行每日签到。"""
        result = await self._do_checkin()
        return CheckinResult(**result)

    async def api_catalog_refresh(self) -> CatalogRefreshResult:
        """强制刷新模型目录。"""
        try:
            credential = await self._resolve_credential()
            models = await self._upstream.fetch_models(credential)
            self._catalog.set_live(models)
            return CatalogRefreshResult(count=len(models), source="live")
        except Exception as error:  # noqa: BLE001
            self._catalog.set_error(str(error))
            models = self._catalog.current(signed_in=self._store.status().get("state") == "signed-in")
            return CatalogRefreshResult(
                count=len(models), source=self._catalog.source(), message=str(error),
            )

    async def api_credits_refresh(self) -> CreditsResult:
        """强制刷新额度。"""
        credits = await self._fetch_credits(force=True)
        return self._credits_model(credits or {"total": 0, "accounts": []})

    async def api_logout(self) -> SimpleResult:
        """退出登录：删除本区域凭据。"""
        self._store.logout()
        self._credits_cache = None
        return SimpleResult(success=True, message="已退出登录")

    async def api_import(self, payload: ImportRequest) -> SimpleResult:
        """导入 workbuddy.json 凭据文档。"""
        try:
            credential = self._store.import_document(payload.text)
        except ValueError as error:
            return SimpleResult(success=False, message=str(error))
        nickname = credential.nickname or credential.uid or "账号"
        return SimpleResult(success=True, message=f"已导入 {nickname} 的凭据")

    # ==================================================================
    # 业务实现
    # ==================================================================

    async def _poll_pending_login(self, state: Optional[str] = None) -> LoginPollResult:
        """轮询挂起的登录尝试。"""
        pending = self._pending_login
        if not pending:
            return LoginPollResult(status="error", message="没有待确认的登录；请先生成登录链接")
        if state and state != pending.get("state"):
            return LoginPollResult(status="error", message="state 与挂起的登录不匹配")
        try:
            outcome = await self._login_client.poll(pending["state"], pending["region"])
        except Exception as error:  # noqa: BLE001
            return LoginPollResult(status="error", message=str(error))
        if outcome["status"] != "complete":
            return LoginPollResult(status="pending", message="等待浏览器授权…")
        tokens = outcome["tokens"]
        account = outcome["account"]
        credential = WorkBuddyCredential(
            access_token=tokens["accessToken"],
            refresh_token=tokens.get("refreshToken") or "",
            expires_at_ms=int(time.time() * 1000 + float(tokens.get("expiresInSec") or 0) * 1000),
            domain=tokens.get("domain") or "",
            region=pending["region"],
            uid=account.get("uid") or "",
            enterprise_id=account.get("enterpriseId"),
            nickname=account.get("nickname"),
        )
        try:
            self._store.save(credential)
        except ValueError as error:
            return LoginPollResult(status="error", message=str(error))
        self._pending_login = None
        self.save_data("pending_login", None)
        self._credits_cache = None
        self._start_warmup()
        if self._notify:
            self.post_message(
                mtype=NotificationType.Plugin, title=self.plugin_name,
                text=f"WorkBuddy 登录成功：{credential.nickname or credential.uid or '账号'}"
                     f"（{REGION_LABELS.get(pending['region'], pending['region'])}）",
            )
        return LoginPollResult(
            status="complete",
            message="登录成功",
            nickname=credential.nickname,
            uid=credential.uid,
        )

    async def _do_checkin(self) -> Dict[str, Any]:
        """执行一次签到并记录流水。"""
        try:
            credential = await self._resolve_credential()
        except PermissionError as error:
            return {"date": protocol.utc8_date_string(), "status": "error",
                    "message": str(error), "amount": None}
        result = await self._checkin_service.check_in(credential)
        self._last_checkin = result
        self.save_data("last_checkin", result)
        log = self.get_data("checkin_log") or []
        if not isinstance(log, list):
            log = []
        log.insert(0, result)
        self.save_data("checkin_log", log[:50])
        if self._notify and result.get("status") in ("claimed", "error"):
            text = {
                "claimed": f"每日签到成功{f'，获得 {result['amount']} 积分' if result.get('amount') else ''}",
                "error": f"每日签到失败：{result.get('message')}",
            }.get(result.get("status"), "")
            if text:
                self.post_message(mtype=NotificationType.Plugin, title=self.plugin_name, text=text)
        return result

    async def _fetch_credits(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """读取额度（5 分钟缓存；force 强制刷新）。"""
        now = time.time()
        if not force and self._credits_cache is not None and now - self._credits_cached_at < 300:
            return self._credits_cache
        try:
            credential = await self._resolve_credential()
            credits = await self._upstream.fetch_credits(credential)
            self._credits_cache = credits
            self._credits_cached_at = now
            return credits
        except Exception as error:  # noqa: BLE001
            logger.warning(f"WorkBuddy 额度查询失败：{error}")
            return self._credits_cache

    def _credits_model(self, credits: Dict[str, Any]) -> CreditsResult:
        packages = [
            CreditsPackage(
                packageName=account.get("packageName") or "(unnamed)",
                remain=float(account.get("remain") or 0),
                size=float(account.get("size") or 0),
                packageEndTime=account.get("packageEndTime"),
                unlimited=account.get("unlimited"),
            )
            for account in credits.get("accounts") or []
        ]
        return CreditsResult(
            total=float(credits.get("total") or 0),
            totalSize=credits.get("totalSize"),
            unlimited=credits.get("unlimited"),
            cycleResetTime=credits.get("cycleResetTime"),
            accounts=packages,
        )

    def _model_briefs(self) -> List[ModelBrief]:
        signed_in = self._store.status().get("state") == "signed-in"
        disabled = self._disabled_set()
        briefs: List[ModelBrief] = []
        for model in self._catalog.current(signed_in=signed_in):
            if model.get("id") in disabled:
                continue
            display = protocol.model_with_current_promotion(model)
            billing = display.get("billing") or {}
            briefs.append(ModelBrief(
                id=display.get("id") or "",
                name=display.get("name") or "",
                contextWindow=int(display.get("contextWindow") or 0),
                maxTokens=int(display.get("maxTokens") or 0),
                supportsImages=bool(display.get("supportsImages")),
                credits=protocol.normalize_credits(billing.get("credits")),
                badges=billing.get("badges"),
                free=bool(billing.get("free")),
                rateUnknown=billing.get("rateUnknown"),
            ))
        return briefs

    def _llm_base_url(self) -> str:
        try:
            from app.core.config import settings  # noqa: PLC0415
            port = getattr(settings, "PORT", None) or 3000
        except Exception:  # noqa: BLE001
            port = 3000
        return f"http://127.0.0.1:{port}/api/v1/plugin/{self._plugin_id()}/v1"

    def _build_status(self) -> StatusResult:
        auth = self._store.status()
        briefs = self._model_briefs()
        default_model = briefs[0].id if briefs else None
        return StatusResult(
            enabled=self._enabled,
            region=self._region,
            regionLabel=REGION_LABELS.get(self._region, self._region),
            signedIn=auth.get("state") == "signed-in",
            nickname=auth.get("nickname"),
            uid=auth.get("uid"),
            domain=auth.get("domain"),
            expiresAtMs=auth.get("expiresAtMs"),
            pendingLogin=self._pending_login,
            catalogSource=self._catalog.source(),
            models=briefs,
            credits=self._credits_model(self._credits_cache) if self._credits_cache else None,
            lastCheckin=CheckinResult(**self._last_checkin) if isinstance(self._last_checkin, dict) else None,
            llmBaseUrl=self._llm_base_url(),
            llmApiKey=self._api_key,
            defaultModel=default_model,
        )

    def _start_warmup(self) -> None:
        """后台预热：拉取目录与额度，避免详情页首开为空。"""
        if not self._enabled:
            return

        def worker() -> None:
            try:
                self._run_sync(self._warmup())
            except Exception as error:  # noqa: BLE001
                logger.debug(f"WorkBuddy 预热失败：{error}")

        threading.Thread(target=worker, daemon=True, name="wbconnect-warmup").start()

    async def _warmup(self) -> None:
        try:
            credential = await self._resolve_credential()
        except Exception:  # noqa: BLE001
            return
        try:
            models = await self._upstream.fetch_models(credential)
            self._catalog.set_live(models)
        except Exception as error:  # noqa: BLE001
            self._catalog.set_error(str(error))
        await self._fetch_credits(force=True)

    # ==================================================================
    # 同步 → 异步桥（服务/命令回调处于同步上下文）
    # ==================================================================

    @staticmethod
    def _run_sync(coro: Any) -> Any:
        import asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        result: Dict[str, Any] = {}
        error: Dict[str, BaseException] = {}

        def worker() -> None:
            try:
                result["value"] = asyncio.run(coro)
            except BaseException as exc:  # noqa: BLE001
                error["exc"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join()
        if "exc" in error:
            raise error["exc"]
        return result.get("value")

    # ==================================================================
    # 定时服务
    # ==================================================================

    def get_service(self) -> list:
        """每日签到 + 登录确认轮询。"""
        if not self._enabled:
            return []
        plugin_id = self._plugin_id()
        services = [
            {
                "id": f"{plugin_id}.LoginPoll",
                "name": "WorkBuddy 登录确认轮询",
                "trigger": CronTrigger.from_crontab("* * * * *"),
                "func": self._service_login_poll,
                "kwargs": {},
            },
        ]
        if self._checkin_enabled:
            services.append({
                "id": f"{plugin_id}.Checkin",
                "name": "WorkBuddy 每日签到",
                "trigger": CronTrigger.from_crontab(f"0 {self._checkin_hour} * * *"),
                "func": self._service_checkin,
                "kwargs": {},
            })
        return services

    def _service_login_poll(self) -> None:
        """有挂起登录时轮询一次；完成即保存凭据并通知。"""
        if not self._enabled or not self._pending_login:
            return
        try:
            self._run_sync(self._poll_pending_login())
        except Exception as error:  # noqa: BLE001
            logger.warning(f"WorkBuddy 登录轮询失败：{error}")

    def _service_checkin(self) -> None:
        """每日签到服务。"""
        if not self._enabled:
            return
        try:
            self._run_sync(self._do_checkin())
        except Exception as error:  # noqa: BLE001
            logger.warning(f"WorkBuddy 每日签到失败：{error}")

    # ==================================================================
    # 远程命令
    # ==================================================================

    @staticmethod
    def get_command() -> list:
        return [
            {
                "cmd": "/wb_status",
                "event": EventType.PluginAction,
                "desc": "查询 WorkBuddy 账号与额度状态",
                "category": "插件命令",
                "data": {"action": "wb_status"},
            },
            {
                "cmd": "/wb_checkin",
                "event": EventType.PluginAction,
                "desc": "立即执行 WorkBuddy 每日签到",
                "category": "插件命令",
                "data": {"action": "wb_checkin"},
            },
        ]

    @eventmanager.register(EventType.PluginAction)
    def handle_command(self, event: Event = None) -> None:
        """处理 /wb_status 与 /wb_checkin 远程命令。"""
        if not event:
            return
        event_data = event.event_data or {}
        action = event_data.get("action")
        if action not in ("wb_status", "wb_checkin"):
            return
        if not self._enabled:
            self.post_message(mtype=NotificationType.Plugin, title=self.plugin_name, text="插件未启用")
            return
        try:
            if action == "wb_checkin":
                result = self._run_sync(self._do_checkin())
                amount = result.get("amount")
                text = f"签到结果：{result.get('status')}"
                if amount:
                    text += f"，获得 {amount} 积分"
                if result.get("message"):
                    text += f"（{result['message']}）"
            else:
                status = self._build_status()
                lines = [f"区域：{status.regionLabel}", f"登录：{'已登录' if status.signedIn else '未登录'}"]
                if status.nickname:
                    lines.append(f"账号：{status.nickname}")
                if status.credits is not None:
                    if status.credits.unlimited:
                        lines.append("额度：不限量（企业）")
                    else:
                        lines.append(f"剩余额度：{status.credits.total:g}")
                        for package in status.credits.accounts:
                            lines.append(f"  - {package.packageName}: {package.remain:g}/{package.size:g}")
                lines.append(f"模型数：{len(status.models)}（来源 {status.catalogSource}）")
                text = "\n".join(lines)
            self.post_message(mtype=NotificationType.Plugin, title=self.plugin_name, text=text)
        except Exception as error:  # noqa: BLE001
            self.post_message(mtype=NotificationType.Plugin, title=self.plugin_name, text=f"命令执行失败：{error}")

    # ==================================================================
    # 智能体工具与摘要（供 get_agent_tools 与命令复用）
    # ==================================================================

    def get_agent_tools(self) -> list:
        """注册智能体工具（宿主无 Agent 能力时返回空列表）。"""
        from .agent_tools import build_agent_tools
        return build_agent_tools(self)

    async def agent_credits_summary(self) -> str:
        """供智能体工具调用的额度摘要。"""
        credits = await self._fetch_credits()
        if credits is None:
            return "暂未取到 WorkBuddy 额度（可能未登录或查询失败）"
        if credits.get("unlimited"):
            reset = credits.get("cycleResetTime")
            return f"WorkBuddy 企业额度不限量{f'，周期重置时间 {reset}' if reset else ''}"
        lines = [f"WorkBuddy 剩余积分：{float(credits.get('total') or 0):g}"]
        total_size = credits.get("totalSize")
        if total_size:
            lines.append(f"本轮总额度：{float(total_size):g}")
        for account in credits.get("accounts") or []:
            expiry = f"，到期 {account['packageEndTime']}" if account.get("packageEndTime") else ""
            lines.append(f"- {account.get('packageName')}: 剩 {float(account.get('remain') or 0):g}"
                         f"/{float(account.get('size') or 0):g}{expiry}")
        return "\n".join(lines)

    async def agent_checkin(self) -> str:
        """供智能体工具调用的签到。"""
        result = await self._do_checkin()
        amount = result.get("amount")
        text = f"签到结果：{result.get('status')}"
        if amount:
            text += f"，获得 {amount} 积分"
        if result.get("message"):
            text += f"（{result['message']}）"
        return text

    def agent_models_summary(self) -> str:
        """供智能体工具调用的模型列表摘要。"""
        briefs = self._model_briefs()
        if not briefs:
            return "当前没有可用模型（请先登录 WorkBuddy）"
        lines = [f"WorkBuddy 可用模型（{len(briefs)} 个，来源 {self._catalog.source()}）："]
        for brief in briefs:
            badges = f" [{'/'.join(brief.badges)}]" if brief.badges else ""
            rate = brief.credits or ("免费" if brief.free else "价格未知")
            lines.append(f"- {brief.id}（{brief.name}）: 上下文 {brief.contextWindow // 1000}K，倍率 {rate}{badges}")
        return "\n".join(lines)

    # ==================================================================
    # 配置页 / 详情页
    # ==================================================================

    def get_form(self) -> Tuple[list, dict]:
        """构建配置页面与默认配置模型。"""
        region_items = [
            {"title": "WorkBuddy（国内版）", "value": REGION_CN},
            {"title": "WorkBuddy AI（国际版）", "value": REGION_GLOBAL},
        ]
        hour_items = [{"title": f"{h:02d}:00", "value": str(h)} for h in range(24)]
        form = [
            {"component": "VForm", "content": [
                {"component": "VAlert", "props": {
                    "type": "info", "variant": "tonal",
                    "text": "本插件把 WorkBuddy（CodeBuddy）模型桥接为 OpenAI 兼容接口，"
                            "供 MoviePilot 智能助手调用。登录与额度管理在插件详情页完成。"
                            "双区域并存：可用「虚拟分身」再开一个实例分别登录国内版与国际版。",
                }},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "enabled", "label": "启用插件",
                            "hint": "启用后暴露 OpenAI 兼容端点与智能体工具", "persistent-hint": True,
                        }},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSelect", "props": {
                            "model": "region", "label": "区域版本",
                            "items": region_items,
                            "hint": "国内版与国际版账号、积分互不通用", "persistent-hint": True,
                        }},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "notify", "label": "消息通知",
                            "hint": "登录/签到结果推送到消息渠道", "persistent-hint": True,
                        }},
                    ]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 8}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "api_key", "label": "访问密钥（LLM_API_KEY）",
                            "hint": "填入智能助手设置的「LLM API密钥」；留空保存时自动生成",
                            "persistent-hint": True,
                        }},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "disabled_models", "label": "隐藏模型",
                            "hint": "逗号分隔模型 ID，不出现在 /v1/models", "persistent-hint": True,
                        }},
                    ]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "checkin_enabled", "label": "每日自动签到",
                            "hint": "按设定时刻领取每日福利", "persistent-hint": True,
                        }},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSelect", "props": {
                            "model": "checkin_hour", "label": "签到时刻（北京时间）",
                            "items": hour_items,
                        }},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "client_version", "label": "客户端版本覆盖",
                            "hint": "聊天 UA 版本号，留空用内置回退值", "persistent-hint": True,
                        }},
                    ]},
                ]},
            ]},
        ]
        default = {
            "enabled": False,
            "region": REGION_CN,
            "api_key": "",
            "checkin_enabled": True,
            "checkin_hour": "10",
            "notify": True,
            "disabled_models": "",
            "client_version": "",
        }
        return form, default

    def get_page(self) -> list:
        """构建详情页面：登录、额度、模型与接入指引。"""
        status = self._build_status()
        plugin_id = self._plugin_id()

        def fmt_ts(value: Optional[int]) -> str:
            if not value:
                return "未知"
            try:
                return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError, OverflowError):
                return "未知"

        # 登录状态区块
        if status.signedIn:
            login_html = (
                f"<p style='margin:0'><b>已登录</b>：{status.nickname or '账号'}"
                f"（{status.regionLabel}）</p>"
                f"<p style='margin:4px 0 0 0'>令牌有效期至 {fmt_ts(status.expiresAtMs)}</p>"
            )
            login_type = "success"
        elif status.pendingLogin:
            auth_url = status.pendingLogin.get("authUrl") or ""
            login_html = (
                "<p style='margin:0'><b>等待浏览器授权</b>：请打开下方链接完成登录，"
                "完成后点击「我已完成授权」或等待自动确认。</p>"
                f'<p style="margin:8px 0 0 0"><a href="{auth_url}" target="_blank" '
                f'rel="noopener noreferrer">{auth_url}</a></p>'
            )
            login_type = "warning"
        else:
            login_html = "<p style='margin:0'><b>未登录</b>：点击「生成登录链接」，在浏览器完成 WorkBuddy 授权。</p>"
            login_type = "info"

        # 额度区块
        if status.credits is not None:
            credits = status.credits
            if credits.unlimited:
                credits_html = f"<p style='margin:0'>企业额度：<b>不限量</b>"
                if credits.cycleResetTime:
                    credits_html += f"（周期重置 {credits.cycleResetTime}）"
                credits_html += "</p>"
            else:
                rows = "".join(
                    f"<tr><td style='padding:2px 12px 2px 0'>{p.packageName}</td>"
                    f"<td style='padding:2px 12px 2px 0'>{p.remain:g} / {p.size:g}</td>"
                    f"<td style='padding:2px 0'>{p.packageEndTime or '无到期'}</td></tr>"
                    for p in credits.accounts
                )
                credits_html = (
                    f"<p style='margin:0'>剩余积分：<b>{credits.total:g}</b>"
                    + (f" / {credits.totalSize:g}" if credits.totalSize else "") + "</p>"
                    + (f"<table style='border-collapse:collapse;margin-top:4px'>{rows}</table>" if rows else "")
                )
        else:
            credits_html = "<p style='margin:0'>额度信息尚未获取（登录后自动刷新）。</p>"

        # 模型区块
        if status.models:
            model_rows = "".join(
                f"<tr><td style='padding:2px 12px 2px 0'><code>{m.id}</code></td>"
                f"<td style='padding:2px 12px 2px 0'>{m.name}</td>"
                f"<td style='padding:2px 12px 2px 0'>{m.contextWindow // 1000}K</td>"
                f"<td style='padding:2px 0'>{m.credits or ('免费' if m.free else '价格未知')}"
                + (f"（{'/'.join(m.badges)}）" if m.badges else "")
                + ("（促销已过期）" if m.rateUnknown else "") + "</td></tr>"
                for m in status.models
            )
            models_html = (
                f"<p style='margin:0'>共 {len(status.models)} 个模型（来源：{status.catalogSource}）</p>"
                f"<table style='border-collapse:collapse;margin-top:4px'>{model_rows}</table>"
            )
        else:
            models_html = "<p style='margin:0'>暂无模型（登录后自动加载目录）。</p>"

        guide_rows = [
            ("LLM提供商", "openai"),
            ("LLM基础URL", status.llmBaseUrl),
            ("LLM API密钥", status.llmApiKey),
            ("LLM模型名称", status.defaultModel or "glm-5.2"),
        ]
        guide_items = "".join(
            f"<p style='margin:2px 0'><code>{label}</code>：<code>{value}</code></p>"
            for label, value in guide_rows
        )
        guide_html = (
            "<p style='margin:0 0 6px 0'>在「设定 → 系统 → 基础设置 → 智能助手」中填写：</p>"
            + guide_items
        )

        def button(text: str, path: str, method: str = "POST", params: Optional[dict] = None,
                   color: str = "primary") -> dict:
            return {
                "component": "VBtn",
                "text": text,
                "props": {"color": color, "variant": "tonal", "class": "mr-2 mb-2"},
                "events": {"click": {"api": f"plugin/{plugin_id}/{path}", "method": method,
                                     "params": params or {}}},
            }

        actions: List[dict] = []
        if not status.signedIn:
            actions.append(button("生成登录链接", "login/begin", params={"region": self._region}))
            actions.append(button("我已完成授权", "login/poll", color="success"))
        actions.append(button("刷新额度", "credits/refresh"))
        actions.append(button("刷新模型", "catalog/refresh"))
        actions.append(button("立即签到", "checkin", color="success"))
        if status.signedIn:
            actions.append(button("退出登录", "logout", color="error"))

        return [
            {"component": "VCard", "props": {"variant": "tonal", "class": "mb-3"}, "content": [
                {"component": "VCardTitle", "text": "登录状态"},
                {"component": "VAlert", "props": {"type": login_type, "variant": "tonal"}, "html": login_html},
            ]},
            {"component": "VCard", "props": {"variant": "tonal", "class": "mb-3"}, "content": [
                {"component": "VCardTitle", "text": "额度"},
                {"component": "VAlert", "props": {"type": "info", "variant": "tonal"}, "html": credits_html},
            ]},
            {"component": "VCard", "props": {"variant": "tonal", "class": "mb-3"}, "content": [
                {"component": "VCardTitle", "text": "模型"},
                {"component": "VAlert", "props": {"type": "info", "variant": "tonal"}, "html": models_html},
            ]},
            {"component": "VCard", "props": {"variant": "tonal", "class": "mb-3"}, "content": [
                {"component": "VCardTitle", "text": "接入智能助手"},
                {"component": "VAlert", "props": {"type": "info", "variant": "tonal"}, "html": guide_html},
            ]},
            {"component": "VCard", "props": {"variant": "tonal"}, "content": [
                {"component": "VCardTitle", "text": "操作"},
                {"component": "VCardText", "content": actions},
            ]},
        ]

    # ==================================================================
    # API 注册
    # ==================================================================

    def get_api(self) -> list:
        """
        OpenAI 兼容端点自管 Bearer 访问密钥（OpenAI SDK 只会发 Authorization 头，
        无法使用宿主的 X-API-KEY 认证），故声明 allow_anonymous 并在端点内校验；
        管理端点走宿主 bear 认证，供详情页按钮调用。
        """
        return [
            {
                "path": "/v1/chat/completions",
                "endpoint": self.openai_chat_completions,
                "methods": ["POST"],
                "allow_anonymous": True,
                "summary": "OpenAI 兼容聊天（供智能助手 LLM_BASE_URL 接入）",
                "description": "自管 Bearer 访问密钥鉴权；stream=true 透传 SSE，否则聚合为 chat.completion。",
                "response_model": None,
                "response_class": StreamingResponse,
                "responses": {
                    200: {
                        "content": {
                            "text/event-stream": {"schema": {"type": "string"}},
                            "application/json": {"schema": {"type": "object"}},
                        },
                    },
                },
            },
            {
                "path": "/v1/models",
                "endpoint": self.openai_models,
                "methods": ["GET"],
                "allow_anonymous": True,
                "summary": "OpenAI 兼容模型列表",
                "response_model": None,
                "response_class": JSONResponse,
                "responses": {
                    200: {"content": {"application/json": {"schema": {"type": "object"}}}},
                },
            },
            {
                "path": "/login/begin",
                "endpoint": self.api_login_begin,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "发起设备授权登录",
                "response_model": LoginBeginResult,
            },
            {
                "path": "/login/poll",
                "endpoint": self.api_login_poll,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "轮询登录确认",
                "response_model": LoginPollResult,
            },
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "插件状态（登录/额度/模型/接入信息）",
                "response_model": StatusResult,
            },
            {
                "path": "/checkin",
                "endpoint": self.api_checkin,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即执行每日签到",
                "response_model": CheckinResult,
            },
            {
                "path": "/catalog/refresh",
                "endpoint": self.api_catalog_refresh,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "刷新模型目录",
                "response_model": CatalogRefreshResult,
            },
            {
                "path": "/credits/refresh",
                "endpoint": self.api_credits_refresh,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "刷新额度",
                "response_model": CreditsResult,
            },
            {
                "path": "/logout",
                "endpoint": self.api_logout,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "退出登录",
                "response_model": SimpleResult,
            },
            {
                "path": "/import",
                "endpoint": self.api_import,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "导入 workbuddy.json 凭据",
                "response_model": SimpleResult,
            },
        ]
