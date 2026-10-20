"""
模型目录缓存与内置兜底。

降级链：实时目录 → 上次保存的目录 → 内置兜底目录，并标注来源。
内置列表是 2026-09/10 实测快照，只覆盖首启与离线窗口，不代表上游现状；
未登录实例对外不暴露任何模型（避免展示必然失败的模型）。
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 内置兜底：国内版 cli 目录快照（16 个模型，保持上游 CLI 顺序）
FALLBACK_CN_MODELS: List[Dict[str, Any]] = [
    {"id": "auto", "name": "Auto", "contextWindow": 168000, "maxTokens": 32000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "high", "canDisableThinking": False},
     "billing": {"free": False}},
    {"id": "hy4-preview", "name": "Hy4 preview", "contextWindow": 1000000, "maxTokens": 64000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["high"], "defaultEffort": "high", "canDisableThinking": False},
     "billing": {"free": False, "rateUnknown": True}},
    {"id": "hy3", "name": "Hy3", "contextWindow": 192000, "maxTokens": 64000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "high", "canDisableThinking": False},
     "billing": {"free": False, "rateUnknown": True}},
    {"id": "hy3-x", "name": "Hy3-X", "contextWindow": 192000, "maxTokens": 64000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["low", "high"], "defaultEffort": "high", "canDisableThinking": False},
     "billing": {"credits": "x0.05", "free": False}},
    {"id": "deepseek-v4.1-flash", "name": "Deepseek-V4.1-Flash", "contextWindow": 1000000, "maxTokens": 128000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "high", "canDisableThinking": False},
     "billing": {"credits": "x0.03", "badges": ["独家优惠"], "free": False}},
    {"id": "glm-5.3", "name": "GLM-5.3", "contextWindow": 1000000, "maxTokens": 48000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["low", "high", "max"], "defaultEffort": "high", "canDisableThinking": True},
     "billing": {"credits": "x0.79", "free": False}},
    {"id": "glm-5.3-flash", "name": "GLM-5.3-Flash", "contextWindow": 1000000, "maxTokens": 32000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["low", "high", "max"], "defaultEffort": "high", "canDisableThinking": True},
     "billing": {"credits": "x0.06", "free": False}},
    {"id": "glm-5.2", "name": "GLM-5.2", "contextWindow": 1000000, "maxTokens": 48000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x0.79", "badges": ["夜间折扣"], "free": False}},
    {"id": "glm-5.1", "name": "GLM-5.1", "contextWindow": 200000, "maxTokens": 48000, "supportsImages": False,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x0.79", "free": False}},
    {"id": "glm-5v-turbo", "name": "GLM-5v-Turbo", "contextWindow": 200000, "maxTokens": 64000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x0.71", "free": False}},
    {"id": "kimi-k3-1", "name": "Kimi-K3", "contextWindow": 1000000, "maxTokens": 32000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x1.62", "free": False}},
    {"id": "kimi-k2.8-preview", "name": "Kimi-K2.8-Preview", "contextWindow": 1000000, "maxTokens": 32000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["low", "high", "max"], "defaultEffort": "high", "canDisableThinking": True},
     "billing": {"credits": "x0.77", "free": False}},
    {"id": "kimi-k2.7", "name": "Kimi-K2.7-Code", "contextWindow": 256000, "maxTokens": 32000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x0.57", "free": False}},
    {"id": "kimi-k2.6", "name": "Kimi-K2.6", "contextWindow": 256000, "maxTokens": 32000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x0.52", "free": False}},
    {"id": "minimax-m3", "name": "MiniMax-M3", "contextWindow": 512000, "maxTokens": 128000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x0.25", "free": False}},
    {"id": "deepseek-v4-pro", "name": "Deepseek-V4-Pro", "contextWindow": 1000000, "maxTokens": 50000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "high", "canDisableThinking": False},
     "billing": {"credits": "x0.51", "free": False}},
]

# 内置兜底：国际版 cli 目录快照（20 个模型）
FALLBACK_GLOBAL_MODELS: List[Dict[str, Any]] = [
    {"id": "default-model", "name": "Auto", "contextWindow": 176000, "maxTokens": 24000, "supportsImages": True,
     "reasoning": {"supports": False, "onlyReasoning": False, "canDisableThinking": True}, "billing": {"free": False}},
    {"id": "fast-model", "name": "Fast", "contextWindow": 200000, "maxTokens": 32000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x0.34", "free": False}},
    {"id": "balanced-model", "name": "Balanced", "contextWindow": 256000, "maxTokens": 32000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x0.59", "free": False}},
    {"id": "primary-model", "name": "Primary", "contextWindow": 272000, "maxTokens": 72000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "high", "canDisableThinking": False},
     "billing": {"credits": "x3.31", "free": False}},
    {"id": "deep-model", "name": "Deep", "contextWindow": 176000, "maxTokens": 24000, "supportsImages": True,
     "reasoning": {"supports": False, "onlyReasoning": False, "canDisableThinking": True}, "billing": {"free": False}},
    {"id": "hy4-preview-f", "name": "Hy4 preview", "contextWindow": 300000, "defaultContextWindow": 300000,
     "supportedContextWindows": [300000, 1000000], "maxTokens": 64000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["high"], "defaultEffort": "high", "canDisableThinking": False},
     "billing": {"free": False, "rateUnknown": True}},
    {"id": "hy3", "name": "Hy3", "contextWindow": 192000, "maxTokens": 64000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["low", "high"], "defaultEffort": "high", "canDisableThinking": False},
     "billing": {"free": False, "rateUnknown": True}},
    {"id": "deepseek-v4.1-flash", "name": "Deepseek-V4.1-Flash", "contextWindow": 300000, "defaultContextWindow": 300000,
     "supportedContextWindows": [300000, 1000000], "maxTokens": 128000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "high", "canDisableThinking": False},
     "billing": {"free": False, "rateUnknown": True}},
    {"id": "gpt-6-astra", "name": "GPT-6-Astra", "contextWindow": 400000, "defaultContextWindow": 400000,
     "supportedContextWindows": [400000, 1000000], "maxTokens": 128000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["low", "medium", "high", "xhigh", "max"], "defaultEffort": "medium", "canDisableThinking": True},
     "billing": {"credits": "x6.67", "free": False}},
    {"id": "gpt-5.6-sol", "name": "GPT-5.6-Sol", "contextWindow": 1000000, "maxTokens": 128000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["low", "medium", "high", "xhigh", "max"], "defaultEffort": "medium", "canDisableThinking": True},
     "billing": {"credits": "x3.47", "free": False}},
    {"id": "gpt-5.6-terra", "name": "GPT-5.6-Terra", "contextWindow": 1000000, "maxTokens": 128000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["low", "medium", "high", "xhigh", "max"], "defaultEffort": "medium", "canDisableThinking": True},
     "billing": {"credits": "x1.39", "free": False}},
    {"id": "gpt-5.6-luna", "name": "GPT-5.6-Luna", "contextWindow": 1000000, "maxTokens": 128000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["low", "medium", "high", "xhigh", "max"], "defaultEffort": "medium", "canDisableThinking": True},
     "billing": {"credits": "x0.14", "free": False}},
    {"id": "gpt-5.5", "name": "GPT-5.5", "contextWindow": 1000000, "maxTokens": 128000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["low", "medium", "high", "xhigh"], "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x3.31", "free": False}},
    {"id": "gpt-5.4", "name": "GPT-5.4", "contextWindow": 272000, "maxTokens": 72000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["low", "medium", "high", "xhigh"], "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x1.65", "free": False}},
    {"id": "gpt-5.3-codex", "name": "GPT-5.3-Codex", "contextWindow": 272000, "maxTokens": 72000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x1.25", "free": False}},
    {"id": "gemini-3.5-flash", "name": "Gemini-3.5-Flash", "contextWindow": 1000000, "maxTokens": 65536, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x0.99", "free": False}},
    {"id": "glm-5.3", "name": "GLM-5.3", "contextWindow": 1000000, "maxTokens": 48000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["low", "high", "max"], "defaultEffort": "high", "canDisableThinking": True},
     "billing": {"credits": "x0.79", "free": False}},
    {"id": "glm-5.2", "name": "GLM-5.2", "contextWindow": 1000000, "maxTokens": 48000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "supportedEfforts": ["high", "xhigh"], "defaultEffort": "high", "canDisableThinking": True},
     "billing": {"credits": "x0.79", "free": False}},
    {"id": "kimi-k3", "name": "Kimi-K3", "contextWindow": 1000000, "maxTokens": 32000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x1.62", "free": False}},
    {"id": "kimi-k2.6", "name": "Kimi-K2.6", "contextWindow": 256000, "maxTokens": 32000, "supportsImages": True,
     "reasoning": {"supports": True, "onlyReasoning": True, "defaultEffort": "medium", "canDisableThinking": False},
     "billing": {"credits": "x0.52", "free": False}},
]


def builtin_models(region: str) -> List[Dict[str, Any]]:
    """按区域返回内置兜底目录（深拷贝，调用方可就地改展示字段）。"""
    import copy
    source = FALLBACK_GLOBAL_MODELS if region == "global" else FALLBACK_CN_MODELS
    return copy.deepcopy(source)


class CatalogStore:
    """
    目录缓存：实时拉取结果落盘，供离线/失败时降级使用。
    降级链与来源标注：live（本次拉取）/ saved（上次保存）/ builtin（内置快照）。
    """

    def __init__(self, state_dir: Path, filename: str, region: str):
        self._path = Path(state_dir) / filename
        self._region = region
        self._models: List[Dict[str, Any]] = []
        self._source = "builtin"
        self._updated_at: Optional[float] = None
        self._last_error: Optional[str] = None
        self._load_saved()

    def _load_saved(self) -> None:
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
            models = document.get("models")
            if isinstance(models, list) and models:
                self._models = models
                self._source = "saved"
                self._updated_at = document.get("updatedAt")
        except (OSError, ValueError, TypeError):
            pass

    def _persist(self, models: List[Dict[str, Any]]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {"models": models, "updatedAt": time.time() * 1000},
                ensure_ascii=False,
            )
            self._path.write_text(payload, encoding="utf-8")
        except OSError:
            pass

    def set_live(self, models: List[Dict[str, Any]]) -> None:
        """记录一次成功拉取的目录。"""
        self._models = models
        self._source = "live"
        self._updated_at = time.time() * 1000
        self._last_error = None
        self._persist(models)

    def set_error(self, message: str) -> None:
        """记录一次失败；目录保持上一档（saved → builtin）继续服务。"""
        self._last_error = message[:200]

    def current(self, signed_in: bool = True) -> List[Dict[str, Any]]:
        """
        当前可用目录。未登录返回空列表（宁可不展示，也不给必失败的模型）；
        无缓存时回落内置快照。
        """
        if not signed_in:
            return []
        if self._models:
            return list(self._models)
        self._source = "builtin"
        self._models = builtin_models(self._region)
        return list(self._models)

    def source(self) -> str:
        return self._source

    def updated_at(self) -> Optional[float]:
        return self._updated_at

    def last_error(self) -> Optional[str]:
        return self._last_error

    def default_effort_for(self, model_id: str) -> Optional[str]:
        """查询模型的默认推理档位（供 reasoning_effort 归一化使用）。"""
        for model in self._models or self.current():
            if model.get("id") == model_id:
                reasoning = model.get("reasoning") or {}
                return reasoning.get("defaultEffort")
        return None
