"""
WorkBuddy 连接器纯逻辑测试（不依赖宿主 SDK / 网络）。

覆盖线协议规整、错误分类、目录与计费解析、凭据读写与目录缓存降级链。
运行：python -m unittest discover tests/v3/workbuddyconnect
"""

import importlib.util
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugins.v3" / "workbuddyconnect"


def _load_pure_package():
    """把纯逻辑模块按包加载到 wbpure 命名空间（跳过插件主类的宿主依赖）。"""
    name = "wbpure"
    if name in sys.modules:
        return sys.modules[name]
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(PLUGIN_DIR)]
    sys.modules[name] = pkg
    for mod_name in ("variants", "protocol", "auth", "catalog"):
        spec = importlib.util.spec_from_file_location(
            f"{name}.{mod_name}", PLUGIN_DIR / f"{mod_name}.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{name}.{mod_name}"] = module
        spec.loader.exec_module(module)
        setattr(pkg, mod_name, module)
    return pkg


wbpure = _load_pure_package()
variants = wbpure.variants
protocol = wbpure.protocol
auth = wbpure.auth
catalog = wbpure.catalog


class TestVariants(unittest.TestCase):
    """区域描述符。"""

    def test_variant_for_region(self):
        self.assertIs(variants.variant_for_region("cn"), variants.CN_VARIANT)
        self.assertIs(variants.variant_for_region("global"), variants.AI_VARIANT)
        self.assertIs(variants.variant_for_region("whatever"), variants.CN_VARIANT)

    def test_paths_per_region(self):
        self.assertEqual(variants.CN_VARIANT.chat_paths(), ["/v2/chat/completions"])
        self.assertEqual(variants.AI_VARIANT.chat_paths(),
                         ["/console/chat/completions", "/v2/chat/completions"])
        self.assertEqual(variants.CN_VARIANT.billing_meter_paths(),
                         ["/v2/billing/meter/get-user-resource"])
        self.assertEqual(variants.AI_VARIANT.billing_meter_paths(),
                         ["/billing/meter/get-user-resource", "/v2/billing/meter/get-user-resource"])
        self.assertEqual(variants.CN_VARIANT.checkin_base(), "https://www.workbuddy.cn")
        self.assertEqual(variants.AI_VARIANT.checkin_base(), "https://www.workbuddy.ai")

    def test_fallback_versions(self):
        self.assertEqual(variants.CN_VARIANT.fallback_app_version(), "5.5.6")
        self.assertEqual(variants.AI_VARIANT.fallback_app_version(), "5.5.2")


class TestErrorClassification(unittest.TestCase):
    """上游失败分类。"""

    def test_hard_credit_status(self):
        self.assertEqual(protocol.classify_upstream_error(402, "x"), "hard_credit")

    def test_session_dead(self):
        self.assertEqual(
            protocol.classify_upstream_error(401, "Offline user session not found"), "session_dead")
        self.assertEqual(protocol.classify_upstream_error(400, "code 12153"), "session_dead")

    def test_429_distinguishes_credit_and_rate(self):
        self.assertEqual(
            protocol.classify_upstream_error(429, '{"code":14018,"msg":"Credits exhausted."}'),
            "hard_credit")
        self.assertEqual(protocol.classify_upstream_error(429, "quota exceeded"), "soft_rate")
        self.assertEqual(protocol.classify_upstream_error(429, "Too Many Requests"), "soft_rate")

    def test_body_phrase_markers(self):
        self.assertEqual(protocol.classify_upstream_error(400, "积分不足"), "hard_credit")
        self.assertEqual(protocol.classify_upstream_error(403, "rate limit reached"), "soft_rate")

    def test_status_buckets(self):
        self.assertEqual(protocol.classify_upstream_error(404, ""), "not_found")
        self.assertEqual(protocol.classify_upstream_error(500, ""), "server")
        self.assertEqual(protocol.classify_upstream_error(0, "transport error"), "server")
        self.assertEqual(protocol.classify_upstream_error(400, "bad request"), "client")

    def test_path_fallback(self):
        self.assertTrue(protocol.path_fallback_status(404))
        self.assertTrue(protocol.path_fallback_status(405))
        self.assertTrue(protocol.path_fallback_status(403, "<html>WAF Block Page</html>"))
        self.assertFalse(protocol.path_fallback_status(403, '{"code":1}'))
        self.assertFalse(protocol.path_fallback_status(429))
        self.assertFalse(protocol.path_fallback_status(401))


class TestChatBodyPreparation(unittest.TestCase):
    """聊天请求体规整。"""

    def test_forces_stream_and_defaults(self):
        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "model": "glm-5.2", "messages": [], "stream": False, "store": False,
        })))
        self.assertTrue(out["stream"])
        self.assertNotIn("store", out)
        self.assertEqual(out["stream_options"], {"include_usage": True})

    def test_keeps_explicit_stream_options(self):
        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "messages": [], "stream_options": {"include_usage": False},
        })))
        self.assertEqual(out["stream_options"], {"include_usage": False})

    def test_max_completion_tokens_translation(self):
        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "messages": [], "max_completion_tokens": 128,
        })))
        self.assertEqual(out["max_tokens"], 128)
        self.assertNotIn("max_completion_tokens", out)

        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "messages": [], "max_tokens": 64, "max_completion_tokens": 128,
        })))
        self.assertEqual(out["max_tokens"], 64)

        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "messages": [], "max_completion_tokens": 0,
        })))
        self.assertNotIn("max_tokens", out)

    def test_developer_role_rewrite(self):
        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "messages": [{"role": "developer", "content": "sys"}, {"role": "user", "content": "hi"}],
        })))
        self.assertEqual(out["messages"][0]["role"], "system")

    def test_tool_choice_flatten(self):
        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "messages": [],
            "tools": [{"type": "function", "function": {"name": "f"}}],
            "tool_choice": {"type": "function", "function": {"name": "f"}},
        })))
        self.assertEqual(out["tool_choice"], "f")

        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "messages": [],
            "tools": [{"type": "function"}],
            "tool_choice": {"type": "none"},
        })))
        self.assertNotIn("tool_choice", out)
        self.assertNotIn("tools", out)

        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "messages": [], "tool_choice": {"type": "auto"},
        })))
        self.assertEqual(out["tool_choice"], "auto")

    def test_reasoning_effort_normalization(self):
        for spelling in ("off", "disabled", "default", "auto"):
            out = json.loads(protocol.prepare_chat_body(
                json.dumps({"messages": [], "reasoning_effort": spelling}),
                default_effort="high"))
            self.assertEqual(out["reasoning_effort"], "high", spelling)

        out = json.loads(protocol.prepare_chat_body(
            json.dumps({"messages": [], "reasoning_effort": "off"})))
        self.assertNotIn("reasoning_effort", out)

        out = json.loads(protocol.prepare_chat_body(
            json.dumps({"messages": [], "reasoning_effort": "max"}), default_effort="high"))
        self.assertEqual(out["reasoning_effort"], "max")

    def test_international_prepends_system(self):
        out = json.loads(protocol.prepare_international_chat_body(json.dumps({
            "messages": [{"role": "user", "content": "hi"}],
        })))
        self.assertEqual(out["messages"][0]["role"], "system")
        self.assertEqual(out["messages"][1]["content"], "hi")

        out = json.loads(protocol.prepare_international_chat_body(json.dumps({
            "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}],
        })))
        self.assertEqual(len(out["messages"]), 2)

    def test_prompt_cache_key(self):
        body = json.dumps({"messages": []})
        once = json.loads(protocol.with_prompt_cache_key(body, "uid-12345678x"))
        twice = json.loads(protocol.with_prompt_cache_key(body, "uid-12345678x"))
        self.assertEqual(once["prompt_cache_key"], twice["prompt_cache_key"])
        other = json.loads(protocol.with_prompt_cache_key(body, "other-user-999"))
        self.assertNotEqual(once["prompt_cache_key"], other["prompt_cache_key"])
        kept = json.loads(protocol.with_prompt_cache_key(
            json.dumps({"messages": [], "prompt_cache_key": "mine"}), "uid"))
        self.assertEqual(kept["prompt_cache_key"], "mine")

    def test_system_channel_bypass_exact(self):
        """system content 以拦截前缀开头时自动加绕过前缀。"""
        blocked = "You are an AI agent powered by DeepSeek Harness."
        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "messages": [{"role": "system", "content": blocked}],
        })))
        content = out["messages"][0]["content"]
        self.assertNotEqual(content[:len(blocked)].lower(), blocked.lower()[:len(blocked)])
        self.assertIn(blocked, content)

    def test_system_channel_bypass_case_insensitive(self):
        """大小写混合同样命中拦截。"""
        for variant in (
            "you are an ai agent powered by deepseek harness",
            "YOU ARE AN AI AGENT POWERED BY DEEPSEEK HARNESS",
            "You Are An AI Agent Powered By DeepSeek Harness",
        ):
            out = json.loads(protocol.prepare_chat_body(json.dumps({
                "messages": [{"role": "system", "content": variant}],
            })))
            self.assertIn("​", out["messages"][0]["content"], variant)

    def test_system_channel_bypass_leading_whitespace(self):
        """前导空白也命中拦截。"""
        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "messages": [{"role": "system", "content": "  You are an AI agent powered by DeepSeek Harness"}],
        })))
        self.assertIn("​", out["messages"][0]["content"])

    def test_system_normal_prompt_untouched(self):
        """正常 system prompt 不受影响。"""
        for prompt in (
            "You are a helpful assistant.",
            "You are an AI coding agent powered by DeepSeek Harness",
            "Some other prompt",
        ):
            out = json.loads(protocol.prepare_chat_body(json.dumps({
                "messages": [{"role": "system", "content": prompt}],
            })))
            self.assertEqual(out["messages"][0]["content"], prompt)

    def test_system_array_content_bypass(self):
        """数组形式 content 中的 text 部分也做绕过。"""
        blocked = "You are an AI agent powered by DeepSeek Harness."
        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "messages": [{"role": "system", "content": [
                {"type": "text", "text": blocked},
                {"type": "text", "text": "You are a helpful assistant."},
            ]}],
        })))
        items = out["messages"][0]["content"]
        self.assertIn("​", items[0]["text"])
        self.assertEqual(items[1]["text"], "You are a helpful assistant.")

    def test_system_user_message_not_touched(self):
        """user 消息即使以拦截前缀开头也不修改。"""
        blocked = "You are an AI agent powered by DeepSeek Harness."
        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "messages": [{"role": "user", "content": blocked}],
        })))
        self.assertEqual(out["messages"][0]["content"], blocked)

    def test_system_developer_role_also_bypassed(self):
        """developer→system 转换后同样生效。"""
        blocked = "You are an AI agent powered by DeepSeek Harness."
        out = json.loads(protocol.prepare_chat_body(json.dumps({
            "messages": [{"role": "developer", "content": blocked}],
        })))
        self.assertEqual(out["messages"][0]["role"], "system")
        self.assertIn("​", out["messages"][0]["content"])


class TestGatewayHeaders(unittest.TestCase):
    """网关会话头族。"""

    def test_header_family_present(self):
        headers = protocol.with_gateway_chat_headers({}, json.dumps({"messages": []}))
        for key in ("X-Conversation-Message-ID", "X-Request-ID", "X-Conversation-Request-ID"):
            self.assertIn(key, headers)
        self.assertEqual(headers["X-Request-ID"], headers["X-Conversation-Message-ID"])

    def test_turn_id_stable_across_tool_steps(self):
        step1 = json.dumps({"messages": [
            {"role": "user", "content": "帮我查一下"},
            {"role": "assistant", "tool_calls": [{"id": "t1"}]},
        ]})
        step2 = json.dumps({"messages": [
            {"role": "user", "content": "帮我查一下"},
            {"role": "assistant", "tool_calls": [{"id": "t1"}]},
            {"role": "tool", "content": "result"},
        ]})
        h1 = protocol.with_gateway_chat_headers({}, step1)
        h2 = protocol.with_gateway_chat_headers({}, step2)
        self.assertEqual(h1["X-Conversation-Request-ID"], h2["X-Conversation-Request-ID"])
        self.assertEqual(h1["X-Conversation-ID"], h2["X-Conversation-ID"])

    def test_new_user_message_changes_turn(self):
        body_a = json.dumps({"messages": [{"role": "user", "content": "第一句"}]})
        body_b = json.dumps({"messages": [{"role": "user", "content": "第二句"}]})
        self.assertNotEqual(
            protocol.with_gateway_chat_headers({}, body_a)["X-Conversation-Request-ID"],
            protocol.with_gateway_chat_headers({}, body_b)["X-Conversation-Request-ID"])

    def test_existing_headers_kept(self):
        headers = {"X-Conversation-ID": "kept"}
        protocol.with_gateway_chat_headers(headers, json.dumps({"messages": []}))
        self.assertEqual(headers["X-Conversation-ID"], "kept")


class TestCatalogParsing(unittest.TestCase):
    """模型目录解析。"""

    SAMPLE = {
        "models": [
            {"id": "glm-5.2", "name": "GLM-5.2", "maxInputTokens": 1000000, "maxOutputTokens": 48000,
             "supportsImages": True, "credits": "x0.79 credits",
             "supportsReasoning": True, "onlyReasoning": True,
             "reasoning": {"defaultEffort": "medium", "canDisableThinking": False}},
            {"id": "off-model", "name": "Off", "maxInputTokens": 1, "maxOutputTokens": 1,
             "disabled": True},
            {"id": "other", "name": "Other", "maxInputTokens": 10, "maxOutputTokens": 10},
        ],
        "agents": [{"name": "cli", "models": ["glm-5.2", "other", "off-model", "missing"]}],
    }

    def test_cli_agent_filter_and_order(self):
        models = protocol.parse_model_catalog(self.SAMPLE)
        self.assertEqual([m["id"] for m in models], ["glm-5.2", "other"])

    def test_billing_and_reasoning_parsed(self):
        models = protocol.parse_model_catalog(self.SAMPLE)
        glm = models[0]
        self.assertEqual(glm["billing"]["credits"], "x0.79 credits")
        self.assertFalse(glm["billing"]["free"])
        self.assertEqual(glm["reasoning"]["defaultEffort"], "medium")

    def test_empty_cli_raises(self):
        with self.assertRaises(ValueError):
            protocol.parse_model_catalog({"models": [], "agents": [{"name": "cli", "models": []}]})
        with self.assertRaises(ValueError):
            protocol.parse_model_catalog({"models": []})

    def test_normalize_credits(self):
        self.assertEqual(protocol.normalize_credits("x0.79 credits"), "x0.79")
        self.assertEqual(protocol.normalize_credits("x0.79"), "x0.79")
        self.assertIsNone(protocol.normalize_credits("credits"))
        self.assertIsNone(protocol.normalize_credits("  "))

    def test_promotion_overlay(self):
        model = {
            "id": "m", "billing": {"credits": "x0.79", "free": False},
            "promotions": [{"start": 0, "end": 10, "factor": 0.0, "label": "限时免费", "priority": 1}],
        }
        live = protocol.model_with_current_promotion(model, now_ms=5)
        self.assertTrue(live["billing"]["free"])
        self.assertIn("限时免费", live["billing"]["badges"])
        lapsed = protocol.model_with_current_promotion(model, now_ms=100)
        self.assertTrue(lapsed["billing"].get("rateUnknown"))
        self.assertFalse(lapsed["billing"]["free"])


class TestCreditsParsing(unittest.TestCase):
    """计费文档解析。"""

    def test_personal_credits(self):
        document = {"data": {"Response": {"Data": {
            "TotalDosage": 500,
            "Accounts": [
                {"PackageName": "A", "CycleCapacitySize": 300, "CycleCapacityRemain": 120,
                 "CycleCapacityUsed": 180, "CycleEndTime": "2026-12-31 23:59:59"},
                {"PackageName": "B", "CapacityRemain": 30, "CapacitySize": 100},
            ],
        }}}}
        credits = protocol.parse_personal_credits(document)
        self.assertEqual(credits["total"], 150)
        self.assertEqual(credits["totalSize"], 500)  # TotalDosage 作下限
        self.assertEqual(credits["accounts"][0]["packageEndTime"], "2026-12-31 23:59:59")
        self.assertEqual(credits["accounts"][1]["remain"], 30)

    def test_enterprise_credits(self):
        credits = protocol.parse_enterprise_credits(
            {"code": 0, "data": {"limitNum": 100, "credit": 40, "cycleResetTime": "2026-11-01"}})
        self.assertEqual(credits["total"], 60)
        self.assertEqual(credits["cycleResetTime"], "2026-11-01")

    def test_enterprise_unlimited(self):
        credits = protocol.parse_enterprise_credits({"data": {"limit_num": -1}})
        self.assertTrue(credits["unlimited"])
        self.assertEqual(credits["total"], 0)

    def test_enterprise_unknown_shape_raises(self):
        with self.assertRaises(ValueError):
            protocol.parse_enterprise_credits({"data": {"foo": 1}})


class TestSseAggregation(unittest.TestCase):
    """SSE 聚合为非流式响应。"""

    def test_content_and_usage(self):
        events = [
            json.dumps({"id": "c1", "choices": [{"delta": {"content": "你"}}]}),
            json.dumps({"choices": [{"delta": {"content": "好"}}]}),
            json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}),
            "[DONE]",
        ]
        result = protocol.aggregate_chat_completion(events, "glm-5.2")
        self.assertEqual(result["object"], "chat.completion")
        self.assertEqual(result["choices"][0]["message"]["content"], "你好")
        self.assertEqual(result["choices"][0]["finish_reason"], "stop")
        self.assertEqual(result["usage"]["total_tokens"], 5)

    def test_tool_calls_merge(self):
        events = [
            json.dumps({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "t1", "function": {"name": "query", "arguments": ""}}]}}]}),
            json.dumps({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "{\"a\":1}"}}]}}]}),
            json.dumps({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        ]
        result = protocol.aggregate_chat_completion(events, "m")
        calls = result["choices"][0]["message"]["tool_calls"]
        self.assertEqual(calls[0]["id"], "t1")
        self.assertEqual(calls[0]["function"]["name"], "query")
        self.assertEqual(calls[0]["function"]["arguments"], '{"a":1}')
        self.assertEqual(result["choices"][0]["finish_reason"], "tool_calls")


class TestCheckinClassification(unittest.TestCase):
    """签到响应分类。"""

    def test_already_claimed(self):
        self.assertEqual(protocol.classify_checkin_response(400, '{"code":10001}')["status"],
                         "already-claimed")
        self.assertEqual(protocol.classify_checkin_response(400, '{"msg":"今天已签到"}')["status"],
                         "already-claimed")

    def test_claimed_with_amount(self):
        result = protocol.classify_checkin_response(200, '{"code":0,"data":{"credit":5}}')
        self.assertEqual(result["status"], "claimed")
        self.assertEqual(result["amount"], 5.0)

    def test_no_campaign(self):
        self.assertEqual(
            protocol.classify_checkin_response(200, '{"msg":"活动未开启"}')["status"], "no-campaign")

    def test_error(self):
        self.assertEqual(protocol.classify_checkin_response(500, '{"msg":"boom"}')["status"], "error")


class TestCredentialStore(unittest.TestCase):
    """凭据解析与存储。"""

    SAMPLE = {
        "auth": {"accessToken": "at-1", "refreshToken": "rt-1", "expiresAt": 1794051445,
                 "domain": "copilot.tencent.com", "realm": "cn"},
        "account": {"uid": "u-1", "nickname": "测试"},
        "region": "cn",
    }

    def test_parse_nested_and_flat(self):
        nested = auth.parse_workbuddy_auth(json.dumps(self.SAMPLE))
        self.assertEqual(nested.access_token, "at-1")
        self.assertEqual(nested.uid, "u-1")
        self.assertEqual(nested.expires_at_ms, 1794051445 * 1000)

        flat = auth.parse_workbuddy_auth(json.dumps(
            {"accessToken": "at-2", "refreshToken": "r", "expiresAt": 100, "uid": "u"}))
        self.assertEqual(flat.access_token, "at-2")

    def test_expiry_units(self):
        self.assertEqual(auth.expiry_to_ms(100), 100_000)
        self.assertEqual(auth.expiry_to_ms(1.8e12), int(1.8e12))
        self.assertEqual(auth.expiry_to_ms(0), 0)
        self.assertEqual(auth.expiry_to_ms(None), 0)

    def test_roundtrip_seconds(self):
        credential = auth.WorkBuddyCredential(
            access_token="at", refresh_token="rt", expires_at_ms=1794051445000,
            domain="copilot.tencent.com", uid="u-1", nickname="n", region="cn")
        document = auth.own_document(credential)
        self.assertEqual(document["auth"]["expiresAt"], 1794051445)  # 秒
        restored = auth.parse_own_document(json.dumps(document))
        self.assertEqual(restored.access_token, "at")
        self.assertEqual(restored.expires_at_ms, 1794051445000)
        self.assertEqual(restored.uid, "u-1")

    def test_store_save_load_and_realm_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".workbuddy-auth.json"
            store = auth.CredentialStore(path=path, expected_region="cn")
            credential = auth.WorkBuddyCredential(
                access_token="at", refresh_token="rt", expires_at_ms=int(time.time() * 1000) + 3600_000,
                domain="copilot.tencent.com", uid="u-1", region="cn")
            store.save(credential)
            self.assertEqual(store.current().access_token, "at")
            status = store.status()
            self.assertEqual(status["state"], "signed-in")
            self.assertEqual(status["uid"], "u-1")

            wrong = auth.WorkBuddyCredential(
                access_token="x", domain="www.workbuddy.ai", region="global")
            with self.assertRaises(ValueError):
                store.save(wrong)

            store.logout()
            self.assertIsNone(store.current())
            self.assertEqual(store.status()["state"], "signed-out")

    def test_import_document_rejects_other_region(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = auth.CredentialStore(path=Path(tmp) / "a.json", expected_region="cn")
            with self.assertRaises(ValueError):
                store.import_document(json.dumps(self.SAMPLE | {
                    "region": "global",
                    "auth": self.SAMPLE["auth"] | {"domain": "www.workbuddy.ai", "realm": "global"},
                }))


class TestCatalogStore(unittest.TestCase):
    """目录缓存降级链。"""

    def test_fallback_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = catalog.CatalogStore(Path(tmp), "catalog-cn.json", "cn")
            self.assertEqual(store.source(), "builtin")
            models = store.current(signed_in=True)
            self.assertGreater(len(models), 10)
            self.assertEqual(models[0]["id"], "auto")

            store.set_live([{"id": "x", "name": "X"}])
            self.assertEqual(store.source(), "live")
            self.assertEqual(store.current()[0]["id"], "x")

            # 重新打开：降级到已保存目录
            reopened = catalog.CatalogStore(Path(tmp), "catalog-cn.json", "cn")
            self.assertEqual(reopened.source(), "saved")
            self.assertEqual(reopened.current()[0]["id"], "x")

    def test_signed_out_hides_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = catalog.CatalogStore(Path(tmp), "c.json", "cn")
            self.assertEqual(store.current(signed_in=False), [])

    def test_default_effort_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = catalog.CatalogStore(Path(tmp), "c.json", "cn")
            self.assertEqual(store.default_effort_for("glm-5.2"), "medium")
            self.assertIsNone(store.default_effort_for("nope"))

    def test_builtin_global(self):
        models = catalog.builtin_models("global")
        self.assertEqual(models[0]["id"], "default-model")
        self.assertEqual(len(models), 20)


if __name__ == "__main__":
    unittest.main()
