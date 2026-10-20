"""
WorkBuddy 每日福利签到（国内版 / 国际版同构）。

- 国内版：https://www.workbuddy.cn/v2/billing/meter/daily-checkin
- 国际版：https://www.workbuddy.ai/v2/billing/meter/daily-checkin

已签到识别：HTTP 400 + code 10001，或消息含「已签到 / already」；
成功：code 0/200 并提取赠送额度；活动未开启单独分类。
"""

import json
import time
from typing import Any, Dict, Optional

from . import protocol
from .variants import CHECKIN_PATH, CHECKIN_TIMEOUT_MS, variant_for_region

try:
    import httpx2 as _httpx
except ImportError:
    import httpx as _httpx  # type: ignore


class WorkBuddyCheckInService:
    """每日签到执行器。"""

    def __init__(self, http_client: Optional[Any] = None):
        self._client = http_client

    async def check_in(self, credential: Any) -> Dict[str, Any]:
        """
        执行一次签到，返回
        {date, timestamp, status, amount?, message}。
        status ∈ claimed / already-claimed / no-campaign / error。
        """
        now_ms = time.time() * 1000
        today = protocol.utc8_date_string(now_ms)
        access_token = getattr(credential, "access_token", None) or getattr(credential, "accessToken", "")
        if not access_token:
            return {"date": today, "timestamp": now_ms, "status": "error",
                    "message": "No access token available", "amount": None}

        region = protocol.realm_of(credential)
        variant = variant_for_region(region)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": variant.checkin_base(),
            "Referer": f"{variant.checkin_base()}/profile/growth-center",
            "User-Agent": "CLI/2.63.2 CodeBuddy/2.63.2",
            "X-CodeBuddy-Request": "1",
            "Accept-Language": variant.accept_language(),
        }
        headers.update(protocol.account_stable_headers(getattr(credential, "uid", "") or ""))
        uid = getattr(credential, "uid", "") or ""
        if uid:
            headers["X-User-Id"] = uid
        enterprise_id = getattr(credential, "enterprise_id", None) or getattr(credential, "enterpriseId", None) or ""
        if region == "global":
            headers["X-Domain"] = "www.workbuddy.ai"
            headers["X-No-Enterprise-Id"] = "1"
        else:
            if enterprise_id:
                headers["X-Enterprise-Id"] = enterprise_id
                headers["X-Tenant-Id"] = enterprise_id
            else:
                headers["X-No-Enterprise-Id"] = "1"
            domain = getattr(credential, "domain", "") or ""
            if domain:
                headers["X-Domain"] = domain

        url = f"{variant.checkin_base()}{CHECKIN_PATH}"
        try:
            if self._client is not None:
                request = self._client.build_request(
                    "POST", url, headers=headers, content="{}",
                    timeout=CHECKIN_TIMEOUT_MS / 1000,
                )
                response = await self._client.send(request)
            else:
                async with _httpx.AsyncClient(timeout=CHECKIN_TIMEOUT_MS / 1000) as client:
                    response = await client.post(url, headers=headers, content="{}")
                    body_text = response.text or ""
                    return self._classify(response.status_code, body_text, today, now_ms)
            body_text = response.text or ""
            try:
                await response.aclose()
            except Exception:  # noqa: BLE001
                pass
            return self._classify(response.status_code, body_text, today, now_ms)
        except Exception as error:  # noqa: BLE001
            return {"date": today, "timestamp": now_ms, "status": "error",
                    "message": str(error), "amount": None}

    @staticmethod
    def _classify(status: int, body_text: str, today: str, now_ms: float) -> Dict[str, Any]:
        result = protocol.classify_checkin_response(status, body_text)
        return {
            "date": today,
            "timestamp": now_ms,
            "status": result["status"],
            "message": result["message"],
            "amount": result["amount"],
        }
