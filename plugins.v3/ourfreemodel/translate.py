"""
请求翻译与流归一：OpenAI Chat ↔ 三种线协议（chat / responses / messages）。

移植自 dsh-our-free-model 的 src/messages.js 与 src/stream.js（MIT），
输入端改为 MoviePilot 智能助手（OpenAI SDK）发出的 Chat Completions 形态：

- 请求侧：OpenAI Chat 消息 → 各线协议请求体（推理内容不重放、工具配对修复、
  图片块转换）；
- 响应侧：三种线协议的 SSE 载荷 → OpenAI Chat chunk 字典流（可聚合成
  chat.completion）。纯逻辑、无宿主依赖，可单测。
"""

import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .wire import restore_tool_name

# ---------------------------------------------------------------------------
# 请求侧：消息规整
# ---------------------------------------------------------------------------

#: 助手历史里的推理字段名（一律不重放上游）。
_REASONING_FIELDS = ("reasoning", "reasoning_content", "reasoning_text", "thinking")

_IMAGE_MEDIA = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}


def strip_reasoning(message: Dict[str, Any]) -> Dict[str, Any]:
    """去掉助手消息里的推理字段（推理内容不重放上游）。"""
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return message
    cleaned = {key: value for key, value in message.items() if key not in _REASONING_FIELDS}
    return cleaned


def normalize_chat_messages(messages: Any) -> List[Dict[str, Any]]:
    """
    OpenAI Chat 消息规整（chat 线直发前的清理）。

    - 去掉 assistant 历史的推理字段；
    - 连续同角色消息不合并（上游接受），但空内容消息剔除。
    """
    out: List[Dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        cleaned = strip_reasoning(message)
        content = cleaned.get("content")
        calls = cleaned.get("tool_calls")
        if content in (None, "", []) and not calls and cleaned.get("role") != "tool":
            continue
        out.append(cleaned)
    return out


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") in (None, "text") and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return ""


def _image_parts_of(content: Any) -> List[Tuple[str, str]]:
    """返回 (media_type, base64) 列表（OpenAI image_url → data URL 解析）。"""
    out: List[Tuple[str, str]] = []
    if not isinstance(content, list):
        return out
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "image_url":
            continue
        url = (block.get("image_url") or {}).get("url") if isinstance(block.get("image_url"), dict) else None
        if not isinstance(url, str) or not url.startswith("data:"):
            continue
        head, _, data = url.partition(",")
        media = head[5:].split(";")[0].strip().lower()
        if media in _IMAGE_MEDIA and data:
            out.append((media, data))
    return out


def to_claude_messages(messages: Any) -> Dict[str, Any]:
    """
    OpenAI Chat 消息 → Anthropic Messages 形态。

    连续同角色回合合并；`role: tool` 变成携带 tool_result 的 user 回合。
    """
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []

    def push(role: str, blocks: List[Dict[str, Any]]) -> None:
        if not blocks:
            return
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": list(blocks)})

    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role in ("system", "developer"):
            text = _text_of(message.get("content"))
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            inner: List[Dict[str, Any]] = []
            text = _text_of(message.get("content"))
            if text:
                inner.append({"type": "text", "text": text})
            for media, data in _image_parts_of(message.get("content")):
                inner.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
            if not inner:
                inner = [{"type": "text", "text": "(no output)"}]
            push("user", [{"type": "tool_result", "tool_use_id": call_id, "content": inner, "is_error": False}])
            continue
        blocks: List[Dict[str, Any]] = []
        text = _text_of(message.get("content"))
        if text:
            blocks.append({"type": "text", "text": text})
        for media, data in _image_parts_of(message.get("content")):
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            arguments: Dict[str, Any] = {}
            raw = fn.get("arguments")
            if isinstance(raw, str) and raw.strip():
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        arguments = parsed
                except ValueError:
                    arguments = {}
            blocks.append({
                "type": "tool_use",
                "id": str(call.get("id") or f"call_{uuid.uuid4().hex[:24]}"),
                "name": str(fn.get("name") or ""),
                "input": arguments,
            })
        if not blocks:
            continue
        push("assistant" if role == "assistant" else "user", blocks)

    shaped: Dict[str, Any] = {"messages": out}
    if system_parts:
        shaped["system"] = "\n\n".join(system_parts)
    return shaped


def to_response_input(messages: Any) -> List[Dict[str, Any]]:
    """OpenAI Chat 消息 → OpenAI Responses input 条目列表。"""
    out: List[Dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "tool":
            text = _text_of(message.get("content")) or "(no output)"
            out.append({
                "type": "function_call_output",
                "call_id": str(message.get("tool_call_id") or ""),
                "output": text,
            })
            continue
        if role in ("system", "developer"):
            text = _text_of(message.get("content"))
            if text:
                out.append({"type": "message", "role": "system", "content": [{"type": "input_text", "text": text}]})
            continue
        if role == "assistant":
            text = _text_of(message.get("content"))
            if text:
                out.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]})
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                out.append({
                    "type": "function_call",
                    "call_id": str(call.get("id") or f"call_{uuid.uuid4().hex[:24]}"),
                    "name": str(fn.get("name") or ""),
                    "arguments": fn.get("arguments") if isinstance(fn.get("arguments"), str) else "{}",
                })
            continue
        parts: List[Dict[str, Any]] = []
        text = _text_of(message.get("content"))
        if text:
            parts.append({"type": "input_text", "text": text})
        for _media, _data in _image_parts_of(message.get("content")):
            # Responses 线接受 data URL 的 input_image。
            parts.append({"type": "input_image", "image_url": f"data:{_media};base64,{_data}"})
        if parts:
            out.append({"type": "message", "role": "user", "content": parts})
    return out


def to_tool_defs(tools: Any, style: str) -> List[Dict[str, Any]]:
    """
    工具 schema → 目标线协议形态。

    :param style: ``chat``（function 包裹）/ ``responses``（flat）/ ``messages``（claude）
    """
    out: List[Dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        source = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = str(source.get("name") or "").strip()
        if not name:
            continue
        parameters = source.get("parameters") if isinstance(source.get("parameters"), dict) else {"type": "object", "properties": {}}
        description = source.get("description") if isinstance(source.get("description"), str) else ""
        name = name[:128]
        if style == "messages":
            out.append({"name": name, "description": description, "input_schema": parameters})
        elif style == "responses":
            out.append({"type": "function", "name": name, "description": description, "parameters": parameters})
        else:
            out.append({"type": "function", "function": {"name": name, "description": description, "parameters": parameters}})
    return out


def build_payload(
    wire: str,
    model_id: str,
    messages: Any,
    budget: int,
    tools: Any = None,
    effort_patch: Optional[Dict[str, Any]] = None,
    temperature: Any = None,
    stop: Any = None,
) -> Dict[str, Any]:
    """
    构造目标线协议的请求体（stream 恒为 True，由本插件决定输出形态）。
    """
    if wire == "responses":
        input_items = to_response_input(messages)
        payload: Dict[str, Any] = {
            "model": model_id,
            "input": input_items or [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "..."}]}],
            "stream": True,
            "store": False,
            "max_output_tokens": budget,
        }
    elif wire == "messages":
        shaped = to_claude_messages(messages)
        payload = {
            "model": model_id,
            "messages": shaped["messages"],
            "stream": True,
            "max_tokens": budget,
        }
        if shaped.get("system") is not None:
            payload["system"] = shaped["system"]
    else:
        chat = normalize_chat_messages(messages)
        payload = {
            "model": model_id,
            "messages": chat or [{"role": "user", "content": "..."}],
            "stream": True,
            "max_tokens": budget,
        }
    if tools:
        payload["tools"] = to_tool_defs(tools, wire)
    if isinstance(temperature, (int, float)) and temperature == temperature:
        payload["temperature"] = temperature
    if wire != "responses" and isinstance(stop, list) and stop:
        payload["stop"] = stop
    if effort_patch:
        payload.update(effort_patch)
    return payload


# ---------------------------------------------------------------------------
# 响应侧：SSE 载荷归一为 OpenAI Chat chunk
# ---------------------------------------------------------------------------


def map_usage(usage: Any) -> Dict[str, int]:
    """上游 usage → OpenAI usage 计数（只保留可信整数）。"""
    if not isinstance(usage, dict):
        return {}
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = usage.get("completion_tokens", usage.get("output_tokens"))
    out: Dict[str, int] = {}
    if isinstance(prompt, (int, float)) and prompt == prompt:
        out["prompt_tokens"] = int(prompt)
    if isinstance(completion, (int, float)) and completion == completion:
        out["completion_tokens"] = int(completion)
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict) and isinstance(details.get("cached_tokens"), (int, float)):
        out["prompt_tokens_details"] = {"cached_tokens": int(details["cached_tokens"])}
    out["total_tokens"] = out.get("prompt_tokens", 0) + out.get("completion_tokens", 0)
    return out


def _reasoning_of(delta: Dict[str, Any]) -> Optional[str]:
    for field in _REASONING_FIELDS:
        value = delta.get(field)
        if isinstance(value, str) and value:
            return value
    details = delta.get("reasoning_details")
    if isinstance(details, list):
        text = "".join(part.get("text") for part in details if isinstance(part, dict) and isinstance(part.get("text"), str))
        return text or None
    return None


def finish_reason_of(token: Any, saw_tool_call: bool = False) -> str:
    """
    上游收尾标记 → OpenAI finish_reason。

    本轮存在工具调用且上游正常收尾（stop/completed）时按 OpenAI 语义报
    ``tool_calls``；截断（length）优先于工具调用。
    """
    if token in ("tool_calls", "tool_use", "function_call"):
        return "tool_calls"
    if token in ("length", "max_tokens", "max_output_tokens", "incomplete"):
        return "length"
    if token in ("content_filter",):
        return "content_filter"
    if saw_tool_call:
        return "tool_calls"
    return "stop"


class StreamAssembler:
    """
    三种线协议的 SSE 载荷 → OpenAI Chat chunk 字典流（可聚合）。

    用法::

        assembler = StreamAssembler("deepseek-v4.1-flash-free", "chat")
        for data in sse_data_lines:
            for chunk in assembler.feed(data):
                yield chunk
        for chunk in assembler.finish():
            yield chunk
        completion = assembler.to_completion()   # 非流式聚合
    """

    def __init__(
        self,
        model: str,
        wire: str = "chat",
        rename_map: Optional[Dict[str, str]] = None,
        drop_tool_names: Optional[List[str]] = None,
    ) -> None:
        self.model = model
        self.wire = wire
        self.rename_map = rename_map or {}
        self.drop_tool_names = set(drop_tool_names or [])
        self._id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        self._created = int(time.time())
        self._text: List[str] = []
        self._reasoning: List[str] = []
        self._tool_order: List[str] = []
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._tool_index: Dict[str, int] = {}
        self._usage: Dict[str, int] = {}
        self._finish_reason: Optional[str] = None
        self._dropped_placeholders: List[str] = []
        self._saw_done = False

    # -- 通用出入 ---------------------------------------------------------

    def _chunk(self, delta: Dict[str, Any], finish: Optional[str] = None) -> Dict[str, Any]:
        return {
            "id": self._id,
            "object": "chat.completion.chunk",
            "created": self._created,
            "model": self.model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }

    def _tool_slot(self, key: str, call_id: str, name: str) -> Optional[int]:
        """登记工具调用槽位；被丢弃的占位调用返回 None。"""
        if name in self.drop_tool_names:
            self._dropped_placeholders.append(name)
            return None
        if key not in self._tools:
            if not name and call_id:
                # 先见 id 后见名字的帧：先占位。
                pass
            index = len(self._tool_order)
            self._tool_order.append(key)
            self._tool_index[key] = index
            self._tools[key] = {
                "id": call_id or f"call_{uuid.uuid4().hex[:24]}",
                "name": restore_tool_name(name, self.rename_map),
                "arguments": [],
                "dropped": False,
            }
        slot = self._tools[key]
        if name:
            restored = restore_tool_name(name, self.rename_map)
            if restored in self.drop_tool_names or name in self.drop_tool_names:
                slot["dropped"] = True
                self._dropped_placeholders.append(restored)
                return None
            slot["name"] = restored
        if call_id:
            slot["id"] = call_id
        if slot.get("dropped"):
            return None
        return self._tool_index[key]

    def _emit_tool_start(self, key: str, call_id: str, name: str) -> List[Dict[str, Any]]:
        index = self._tool_slot(key, call_id, name)
        if index is None:
            return []
        slot = self._tools[key]
        return [self._chunk({"tool_calls": [{
            "index": index,
            "id": slot["id"],
            "type": "function",
            "function": {"name": slot["name"], "arguments": ""},
        }]})]

    def _emit_tool_args(self, key: str, arguments: str) -> List[Dict[str, Any]]:
        slot = self._tools.get(key)
        if slot is None or slot.get("dropped") or not arguments:
            return []
        slot["arguments"].append(arguments)
        return [self._chunk({"tool_calls": [{
            "index": self._tool_index[key],
            "function": {"arguments": arguments},
        }]})]

    def _emit_text(self, text: str) -> List[Dict[str, Any]]:
        if not text:
            return []
        self._text.append(text)
        return [self._chunk({"content": text})]

    def _emit_reasoning(self, text: str) -> List[Dict[str, Any]]:
        if not text:
            return []
        self._reasoning.append(text)
        return [self._chunk({"reasoning_content": text})]

    # -- 各线协议喂入 -----------------------------------------------------

    def feed(self, data: str) -> List[Dict[str, Any]]:
        """
        喂入一条 SSE ``data:`` 载荷（已去前缀）。

        ``[DONE]`` 或无法解析的载荷返回空列表；事件型线协议按事件分发。
        """
        text = (data or "").strip()
        if not text or text == "[DONE]":
            self._saw_done = self._saw_done or text == "[DONE]"
            return []
        try:
            payload = json.loads(text)
        except ValueError:
            return []
        if not isinstance(payload, dict):
            return []
        if payload.get("error"):
            message = payload.get("error")
            message = message.get("message") if isinstance(message, dict) else message
            raise UpstreamStreamError(str(message)[:400])
        if self.wire == "messages":
            return self._feed_claude(payload)
        if self.wire == "responses":
            return self._feed_responses(payload)
        return self._feed_chat(payload)

    def _feed_chat(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if payload.get("usage"):
            mapped = map_usage(payload["usage"])
            if mapped:
                self._usage.update(mapped)
        for choice in payload.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            reasoning = _reasoning_of(delta)
            if reasoning:
                out.extend(self._emit_reasoning(reasoning))
            content = delta.get("content")
            if isinstance(content, str) and content:
                out.extend(self._emit_text(content))
            for call in delta.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                key = f"c{call.get('index') if isinstance(call.get('index'), int) else len(self._tools)}"
                name = fn.get("name") if isinstance(fn.get("name"), str) else ""
                call_id = call.get("id") if isinstance(call.get("id"), str) else ""
                if name or call_id:
                    out.extend(self._emit_tool_start(key, call_id, name))
                arguments = fn.get("arguments")
                if isinstance(arguments, str) and arguments:
                    out.extend(self._emit_tool_args(key, arguments))
            finish = choice.get("finish_reason")
            if finish:
                self._finish_reason = finish_reason_of(finish, bool(self._tool_order))
                out.append(self._chunk({}, self._finish_reason))
        return out

    def _feed_claude(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        etype = event.get("type")
        if etype == "content_block_start":
            block = event.get("content_block") if isinstance(event.get("content_block"), dict) else {}
            if block.get("type") == "tool_use":
                key = f"b{event.get('index', 0)}"
                out.extend(self._emit_tool_start(key, str(block.get("id") or ""), str(block.get("name") or "")))
            return out
        if etype == "content_block_delta":
            part = event.get("delta") if isinstance(event.get("delta"), dict) else {}
            key = f"b{event.get('index', 0)}"
            if part.get("type") == "text_delta":
                out.extend(self._emit_text(str(part.get("text") or "")))
            elif part.get("type") == "thinking_delta":
                out.extend(self._emit_reasoning(str(part.get("thinking") or "")))
            elif part.get("type") == "input_json_delta":
                out.extend(self._emit_tool_args(key, str(part.get("partial_json") or "")))
            return out
        if etype == "message_start":
            usage = (event.get("message") or {}).get("usage") if isinstance(event.get("message"), dict) else None
            if isinstance(usage, dict):
                mapped = map_usage({
                    "prompt_tokens": usage.get("input_tokens"),
                    "completion_tokens": usage.get("output_tokens"),
                })
                if mapped:
                    self._usage.update(mapped)
            return out
        if etype == "message_delta":
            usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
            if isinstance(usage.get("output_tokens"), (int, float)):
                self._usage["completion_tokens"] = int(usage["output_tokens"])
                self._usage["total_tokens"] = self._usage.get("prompt_tokens", 0) + int(usage["output_tokens"])
            stop = (event.get("delta") or {}).get("stop_reason") if isinstance(event.get("delta"), dict) else None
            if stop:
                self._finish_reason = finish_reason_of(stop, bool(self._tool_order))
                out.append(self._chunk({}, self._finish_reason))
            return out
        if etype == "message_stop":
            if self._finish_reason is None:
                self._finish_reason = finish_reason_of("message_stop", bool(self._tool_order))
                out.append(self._chunk({}, self._finish_reason))
            return out
        return out

    def _feed_responses(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        etype = event.get("type")
        if etype == "response.output_item.added":
            item = event.get("item") if isinstance(event.get("item"), dict) else {}
            if item.get("type") == "function_call":
                key = f"i{event.get('output_index', 0)}"
                out.extend(self._emit_tool_start(
                    key,
                    str(item.get("call_id") or item.get("id") or ""),
                    str(item.get("name") or ""),
                ))
            return out
        if etype == "response.output_text.delta":
            out.extend(self._emit_text(str(event.get("delta") or "")))
            return out
        if etype in ("response.reasoning_summary_text.delta", "response.output_reasoning.text.delta"):
            out.extend(self._emit_reasoning(str(event.get("delta") or "")))
            return out
        if etype == "response.function_call_arguments.delta":
            key = f"i{event.get('output_index', 0)}"
            out.extend(self._emit_tool_args(key, str(event.get("delta") or "")))
            return out
        if etype in ("response.completed", "response.incomplete", "response.failed", "response.done"):
            response = event.get("response") if isinstance(event.get("response"), dict) else {}
            usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
            if usage:
                mapped = map_usage({
                    "prompt_tokens": usage.get("input_tokens"),
                    "completion_tokens": usage.get("output_tokens"),
                })
                if mapped:
                    self._usage.update(mapped)
                details = usage.get("output_tokens_details")
                if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), (int, float)):
                    self._usage["completion_tokens_details"] = {"reasoning_tokens": int(details["reasoning_tokens"])}
            status = response.get("status")
            incomplete = (response.get("incomplete_details") or {}).get("reason") \
                if isinstance(response.get("incomplete_details"), dict) else None
            if incomplete == "max_output_tokens":
                token = "length"
            elif etype == "response.failed":
                token = "failed"
            elif etype == "response.incomplete":
                token = "incomplete"
            else:
                token = "stop"
            self._finish_reason = finish_reason_of(token, bool(self._tool_order))
            out.append(self._chunk({}, self._finish_reason))
            return out
        return out

    # -- 收尾与聚合 -------------------------------------------------------

    @property
    def saw_done(self) -> bool:
        """上游是否发送过 [DONE] 终帧。"""
        return self._saw_done

    @property
    def dropped_placeholders(self) -> List[str]:
        """被丢弃的占位工具调用名（诊断用）。"""
        return list(self._dropped_placeholders)

    def finish(self) -> List[Dict[str, Any]]:
        """输出收尾 chunk（finish_reason / usage）；已收尾则补聚合收尾。"""
        out: List[Dict[str, Any]] = []
        if self._finish_reason is None:
            self._finish_reason = "tool_calls" if self._tool_order else "stop"
            out.append(self._chunk({}, self._finish_reason))
        if self._usage:
            out.append({
                "id": self._id,
                "object": "chat.completion.chunk",
                "created": self._created,
                "model": self.model,
                "choices": [],
                "usage": dict(self._usage),
            })
        out.append({
            "id": self._id,
            "object": "chat.completion.chunk",
            "created": self._created,
            "model": self.model,
            "choices": [],
        })
        return out

    def to_completion(self) -> Dict[str, Any]:
        """聚合为 chat.completion JSON（非流式响应体）。"""
        tool_calls = []
        for key in self._tool_order:
            slot = self._tools.get(key) or {}
            if slot.get("dropped"):
                continue
            tool_calls.append({
                "id": slot.get("id") or f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": slot.get("name") or "",
                    "arguments": "".join(slot.get("arguments") or []),
                },
            })
        message: Dict[str, Any] = {"role": "assistant", "content": "".join(self._text) or None}
        reasoning = "".join(self._reasoning)
        if reasoning:
            message["reasoning_content"] = reasoning
        if tool_calls:
            message["tool_calls"] = tool_calls
        finish = self._finish_reason or ("tool_calls" if tool_calls else "stop")
        if finish in ("tool_calls", "function_call", "tool_use") and not tool_calls:
            finish = "stop"
        completion: Dict[str, Any] = {
            "id": self._id,
            "object": "chat.completion",
            "created": self._created,
            "model": self.model,
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": finish,
            }],
        }
        if self._usage:
            completion["usage"] = {
                "prompt_tokens": self._usage.get("prompt_tokens", 0),
                "completion_tokens": self._usage.get("completion_tokens", 0),
                "total_tokens": self._usage.get("total_tokens", 0),
            }
        return completion


class UpstreamStreamError(Exception):
    """上游 SSE 流内 error 事件。"""
