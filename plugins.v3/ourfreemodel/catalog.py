"""
模型目录：免费车道（OpenCode）与 Kilo 免费池的清单构建与能力表。

移植自 dsh-our-free-model 的 src/catalog.js（免费车道 + Kilo 部分，MIT）：
上游清单只给 id，能力表（上下文窗口 / 视觉 / 思考档位）由本地核定；
清单 → 能力表合流构成本插件的模型目录。纯函数可单测。
"""

import re
from typing import Any, Dict, List, Optional

from .wire import base_model_id, is_responses_model

# ---------------------------------------------------------------------------
# 免费车道（OpenCode）
# ---------------------------------------------------------------------------

#: 清单不带 `-free` 后缀但确属免密车道的 ID。
ALWAYS_FREE = {"union-alpha", "space-bunny-free", "big-pickle"}

#: 家族级能力基线。`match` 对基础模型 ID 生效。
CAPABILITIES: List[Dict[str, Any]] = [
    {"match": re.compile(r"^mimo.*v2\.6"), "vision": True, "reasoning": True, "contextWindow": 1048576, "maxOutput": 131072, "canDisableThinking": False},
    {"match": re.compile(r"^mimo.*v2\.5"), "vision": True, "reasoning": True, "contextWindow": 1048576, "maxOutput": 131072, "canDisableThinking": False},
    {"match": re.compile(r"^mimo"), "vision": True, "reasoning": True, "contextWindow": 262144, "maxOutput": 131072},
    {"match": re.compile(r"^muse.?spark"), "vision": True, "reasoning": True, "contextWindow": 1048576, "maxOutput": 131072},
    {"match": re.compile(r"^nemotron"), "vision": False, "reasoning": True, "contextWindow": 128000, "maxOutput": 32768},
    {"match": re.compile(r"^ling"), "vision": False, "reasoning": True, "contextWindow": 128000, "maxOutput": 32768},
    {"match": re.compile(r"^space.?bunny"), "vision": True, "reasoning": True, "contextWindow": 262144, "maxOutput": 65536},
    {"match": re.compile(r"^union"), "vision": True, "reasoning": False, "contextWindow": 262144, "maxOutput": 131072},
    {"match": re.compile(r"^deepseek"), "vision": False, "reasoning": True, "contextWindow": 128000, "maxOutput": 64000},
    {"match": re.compile(r"^jev"), "vision": False, "reasoning": False, "contextWindow": 32768, "maxOutput": 4096},
]

#: 按精确 ID 覆盖（优先于家族级），含思考档位菜单。
#: `efforts` 声明了模型自己的档位时，档位以 `reasoning_effort` 上线；
#: `effortPatch` 用 `$effort` 占位，`effortOffPatch` 是关闭档的补丁。
FREE_ID_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "deepseek-v4.1-flash-free": {
        "vision": True, "contextWindow": 1048576, "maxOutput": 384000,
        "efforts": ["disabled", "low", "high", "max"], "effortDefault": "high",
        "effortPatch": {"reasoning_effort": "$effort"},
        "effortOffPatch": {"reasoning_effort": "none"},
    },
    "glm-5.3-flash-free": {
        "vision": True, "contextWindow": 1048576, "maxOutput": 131072,
        "efforts": ["low", "high", "max"], "effortDefault": "high",
        "effortPatch": {"reasoning_effort": "$effort"},
    },
    "nemotron-3.5-super-vl-free": {
        "vision": True, "contextWindow": 1048576, "maxOutput": 131072,
        "efforts": ["disabled", "minimal", "low", "medium", "high", "xhigh"], "effortDefault": "high",
        "effortPatch": {"reasoning_effort": "$effort"},
        "effortOffPatch": {"reasoning_effort": "none"},
    },
    "space-bunny-free": {
        "vision": True, "contextWindow": 1048576, "maxOutput": 524288,
        "efforts": ["low", "medium", "high", "xhigh", "max"], "effortDefault": "high",
        "effortPatch": {"reasoning_effort": "$effort"},
    },
    "longcat-2.5-preview-free": {
        "vision": False, "contextWindow": 1048576, "maxOutput": 131072,
    },
    "big-pickle": {"vision": True, "contextWindow": 262144, "maxOutput": 131072},
}

#: 展示名（裸上游 id 不进选择器）。
DISPLAY_NAMES: Dict[str, str] = {
    "mimo-v2.6-flash-free": "MiMo V2.6 Flash",
    "mimo-v2.5-free": "MiMo V2.5",
    "muse-spark-1.3-contributor-free": "Muse Spark 1.3",
    "muse-spark-1.2-contributor-free": "Muse Spark 1.2",
    "nemotron-3-ultra-free": "Nemotron 3 Ultra",
    "nemotron-3.5-lightning-free": "Nemotron 3.5 Lightning",
    "ling-3.0-flash-fin-free": "Ling 3.0 Flash Fin",
    "space-bunny-free": "Space Bunny",
    "union-alpha": "Union Alpha",
    "deepseek-v4-flash-free": "DeepSeek V4 Flash",
    "deepseek-v4.1-flash-free": "DeepSeek V4.1 Flash",
    "glm-5.3-flash-free": "GLM 5.3 Flash",
    "jev-1.13-free": "Jev 1.13",
}

#: 已知出口地域敏感的模型。
REGION_SENSITIVE = [re.compile(r"^muse.?spark")]

#: 车道标识。
LANE_OPENCODE = "opencode"
LANE_KILO = "kilo"
KILO_TAG = "Kilo"


def is_free_lane(model_id: Any) -> bool:
    """该 id 是否免密车道模型（清单里混着付费 id，只有这些免密可答）。"""
    base = base_model_id(model_id)
    if not base:
        return False
    if base in ALWAYS_FREE:
        return True
    return re.search(r"(?:^|[-_])free(?:$|[-_.])", base) is not None


def capabilities_for(model_id: Any) -> Dict[str, Any]:
    """查能力表：精确 ID 覆盖优先于家族模式，都没有则保守缺省。"""
    base = base_model_id(model_id)
    override = FREE_ID_OVERRIDES.get(base)
    if override is not None:
        return {"reasoning": True, **override}
    for entry in CAPABILITIES:
        if entry["match"].search(base):
            return entry
    return {"vision": False, "reasoning": True, "contextWindow": 131072, "maxOutput": 32768}


def is_region_sensitive(model_id: Any) -> bool:
    """该模型的可用性是否与出口地域相关。"""
    base = base_model_id(model_id)
    return any(pattern.search(base) for pattern in REGION_SENSITIVE)


def display_model_name(model_id: Any) -> str:
    """裸上游 id → 可展示名。"""
    base = base_model_id(model_id)
    known = DISPLAY_NAMES.get(base)
    if known is not None:
        return known
    words = re.sub(r"[-_.]+", " ", base).strip().split()
    pretty = " ".join(word if word[:1].isdigit() else word[:1].upper() + word[1:] for word in words if word)
    return pretty or base


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, (int, float)) and value == value and value > 0:
        return int(value)
    return None


def build_free_catalog(ids: List[Any]) -> List[Dict[str, Any]]:
    """
    上游清单 id + 本地能力表 → 免费车道目录条目（清单顺序）。

    条目字段：id / name / lane / wire / vision / reasoning / contextWindow /
    maxOutput / canDisableThinking / regionSensitive / efforts…
    """
    seen = set()
    entries: List[Dict[str, Any]] = []
    for raw in ids or []:
        model_id = base_model_id(raw)
        if not model_id or not is_free_lane(model_id) or model_id in seen:
            continue
        seen.add(model_id)
        caps = capabilities_for(model_id)
        efforts = caps.get("efforts") if isinstance(caps.get("efforts"), list) else None
        entry: Dict[str, Any] = {
            "id": model_id,
            "name": display_model_name(model_id),
            "lane": LANE_OPENCODE,
            "wire": "responses" if is_responses_model(model_id) else "chat",
            "vision": caps.get("vision") is True,
            "reasoning": caps.get("reasoning") is not False,
            "contextWindow": _positive_int(caps.get("contextWindow")) or 131072,
            "maxOutput": _positive_int(caps.get("maxOutput")) or 32768,
            "canDisableThinking": ("disabled" in efforts) if efforts else caps.get("canDisableThinking") is not False,
            "regionSensitive": is_region_sensitive(model_id),
        }
        if efforts:
            entry["efforts"] = list(efforts)
            entry["effortDefault"] = caps.get("effortDefault") or "high"
            if "effortPatch" in caps:
                entry["effortPatch"] = caps["effortPatch"]
            if "effortOffPatch" in caps:
                entry["effortOffPatch"] = caps["effortOffPatch"]
        entries.append(entry)
    return entries


def parse_listing(payload: Any) -> List[str]:
    """解析网关 `{"data":[{"id":…}]}` 形态的清单，返回 id 列表。"""
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("models") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, str) and row:
            out.append(row)
        elif isinstance(row, dict):
            model_id = row.get("id")
            if isinstance(model_id, str) and model_id:
                out.append(model_id)
    return out


# ---------------------------------------------------------------------------
# Kilo 免费池
# ---------------------------------------------------------------------------

#: Kilo 上思考不可关闭的系列 / ID。
_KILO_REASONING_MANDATORY = [re.compile(r"^stepfun/"), re.compile(r"^liquid/"), re.compile(r"^thinkingmachines/")]
_KILO_NO_DISABLE_IDS = {"kilo-auto/free", "openrouter/free"}
_KILO_EFFORT_PATCH = {"reasoning_effort": "$effort"}
_KILO_EFFORT_OFF_PATCH = {"reasoning": {"enabled": False}}


def is_kilo_free_row(row: Any) -> bool:
    """该清单行是否 Kilo 免费池（其余是付费 id，免密请求回 401）。"""
    return isinstance(row, dict) and row.get("isFree") is True \
        and isinstance(row.get("id"), str) and bool(row.get("id").strip())


def _kilo_effort_menu(row: Dict[str, Any]) -> Dict[str, Any]:
    params = row.get("supported_parameters") if isinstance(row.get("supported_parameters"), list) else []
    if "reasoning" not in params:
        return {}
    model_id = str(row.get("id") or "")
    can_disable = not any(pattern.search(model_id) for pattern in _KILO_REASONING_MANDATORY) \
        and model_id not in _KILO_NO_DISABLE_IDS
    menu: Dict[str, Any] = {
        "efforts": ["disabled", "low", "medium", "high"] if can_disable else ["low", "medium", "high"],
        "effortDefault": "high",
        "effortPatch": _KILO_EFFORT_PATCH,
        "canDisableThinking": can_disable,
    }
    if can_disable:
        menu["effortOffPatch"] = _KILO_EFFORT_OFF_PATCH
    return menu


def kilo_display_name(row: Dict[str, Any]) -> str:
    """清单名去掉厂商前缀与 `(free)` 限定，加 `Kilo` 频道标记。"""
    raw = str(row.get("name") or "").strip()
    bare = (raw or str(row.get("id") or ""))
    bare = re.sub(r"^[^:]{1,40}:\s+", "", bare)
    bare = re.sub(r"\s*\(free\)\s*$", "", bare, flags=re.IGNORECASE).strip()
    if bare:
        pretty = bare
    else:
        words = re.sub(r"[-_.]+", " ", str(row.get("id") or "")).strip().split()
        pretty = " ".join(
            word if word[:1].isdigit() or word.upper() == word else word[:1].upper() + word[1:]
            for word in words if word
        )
    return f"{KILO_TAG} {pretty or row.get('id')}"


def build_kilo_catalog(rows: List[Any]) -> List[Dict[str, Any]]:
    """Kilo 清单行 → 目录条目；非免费池与重复 id 丢弃。"""
    seen = set()
    entries: List[Dict[str, Any]] = []
    for row in rows or []:
        if not is_kilo_free_row(row):
            continue
        model_id = str(row["id"]).strip()
        if model_id in seen:
            continue
        seen.add(model_id)
        context = _positive_int(row.get("context_length")) \
            or _positive_int((row.get("top_provider") or {}).get("context_length")) or 131072
        output = _positive_int((row.get("top_provider") or {}).get("max_completion_tokens")) or 32768
        modalities = (row.get("architecture") or {}).get("input_modalities") or []
        menu = _kilo_effort_menu(row)
        entry: Dict[str, Any] = {
            "id": model_id,
            "name": kilo_display_name(row),
            "lane": LANE_KILO,
            "wire": "chat",
            "vision": "image" in (modalities if isinstance(modalities, list) else []),
            "reasoning": True,
            "contextWindow": context,
            "maxOutput": output,
            "canDisableThinking": menu.get("canDisableThinking") is True,
            "regionSensitive": False,
        }
        if menu.get("efforts"):
            entry["efforts"] = list(menu["efforts"])
            entry["effortDefault"] = menu.get("effortDefault")
            entry["effortPatch"] = menu.get("effortPatch")
            if "effortOffPatch" in menu:
                entry["effortOffPatch"] = menu["effortOffPatch"]
        entries.append(entry)
    return entries


def revive_catalog(stored: List[Any]) -> List[Dict[str, Any]]:
    """
    从持久化缓存重建目录（逐字段校验，坏数据降级为更短清单而非畸形清单）。
    """
    seen = set()
    entries: List[Dict[str, Any]] = []
    for row in stored or []:
        if not isinstance(row, dict):
            continue
        model_id = base_model_id(row.get("id"))
        lane = row.get("lane")
        if not model_id or lane not in (LANE_OPENCODE, LANE_KILO) or model_id in seen:
            continue
        entry: Dict[str, Any] = {
            "id": model_id,
            "name": str(row.get("name") or display_model_name(model_id)),
            "lane": lane,
            "wire": row.get("wire") if row.get("wire") in ("chat", "responses", "messages") else "chat",
            "vision": row.get("vision") is True,
            "reasoning": row.get("reasoning") is not False,
            "contextWindow": _positive_int(row.get("contextWindow")) or 131072,
            "maxOutput": _positive_int(row.get("maxOutput")) or 32768,
            "canDisableThinking": row.get("canDisableThinking") is not False,
            "regionSensitive": row.get("regionSensitive") is True,
        }
        efforts = row.get("efforts")
        if isinstance(efforts, list) and efforts:
            entry["efforts"] = [str(level) for level in efforts if isinstance(level, str)]
            entry["effortDefault"] = str(row.get("effortDefault") or "high")
            if isinstance(row.get("effortPatch"), dict):
                entry["effortPatch"] = row["effortPatch"]
            if isinstance(row.get("effortOffPatch"), dict):
                entry["effortOffPatch"] = row["effortOffPatch"]
            entry["canDisableThinking"] = "disabled" in entry["efforts"]
        seen.add(model_id)
        entries.append(entry)
    return entries


def find_entry(entries: List[Dict[str, Any]], model_id: Any) -> Optional[Dict[str, Any]]:
    """按基础 ID 查目录条目。"""
    base = base_model_id(model_id)
    for entry in entries or []:
        if entry.get("id") == base:
            return entry
    return None


# ---------------------------------------------------------------------------
# 思考强度（effort）
# ---------------------------------------------------------------------------

MIN_BUDGET = 1


def _instantiate_patch(patch: Any, effort: str) -> Any:
    """把补丁模板里的 `$effort` 占位换成选定档位。"""
    if isinstance(patch, str):
        return effort if patch == "$effort" else patch
    if isinstance(patch, list):
        return [_instantiate_patch(item, effort) for item in patch]
    if isinstance(patch, dict):
        return {key: _instantiate_patch(value, effort) for key, value in patch.items()}
    return patch


def default_effort_level(entry: Dict[str, Any]) -> str:
    """该条目思考菜单的缺省档位。"""
    levels = entry.get("efforts") if isinstance(entry.get("efforts"), list) else []
    if not levels:
        return ""
    preferred = entry.get("effortDefault")
    return preferred if preferred in levels else levels[0]


def effort_patch_for(level: Any, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    选定思考档位 → 请求体合并补丁（ZCode 声明形态）。

    无档位菜单的条目返回 None（走输出预算阶梯的语义在 budget_for）。
    """
    efforts = entry.get("efforts") if isinstance(entry.get("efforts"), list) else None
    if not efforts:
        return None
    chosen = level if level in efforts else default_effort_level(entry)
    if chosen == "disabled" and "effortOffPatch" in entry:
        return _instantiate_patch(entry["effortOffPatch"], chosen)
    if "effortPatch" not in entry:
        return None
    return _instantiate_patch(entry["effortPatch"], chosen)


def has_declared_effort_menu(entry: Optional[Dict[str, Any]]) -> bool:
    """条目是否声明了自己的思考档位菜单。"""
    return bool(entry and isinstance(entry.get("efforts"), list) and entry.get("efforts"))


def budget_for(entry: Optional[Dict[str, Any]], requested: Any, fallback: Any = None) -> int:
    """
    本轮输出 token 预算。

    声明了思考菜单的条目：菜单本身就是控制，上限取模型容量；
    未声明的条目按免密车道的预算语义取容量上限（MoviePilot 侧不再细分阶梯）。
    """
    capacity = entry.get("maxOutput") if entry else None
    capacity = _positive_int(capacity) or 32768
    for candidate in (requested, fallback):
        usable = _positive_int(candidate)
        if usable is not None:
            capacity = min(capacity, usable)
            break
    return max(MIN_BUDGET, int(capacity))
