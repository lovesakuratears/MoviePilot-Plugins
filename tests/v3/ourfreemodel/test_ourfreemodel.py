"""
我们的免费模型纯逻辑测试（不依赖宿主 SDK / 网络）。

覆盖会话铸造、指纹闸门、目录构建、思考档位、三线协议翻译与 SSE 归一。
运行：python -m unittest discover tests/v3/ourfreemodel
"""

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugins.v3" / "ourfreemodel"


def _load_pure_package():
    """把纯逻辑模块按包加载到 ofpure 命名空间（跳过插件主类的宿主依赖）。"""
    name = "ofpure"
    if name in sys.modules:
        return sys.modules[name]
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(PLUGIN_DIR)]
    sys.modules[name] = pkg
    for mod_name in ("wire", "catalog", "translate"):
        spec = importlib.util.spec_from_file_location(
            f"{name}.{mod_name}", PLUGIN_DIR / f"{mod_name}.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{name}.{mod_name}"] = module
        spec.loader.exec_module(module)
        setattr(pkg, mod_name, module)
    return pkg


ofpure = _load_pure_package()
wire = ofpure.wire
catalog = ofpure.catalog
translate = ofpure.translate


class TestSession(unittest.TestCase):
    """会话 ID 铸造与降序编码。"""

    def test_mint_session_shape(self):
        sid = wire.mint_session_id()
        self.assertTrue(sid.startswith("ses_"))
        self.assertRegex(sid, wire.SESSION_RE)
        self.assertTrue(wire.is_canonical_session(sid))

    def test_mint_session_counter_window(self):
        # 同一毫秒内连续铸造：counter 1–63 均须合规（低 12 位 0xfc0–0xfff）
        sid = wire.mint_session_id(1760000000000)
        self.assertTrue(wire.is_canonical_session(sid))
        sid2 = wire.mint_session_id(1760000000000)
        self.assertTrue(wire.is_canonical_session(sid2))
        self.assertNotEqual(sid, sid2)

    def test_canonicalize_deterministic(self):
        a = wire.canonicalize_session("conv-42")
        b = wire.canonicalize_session("conv-42")
        self.assertEqual(a, b)
        self.assertTrue(wire.is_canonical_session(a))
        c = wire.canonicalize_session("other")
        self.assertNotEqual(a, c)

    def test_is_canonical_rejects_ascending(self):
        # 形状正确但时间部分升序（低 12 位非 0xfc0–0xfff）也必须拒绝
        fake = "ses_" + "0" * 9 + "abc" + "X" * 14
        self.assertFalse(wire.is_canonical_session(fake))
        self.assertFalse(wire.is_canonical_session("not-a-session"))

    def test_session_store_stable(self):
        persisted = {}
        store = wire.SessionStore(persist=lambda mapping: persisted.update(mapping))
        first = store.session_for("user-1")
        second = store.session_for("user-1")
        self.assertEqual(first, second)
        self.assertIn("user-1", persisted)
        # 恢复后仍然映射到同一会话
        store2 = wire.SessionStore()
        store2.load(persisted)
        self.assertEqual(store2.session_for("user-1"), first)

    def test_session_store_signal_fallback(self):
        store = wire.SessionStore()
        self.assertEqual(store.session_for(""), store.session_for(None))


class TestGateway(unittest.TestCase):
    """网关指纹头与端点路由。"""

    def test_gateway_headers_v2_shape(self):
        headers = wire.gateway_headers("ses_000000000000abcdefghijklmn", stream=True)
        self.assertEqual(headers["authorization"], "Bearer public")
        self.assertEqual(headers["user-agent"], wire.CLIENT_UA)
        for key in ("x-opencode-session", "x-opencode-session-id", "x-session-affinity", "x-session-id"):
            self.assertEqual(headers[key], "ses_000000000000abcdefghijklmn")
        self.assertNotIn("x-opencode-request", headers)
        self.assertEqual(headers["accept"], "text/event-stream")

    def test_endpoint_routing(self):
        self.assertEqual(wire.wire_for("deepseek-v4.1-flash-free"), "chat")
        self.assertEqual(wire.wire_for("muse-spark-1.3-contributor-free"), "responses")
        self.assertEqual(wire.wire_for("union-alpha"), "messages")
        self.assertEqual(wire.endpoint_for("glm-5.3-flash-free"), "/inference/v1/chat/completions")

    def test_base_model_id(self):
        self.assertEqual(wire.base_model_id("deepseek-v4.1-flash-free(high)"), "deepseek-v4.1-flash-free")
        self.assertEqual(wire.base_model_id(" plain "), "plain")


class TestFingerprint(unittest.TestCase):
    """免密工具闸门。"""

    def test_injects_when_no_tools(self):
        body = {"messages": [{"role": "user", "content": "hi"}]}
        rename = wire.apply_fingerprint(body, "chat")
        self.assertEqual(rename, {})
        names = [tool["function"]["name"] for tool in body["tools"]]
        self.assertEqual(names, ["read", "shell"])
        # 提示词压制注入工具
        self.assertIn("placeholder", body["messages"][0]["content"])

    def test_verbatim_definitions(self):
        body = {}
        wire.apply_fingerprint(body, "chat")
        for tool in body["tools"]:
            name = tool["function"]["name"]
            self.assertEqual(tool["function"]["description"], wire.FINGERPRINT_TOOL_DEFINITIONS[name]["description"])
            self.assertEqual(tool["function"]["parameters"], wire.FINGERPRINT_TOOL_DEFINITIONS[name]["parameters"])

    def test_keeps_caller_tools_and_renames_collision(self):
        body = {
            "tools": [
                {"type": "function", "function": {"name": "search", "description": "d", "parameters": {"type": "object"}}},
                {"type": "function", "function": {"name": "read", "description": "我的读文件", "parameters": {"type": "object"}}},
            ],
            "tool_choice": {"type": "function", "function": {"name": "read"}},
            "messages": [
                {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "read", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": "ok"},
            ],
        }
        rename = wire.apply_fingerprint(body, "chat")
        names = [tool["function"]["name"] for tool in body["tools"]]
        self.assertIn("search", names)
        self.assertIn("read_client", names)
        self.assertIn("read", names)  # 闸门注入的官方定义
        self.assertEqual(rename, {"read_client": "read"})
        # tool_choice 与历史调用同步改名（注入提示词后 assistant 顺延到下一条）
        self.assertEqual(body["tool_choice"]["function"]["name"], "read_client")
        assistant = next(m for m in body["messages"] if m.get("role") == "assistant")
        self.assertEqual(assistant["tool_calls"][0]["function"]["name"], "read_client")

    def test_never_sends_tool_choice_none(self):
        body = {"tool_choice": "none", "messages": []}
        wire.apply_fingerprint(body, "chat")
        self.assertNotIn("tool_choice", body)

    def test_responses_flat_shape(self):
        body = {"tools": [{"name": "my_tool", "description": "d", "parameters": {"type": "object"}}]}
        wire.apply_fingerprint(body, "responses")
        names = [tool["name"] for tool in body["tools"]]
        self.assertEqual(names, ["my_tool", "read", "shell"])
        self.assertEqual(body["tool_choice"], "auto")

    def test_claude_shape(self):
        body = {"tools": [{"name": "my_tool", "description": "d", "input_schema": {"type": "object"}}]}
        wire.apply_fingerprint(body, "messages")
        names = [tool["name"] for tool in body["tools"]]
        self.assertEqual(names, ["my_tool", "read", "shell"])
        self.assertIn("system", body)

    def test_restore_and_placeholders(self):
        rename = {"read_client": "read"}
        self.assertEqual(wire.restore_tool_name("read_client", rename), "read")
        self.assertEqual(wire.restore_tool_name("other", rename), "other")
        # 注入的 read/shell 应被丢弃；调用方自己的同名工具不丢
        self.assertEqual(wire.injected_placeholder_names({}, []), ["read", "shell"])
        self.assertEqual(wire.injected_placeholder_names(rename, ["read"]), ["shell"])
        self.assertEqual(wire.injected_placeholder_names({}, ["shell"]), ["read"])


class TestCatalog(unittest.TestCase):
    """模型目录与能力表。"""

    def test_is_free_lane(self):
        self.assertTrue(catalog.is_free_lane("deepseek-v4.1-flash-free"))
        self.assertTrue(catalog.is_free_lane("union-alpha"))
        self.assertTrue(catalog.is_free_lane("big-pickle"))
        self.assertFalse(catalog.is_free_lane("deepseek-v4.1-flash"))
        self.assertFalse(catalog.is_free_lane("gpt-5"))

    def test_build_free_catalog(self):
        entries = catalog.build_free_catalog([
            "deepseek-v4.1-flash-free", "gpt-5", "deepseek-v4.1-flash-free", "muse-spark-1.3-contributor-free",
        ])
        ids = [entry["id"] for entry in entries]
        self.assertEqual(ids, ["deepseek-v4.1-flash-free", "muse-spark-1.3-contributor-free"])
        deepseek = entries[0]
        self.assertEqual(deepseek["lane"], catalog.LANE_OPENCODE)
        self.assertEqual(deepseek["wire"], "chat")
        self.assertIn("disabled", deepseek["efforts"])
        self.assertEqual(deepseek["contextWindow"], 1048576)
        self.assertEqual(entries[1]["wire"], "responses")

    def test_display_name(self):
        self.assertEqual(catalog.display_model_name("deepseek-v4.1-flash-free"), "DeepSeek V4.1 Flash")
        self.assertEqual(catalog.display_model_name("some-new-model-free"), "Some New Model Free")

    def test_parse_listing_shapes(self):
        self.assertEqual(catalog.parse_listing({"data": [{"id": "a"}, {"id": "b"}]}), ["a", "b"])
        self.assertEqual(catalog.parse_listing({"models": ["x"]}), ["x"])
        self.assertEqual(catalog.parse_listing(["y"]), ["y"])
        self.assertEqual(catalog.parse_listing(None), [])

    def test_kilo_free_filter(self):
        rows = [
            {"id": "kilo-auto/free", "isFree": True, "name": "Kilo: Auto (free)", "context_length": 200000,
             "top_provider": {"max_completion_tokens": 64000}, "architecture": {"input_modalities": ["text"]},
             "supported_parameters": ["reasoning"]},
            {"id": "paid-model", "isFree": False, "name": "Paid"},
            {"id": "no-flag", "name": "No"},
        ]
        entries = catalog.build_kilo_catalog(rows)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["lane"], catalog.LANE_KILO)
        self.assertEqual(entry["id"], "kilo-auto/free")
        self.assertTrue(entry["name"].startswith("Kilo"))
        self.assertIn("efforts", entry)
        self.assertNotIn("disabled", entry["efforts"])  # kilo-auto/free 不可关思考

    def test_effort_patch(self):
        entry = catalog.build_free_catalog(["deepseek-v4.1-flash-free"])[0]
        self.assertEqual(catalog.effort_patch_for("high", entry), {"reasoning_effort": "high"})
        self.assertEqual(catalog.effort_patch_for("disabled", entry), {"reasoning_effort": "none"})
        # 非法档位回落默认档
        self.assertEqual(catalog.effort_patch_for("nope", entry), {"reasoning_effort": "high"})
        plain = {"id": "x"}
        self.assertIsNone(catalog.effort_patch_for("high", plain))

    def test_budget_for(self):
        entry = {"maxOutput": 384000}
        self.assertEqual(catalog.budget_for(entry, None), 384000)
        self.assertEqual(catalog.budget_for(entry, 1000), 1000)
        self.assertEqual(catalog.budget_for(entry, "bad", 500), 500)

    def test_revive_catalog(self):
        stored = [
            {"id": "a-free", "lane": "opencode", "wire": "chat", "contextWindow": 128, "maxOutput": 64, "efforts": ["low", "high"]},
            {"id": "b", "lane": "unknown"},
            "junk",
        ]
        entries = catalog.revive_catalog(stored)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["efforts"], ["low", "high"])


class TestTranslate(unittest.TestCase):
    """请求翻译。"""

    def test_normalize_strips_reasoning(self):
        messages = translate.normalize_chat_messages([
            {"role": "assistant", "content": "hi", "reasoning_content": "secret thinking"},
            {"role": "user", "content": ""},
        ])
        self.assertEqual(len(messages), 1)
        self.assertNotIn("reasoning_content", messages[0])

    def test_to_claude_messages(self):
        shaped = translate.to_claude_messages([
            {"role": "system", "content": "S1"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "function": {"name": "t", "arguments": "{\"a\": 1}"}},
            ]},
            {"role": "tool", "tool_call_id": "c1", "content": "result"},
        ])
        self.assertEqual(shaped["system"], "S1")
        roles = [m["role"] for m in shaped["messages"]]
        self.assertEqual(roles, ["user", "assistant", "user"])
        tool_result = shaped["messages"][2]["content"][0]
        self.assertEqual(tool_result["type"], "tool_result")
        self.assertEqual(tool_result["tool_use_id"], "c1")

    def test_to_response_input(self):
        items = translate.to_response_input([
            {"role": "system", "content": "S"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a", "tool_calls": [
                {"id": "c1", "function": {"name": "t", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "c1", "content": "r"},
        ])
        types = [item["type"] for item in items]
        self.assertEqual(types, ["message", "message", "message", "function_call", "function_call_output"])
        self.assertEqual(items[3]["call_id"], "c1")

    def test_build_payload_wires(self):
        messages = [{"role": "user", "content": "hi"}]
        chat = translate.build_payload("chat", "m", messages, 100, temperature=0.5)
        self.assertTrue(chat["stream"])
        self.assertEqual(chat["max_tokens"], 100)
        self.assertEqual(chat["temperature"], 0.5)
        claude = translate.build_payload("messages", "m", messages, 100)
        self.assertIn("messages", claude)
        self.assertEqual(claude["max_tokens"], 100)
        responses = translate.build_payload("responses", "m", messages, 100)
        self.assertEqual(responses["max_output_tokens"], 100)
        self.assertFalse(responses["store"])

    def test_build_payload_effort_patch(self):
        payload = translate.build_payload(
            "chat", "m", [{"role": "user", "content": "x"}], 100,
            effort_patch={"reasoning_effort": "high"},
        )
        self.assertEqual(payload["reasoning_effort"], "high")


class TestStreamAssembler(unittest.TestCase):
    """SSE 归一：三线协议 → OpenAI Chat。"""

    def test_chat_stream_text_and_finish(self):
        assembler = translate.StreamAssembler("m", "chat")
        out = []
        out += assembler.feed(json.dumps({
            "choices": [{"delta": {"content": "Hello"}}],
        }))
        out += assembler.feed(json.dumps({
            "choices": [{"delta": {"content": " world"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }))
        out += assembler.finish()
        texts = [chunk["choices"][0]["delta"].get("content") for chunk in out if chunk["choices"] and chunk["choices"][0]["delta"].get("content")]
        self.assertEqual("".join(texts), "Hello world")
        completion = assembler.to_completion()
        self.assertEqual(completion["choices"][0]["message"]["content"], "Hello world")
        self.assertEqual(completion["choices"][0]["finish_reason"], "stop")
        self.assertEqual(completion["usage"]["prompt_tokens"], 3)

    def test_chat_tool_calls_and_rename(self):
        assembler = translate.StreamAssembler("m", "chat", rename_map={"read_client": "read"})
        assembler.feed(json.dumps({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "c1", "function": {"name": "read_client", "arguments": ""}},
        ]}}]}))
        assembler.feed(json.dumps({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": "{\"path\": \"a\"}"}},
        ]}, "finish_reason": "tool_calls"}]}))
        completion = assembler.to_completion()
        calls = completion["choices"][0]["message"]["tool_calls"]
        self.assertEqual(calls[0]["function"]["name"], "read")
        self.assertEqual(calls[0]["function"]["arguments"], "{\"path\": \"a\"}")
        self.assertEqual(completion["choices"][0]["finish_reason"], "tool_calls")

    def test_drops_placeholder_tool_calls(self):
        assembler = translate.StreamAssembler("m", "chat", drop_tool_names=["read", "shell"])
        assembler.feed(json.dumps({"choices": [{"delta": {"content": "ok", "tool_calls": [
            {"index": 0, "id": "c1", "function": {"name": "read", "arguments": "{}"}},
        ]}, "finish_reason": "tool_calls"}]}))
        completion = assembler.to_completion()
        self.assertNotIn("tool_calls", completion["choices"][0]["message"])
        self.assertEqual(completion["choices"][0]["finish_reason"], "stop")
        self.assertEqual(assembler.dropped_placeholders, ["read"])

    def test_claude_stream(self):
        assembler = translate.StreamAssembler("m", "messages")
        assembler.feed(json.dumps({"type": "message_start", "message": {"usage": {"input_tokens": 5, "output_tokens": 1}}}))
        assembler.feed(json.dumps({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hmm"}}))
        assembler.feed(json.dumps({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}}))
        assembler.feed(json.dumps({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1", "name": "my_tool"}}))
        assembler.feed(json.dumps({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"x\":1}"}}))
        assembler.feed(json.dumps({"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 9}}))
        completion = assembler.to_completion()
        message = completion["choices"][0]["message"]
        self.assertEqual(message["content"], "Hi")
        self.assertEqual(message["reasoning_content"], "hmm")
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "my_tool")
        self.assertEqual(message["tool_calls"][0]["function"]["arguments"], "{\"x\":1}")
        self.assertEqual(completion["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(completion["usage"]["completion_tokens"], 9)

    def test_responses_stream(self):
        assembler = translate.StreamAssembler("m", "responses")
        assembler.feed(json.dumps({"type": "response.output_item.added", "output_index": 0,
                                   "item": {"type": "function_call", "call_id": "c9", "name": "tool_a"}}))
        assembler.feed(json.dumps({"type": "response.function_call_arguments.delta", "output_index": 0, "delta": "{\"k\":2}"}))
        assembler.feed(json.dumps({"type": "response.output_text.delta", "output_index": 1, "delta": "done"}))
        assembler.feed(json.dumps({"type": "response.completed", "response": {
            "status": "completed",
            "usage": {"input_tokens": 4, "output_tokens": 6},
        }}))
        completion = assembler.to_completion()
        message = completion["choices"][0]["message"]
        self.assertEqual(message["content"], "done")
        self.assertEqual(message["tool_calls"][0]["id"], "c9")
        self.assertEqual(message["tool_calls"][0]["function"]["arguments"], "{\"k\":2}")
        self.assertEqual(completion["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(completion["usage"]["prompt_tokens"], 4)

    def test_error_event_raises(self):
        assembler = translate.StreamAssembler("m", "chat")
        with self.assertRaises(translate.UpstreamStreamError):
            assembler.feed(json.dumps({"error": {"message": "boom"}}))

    def test_reasoning_passthrough(self):
        assembler = translate.StreamAssembler("m", "chat")
        chunks = assembler.feed(json.dumps({"choices": [{"delta": {"reasoning_content": "think"}}]}))
        self.assertEqual(chunks[0]["choices"][0]["delta"]["reasoning_content"], "think")
        self.assertEqual(assembler.to_completion()["choices"][0]["message"]["reasoning_content"], "think")


if __name__ == "__main__":
    unittest.main()
