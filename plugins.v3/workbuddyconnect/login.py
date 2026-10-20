"""
WorkBuddy 设备授权登录（两个区域同构）。

流程：auth/state 签发待确认 state 与浏览器授权链接 → 用户在浏览器完成授权 →
轮询 auth/token 得到令牌 → login/account 补全账号身份。

两个承重细节：

- **每次尝试独立 cookie jar**：国内网关在 auth/state 响应里下发路由 cookie，
  并用它关联回调；发起与后续轮询必须携带同一 jar，共享 jar 会让两次并发登录
  互相应答。
- **待确认不是错误**：auth/token 在用户未完成授权时返回 HTTP 200 + 业务码
  11217，判定 pending/complete 看业务码而非 HTTP 状态。
"""

import time
from typing import Any, Dict, Optional

from .variants import (
    AUTH_STATE_PATH,
    LOGIN_PENDING_CODE,
    LOGIN_TIMEOUT_MS,
    LOGIN_USER_AGENT,
    auth_token_path,
    login_account_path,
    variant_for_region,
)

try:  # 宿主共享环境提供 HTTPX2；直接依赖异常/响应类型时必须导入 httpx2
    import httpx2 as _httpx
except ImportError:  # 纯逻辑测试环境回退 httpx
    import httpx as _httpx  # type: ignore


class LoginCookieJar:
    """单次登录尝试的最小 cookie 罐。"""

    def __init__(self) -> None:
        self._cookies: Dict[str, str] = {}

    def absorb(self, response: Any) -> None:
        """吸收响应里下发的全部 cookie，同名后写覆盖。"""
        try:
            raw_values = response.headers.get_list("set-cookie")
        except AttributeError:
            raw = response.headers.get("set-cookie") or ""
            raw_values = [raw] if raw else []
        for raw in raw_values:
            pair = raw.split(";", 1)[0]
            if "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            name = name.strip()
            if name:
                self._cookies[name] = value.strip()

    def header(self) -> Optional[str]:
        if not self._cookies:
            return None
        return "; ".join(f"{name}={value}" for name, value in self._cookies.items())


class WorkBuddyLoginClient:
    """
    设备授权登录客户端。一次尝试一个 state，jars 按 state 隔离。

    `pending` 覆盖两种情形：用户尚未完成授权（业务码 11217）与
    浏览器半程中网关拒绝本轮轮询（4xx）。5xx 与传输失败视为真实错误抛出，
    避免把故障藏进永不结束的 pending。
    """

    def __init__(self, client: Optional[Any] = None) -> None:
        self._client = client
        self._jars: Dict[str, LoginCookieJar] = {}

    # -- 内部：HTTP 客户端管理 -------------------------------------------------

    def _headers(self, region: str, jar: Optional[LoginCookieJar] = None) -> Dict[str, str]:
        variant = variant_for_region(region)
        origin = variant.login_origin()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": origin,
            "Referer": f"{origin}/",
            "User-Agent": LOGIN_USER_AGENT,
        }
        cookie = jar.header() if jar else None
        if cookie:
            headers["Cookie"] = cookie
        return headers

    async def _request(self, method: str, url: str, headers: Dict[str, str],
                       body: Optional[str] = None) -> Any:
        if self._client is not None:
            request = self._client.build_request(method, url, headers=headers,
                                                 content=body, timeout=LOGIN_TIMEOUT_MS / 1000)
            return await self._client.send(request)
        # 自管客户端：request() 非流式返回（内容已读入），离开上下文即可释放连接
        async with _httpx.AsyncClient(timeout=LOGIN_TIMEOUT_MS / 1000) as client:
            return await client.request(method, url, headers=headers, content=body)

    # -- 对外接口 -------------------------------------------------------------

    async def begin(self, region: str) -> Dict[str, str]:
        """
        发起一次登录：返回 state 与用户需要打开的授权链接。
        响应 cookie 保存在该 state 对应的 jar 中，供后续轮询使用。
        """
        variant = variant_for_region(region)
        jar = LoginCookieJar()
        response = await self._request(
            "POST", f"{variant.login_base()}{AUTH_STATE_PATH}", self._headers(region), "{}",
        )
        jar.absorb(response)
        envelope = self._read_envelope(response)
        if response.status_code >= 400 or envelope["code"] != 0:
            raise RuntimeError(
                f"auth state 获取失败（http {response.status_code}, code {envelope['code']}）：{envelope['msg'][:160]}"
            )
        data = envelope["data"] if isinstance(envelope["data"], dict) else {}
        state = data.get("state") if isinstance(data.get("state"), str) else ""
        auth_url = data.get("authUrl") if isinstance(data.get("authUrl"), str) else ""
        if not state or not auth_url:
            raise RuntimeError("auth/state 响应缺少 state 或 authUrl")
        self._jars[state] = jar
        return {"state": state, "authUrl": auth_url, "region": region}

    async def poll(self, state: str, region: str) -> Dict[str, Any]:
        """
        轮询一次登录结果。返回 {"status": "pending"} 或
        {"status": "complete", "tokens": {...}, "account": {...}}。
        """
        jar = self._jars.get(state)
        variant = variant_for_region(region)
        response = await self._request(
            "GET", f"{variant.login_base()}{auth_token_path(state)}", self._headers(region, jar),
        )
        if jar:
            jar.absorb(response)
        if response.status_code >= 500:
            raise RuntimeError(f"auth/token 端点故障（http {response.status_code}）")
        if response.status_code >= 400:
            return {"status": "pending"}
        envelope = self._read_envelope(response)
        if envelope["code"] in (LOGIN_PENDING_CODE, None) or envelope["code"] != 0:
            # 业务码非 0（含 11217）都是"尚未完成"
            if envelope["code"] != 0:
                return {"status": "pending"}
        data = envelope["data"] if isinstance(envelope["data"], dict) else {}
        access_token = data.get("accessToken") if isinstance(data.get("accessToken"), str) else ""
        if not access_token:
            return {"status": "pending"}
        tokens = {
            "accessToken": access_token,
            "refreshToken": data.get("refreshToken") if isinstance(data.get("refreshToken"), str) else "",
            "expiresInSec": data.get("expiresIn") if isinstance(data.get("expiresIn"), (int, float)) else 0,
            "domain": data.get("domain") if isinstance(data.get("domain"), str) else "",
        }
        account = await self.fetch_account(state, region, access_token)
        self.forget(state)
        return {"status": "complete", "tokens": tokens, "account": account}

    async def fetch_account(self, state: str, region: str, access_token: str) -> Dict[str, Any]:
        """
        读取账号身份（uid / enterpriseId / nickname）。
        尽力而为：失败只影响展示名与 X-User-Id，不影响凭据可用性。
        """
        jar = self._jars.get(state)
        variant = variant_for_region(region)
        try:
            headers = self._headers(region, jar)
            headers["Authorization"] = f"Bearer {access_token}"
            response = await self._request(
                "GET", f"{variant.login_base()}{login_account_path(state)}", headers,
            )
            if jar:
                jar.absorb(response)
            if response.status_code >= 400:
                return {"uid": ""}
            envelope = self._read_envelope(response)
            data = envelope["data"] if isinstance(envelope["data"], dict) else {}
            account: Dict[str, Any] = {
                "uid": data.get("uid") if isinstance(data.get("uid"), str) else "",
            }
            if isinstance(data.get("enterpriseId"), str) and data["enterpriseId"]:
                account["enterpriseId"] = data["enterpriseId"]
            if isinstance(data.get("nickname"), str) and data["nickname"]:
                account["nickname"] = data["nickname"]
            return account
        except Exception:  # noqa: BLE001 - 尽力而为
            return {"uid": ""}

    def forget(self, state: str) -> None:
        """丢弃一次尝试的 cookie jar。"""
        self._jars.pop(state, None)

    def pending_count(self) -> int:
        """当前持有的尝试数（诊断用）。"""
        return len(self._jars)

    @staticmethod
    def _read_envelope(response: Any) -> Dict[str, Any]:
        text = response.text if isinstance(response.text, str) else ""
        import json as _json
        try:
            parsed = _json.loads(text)
        except (ValueError, TypeError):
            raise RuntimeError(
                f"workbuddy 登录端点返回非 JSON（http {response.status_code}）：{text[:160]}"
            ) from None
        if not isinstance(parsed, dict):
            raise RuntimeError(f"workbuddy 登录端点返回异常文档（http {response.status_code}）")
        return {
            "code": parsed["code"] if isinstance(parsed.get("code"), int) else 0,
            "msg": parsed["msg"] if isinstance(parsed.get("msg"), str) else "",
            "data": parsed.get("data"),
        }


def new_attempt_record(state: str, auth_url: str, region: str) -> Dict[str, Any]:
    """生成可序列化的登录尝试记录（供插件持久化待确认状态）。"""
    return {
        "state": state,
        "authUrl": auth_url,
        "region": region,
        "createdAt": time.time(),
    }
