"""
WorkBuddy 上游线协议规整与解析（纯函数，不发起网络请求）。

覆盖 dsh-workbuddy-connect/src/upstream.ts 中与线格式有关的全部可移植逻辑：
聊天请求体规整、网关会话头、错误分类、模型目录解析、计费文档解析、
SSE 聚合为非流式 chat.completion 等。模块保持无 I/O，便于独立测试。
"""

import hashlib
import json
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .variants import INTERNATIONAL_SYSTEM_PROMPT

# ---------------------------------------------------------------------------
# 错误分类
# ---------------------------------------------------------------------------

# 积分不足标记（ASCII 小写 + 中文原文）
HARD_CREDIT_MARKERS: Tuple[str, ...] = (
    "insufficient credit", "no credit", "credit exhausted", "credits exhausted",
    "out of credit", "quota exceeded", "quota exhaust", "payment required",
    "credit not enough", "not enough credit",
    "积分不足", "额度不足", "余额不足", "积分用完", "额度用尽", "没有积分",
)

# 429 场景专用的硬性积分标记（限流响应也可能含 quota 字样，不能混用通用列表）
HARD_CREDIT_MARKERS_ON_429: Tuple[str, ...] = (
    "14018",
    "credit exhausted", "credits exhausted", "insufficient credit", "no credit",
    "out of credit", "credit not enough", "not enough credit", "payment required",
    "积分不足", "额度不足", "余额不足", "积分用完", "额度用尽", "没有积分",
)

# 无 429 状态码也可能出现的限流标记
SOFT_RATE_MARKERS: Tuple[str, ...] = (
    "rate limit", "rate-limiting", "rate-limited", "too many requests", "too many",
    "usage limit", "请求过于频繁", "限流",
)

# 会话失效标记：需要重新登录
SESSION_DEAD_MARKERS: Tuple[str, ...] = ("Offline user session not found", "12153")

# 上游暴露的 reasoning_effort 取值集合（目录元数据词汇）
EFFORT_VALUES: Tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")
# 线上校验实际接受的集合更大（含 minimal/none），仅作归一化目标参考

_BADGE_PREFIX = "badge:"


def classify_upstream_error(status: int, body: str) -> str:
    """
    依据 HTTP 状态与响应体摘要给上游失败分类。

    分类顺序是承重的：硬性积分拒绝最致命最先判；会话死亡其次；
    429 先查自身专用标记，再落回限流；短语列表补足状态码看不出来的失败。
    返回 hard_credit / soft_rate / session_dead / not_found / server / client 之一。
    """
    lower = body.lower()
    if status == 402:
        return "hard_credit"
    for marker in SESSION_DEAD_MARKERS:
        if marker in body:
            return "session_dead"
    if status == 429:
        for marker in HARD_CREDIT_MARKERS_ON_429:
            if marker.lower() in lower or marker in body:
                return "hard_credit"
        return "soft_rate"
    for marker in HARD_CREDIT_MARKERS:
        if marker.lower() in lower or marker in body:
            return "hard_credit"
    for marker in SOFT_RATE_MARKERS:
        if marker.lower() in lower or marker in body:
            return "soft_rate"
    if status == 404:
        return "not_found"
    if status >= 500 or status == 0:
        return "server"
    return "client"


# 上游失败类到 OpenAI 兼容层 HTTP 状态的映射（与 shim.ts 的 KIND_STATUS 一致）
KIND_STATUS: Dict[str, int] = {
    "hard_credit": 402,
    "soft_rate": 429,
    "session_dead": 401,
    "not_found": 502,
    "server": 502,
    "client": 400,
}


def is_interception_page(body: str) -> bool:
    """判断 403 响应体是否为 WAF 拦截页（HTML），而非 API 拒绝（JSON）。"""
    head = body[:2048].lower()
    return "<html" in head or "<!doctype html" in head


def path_fallback_status(status: int, body: Optional[str] = None) -> bool:
    """
    失败请求是否应改试下一个候选路径。

    刻意收窄：只有 404/405（路由不存在）与 WAF 拦截页 403 才回落，
    账号级拒绝（401/402/429）与网关故障（5xx）不重复请求。
    """
    if status in (404, 405):
        return True
    if status == 403 and body is not None:
        return is_interception_page(body)
    return False


# ---------------------------------------------------------------------------
# 区域判定
# ---------------------------------------------------------------------------

def region_of(domain: str) -> str:
    """由登录域判断区域；空域名视为国内版（与上游工具链一致）。"""
    lowered = (domain or "").strip().lower()
    if lowered == "workbuddy.ai" or lowered.endswith(".workbuddy.ai"):
        return "global"
    return "cn"


def realm_of(credential: Any) -> str:
    """
    凭据所属区域：显式 region 优先（值为 global 即国际版），
    否则由 domain 判定；其余一律国内版。
    """
    region = getattr(credential, "region", None)
    if isinstance(credential, dict):
        region = credential.get("region", region)
    if region == "global":
        return "global"
    domain = getattr(credential, "domain", "")
    if isinstance(credential, dict):
        domain = credential.get("domain", domain)
    return region_of(domain or "")


# ---------------------------------------------------------------------------
# 设备指纹与稳定 ID
# ---------------------------------------------------------------------------

def derive_account_stable_id(uid: str, purpose: str) -> str:
    """由 uid 派生稳定的 36 位十六进制设备标识（跨重启稳定、按账号隔离）。"""
    digest = hashlib.sha256(f"wb2a:{purpose}:{uid}".encode("utf-8")).hexdigest()
    return digest[:36]


def account_stable_headers(uid: str) -> Dict[str, str]:
    """按账号派生的 X-Machine-ID / X-Session-ID；无 uid 时不携带。"""
    if not uid:
        return {}
    return {
        "X-Machine-ID": derive_account_stable_id(uid, "machine"),
        "X-Session-ID": derive_account_stable_id(uid, "session"),
    }


# ---------------------------------------------------------------------------
# 请求头组装
# ---------------------------------------------------------------------------

def build_common_headers(credential: Any, user_agent: Optional[str] = None) -> Dict[str, str]:
    """所有上游请求共享的基础请求头。"""
    region = realm_of(credential)
    domain = getattr(credential, "domain", "") or ""
    uid = getattr(credential, "uid", "") or ""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.workbuddy.ai" if region == "global" else "https://www.codebuddy.cn",
        "Referer": ("https://www.workbuddy.ai" if region == "global" else "https://www.codebuddy.cn") + "/",
        "User-Agent": user_agent or "CLI/2.63.2 CodeBuddy/2.63.2",
        "X-CodeBuddy-Request": "1",
        "Accept-Language": "en-US" if region == "global" else "zh-CN",
    }
    headers.update(account_stable_headers(uid))
    return headers


def build_chat_headers(credential: Any, user_agent: Optional[str] = None) -> Dict[str, str]:
    """
    聊天请求头：在公共头之上叠加鉴权、会话归属与归因头族。

    - X-Agent-Type 仅国际版发送（国内版客户端没有该身份）；
    - 国际版恒声明 X-Domain: www.workbuddy.ai，携带企业 ID 会被判非法；
    - 安全红线：聊天请求绝不携带 refresh token。
    """
    region = realm_of(credential)
    international = region == "global"
    domain = getattr(credential, "domain", "") or ""
    uid = getattr(credential, "uid", "") or ""
    enterprise_id = getattr(credential, "enterpriseId", None) or getattr(credential, "enterprise_id", None) or ""
    access_token = getattr(credential, "accessToken", "") or getattr(credential, "access_token", "") or ""

    headers = build_common_headers(credential, user_agent)
    headers["Accept"] = "application/json, text/event-stream"
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    else:
        headers["X-No-Authorization"] = "1"
    if uid:
        headers["X-User-Id"] = uid
    else:
        headers["X-No-User-Id"] = "1"
    if international:
        headers["X-No-Enterprise-Id"] = "1"
        headers["X-Domain"] = "www.workbuddy.ai"
    else:
        if enterprise_id:
            headers["X-Enterprise-Id"] = enterprise_id
        else:
            headers["X-No-Enterprise-Id"] = "1"
        if domain:
            headers["X-Domain"] = domain
        else:
            headers["X-No-Department-Info"] = "1"
    # 使用归因：上游按客户端统计用量，无归因头会被记为匿名网关调用
    headers["X-Agent-Intent"] = "craft"
    headers["X-Agent-Purpose"] = "conversation"
    if international:
        headers["X-Agent-Type"] = "main"
    headers["X-IDE-Name"] = "WorkBuddy"
    headers["X-IDE-Type"] = "WorkBuddy"
    headers["X-IDE-Version"] = "2.63.2"
    headers["X-Product"] = "WorkBuddy"
    return headers


def build_refresh_headers(credential: Any) -> Dict[str, str]:
    """刷新端点头：X-Refresh-Token 只出现在这里。"""
    enterprise_id = getattr(credential, "enterpriseId", None) or getattr(credential, "enterprise_id", None) or ""
    headers = build_common_headers(credential)
    headers["X-Refresh-Token"] = getattr(credential, "refreshToken", "") or getattr(credential, "refresh_token", "") or ""
    headers["X-Auth-Refresh-Source"] = "plugin"
    if enterprise_id:
        headers["X-Enterprise-Id"] = enterprise_id
    return headers


def build_billing_headers(credential: Any) -> Dict[str, str]:
    """计费请求头（不走公共头组装，设备指纹与网关头在此同样补齐）。"""
    region = realm_of(credential)
    domain = getattr(credential, "domain", "") or ""
    uid = getattr(credential, "uid", "") or ""
    enterprise_id = getattr(credential, "enterpriseId", None) or getattr(credential, "enterprise_id", None) or ""
    access_token = getattr(credential, "accessToken", "") or getattr(credential, "access_token", "") or ""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-CodeBuddy-Request": "1",
        "Accept-Language": "en-US" if region == "global" else "zh-CN",
        "User-Agent": "CLI/2.63.2 CodeBuddy/2.63.2",
    }
    headers.update(account_stable_headers(uid))
    if uid:
        headers["X-User-Id"] = uid
    if enterprise_id:
        headers["X-Enterprise-Id"] = enterprise_id
        headers["X-Tenant-Id"] = enterprise_id
    if domain:
        headers["X-Domain"] = domain
    return headers


def chat_user_agent(region: str, client_version: str, cli_version: Optional[str] = None) -> str:
    """
    聊天请求的桌面端形态 User-Agent：
    WorkBuddy/<v> <产品>/<v> [CLI/<cli>]。
    CLI 版本无法确定时省略该段，绝不编造。
    """
    product = "WorkBuddy AI" if region == "global" else "WorkBuddy"
    parts = [f"WorkBuddy/{client_version}", f"{product}/{client_version}"]
    if cli_version:
        parts.append(f"CLI/{cli_version}")
    return " ".join(parts)


def app_user_agent(version: str) -> str:
    """国际版目录接口的 App 形态 User-Agent。"""
    return f"WorkBuddyAI/{version}"


# ---------------------------------------------------------------------------
# 网关会话头（X-Conversation-* 家族）
# ---------------------------------------------------------------------------

# 每进程随机盐：派生 ID 不可逆推原文，进程重启后进入新命名空间
_CONVERSATION_ID_SALT = os.urandom(16).hex()


def _conversation_id_hex() -> str:
    """生成上游客户端形态的 32 位十六进制 ID。"""
    return os.urandom(16).hex()


def _derived_conversation_id(kind: str, key: str) -> str:
    digest = hashlib.sha256(f"{_CONVERSATION_ID_SALT}|{kind}|{key}".encode("utf-8")).hexdigest()
    return digest[:32]


def _message_signature(content: Any) -> str:
    """消息内容签名：文本 + 非文本部分摘要（纯图消息也能标识一轮）。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    out = ""
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type") or ""
        if part_type in ("", "text"):
            text = part.get("text")
            out += text if isinstance(text, str) else ""
        else:
            digest = hashlib.sha256(json.dumps(part, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:8]
            out += f"[{part_type}:{digest}]"
    return out


def _answered_before(messages: List[Any], index: int) -> bool:
    """messages[index] 是否是在回答前一条（工具结果或助手工具调用）。"""
    if index <= 0:
        return False
    prev = messages[index - 1]
    if not isinstance(prev, dict):
        return False
    if prev.get("role") == "tool":
        return True
    return prev.get("role") == "assistant" and bool(prev.get("tool_calls"))


def _is_tool_result_only(content: Any) -> bool:
    """消息内容是否只是工具结果（Anthropic 形态客户端会放进 user 消息）。"""
    if not isinstance(content, list) or not content:
        return False
    for part in content:
        if not isinstance(part, dict):
            return False
        if part.get("type") not in ("tool_result", "tool-result"):
            return False
    return True


def turn_key_of(body: Optional[Dict[str, Any]]) -> str:
    """
    命名本次用户发送：取最后一条属于用户本人的 user 消息的签名。
    工具循环的每一步沿用同一轮 ID，用户的下一条消息才开启新轮。
    """
    messages = body.get("messages") if isinstance(body, dict) else None
    if not isinstance(messages, list):
        return ""
    for i in range(len(messages) - 1, -1, -1):
        message = messages[i]
        if not isinstance(message, dict):
            continue
        if message.get("role") != "user" or _answered_before(messages, i):
            continue
        if _is_tool_result_only(message.get("content")):
            continue
        signature = _message_signature(message.get("content"))
        return f"u{i}:{signature}" if signature else ""
    return ""


def conversation_key_of(body: Optional[Dict[str, Any]]) -> str:
    """命名会话：取首条 user 消息的签名；无用户消息则不声称会话。"""
    messages = body.get("messages") if isinstance(body, dict) else None
    if not isinstance(messages, list):
        return ""
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        signature = _message_signature(message.get("content"))
        if signature:
            return f"first:{signature}"
    return ""


def with_gateway_chat_headers(headers: Dict[str, str], prepared_body: str) -> Dict[str, str]:
    """
    为聊天请求附加 X-Conversation-* 会话追踪头族。

    会话门禁是独立开关（实测两区域多数账号未开启，但部分部署要求携带，
    缺失报 400/code 11128 "request illegal"），因此无条件补齐。
    调用方已携带的同名头保持不变。
    """
    body: Optional[Dict[str, Any]] = None
    try:
        parsed = json.loads(prepared_body)
        if isinstance(parsed, dict):
            body = parsed
    except (ValueError, TypeError):
        body = None
    message_id = _conversation_id_hex()
    headers.setdefault("X-Conversation-Message-ID", message_id)
    # 官方客户端这两个头是同一个值
    headers.setdefault("X-Request-ID", headers["X-Conversation-Message-ID"])
    turn = turn_key_of(body)
    if "X-Conversation-Request-ID" not in headers:
        headers["X-Conversation-Request-ID"] = (
            _derived_conversation_id("turn", turn) if turn else _conversation_id_hex()
        )
    conversation = conversation_key_of(body)
    if conversation:
        headers.setdefault("X-Conversation-ID", _derived_conversation_id("conversation", conversation))
    return headers


# ---------------------------------------------------------------------------
# 聊天请求体规整
# ---------------------------------------------------------------------------

def normalize_reasoning_effort(obj: Dict[str, Any], default_effort: Optional[str] = None) -> None:
    """
    把"无显式选择"的 reasoning_effort 拼写归一化为目录声明的默认档位。

    off/disabled/default/auto 都是"用上游默认"的语义，但上游校验会拒绝这些
    拼写（HTTP 400 / code 11133）。归一化为目录 defaultEffort；目录也没有
    默认值时直接删除字段。其余取值原样透传。
    """
    effort = obj.get("reasoning_effort")
    if effort not in ("default", "auto", "off", "disabled"):
        return
    if isinstance(default_effort, str) and default_effort:
        obj["reasoning_effort"] = default_effort
    else:
        obj.pop("reasoning_effort", None)


def translate_max_completion_tokens(obj: Dict[str, Any]) -> None:
    """
    把 OpenAI 的 max_completion_tokens 别名翻译为上游读取的 max_tokens。

    显式 max_tokens 优先；别名仅在为正整数时翻译，0/null/负数视为未设置。
    """
    present = "max_completion_tokens" in obj
    alias = obj.pop("max_completion_tokens", None)
    if not present or "max_tokens" in obj:
        return
    if isinstance(alias, int) and not isinstance(alias, bool) and alias > 0:
        obj["max_tokens"] = alias


def normalize_developer_role(obj: Dict[str, Any]) -> None:
    """把 role=developer 改写为 system（上游拒绝 developer，报 400/11128）。"""
    messages = obj.get("messages")
    if not isinstance(messages, list):
        return
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "developer":
            message["role"] = "system"


# 上游渠道指纹：system content 以此开头（大小写不敏感）→ 400/11128「请求被拦截」。
_BLOCKED_SYSTEM_PREFIX = "you are an ai agent powered by deepseek harness"
# 绕过前缀：任意非空文本均可让 startsWith 失配；选零宽空格不影响语义。
_CHANNEL_BYPASS_PREFIX = "​"


def _system_content_starts_blocked(text: str) -> bool:
    return text.lstrip().lower().startswith(_BLOCKED_SYSTEM_PREFIX)


def _bypass_system_content(text: str) -> str:
    return _CHANNEL_BYPASS_PREFIX + text


def sanitize_system_prompt_channel(obj: Dict[str, Any]) -> None:
    """
    上游对 system 消息做渠道指纹校验：content 以
    "You are an AI agent powered by DeepSeek Harness" 开头（大小写不敏感）
    时直接 400/11128「请求被拦截，请重新发送」。实测在前面加任意文本即可绕过。
    此处给命中的 system 消息统一加零宽空格前缀，保证透传不被误拦。
    """
    messages = obj.get("messages")
    if not isinstance(messages, list):
        return
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "system":
            continue
        content = message.get("content")
        if isinstance(content, str):
            if _system_content_starts_blocked(content):
                message["content"] = _bypass_system_content(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    if isinstance(text, str) and _system_content_starts_blocked(text):
                        item["text"] = _bypass_system_content(text)


def normalize_tool_choice(obj: Dict[str, Any]) -> None:
    """
    把 OpenAI 的 tool_choice 对象拼写压平为上游接受的字符串形态。
    tool_choice=none 时连同 tools 一起移除（上游没有 none 语义）。
    """
    if "tool_choice" not in obj:
        return

    def suppress() -> None:
        obj.pop("tools", None)
        obj.pop("functions", None)

    choice = obj["tool_choice"]
    if isinstance(choice, str):
        if choice.strip().lower() == "none":
            obj.pop("tool_choice", None)
            suppress()
        return
    if isinstance(choice, dict):
        choice_type = str(choice.get("type", "")).strip().lower()
        if choice_type == "none":
            obj.pop("tool_choice", None)
            suppress()
        elif choice_type in ("auto", "required"):
            obj["tool_choice"] = choice_type
        elif choice_type == "function":
            fn = choice.get("function") if isinstance(choice.get("function"), dict) else {}
            name = str(fn.get("name") or choice.get("name") or "").strip()
            obj["tool_choice"] = name or "auto"
        else:
            obj.pop("tool_choice", None)
        return
    obj.pop("tool_choice", None)


def prepare_chat_body(source: str, default_effort: Optional[str] = None) -> str:
    """
    把 OpenAI chat-completions 请求体规整为 WorkBuddy 上游接受的形态：

    - 强制 stream=true（上游拒绝非流式）；
    - max_completion_tokens → max_tokens；
    - 默认 stream_options.include_usage（与官方客户端一致）；
    - developer → system；tool_choice 压平为字符串；
    - system 消息渠道指纹绕过（"You are an AI agent powered by DeepSeek Harness"
      开头的 system prompt 被上游 400/11128 拦截，自动加零宽前缀规避）；
    - reasoning_effort 的"默认/关闭"拼写归一化；
    - 删除 store（OpenAI 专有字段，上游整单 400/11133）。
    """
    try:
        body = json.loads(source)
    except (ValueError, TypeError):
        return source
    if not isinstance(body, dict):
        return source
    body["stream"] = True
    translate_max_completion_tokens(body)
    if "stream_options" not in body:
        body["stream_options"] = {"include_usage": True}
    normalize_developer_role(body)
    sanitize_system_prompt_channel(body)
    normalize_tool_choice(body)
    normalize_reasoning_effort(body, default_effort)
    body.pop("store", None)
    return json.dumps(body, ensure_ascii=False)


def prepare_international_chat_body(source: str, default_effort: Optional[str] = None) -> str:
    """
    国际版附加要求：首条消息必须是 system，否则 400/11128。
    已有 system 开头的请求体原样保留；缺失时前置最小提示词。
    """
    prepared = prepare_chat_body(source, default_effort)
    try:
        body = json.loads(prepared)
    except (ValueError, TypeError):
        return prepared
    if not isinstance(body, dict):
        return prepared
    messages = body.get("messages")
    if not isinstance(messages, list):
        return prepared
    if messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        return prepared
    messages.insert(0, {"role": "system", "content": INTERNATIONAL_SYSTEM_PROMPT})
    return json.dumps(body, ensure_ascii=False)


def with_prompt_cache_key(source: str, uid: str) -> str:
    """
    为请求体补 prompt_cache_key：同账号同会话命中上游前缀缓存，
    且不同账号的键永不碰撞。已携带键的请求体原样保留。
    """
    try:
        body = json.loads(source)
    except (ValueError, TypeError):
        return source
    if not isinstance(body, dict):
        return source
    existing = body.get("prompt_cache_key")
    if isinstance(existing, str) and existing:
        return source
    conversation = body.get("conversation_id") or body.get("conversationId") or ""
    if not isinstance(conversation, str):
        conversation = ""
    account_segment = uid[:8] if uid else "-"
    conversation_hash = hashlib.sha256(f"{uid}|{conversation}".encode("utf-8")).hexdigest()[:32]
    body["prompt_cache_key"] = f"wb2a-{account_segment}-{conversation_hash}"
    return json.dumps(body, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 信封与模型目录解析
# ---------------------------------------------------------------------------

def read_envelope(document: Any) -> Dict[str, Any]:
    """把 {code,msg,data} 信封解包为统一结构；document 保留整份响应。"""
    if not isinstance(document, dict):
        return {"code": 0, "msg": "", "data": None, "document": {}}
    return {
        "code": document["code"] if isinstance(document.get("code"), int) else 0,
        "msg": document["msg"] if isinstance(document.get("msg"), str) else "",
        "data": document.get("data"),
        "document": document,
    }


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def resolve_upstream_reasoning(wrapped: Dict[str, Any]) -> Dict[str, Any]:
    """解析目录行的 reasoning 元数据。"""
    supports = wrapped.get("supportsReasoning") is True
    only_reasoning = wrapped.get("onlyReasoning") is True
    supported_efforts: Optional[List[str]] = None
    default_effort: Optional[str] = None
    can_disable = False
    raw = wrapped.get("reasoning")
    if isinstance(raw, dict):
        raw_efforts = raw.get("supportedEfforts")
        if isinstance(raw_efforts, list):
            efforts = [e for e in raw_efforts if e in EFFORT_VALUES]
            if efforts:
                supported_efforts = efforts
        candidate = raw.get("defaultEffort") or raw.get("effort")
        if candidate in EFFORT_VALUES:
            default_effort = candidate
        # 只有显式 true 才允许"关闭思考"；旧行多不接受 off，保守取否
        can_disable = raw.get("canDisableThinking") is True
    return {
        "supports": supports,
        "onlyReasoning": only_reasoning,
        "supportedEfforts": supported_efforts,
        "defaultEffort": default_effort,
        "canDisableThinking": can_disable,
    }


def normalize_credits(credits: Optional[str]) -> Optional[str]:
    """把上游 credits 字符串收敛为语言中立的倍率显示（去掉尾部 credits 单位词）。"""
    if credits is None:
        return None
    trimmed = credits.strip()
    if not trimmed:
        return None
    if re.fullmatch(r"credits?", trimmed, flags=re.IGNORECASE):
        return None
    bare = re.sub(r"\s+credits?$", "", trimmed, flags=re.IGNORECASE).strip()
    return bare or None


def resolve_upstream_billing(wrapped: Dict[str, Any]) -> Dict[str, Any]:
    """解析目录行的计费元数据（credits 倍率与促销徽章）。"""
    raw_credits = wrapped.get("credits")
    credits = raw_credits.strip() if isinstance(raw_credits, str) and raw_credits.strip() else None
    badges: List[str] = []
    tags = wrapped.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, str) or not tag.lower().startswith(_BADGE_PREFIX):
                continue
            label = tag[len(_BADGE_PREFIX):].split(":")[0]
            if label:
                badges.append(label)
    free = credits is not None and re.fullmatch(r"x?0\.0+", credits) is not None
    return {
        "credits": credits,
        "badges": badges or None,
        "free": free,
    }


def parse_promotions(value: Any, model: str) -> List[Dict[str, Any]]:
    """提取覆盖指定模型的启用态、可解析的 replace 型促销。"""
    if not isinstance(value, list):
        return []
    result: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or item.get("enabled") is not True:
            continue
        model_ids = item.get("modelIds")
        if not isinstance(model_ids, list) or model not in model_ids:
            continue
        schedule = item.get("schedule")
        discount = item.get("discount")
        badge = item.get("badge")
        if not all(isinstance(x, dict) for x in (schedule, discount, badge)):
            continue
        if discount.get("displayMode") != "replace":
            continue
        try:
            start = _parse_offset_ts(schedule.get("validFrom"))
            end = _parse_offset_ts(schedule.get("validUntil"))
        except (ValueError, TypeError):
            continue
        factor = discount.get("factor")
        if start is None or end is None or end <= start:
            continue
        if not isinstance(factor, (int, float)) or isinstance(factor, bool) or factor < 0:
            continue
        label = badge.get("label") if isinstance(badge.get("label"), str) else ""
        priority = item.get("priority") if isinstance(item.get("priority"), (int, float)) else 0
        result.append({
            "start": start, "end": end, "factor": float(factor),
            "label": label, "priority": float(priority),
        })
    return result


def _parse_offset_ts(value: Any) -> Optional[int]:
    """解析带偏移的 ISO 时间戳为 epoch 毫秒。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(value).timestamp() * 1000)
    except ValueError:
        return None


def parse_model_catalog(data: Dict[str, Any], international: bool = False) -> List[Dict[str, Any]]:
    """
    解析模型目录（两种响应形态共用）：
    data.models[] 提供行明细，data.agents[] 中 name=cli 的模型 ID 列表决定
    目录的成员与顺序。目录不含任何 cli 模型时报错而不是返回空列表。
    """
    raw_models = data.get("models") if isinstance(data.get("models"), list) else []
    agents = data.get("agents") if isinstance(data.get("agents"), list) else []
    cli_ids: Optional[List[str]] = None
    for agent in agents:
        if isinstance(agent, dict) and agent.get("name") == "cli" and isinstance(agent.get("models"), list):
            cli_ids = [m for m in agent["models"] if isinstance(m, str)]
            break
    if not cli_ids:
        raise ValueError("workbuddy model catalog lists no cli agent models")
    by_id: Dict[str, Dict[str, Any]] = {}
    for wrapped in raw_models:
        if not isinstance(wrapped, dict):
            continue
        model_id = wrapped.get("id") if isinstance(wrapped.get("id"), str) else ""
        if not model_id or wrapped.get("disabled") is True:
            continue
        input_tokens = wrapped.get("maxInputTokens") if isinstance(wrapped.get("maxInputTokens"), (int, float)) else 0
        output_tokens = wrapped.get("maxOutputTokens") if isinstance(wrapped.get("maxOutputTokens"), (int, float)) else 0
        if input_tokens <= 0 or output_tokens <= 0:
            continue
        context_window = wrapped.get("contextWindow") if isinstance(wrapped.get("contextWindow"), dict) else {}
        entry: Dict[str, Any] = {
            "id": model_id,
            "name": wrapped.get("name") if isinstance(wrapped.get("name"), str) and wrapped.get("name") else model_id,
            "contextWindow": int(context_window.get("defaultLength")) if international and _positive(context_window.get("defaultLength")) else int(input_tokens),
            "maxTokens": int(output_tokens),
            "supportsImages": wrapped.get("supportsImages") is True and wrapped.get("disabledMultimodal") is not True,
            "reasoning": resolve_upstream_reasoning(wrapped),
            "billing": resolve_upstream_billing(wrapped),
        }
        if international:
            if _positive(context_window.get("defaultLength")):
                entry["defaultContextWindow"] = int(context_window["defaultLength"])
            entry["maxInputTokens"] = int(input_tokens)
            supported = context_window.get("supportedLengths")
            entry["supportedContextWindows"] = [int(x) for x in supported if _positive(x)] if isinstance(supported, list) else []
            entry["promotions"] = parse_promotions(data.get("modelPromotions"), model_id)
        by_id[model_id] = entry
    models = [by_id[m] for m in cli_ids if m in by_id]
    if not models:
        raise ValueError("workbuddy model catalog resolved to an empty list")
    return models


def model_with_current_promotion(model: Dict[str, Any], now_ms: Optional[float] = None) -> Dict[str, Any]:
    """
    按当前时间重估模型促销：生效则叠加徽章与折后倍率；
    全部过期且倍率来自促销时标记 rateUnknown，避免继续宣称免费。
    """
    promotions = model.get("promotions")
    if not promotions:
        return model
    now = now_ms if now_ms is not None else time.time() * 1000
    live = sorted(
        [p for p in promotions if p["start"] <= now < p["end"]],
        key=lambda p: p["priority"], reverse=True,
    )
    billing = dict(model.get("billing") or {})
    if not live:
        derived = billing.get("free") is True or billing.get("badges") or any(p["factor"] != 1 for p in promotions)
        if not derived:
            return model
        stale = normalize_credits(billing.get("credits"))
        expired = sorted({p["label"] for p in promotions if p.get("label")})
        new_billing = {"free": False, "rateUnknown": True}
        if stale:
            new_billing["credits"] = stale
        if expired:
            new_billing["expiredPromotions"] = expired
        return {**model, "billing": new_billing}
    promotion = live[0]
    rate = normalize_credits(billing.get("credits"))
    original = float(rate[1:]) if rate and rate.startswith("x") else float("nan")
    if promotion["factor"] != 0 and original != original:  # NaN
        return model
    value = 0.0 if promotion["factor"] == 0 else original * promotion["factor"]
    badges = list(billing.get("badges") or [])
    if promotion.get("label"):
        badges.append(promotion["label"])
    return {**model, "billing": {
        **billing,
        "credits": f"x{value:.2f}",
        "free": value == 0,
        "badges": badges or None,
    }}


# ---------------------------------------------------------------------------
# 计费文档解析
# ---------------------------------------------------------------------------

def billing_request_body(now: Optional[float] = None) -> str:
    """构造个人计费接口的查询体（时间窗取当前起 365*101 天，与上游工具链一致）。"""
    import datetime as _dt
    moment = _dt.datetime.fromtimestamp(now / 1000 if (now or 0) > 1e12 else (now or time.time()))
    end = moment + _dt.timedelta(days=365 * 101)

    def fmt(value: _dt.datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")

    return json.dumps({
        "PageNumber": 1,
        "PageSize": 100,
        "ProductCode": "p_tcaca",
        "Status": [0, 3],
        "PackageEndTimeRangeBegin": fmt(moment),
        "PackageEndTimeRangeEnd": fmt(end),
    }, ensure_ascii=False)


def parse_personal_credits(document: Dict[str, Any]) -> Dict[str, Any]:
    """
    解析个人计费响应：data.Response.Data.Accounts[] 聚合为
    {total, totalSize?, accounts:[{packageName, remain, size, packageEndTime?}]}。
    """
    wrapper = document.get("data") if isinstance(document.get("data"), dict) else {}
    response = wrapper.get("Response") if isinstance(wrapper.get("Response"), dict) else {}
    inner = response.get("Data") if isinstance(response.get("Data"), dict) else {}
    raw_accounts = inner.get("Accounts") if isinstance(inner.get("Accounts"), list) else []
    accounts: List[Dict[str, Any]] = []
    total = 0
    total_size = 0
    for raw in raw_accounts:
        if not isinstance(raw, dict):
            continue

        def number_field(key: str) -> float:
            value = raw.get(key)
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

        size = number_field("CycleCapacitySize")
        cycle_remain = number_field("CycleCapacityRemain")
        cycle_used = number_field("CycleCapacityUsed")
        capacity_remain = number_field("CapacityRemain")
        if size > 0:
            remain = cycle_remain
        elif cycle_remain > 0 or cycle_used > 0:
            remain = cycle_remain
        else:
            remain = capacity_remain
        remain = max(remain, 0.0)
        total += remain
        total_size += size if size > 0 else number_field("CapacitySize")
        entry: Dict[str, Any] = {
            "packageName": raw.get("PackageName") if isinstance(raw.get("PackageName"), str) else "(unnamed)",
            "remain": remain,
            "size": size if size > 0 else number_field("CapacitySize"),
        }
        # 到期字段：上游实测为 CycleEndTime（周期）或 ExpiredTime（绝对到期）
        for key in ("CycleEndTime", "ExpiredTime"):
            value = raw.get(key)
            if isinstance(value, str) and value:
                entry["packageEndTime"] = value
                break
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                import datetime as _dt
                moment = _dt.datetime.fromtimestamp(value / 1000 if value > 1e12 else value)
                entry["packageEndTime"] = moment.strftime("%Y-%m-%d %H:%M:%S")
                break
        accounts.append(entry)
    # TotalDosage 只作总额下限（已消耗不可能超过总授予），不作虚构值
    dosage = inner.get("TotalDosage")
    if isinstance(dosage, (int, float)) and not isinstance(dosage, bool) and dosage > total_size:
        total_size = float(dosage)
    result: Dict[str, Any] = {"total": total, "accounts": accounts}
    if total_size > 0:
        result["totalSize"] = total_size
    return result


def parse_enterprise_credits(document: Dict[str, Any]) -> Dict[str, Any]:
    """
    解析国内版企业计费响应：单周期额度（limitNum/limit_num + credit/used_num）。
    limit=-1 表示不限量（显式标记，绝不当 0）；无法识别的响应报错而非返回 0。
    """
    sources: List[Dict[str, Any]] = []
    for candidate in (document.get("data"), document):
        if isinstance(candidate, dict):
            if isinstance(candidate.get("data"), dict):
                sources.append(candidate["data"])
            sources.append(candidate)
    limit: Optional[float] = None
    used: Optional[float] = None
    reset_time: Optional[str] = None

    def number_at(source: Dict[str, Any], key: str) -> Optional[float]:
        value = source.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    for source in sources:
        candidate = number_at(source, "limitNum")
        if candidate is None:
            candidate = number_at(source, "limit_num")
        if candidate is None:
            continue
        limit = candidate
        used = number_at(source, "credit")
        if used is None:
            used = number_at(source, "used_num")
        if isinstance(source.get("cycleResetTime"), str) and source["cycleResetTime"]:
            reset_time = source["cycleResetTime"]
        break
    if limit is None:
        raise ValueError("workbuddy enterprise billing response carried no recognised quota field")
    if limit == -1:
        result: Dict[str, Any] = {
            "total": 0,
            "accounts": [{"packageName": "enterprise", "remain": 0, "size": 0, "unlimited": True}],
            "unlimited": True,
        }
        if reset_time:
            result["cycleResetTime"] = reset_time
        return result
    if used is None:
        raise ValueError("workbuddy enterprise billing response carried a quota limit but no recognised usage field")
    remain = max(limit - used, 0.0)
    result = {
        "total": remain,
        "accounts": [{"packageName": "enterprise", "remain": remain, "size": limit}],
    }
    if reset_time:
        result["cycleResetTime"] = reset_time
    return result


# ---------------------------------------------------------------------------
# SSE 聚合（把上游流拼回非流式 chat.completion）
# ---------------------------------------------------------------------------

def iter_sse_data(raw_chunks: Iterable[bytes]) -> Iterable[str]:
    """从原始字节流提取 SSE 的 data 行负载。"""
    buffer = ""
    for chunk in raw_chunks:
        buffer += chunk.decode("utf-8", errors="replace")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.rstrip("\r")
            if line.startswith("data:"):
                yield line[5:].strip()
            elif line == "":
                continue


def aggregate_chat_completion(events: Iterable[str], model: str) -> Dict[str, Any]:
    """
    把流式 SSE 事件聚合为 OpenAI 非流式 chat.completion 文档。
    支持 content / reasoning_content 增量、tool_calls 增量与 usage 终帧。
    """
    content_parts: List[str] = []
    reasoning_parts: List[str] = []
    tool_calls: Dict[int, Dict[str, Any]] = {}
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    created = int(time.time())
    response_id: Optional[str] = None
    for payload in events:
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        if isinstance(event.get("id"), str) and event["id"] and response_id is None:
            response_id = event["id"]
        if isinstance(event.get("created"), int):
            created = event["created"]
        if isinstance(event.get("usage"), dict):
            usage = event["usage"]
        choices = event.get("choices") if isinstance(event.get("choices"), list) else []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            text = delta.get("content")
            if isinstance(text, str):
                content_parts.append(text)
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if isinstance(reasoning, str):
                reasoning_parts.append(reasoning)
            for call in delta.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                index = call.get("index") if isinstance(call.get("index"), int) else 0
                target = tool_calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if call.get("id"):
                    target["id"] = call["id"]
                fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                if fn.get("name"):
                    target["function"]["name"] += fn["name"] if not target["function"]["name"] else ""
                    if not target["function"]["name"]:
                        target["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    target["function"]["arguments"] += fn["arguments"]
    message: Dict[str, Any] = {"role": "assistant", "content": "".join(content_parts) or None}
    if reasoning_parts:
        message["reasoning_content"] = "".join(reasoning_parts)
    if tool_calls:
        message["tool_calls"] = [tool_calls[i] for i in sorted(tool_calls)]
        if not message["content"]:
            message["content"] = None
    return {
        "id": response_id or f"chatcmpl-{os.urandom(8).hex()}",
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason or ("tool_calls" if tool_calls else "stop"),
        }],
        "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


# ---------------------------------------------------------------------------
# 签到响应分类
# ---------------------------------------------------------------------------

def utc8_date_string(now_ms: Optional[float] = None) -> str:
    """UTC+8（北京时间）的 YYYY-MM-DD 日期串。"""
    import datetime as _dt
    tz = _dt.timezone(_dt.timedelta(hours=8))
    moment = _dt.datetime.fromtimestamp((now_ms if now_ms is not None else time.time() * 1000) / 1000, tz=tz)
    return moment.strftime("%Y-%m-%d")


def classify_checkin_response(status: int, body_text: str) -> Dict[str, Any]:
    """
    判定签到结果：already-claimed / no-campaign / claimed / error。
    判定口径与 dsh-workbuddy-connect/src/checkin.ts 一致。
    """
    try:
        data = json.loads(body_text) if body_text else {}
    except (ValueError, TypeError):
        data = None
    code = data.get("code") if isinstance(data, dict) else None
    msg = ""
    if isinstance(data, dict):
        msg = data.get("msg") if isinstance(data.get("msg"), str) else (
            data.get("message") if isinstance(data.get("message"), str) else ""
        )
    if code == 10001 or "今天已签到" in msg or "已签到" in msg or "already" in msg.lower():
        return {"status": "already-claimed", "message": msg or "Already checked in today", "amount": None}
    inner = data.get("data") if isinstance(data, dict) else None
    if (isinstance(inner, dict) and inner.get("active") is False) or \
            "活动未开启" in msg or "已过期" in msg or "not active" in msg.lower():
        return {"status": "no-campaign", "message": msg or "Check-in campaign not active", "amount": None}
    if 200 <= status < 300 and (code in (0, 200, None)):
        amount = None
        for source in ((inner if isinstance(inner, dict) else {}), (data if isinstance(data, dict) else {})):
            for key in ("credit", "amount", "points"):
                value = source.get(key) if isinstance(source, dict) else None
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    amount = float(value)
                    break
            if amount is not None:
                break
        return {"status": "claimed", "message": msg or "Check-in successful", "amount": amount}
    return {
        "status": "error",
        "message": msg or f"HTTP {status}: {body_text[:100]}",
        "amount": None,
    }
