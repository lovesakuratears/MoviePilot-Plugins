"""
免费车道线协议要素（移植自 dsh-our-free-model 的 src/upstream.js，MIT）。

会话 ID 铸造、网关指纹头、免密工具闸门（read/shell 逐字定义）、
模型端点路由。纯函数/纯数据，无宿主依赖，可脱离 MoviePilot 单测。

上游免密车道事实（源仓库 2026-10-17 实测口径）：
- 聊天端点 `https://opencode.ai/inference/v1/chat/completions`（`/zen/v1` 已废弃）；
- 鉴权 `Authorization: Bearer public`（公共池，无个人密钥）；
- v2 指纹：UA `opencode/latest/2.0.26/cli`，须同时携带
  `x-opencode-session` / `x-opencode-session-id` / `x-session-affinity` /
  `x-session-id`，不得携带 v1 的 `x-opencode-request`；
- 会话 ID 必须是降序时间编码（`~(ts_ms << 12 | counter)`，counter 1–63），
  升序或 sha256 摘要一律 403 FreeTierError；
- 带 tools 的请求必须逐字声明 `read` / `shell` 两个工具定义，且
  **绝不下发** `tool_choice: "none"`（见即 403）。
"""

import hashlib
import re
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 模型 ID 与端点路由
# ---------------------------------------------------------------------------

#: 走 OpenAI Responses 端点的模型（其余按 chat/completions 处理）。
RESPONSES_MODELS = {"muse-spark-1.2-contributor-free", "muse-spark-1.3-contributor-free"}

#: 走 Anthropic Messages 端点的模型。
MESSAGES_MODELS = {"union-alpha"}

#: 会话 ID 整体形状：`ses_` + 12 hex + 14 base62。
SESSION_RE = re.compile(r"^ses_[0-9a-f]{12}[0-9A-Za-z]{14}$")

#: 降序时间编码约束：低 12 位落在 `0xfc0–0xfff`（前 9 位任意 hex、第 10 位 c–f）。
SESSION_DESCENDING_RE = re.compile(r"^[0-9a-f]{9}f[c-f][0-9a-f]$")

_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

#: 网关指纹 User-Agent。v2 整串比对，不得加前后缀。
CLIENT_UA = "opencode/latest/2.0.26/cli"

MAX_SESSION_LENGTH = 256
MAX_TOOL_NAME_LEN = 128


def base_model_id(model: Any) -> str:
    """去掉尾部 `(level)` 思考强度后缀，得到基础模型 ID。"""
    return re.sub(r"\([^()]+\)\s*$", "", str(model or "")).strip()


def is_muse_spark(model_id: str) -> bool:
    """是否 muse-spark 系列（走 Responses 端点）。"""
    clean = base_model_id(model_id)
    base = clean.split("/")[-1] if "/" in clean else clean
    return re.match(r"^muse[-_]?spark(?:$|[-_:.\s])", base, re.IGNORECASE) is not None


def is_responses_model(model_id: str) -> bool:
    """该模型是否走 `/inference/v1/responses`。"""
    return base_model_id(model_id) in RESPONSES_MODELS or is_muse_spark(model_id)


def is_messages_model(model_id: str) -> bool:
    """该模型是否走 Anthropic 形态的 `/inference/v1/messages`。"""
    return base_model_id(model_id) in MESSAGES_MODELS


def endpoint_for(model_id: str) -> str:
    """免密车道上该模型的上游路径。"""
    if is_responses_model(model_id):
        return "/inference/v1/responses"
    if is_messages_model(model_id):
        return "/inference/v1/messages"
    return "/inference/v1/chat/completions"


def wire_for(model_id: str) -> str:
    """线协议形态：`chat` / `responses` / `messages`。"""
    path = endpoint_for(model_id)
    if path.endswith("/responses"):
        return "responses"
    if path.endswith("/messages"):
        return "messages"
    return "chat"


# ---------------------------------------------------------------------------
# 会话 ID 铸造
# ---------------------------------------------------------------------------


def _base62_fixed(data: bytes, width: int) -> str:
    """把字节串渲染为定长 base62（大端）。"""
    number = 0
    for byte in data:
        number = (number << 8) | byte
    out = [""] * width
    for index in range(width - 1, -1, -1):
        out[index] = _BASE62[number % 62]
        number //= 62
    return "".join(out)


def _base62_from(data: bytes) -> str:
    return "".join(_BASE62[byte % 62] for byte in data)


class _SessionMint:
    """毫秒内单调计数的会话 ID 铸造器（进程内共享）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_stamp = 0
        self._seq = 0

    def mint(self, timestamp: Optional[int] = None) -> str:
        ts = int(timestamp if timestamp is not None else time.time() * 1000)
        with self._lock:
            if ts != self._last_stamp:
                self._last_stamp = ts
                self._seq = 0
            self._seq += 1
            seq = self._seq
        value = ~(ts * 0x1000 + seq) & 0xFFFFFFFFFFFF
        hex_part = f"{value:012x}"
        return f"ses_{hex_part}{_base62_from(secrets.token_bytes(14))}"


_mint = _SessionMint()


def mint_session_id(timestamp: Optional[int] = None) -> str:
    """铸造网关形态的降序时间编码会话 ID。"""
    return _mint.mint(timestamp)


def canonicalize_session(signal: str) -> str:
    """
    把任意信号确定性地重编码为门禁接受的降序布局。

    摘要与参考网关一致（`ses\\0<signal>` 的 sha256），同一会话信号恒映射到
    同一上游会话；counter 取 1，低 12 位落在 `0xffe`。
    """
    digest = hashlib.sha256(b"ses\0" + str(signal or "global").encode("utf-8")).digest()
    current = ((digest[0] << 28 | digest[1] << 20 | digest[2] << 12 | digest[3] << 4 | digest[4] >> 4) << 12) | 1
    inverted = (~current) & 0xFFFFFFFFFFFF
    time_hex = f"{inverted:012x}"
    return f"ses_{time_hex}{_base62_fixed(digest[6:16], 14)}"


def is_canonical_session(session_id: Any) -> bool:
    """该 ID 是否原样可过降序编码门禁。"""
    if not isinstance(session_id, str):
        return False
    trimmed = session_id.strip()
    return bool(SESSION_RE.match(trimmed)) and bool(SESSION_DESCENDING_RE.match(trimmed[4:16]))


class SessionStore:
    """
    下游会话信号 → 稳定上游会话 ID 的映射。

    免密额度按会话记账：每请求新铸 ID 会被 429 拒绝，因此一个对话固定一个
    上游会话；ID 形状不合规时确定性重编码，保证同一对话始终同一会话。
    """

    def __init__(self, persist=None) -> None:
        """
        :param persist: 可选 callable(dict) 持久化；load 由调用方预填。
        """
        self._map: Dict[str, str] = {}
        self._persist = persist

    def load(self, mapping: Optional[Dict[str, str]]) -> None:
        """从持久化存储恢复映射（只收形状合规的 ID）。"""
        for seed, sid in (mapping or {}).items():
            if isinstance(sid, str) and SESSION_RE.match(sid.strip()):
                self._map[str(seed)] = sid.strip()

    def snapshot(self) -> Dict[str, str]:
        """当前映射（供持久化）。"""
        return dict(self._map)

    def session_for(self, signal: Any) -> str:
        """取（或铸出）该会话信号对应的稳定上游会话 ID。"""
        seed = str(signal or "").strip() or "global"
        remembered = self._map.get(seed)
        if remembered is not None and is_canonical_session(remembered):
            return remembered
        minted = canonicalize_session(seed)
        self._map[seed] = minted
        if self._persist is not None:
            try:
                self._persist(self.snapshot())
            except Exception:  # noqa: BLE001 - 持久化失败不影响会话可用
                pass
        return minted


# ---------------------------------------------------------------------------
# 网关指纹头
# ---------------------------------------------------------------------------


def gateway_headers(session: str, stream: bool = True) -> Dict[str, str]:
    """
    免密车道 v2 指纹头。

    ⚠️ `x-opencode-request` 是 v1 专用头，v2 收到即 403，绝不携带。
    """
    return {
        "content-type": "application/json",
        "authorization": "Bearer public",
        "user-agent": CLIENT_UA,
        "x-opencode-client": "cli",
        "x-opencode-session": session,
        "x-opencode-session-id": session,
        "x-session-affinity": session,
        "x-session-id": session,
        "x-opencode-project": "global",
        "accept": "text/event-stream" if stream else "*/*",
    }


# ---------------------------------------------------------------------------
# 免密工具闸门（read / shell 逐字定义，改写即 403）
# ---------------------------------------------------------------------------

FINGERPRINT_TOOLS = ["read", "shell"]

#: ⚠️ 逐字取自 OpenCode v2.0.26 CLI。上游比对 description 与 parameters，
#: 改写措辞/精简 schema/改名都会 403 FreeTierError。不要"美化"这些字符串。
FINGERPRINT_TOOL_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "read": {
        "description": (
            "Read the contents of a file or directory. Supports text files, images, and PDFs. "
            "Images and PDFs are presented directly to the model. Each text line is prefixed by "
            "its 1-based line number as <line>: <content>. The prefix is for reference and is not "
            "part of the file content. Directory entries are returned one per line. Use offset and "
            "limit to read large files or directories in sections. Prefer one larger read over many "
            "small slices, and use grep to find specific content in large files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory to read"},
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "The line or directory entry to start reading from (1-based)",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "The maximum number of lines or directory entries to read "
                        "(defaults to and capped at 2000)"
                    ),
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    "shell": {
        "description": (
            "Execute a shell command and return its output. Commands run on Linux using bash. "
            "Quote file paths containing spaces or special characters. Prefer dedicated tools over "
            "shell commands when possible. When output is large, the full result is saved to a file "
            "and a truncated preview is returned. Rely on automatic truncation unless filtering the "
            "output is more useful. Commands accept an optional timeout, background commands have no "
            "timeout by default. Background commands return immediately, and you will be notified "
            "when they complete."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command string to execute"},
                "workdir": {
                    "type": "string",
                    "description": (
                        "Working directory to execute the command in. Defaults to the current "
                        "working directory. When possible, avoid changing directories in the command "
                        "and set the working directory here instead."
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "Timeout in milliseconds. Set to 0 to disable the timeout. Defaults to "
                        "120000 for foreground commands. Background commands have no timeout by default."
                    ),
                },
                "background": {
                    "type": "boolean",
                    "description": (
                        "Run the command in the background and return immediately (useful for dev "
                        "servers and long-running builds). You do not need to use '&' at the end of "
                        "the command when using this parameter. You will be notified when it "
                        "completes. DO NOT poll for completion."
                    ),
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}

_PLACEHOLDER_NOTE = (
    "Do not call the {list} tools; they are placeholders that do nothing. "
    "Use the other tools you have been given instead."
)
_PLACEHOLDER_NOTE_ONE = (
    "Do not call the {list} tool; it is a placeholder that does nothing. "
    "Use the other tools you have been given instead."
)


def _placeholder_note(names: List[str]) -> str:
    listed = " or ".join(f"`{name}`" for name in names)
    if len(names) > 1:
        return _PLACEHOLDER_NOTE.format(list=listed)
    return _PLACEHOLDER_NOTE_ONE.format(list=listed)


def _tool_name_of(tool: Any) -> str:
    if not isinstance(tool, dict):
        return ""
    name = tool.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    fn = tool.get("function")
    if isinstance(fn, dict):
        name = fn.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return ""


def _function_of(tool: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fn = tool.get("function")
    return fn if isinstance(fn, dict) else None


def _definition_of(tool: Dict[str, Any], claude: bool, flat: bool):
    wrapper = tool if (claude or flat) else _function_of(tool)
    if wrapper is None:
        return None
    schema = wrapper.get("input_schema") if claude else wrapper.get("parameters")
    return wrapper.get("description"), schema


def _carries_fingerprint_definition(tool: Dict[str, Any], name: str, claude: bool, flat: bool) -> bool:
    own = _definition_of(tool, claude, flat)
    if own is None:
        return False
    want = FINGERPRINT_TOOL_DEFINITIONS[name]
    return own[0] == want["description"] and own[1] == want["parameters"]


def _with_tool_name(tool: Dict[str, Any], name: str) -> Dict[str, Any]:
    fn = _function_of(tool)
    if fn is not None:
        merged = dict(tool)
        merged["function"] = {**fn, "name": name}
        return merged
    return {**tool, "name": name}


def _fingerprint_tool(name: str, claude: bool, flat: bool) -> Dict[str, Any]:
    spec = FINGERPRINT_TOOL_DEFINITIONS[name]
    if claude:
        return {"name": name, "description": spec["description"], "input_schema": spec["parameters"]}
    if flat:
        return {"type": "function", "name": name, "description": spec["description"], "parameters": spec["parameters"]}
    return {
        "type": "function",
        "function": {"name": name, "description": spec["description"], "parameters": spec["parameters"]},
    }


def _retarget_tool_choice(body: Dict[str, Any], rename_map: Dict[str, str]) -> None:
    if not rename_map:
        return
    choice = body.get("tool_choice")
    if not isinstance(choice, dict):
        return
    reverse = {original: alias for alias, original in rename_map.items()}
    name = choice.get("name")
    if isinstance(name, str) and name.strip() in reverse:
        body["tool_choice"] = {**choice, "name": reverse[name.strip()]}
        return
    fn = choice.get("function")
    if isinstance(fn, dict):
        name = fn.get("name")
        if isinstance(name, str) and name.strip() in reverse:
            body["tool_choice"] = {**choice, "function": {**fn, "name": reverse[name.strip()]}}


def _alias_history_tool_calls(body: Dict[str, Any], rename_map: Dict[str, str]) -> None:
    if not rename_map:
        return
    reverse = {original: alias for alias, original in rename_map.items()}

    def rename(name: Any) -> Any:
        return reverse.get(name, name) if isinstance(name, str) else name

    items = body.get("input")
    if isinstance(items, list):
        body["input"] = [
            {**item, "name": rename(item.get("name"))}
            if isinstance(item, dict) and item.get("type") == "function_call" and item.get("name") in reverse
            else item
            for item in items
        ]
    messages = body.get("messages")
    if not isinstance(messages, list):
        return
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, list):
            blocks = [
                {**block, "name": rename(block.get("name"))}
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") in reverse
                else block
                for block in content
            ]
            messages[index] = {**message, "content": blocks}
        calls = message.get("tool_calls")
        if isinstance(calls, list):
            new_calls = []
            for call in calls:
                if isinstance(call, dict) and isinstance(call.get("function"), dict) \
                        and call["function"].get("name") in reverse:
                    new_calls.append({**call, "function": {**call["function"], "name": rename(call["function"].get("name"))}})
                else:
                    new_calls.append(call)
            messages[index] = {**message, "tool_calls": new_calls}


def _note_injected_tools(body: Dict[str, Any], claude: bool, flat: bool, names: List[str]) -> None:
    note = _placeholder_note(names)
    if flat:
        instructions = body.get("instructions")
        body["instructions"] = f"{instructions}\n\n{note}" if isinstance(instructions, str) and instructions.strip() else note
        return
    if claude:
        system = body.get("system")
        body["system"] = f"{system}\n\n{note}" if isinstance(system, str) and system else note
        return
    messages = body.get("messages") if isinstance(body.get("messages"), list) else []
    first = messages[0] if messages else None
    if isinstance(first, dict) and first.get("role") == "system" and isinstance(first.get("content"), str):
        body["messages"] = [{**first, "content": f"{first['content']}\n\n{note}"}, *messages[1:]]
        return
    body["messages"] = [{"role": "system", "content": note}, *messages]


def apply_fingerprint(body: Dict[str, Any], style: str) -> Dict[str, str]:
    """
    满足 v2 免密工具闸门（原地改写 body）。

    规则（每条对应一次实测 403）：
    1. `read` 与 `shell` 必须声明，定义逐字一致；
    2. 调用方工具原样保留（含大小写变体）；
    3. 同名但定义不同的调用方工具改名为 ``<name>_client[N]``，并同步历史与
       ``tool_choice``；响应侧用返回的映射还原；
    4. 同名重复声明只留第一个；
    5. **绝不下发** ``tool_choice: "none"``（见即 403）。

    :param style: ``chat`` / ``responses``（flat）/ ``messages``（claude）
    :returns: 上游名 → 调用方名 的重命名映射
    """
    flat = style == "responses"
    claude = style == "messages"
    rename_map: Dict[str, str] = {}
    tools = body.get("tools") if isinstance(body.get("tools"), list) else []
    taken = {_tool_name_of(tool) for tool in tools} - {""}
    seen: set = set()
    present: set = set()
    out: List[Dict[str, Any]] = []

    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = _tool_name_of(tool)
        key = name if name in FINGERPRINT_TOOLS else ""
        if key == "":
            out.append(tool)
            continue
        # 同名重复声明：上游拒收，留第一个。
        if key in seen:
            continue
        seen.add(key)
        if _carries_fingerprint_definition(tool, key, claude, flat):
            out.append(tool)
            present.add(key)
            continue
        alias = f"{key}_client"
        counter = 2
        while alias in taken:
            alias = f"{key}_client{counter}"
            counter += 1
        taken.add(alias)
        rename_map[alias] = name
        out.append(_with_tool_name(tool, alias))

    injected: List[str] = []
    for name in FINGERPRINT_TOOLS:
        if name in present:
            continue
        out.append(_fingerprint_tool(name, claude, flat))
        injected.append(name)

    body["tools"] = out
    _retarget_tool_choice(body, rename_map)
    _alias_history_tool_calls(body, rename_map)
    if injected:
        _note_injected_tools(body, claude, flat, injected)
    # ⚠️ v2 见到 `tool_choice: "none"` 即 403；兜底清除。
    choice = body.get("tool_choice")
    if choice == "none" or (isinstance(choice, dict) and choice.get("type") == "none"):
        body.pop("tool_choice", None)
    if flat and not body.get("tool_choice"):
        body["tool_choice"] = "auto"
    return rename_map


def restore_tool_name(name: Any, rename_map: Optional[Dict[str, str]]) -> Any:
    """把上游工具名还原为调用方拼写。"""
    if not rename_map or not isinstance(name, str):
        return name
    return rename_map.get(name, name)


def injected_placeholder_names(rename_map: Optional[Dict[str, str]], caller_tools: List[str]) -> List[str]:
    """
    响应侧应丢弃的占位工具调用名。

    闸门注入的 `read`/`shell` 是占位（提示词已压制），模型偶发仍会调用；
    只有**确实由本插件注入**且并非调用方自己同名工具的名字才丢弃。
    """
    caller_set = set(caller_tools)
    out = []
    for name in FINGERPRINT_TOOLS:
        # 调用方声明过同名工具（无论是否被改名）时，这个名字属于调用方。
        restored = rename_map or {}
        if name in restored.values():
            continue
        if name in caller_set:
            continue
        out.append(name)
    return out
