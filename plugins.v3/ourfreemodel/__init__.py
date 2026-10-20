"""
我们的免费模型（MoviePilot V3 插件）。

把 dsh-our-free-model 的免费模型车道（OpenCode 免密车道 + Kilo 免费池）
桥接为 OpenAI 兼容接口，供 MoviePilot 智能助手（LLM_BASE_URL）直接调用；
同时提供模型目录、车道状态等管理接口与智能体工具。

协议移植自 Ebony-Vinyl/dsh-our-free-model（MIT）：会话 ID 降序编码铸造、
v2 网关指纹头、免密工具闸门（read/shell 逐字定义）、三线协议翻译与
SSE 归一、思考强度档位补丁、免费模型目录与能力表。

接入方式（系统设置 → 智能助手）：
    LLM提供商   openai（OpenAI 兼容）
    LLM基础URL  http://127.0.0.1:3000/api/v1/plugin/OurFreeModel/v1
    LLM API密钥 插件设置页的「访问密钥」
    LLM模型名称 如 deepseek-v4.1-flash-free（详情页可查看完整模型列表）
"""

import asyncio
import json
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
        logger = logging.getLogger("ourfreemodel")  # type: ignore

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

from . import catalog as catalog_mod
from . import translate, wire
from .catalog import (
    LANE_KILO,
    LANE_OPENCODE,
    budget_for,
    build_free_catalog,
    build_kilo_catalog,
    default_effort_level,
    effort_patch_for,
    find_entry,
    has_declared_effort_menu,
    revive_catalog,
)
from .lanes import LaneClient, LaneError
from .translate import StreamAssembler, UpstreamStreamError, build_payload
from .wire import SessionStore, apply_fingerprint, injected_placeholder_names

# ---------------------------------------------------------------------------
# API 响应模型（普通 JSON 端点必须声明具体 response_model）
# ---------------------------------------------------------------------------


class ModelBrief(BaseModel):
    """模型简要信息。"""
    id: str
    name: str
    lane: str
    wire: str = "chat"
    contextWindow: int = 131072
    maxOutput: int = 32768
    vision: bool = False
    reasoning: bool = True


class CatalogRefreshResult(BaseModel):
    """目录刷新结果。"""
    count: int
    source: str
    message: Optional[str] = None


class StatusResult(BaseModel):
    """插件状态。"""
    enabled: bool
    defaultModel: str
    catalogCount: int
    catalogSource: str
    catalogUpdatedAt: Optional[int] = None
    llmBaseUrl: str
    llmApiKey: str
    lanes: Dict[str, bool]
    models: List[ModelBrief] = Field(default_factory=list)


class SimpleResult(BaseModel):
    """通用结果。"""
    success: bool
    message: Optional[str] = None


class SwitchModelRequest(BaseModel):
    """切换默认模型请求体。"""
    model_id: str = Field(..., description="目标模型 ID")


# ---------------------------------------------------------------------------
# 内置兜底目录（联网清单不可用时仍可出模型列表）
# ---------------------------------------------------------------------------

#: 免密车道已知免费 id（与 catalog.DISPLAY_NAMES 同源）。
_BUILTIN_FREE_IDS = list(catalog_mod.DISPLAY_NAMES.keys())


class OurFreeModel(_PluginBase):
    """我们的免费模型：免费模型车道接入 MoviePilot 智能助手。"""

    plugin_name = "我们的免费模型"
    plugin_desc = "把免费模型车道（OpenCode 免密 / Kilo 免费池）接入智能助手：OpenAI 兼容接口、模型目录、免密免注册。"
    plugin_icon = "Ourfree_A.png"
    plugin_version = "1.0.0"
    plugin_author = "lovesakuratears"
    author_url = "https://github.com/lovesakuratears/MoviePilot-Plugins"
    plugin_config_prefix = "ourfreemodel_"
    plugin_order = 41
    auth_level = 1

    # -- 配置字段 -----------------------------------------------------------
    _enabled: bool = False
    _api_key: str = ""
    _default_model: str = ""
    _effort: str = ""
    _disabled_models: str = ""
    _opencode_enabled: bool = True
    _kilo_enabled: bool = True
    _notify: bool = False

    # -- 运行时状态 ---------------------------------------------------------
    _lane_client: Optional[LaneClient] = None
    _sessions: Optional[SessionStore] = None
    _catalog_entries: List[Dict[str, Any]] = []
    _catalog_source: str = "builtin"
    _catalog_updated_at: float = 0.0
    _catalog_lock: Optional[threading.Lock] = None

    # ==================================================================
    # 生命周期
    # ==================================================================

    def init_plugin(self, config: dict = None) -> None:
        """读取配置并建立本次运行状态；允许重复调用。"""
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._api_key = str(config.get("api_key") or "")
        self._default_model = str(config.get("default_model") or "").strip()
        self._effort = str(config.get("effort") or "").strip()
        self._disabled_models = str(config.get("disabled_models") or "")
        self._opencode_enabled = bool(config.get("opencode_enabled", True))
        self._kilo_enabled = bool(config.get("kilo_enabled", True))
        self._notify = bool(config.get("notify", False))

        # 访问密钥缺失时生成一个并回写配置（OpenAI 兼容端点的 Bearer 口令）
        if not self._api_key:
            self._api_key = secrets.token_urlsafe(24)
            config["api_key"] = self._api_key
            self.update_config(config)

        self._catalog_lock = threading.Lock()
        self._lane_client = LaneClient()
        self._sessions = SessionStore(persist=self._persist_sessions)
        self._sessions.load(self.get_data("session_map"))

        # 恢复目录缓存：live 未刷新前先用上次的（fail-open 到内置兜底）
        cached = self.get_data("catalog")
        if isinstance(cached, dict):
            entries = revive_catalog(cached.get("entries"))
            if entries:
                self._catalog_entries = entries
                self._catalog_source = str(cached.get("source") or "cache")
                self._catalog_updated_at = float(cached.get("updatedAt") or 0)
        if not self._catalog_entries:
            self._catalog_entries = build_free_catalog(_BUILTIN_FREE_IDS)
            self._catalog_source = "builtin"

        if self._enabled:
            self._start_warmup()

    def get_state(self) -> bool:
        """返回插件是否启用。"""
        return self._enabled

    def stop_service(self) -> None:
        """释放运行时状态；可重复调用。"""
        # HTTP 客户端的关闭是异步的；交给后台线程尽力释放，不阻塞宿主。
        client = self._lane_client
        self._lane_client = None
        if client is not None:
            def _close() -> None:
                try:
                    loop = asyncio.new_event_loop()
                    try:
                        loop.run_until_complete(client.aclose())
                    finally:
                        loop.close()
                except Exception:  # noqa: BLE001
                    pass
            threading.Thread(target=_close, daemon=True).start()

    # ==================================================================
    # 内部：会话 / 目录
    # ==================================================================

    def _plugin_id(self) -> str:
        """当前实例 ID（虚拟分身兼容：以类名为准）。"""
        return self.__class__.__name__

    def _persist_sessions(self, mapping: Dict[str, str]) -> None:
        """会话映射持久化（save_data 同步接口）。"""
        try:
            self.save_data("session_map", mapping)
        except Exception:  # noqa: BLE001
            pass

    def _disabled_set(self) -> set:
        return {item.strip() for item in self._disabled_models.split(",") if item.strip()}

    def _visible_models(self) -> List[Dict[str, Any]]:
        """当前目录中对用户可见的模型（按车道开关与隐藏列表过滤）。"""
        disabled = self._disabled_set()
        out = []
        for entry in self._catalog_entries:
            if entry.get("id") in disabled:
                continue
            lane = entry.get("lane")
            if lane == LANE_OPENCODE and not self._opencode_enabled:
                continue
            if lane == LANE_KILO and not self._kilo_enabled:
                continue
            out.append(entry)
        return out

    def _persist_catalog(self, entries: List[Dict[str, Any]], source: str) -> None:
        """目录缓存持久化。"""
        try:
            self.save_data("catalog", {
                "source": source,
                "updatedAt": time.time(),
                "entries": entries,
            })
        except Exception:  # noqa: BLE001
            pass

    async def _refresh_catalog(self) -> CatalogRefreshResult:
        """
        拉取两条车道的在线清单并重建目录。

        单条车道失败不拖垮另一条；全部失败时保留现有目录。
        """
        assert self._lane_client is not None
        entries: List[Dict[str, Any]] = []
        sources: List[str] = []
        errors: List[str] = []

        if self._opencode_enabled:
            try:
                ids = await self._lane_client.fetch_opencode_listing()
                built = build_free_catalog(ids)
                entries.extend(built)
                sources.append(f"opencode:{len(built)}")
            except LaneError as error:
                errors.append(f"opencode {error.kind}")
                logger.warning(f"我们的免费模型：免密车道清单刷新失败（{error.kind}）")

        if self._kilo_enabled:
            try:
                rows = await self._lane_client.fetch_kilo_listing()
                built = build_kilo_catalog(rows)
                entries.extend(built)
                sources.append(f"kilo:{len(built)}")
            except LaneError as error:
                errors.append(f"kilo {error.kind}")
                logger.warning(f"我们的免费模型：Kilo 清单刷新失败（{error.kind}）")

        if entries:
            with self._catalog_lock:
                self._catalog_entries = entries
                self._catalog_source = "+".join(sources) if sources else "live"
                self._catalog_updated_at = time.time()
            self._persist_catalog(entries, self._catalog_source)
            return CatalogRefreshResult(count=len(entries), source=self._catalog_source)

        # 全部失败：保留现有（缓存/内置）目录，明确报告来源
        return CatalogRefreshResult(
            count=len(self._catalog_entries),
            source=self._catalog_source,
            message=f"在线清单刷新失败（{'; '.join(errors) or 'unknown'}），沿用现有目录",
        )

    def _start_warmup(self) -> None:
        """后台预热：启动即刷新一次模型目录（不阻塞 init）。"""
        def worker() -> None:
            try:
                self._run_sync(self._refresh_catalog())
            except Exception as error:  # noqa: BLE001
                logger.warning(f"我们的免费模型：目录预热失败：{error}")
        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _run_sync(coro: Any) -> Any:
        """在独立事件循环里执行协程（后台线程用）。"""
        def runner() -> Any:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        return runner()

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

    async def openai_models(self, request: Request) -> Any:
        """GET /v1/models —— OpenAI 协议模型列表。"""
        denied = self._check_api_key(request)
        if denied is not None:
            return denied
        models = self._visible_models()
        return JSONResponse(content={
            "object": "list",
            "data": [
                {
                    "id": entry["id"],
                    "object": "model",
                    "created": int(self._catalog_updated_at or 0),
                    "owned_by": entry.get("lane", "ourfreemodel"),
                }
                for entry in models
            ],
        })

    async def openai_chat_completions(self, request: Request) -> Any:
        """
        POST /v1/chat/completions —— OpenAI 协议聊天。

        请求 stream=true 时输出 OpenAI SSE chunk 流；否则服务端聚合为
        chat.completion JSON。上游一律流式拉取（免密车道只放行 stream）。
        """
        denied = self._check_api_key(request)
        if denied is not None:
            return denied

        raw = (await request.body()).decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            body = {}
        if not isinstance(body, dict):
            body = {}

        model_id = str(body.get("model") or "").strip() or self._default_model
        wants_stream = body.get("stream") is True

        if not model_id:
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "model is required", "type": "invalid_request", "code": "invalid_request"}},
            )

        disabled = self._disabled_set()
        if model_id in disabled or wire.base_model_id(model_id) in disabled:
            return JSONResponse(
                status_code=404,
                content={"error": {"message": f"model '{model_id}' is disabled", "type": "not_found", "code": "not_found"}},
            )

        entry = find_entry(self._catalog_entries, model_id)
        if entry is None:
            # 目录未命中：尝试在线刷新一次再查（模型清单是动态的）
            try:
                await self._refresh_catalog()
            except Exception:  # noqa: BLE001
                pass
            entry = find_entry(self._catalog_entries, model_id)
        if entry is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"message": f"model '{model_id}' not found on free lanes", "type": "not_found", "code": "not_found"}},
            )

        lane = entry.get("lane", LANE_OPENCODE)
        if lane == LANE_OPENCODE and not self._opencode_enabled:
            return JSONResponse(
                status_code=503,
                content={"error": {"message": "OpenCode lane is switched off", "type": "server", "code": "lane_disabled"}},
            )
        if lane == LANE_KILO and not self._kilo_enabled:
            return JSONResponse(
                status_code=503,
                content={"error": {"message": "Kilo lane is switched off", "type": "server", "code": "lane_disabled"}},
            )

        messages = body.get("messages") if isinstance(body.get("messages"), list) else []
        tools = body.get("tools") if isinstance(body.get("tools"), list) else []
        requested_budget = body.get("max_tokens")
        if not isinstance(requested_budget, (int, float)):
            requested_budget = body.get("max_completion_tokens")
        budget = budget_for(entry, requested_budget)

        effort_level = body.get("reasoning_effort") if isinstance(body.get("reasoning_effort"), str) else None
        if not effort_level:
            effort_level = self._effort or None
        patch = effort_patch_for(effort_level, entry) if has_declared_effort_menu(entry) else None

        entry_wire = entry.get("wire") or "chat"
        payload = build_payload(
            wire=entry_wire,
            model_id=entry["id"],
            messages=messages,
            budget=budget,
            tools=tools,
            effort_patch=patch,
            temperature=body.get("temperature"),
            stop=body.get("stop"),
        )

        # 免密车道有工具闸门；Kilo 无闸门，工具名原样透传。
        rename_map: Dict[str, str] = {}
        drop_names: List[str] = []
        if lane == LANE_OPENCODE:
            rename_map = apply_fingerprint(payload, entry_wire)
            caller_names = []
            for tool in tools:
                if not isinstance(tool, dict):
                    continue
                fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
                name = fn.get("name")
                if isinstance(name, str) and name:
                    caller_names.append(name)
            drop_names = injected_placeholder_names(rename_map, caller_names)

        session_id = self._sessions.session_for(body.get("user") or "mp-default")
        assembler = StreamAssembler(
            model=entry["id"],
            wire=entry_wire,
            rename_map=rename_map,
            drop_tool_names=drop_names,
        )

        try:
            handle = await self._lane_client.open_chat_stream(
                lane, payload, session_id=session_id, model_id=entry["id"],
            )
        except LaneError as error:
            status = 502 if error.kind in ("server", "transport") else 429 if error.kind == "rate_limit" else 502
            logger.error(f"我们的免费模型：{entry['id']} 请求失败（{error.kind}）：{error}")
            return JSONResponse(
                status_code=status,
                content={"error": {
                    "message": f"our-free-model {error.kind}: {str(error)[:400]}",
                    "type": error.kind, "code": error.kind,
                }},
            )

        if wants_stream:
            return StreamingResponse(
                self._sse_stream(handle, assembler),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # 非流式：喂完所有载荷后聚合
        try:
            async for data in handle.iter_data():
                try:
                    assembler.feed(data)
                except UpstreamStreamError as error:
                    return JSONResponse(
                        status_code=502,
                        content={"error": {"message": f"upstream error: {error}", "type": "server", "code": "server"}},
                    )
        finally:
            await handle.aclose()
        if assembler.dropped_placeholders:
            logger.info(f"我们的免费模型：已忽略占位工具调用 {assembler.dropped_placeholders}")
        return JSONResponse(content=assembler.to_completion())

    async def _sse_stream(self, handle: Any, assembler: StreamAssembler):
        """把上游流归一为 OpenAI chunk SSE 流；中断时补 error 终帧。"""
        try:
            async for data in handle.iter_data():
                try:
                    chunks = assembler.feed(data)
                except UpstreamStreamError as error:
                    payload = {"error": {"message": f"upstream error: {error}", "type": "server", "code": "server"}}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                for chunk in chunks:
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                if data.strip() == "[DONE]":
                    break
            for chunk in assembler.finish():
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as error:  # noqa: BLE001
            logger.warning(f"我们的免费模型：上游流中断：{error}")
            payload = {"error": {"message": f"stream interrupted: {error}", "type": "server", "code": "server"}}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            await handle.aclose()

    # ==================================================================
    # 管理端点（详情页按钮 / 前端调用，走宿主 bear 认证）
    # ==================================================================

    async def api_status(self) -> StatusResult:
        """插件状态（目录 / 默认模型 / 接入信息）。"""
        return self._build_status()

    async def api_catalog_refresh(self) -> CatalogRefreshResult:
        """立即刷新模型目录。"""
        return await self._refresh_catalog()

    async def api_switch_model(self, payload: SwitchModelRequest) -> SimpleResult:
        """切换默认模型（保存到插件配置）。"""
        model_id = (payload.model_id or "").strip()
        entry = find_entry(self._catalog_entries, model_id)
        if entry is None:
            return SimpleResult(success=False, message=f"模型 {model_id} 不在当前免费目录中")
        self._default_model = entry["id"]
        config = self.get_config() or {}
        config["default_model"] = entry["id"]
        self.update_config(config)
        return SimpleResult(success=True, message=f"默认模型已切换为 {entry['id']}")

    def _build_status(self) -> StatusResult:
        models = [
            ModelBrief(
                id=entry["id"],
                name=entry.get("name") or entry["id"],
                lane=entry.get("lane") or LANE_OPENCODE,
                wire=entry.get("wire") or "chat",
                contextWindow=int(entry.get("contextWindow") or 131072),
                maxOutput=int(entry.get("maxOutput") or 32768),
                vision=bool(entry.get("vision")),
                reasoning=bool(entry.get("reasoning", True)),
            )
            for entry in self._visible_models()
        ]
        return StatusResult(
            enabled=self._enabled,
            defaultModel=self._default_model or (models[0].id if models else ""),
            catalogCount=len(models),
            catalogSource=self._catalog_source,
            catalogUpdatedAt=int(self._catalog_updated_at * 1000) if self._catalog_updated_at else None,
            llmBaseUrl=self._llm_base_url(),
            llmApiKey=self._api_key,
            lanes={"opencode": self._opencode_enabled, "kilo": self._kilo_enabled},
            models=models,
        )

    def _llm_base_url(self) -> str:
        return f"/api/v1/plugin/{self._plugin_id()}/v1"

    # ==================================================================
    # 智能体工具支撑（agent_tools.build_agent_tools 调用）
    # ==================================================================

    async def agent_models_summary(self) -> str:
        """模型列表摘要（智能体工具用）。"""
        models = self._visible_models()
        if not models:
            return "当前免费目录为空，请先在插件详情页点击「刷新模型」。"
        lines = [f"共 {len(models)} 个免费模型（来源：{self._catalog_source}）："]
        for entry in models:
            flags = []
            if entry.get("vision"):
                flags.append("视觉")
            if entry.get("reasoning"):
                flags.append("思考")
            if entry.get("efforts"):
                flags.append("档位:" + "/".join(entry["efforts"]))
            lines.append(
                f"- {entry['id']}（{entry.get('name')}，{entry.get('lane')}，"
                f"上下文 {int(entry.get('contextWindow', 0)) // 1000}K，"
                f"输出上限 {int(entry.get('maxOutput', 0)) // 1000}K"
                + (f"，{'、'.join(flags)}" if flags else "")
                + "）"
            )
        if self._default_model:
            lines.append(f"当前默认模型：{self._default_model}")
        return "\n".join(lines)

    async def agent_switch_model(self, model_id: str) -> str:
        """切换默认模型（智能体工具用）。"""
        result = await self.api_switch_model(SwitchModelRequest(model_id=model_id))
        return result.message or ("已切换" if result.success else "切换失败")

    async def agent_status_summary(self) -> str:
        """状态摘要（智能体工具用）。"""
        status = self._build_status()
        updated = datetime.fromtimestamp(status.catalogUpdatedAt / 1000).strftime("%Y-%m-%d %H:%M") \
            if status.catalogUpdatedAt else "未知"
        return "\n".join([
            f"插件状态：{'启用' if status.enabled else '停用'}",
            f"模型目录：{status.catalogCount} 个模型（来源 {status.catalogSource}，刷新于 {updated}）",
            f"车道开关：OpenCode {'开' if status.lanes.get('opencode') else '关'} / "
            f"Kilo {'开' if status.lanes.get('kilo') else '关'}",
            f"默认模型：{status.defaultModel or '未设置'}",
            f"接入地址（LLM基础URL）：{status.llmBaseUrl}",
            f"访问密钥（LLM API密钥）：{status.llmApiKey}",
        ])

    # ==================================================================
    # 注册：API / 服务 / 表单 / 详情页 / 命令 / 智能体工具
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
                "description": "自管 Bearer 访问密钥鉴权；stream=true 输出 SSE chunk 流，否则聚合为 chat.completion。",
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
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "插件状态（目录/默认模型/接入信息）",
                "response_model": StatusResult,
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
                "path": "/model/switch",
                "endpoint": self.api_switch_model,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "切换默认模型",
                "response_model": SimpleResult,
            },
        ]

    def get_service(self) -> list:
        """每小时刷新一次模型目录（免费清单跟随上游实时变化）。"""
        if not self.get_state():
            return []
        return [
            {
                "id": "OurFreeModel.CatalogRefresh",
                "name": "免费模型目录刷新",
                "trigger": CronTrigger.from_crontab("15 * * * *"),
                "func": self._service_catalog_refresh,
                "kwargs": {},
            }
        ]

    def _service_catalog_refresh(self) -> None:
        """定时服务入口：同步包装异步刷新。"""
        try:
            result = self._run_sync(self._refresh_catalog())
            logger.info(f"我们的免费模型：目录定时刷新完成（{result.count} 个模型，来源 {result.source}）")
        except Exception as error:  # noqa: BLE001
            logger.warning(f"我们的免费模型：目录定时刷新失败：{error}")

    @staticmethod
    def get_command() -> list:
        """当前插件不注册远程命令。"""
        return []

    def get_agent_tools(self) -> list:
        """注册智能体工具（宿主无 Agent 能力时返回空列表）。"""
        from .agent_tools import build_agent_tools
        return build_agent_tools(self)

    def get_form(self) -> Tuple[list, dict]:
        """构建配置页面与默认配置模型。"""
        effort_items = [
            {"title": "模型默认档位", "value": ""},
            {"title": "关闭思考（disabled）", "value": "disabled"},
            {"title": "低（low）", "value": "low"},
            {"title": "中（medium）", "value": "medium"},
            {"title": "高（high）", "value": "high"},
            {"title": "最高（max）", "value": "max"},
        ]
        form = [
            {"component": "VForm", "content": [
                {"component": "VAlert", "props": {
                    "type": "info", "variant": "tonal",
                    "text": "本插件把免费模型车道（OpenCode 免密车道 + Kilo 免费池）桥接为 OpenAI 兼容接口，"
                            "供 MoviePilot 智能助手调用：免登录、免 API Key、免注册。"
                            "在智能助手设置里把「LLM基础URL」指向本插件即可。",
                }},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "enabled", "label": "启用插件",
                            "hint": "启用后暴露 OpenAI 兼容端点与智能体工具", "persistent-hint": True,
                        }},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "opencode_enabled", "label": "OpenCode 免密车道",
                            "hint": "opencode.ai 公共免密额度", "persistent-hint": True,
                        }},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "kilo_enabled", "label": "Kilo 免费池",
                            "hint": "api.kilo.ai 免费池（上游可能记录提示词）", "persistent-hint": True,
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
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "default_model", "label": "默认模型 ID",
                            "hint": "如 deepseek-v4.1-flash-free；请求缺省 model 时使用", "persistent-hint": True,
                        }},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSelect", "props": {
                            "model": "effort", "label": "思考强度档位",
                            "items": effort_items,
                            "hint": "仅对声明了档位菜单的模型生效", "persistent-hint": True,
                        }},
                    ]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "notify", "label": "消息通知",
                            "hint": "目录刷新异常时推送到消息渠道", "persistent-hint": True,
                        }},
                    ]},
                ]},
            ]},
        ]
        default = {
            "enabled": False,
            "api_key": "",
            "default_model": "deepseek-v4.1-flash-free",
            "effort": "",
            "disabled_models": "",
            "opencode_enabled": True,
            "kilo_enabled": True,
            "notify": False,
        }
        return form, default

    def get_page(self) -> list:
        """构建详情页面：状态、模型目录与接入指引。"""
        status = self._build_status()
        plugin_id = self._plugin_id()

        def fmt_ts(value: Optional[int]) -> str:
            if not value:
                return "未知"
            try:
                return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError, OverflowError):
                return "未知"

        lanes_html = (
            f"<p style='margin:0'>OpenCode 免密车道：{'启用' if status.lanes.get('opencode') else '停用'} ｜ "
            f"Kilo 免费池：{'启用' if status.lanes.get('kilo') else '停用'}</p>"
            f"<p style='margin:4px 0 0 0'>目录来源：{status.catalogSource}，"
            f"刷新于 {fmt_ts(status.catalogUpdatedAt)}</p>"
            f"<p style='margin:4px 0 0 0'>默认模型：<code>{status.defaultModel or '未设置'}</code></p>"
        )

        if status.models:
            model_rows = "".join(
                f"<tr><td style='padding:2px 12px 2px 0'><code>{m.id}</code></td>"
                f"<td style='padding:2px 12px 2px 0'>{m.name}</td>"
                f"<td style='padding:2px 12px 2px 0'>{m.lane}</td>"
                f"<td style='padding:2px 12px 2px 0'>{m.contextWindow // 1000}K</td>"
                f"<td style='padding:2px 0'>{'视觉 ' if m.vision else ''}{'思考' if m.reasoning else ''}</td></tr>"
                for m in status.models
            )
            models_html = (
                f"<p style='margin:0'>共 {len(status.models)} 个免费模型</p>"
                f"<table style='border-collapse:collapse;margin-top:4px'>{model_rows}</table>"
            )
        else:
            models_html = "<p style='margin:0'>暂无模型，请点击「刷新模型」。</p>"

        guide_rows = [
            ("LLM提供商", "openai"),
            ("LLM基础URL", f"http://127.0.0.1:3000{status.llmBaseUrl}"),
            ("LLM API密钥", status.llmApiKey),
            ("LLM模型名称", status.defaultModel or "deepseek-v4.1-flash-free"),
        ]
        guide_items = "".join(
            f"<tr>"
            f"<td style='padding:3px 16px 3px 0;white-space:nowrap;vertical-align:top'>"
            f"<code>{label}</code>：</td>"
            f"<td style='padding:3px 0;vertical-align:top;word-break:break-all'>"
            f"<code>{value}</code></td>"
            f"</tr>"
            for label, value in guide_rows
        )
        guide_html = (
            "<p style='margin:0 0 8px 0'>在「设定 → 系统 → 基础设置 → 智能助手」中填写：</p>"
            f"<table style='border-collapse:collapse;width:100%'>{guide_items}</table>"
        )

        def button(text: str, path: str, method: str = "POST", color: str = "primary") -> dict:
            return {
                "component": "VBtn",
                "text": text,
                "props": {"color": color, "variant": "tonal", "class": "mr-2 mb-2"},
                "events": {"click": {"api": f"plugin/{plugin_id}/{path}", "method": method, "params": {}}},
            }

        actions: List[dict] = [
            button("刷新模型", "catalog/refresh"),
            button("查看状态", "status", method="GET"),
        ]

        return [
            {"component": "VCard", "props": {"variant": "tonal", "class": "mb-3"}, "content": [
                {"component": "VCardTitle", "text": "车道状态"},
                {"component": "VAlert", "props": {"type": "info", "variant": "tonal"}, "html": lanes_html},
            ]},
            {"component": "VCard", "props": {"variant": "tonal", "class": "mb-3"}, "content": [
                {"component": "VCardTitle", "text": "免费模型"},
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
