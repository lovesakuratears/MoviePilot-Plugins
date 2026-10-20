"""
WorkBuddy 凭据模型与存储。

凭据只来自本插件自己的设备授权登录（或用户导入的 workbuddy.json），
不读取桌面客户端的本地文件。磁盘文档保持跨工具兼容的
`{"auth":{...},"account":{...}}` 布局（expiresAt 为秒），便于与
workbuddy2api / workbuddy-cliproxy 等兄弟工具互认。

凭据文件位于插件数据目录根部（与可重建的缓存分开，"清缓存"永不误删凭据）。
"""

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .protocol import realm_of

# 凭据唯一来源标记
CREDENTIAL_SOURCE = "login"


@dataclass
class WorkBuddyCredential:
    """归一化后的凭据，时间戳统一为 epoch 毫秒。"""

    access_token: str
    refresh_token: str = ""
    expires_at_ms: int = 0
    refresh_expires_at_ms: Optional[int] = None
    domain: str = ""
    region: Optional[str] = None
    uid: str = ""
    enterprise_id: Optional[str] = None
    nickname: Optional[str] = None
    source: str = CREDENTIAL_SOURCE

    # 兼容协议模块里按驼峰取字段的函数
    @property
    def accessToken(self) -> str:  # noqa: N802 - 线协议字段名保持驼峰
        return self.access_token

    @property
    def refreshToken(self) -> str:  # noqa: N802
        return self.refresh_token

    @property
    def enterpriseId(self) -> Optional[str]:  # noqa: N802
        return self.enterprise_id


def expiry_to_ms(value: Any) -> int:
    """归一化过期时间：兼容秒与毫秒两种写法。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return 0
    return int(value) if value > 1e12 else int(value * 1000)


def _optional_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _build_credential(auth: Dict[str, Any], identity: Dict[str, Any],
                      region: Optional[str] = None) -> Optional[WorkBuddyCredential]:
    access_token = auth.get("accessToken") if isinstance(auth.get("accessToken"), str) else ""
    if not access_token:
        return None
    refresh_expires = auth.get("refreshExpiresAt")
    realm = region or _optional_str(auth.get("realm"))
    enterprise = _optional_str(identity.get("enterpriseId"))
    nickname = _optional_str(identity.get("nickname"))
    return WorkBuddyCredential(
        access_token=access_token,
        refresh_token=auth.get("refreshToken") if isinstance(auth.get("refreshToken"), str) else "",
        expires_at_ms=expiry_to_ms(auth.get("expiresAt")),
        refresh_expires_at_ms=expiry_to_ms(refresh_expires) if refresh_expires is not None else None,
        domain=_optional_str(auth.get("domain")) or "",
        region="global" if (realm or "").strip().lower() == "global" else ("cn" if realm else None),
        uid=_optional_str(identity.get("uid")) or "",
        enterprise_id=enterprise,
        nickname=nickname,
    )


def parse_workbuddy_auth(text: str) -> Optional[WorkBuddyCredential]:
    """
    解析跨工具凭据文档：嵌套布局 {"auth":{...},"account":{...}} 与手写扁平均可。
    区域声明接受顶层 region 与 auth.realm 两种拼写。
    """
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    if isinstance(parsed.get("auth"), dict):
        auth = parsed["auth"]
        identity = parsed.get("account") if isinstance(parsed.get("account"), dict) else {}
    else:
        auth = parsed
        identity = parsed
    region = _optional_str(parsed.get("region"))
    return _build_credential(auth, identity, region)


def parse_own_document(text: str) -> Optional[WorkBuddyCredential]:
    """解析本插件写出的文档；旧版 credential 包裹布局同样可读。"""
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    stored = parsed.get("credential")
    if isinstance(stored, dict) and isinstance(stored.get("accessToken"), str) and stored["accessToken"]:
        region = _optional_str(stored.get("region"))
        return WorkBuddyCredential(
            access_token=stored["accessToken"],
            refresh_token=stored.get("refreshToken") if isinstance(stored.get("refreshToken"), str) else "",
            expires_at_ms=int(stored["expiresAtMs"]) if isinstance(stored.get("expiresAtMs"), (int, float)) else 0,
            refresh_expires_at_ms=(int(stored["refreshExpiresAtMs"])
                                   if isinstance(stored.get("refreshExpiresAtMs"), (int, float)) else None),
            domain=_optional_str(stored.get("domain")) or "",
            region="global" if (region or "").strip().lower() == "global" else ("cn" if region else None),
            uid=_optional_str(stored.get("uid")) or "",
            enterprise_id=_optional_str(stored.get("enterpriseId")),
            nickname=_optional_str(stored.get("nickname")),
        )
    return parse_workbuddy_auth(text)


def own_document(credential: WorkBuddyCredential) -> Dict[str, Any]:
    """序列化为跨工具嵌套布局；expiresAt 写秒（与兄弟工具一致）。"""
    region = realm_of(credential)
    auth: Dict[str, Any] = {
        "accessToken": credential.access_token,
        "refreshToken": credential.refresh_token,
        "expiresAt": int(credential.expires_at_ms / 1000),
        "domain": credential.domain,
        "realm": region,
    }
    if credential.refresh_expires_at_ms:
        auth["refreshExpiresAt"] = int(credential.refresh_expires_at_ms / 1000)
    account: Dict[str, Any] = {"uid": credential.uid}
    if credential.enterprise_id:
        account["enterpriseId"] = credential.enterprise_id
    if credential.nickname:
        account["nickname"] = credential.nickname
    return {"version": 1, "region": region, "auth": auth, "account": account}


def write_credential_file(path: Path, credential: WorkBuddyCredential) -> None:
    """原子写入凭据文件（临时文件 + rename），权限收敛为仅属主可读写。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(own_document(credential), ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".wbcred-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        try:
            os.chmod(tmp_name, 0o600)
        except OSError:
            pass
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_credential_file(path: Path) -> Optional[WorkBuddyCredential]:
    """读取凭据文件；不存在或不可读一律视为未登录。"""
    try:
        return parse_own_document(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    except Exception:
        return None


class CredentialStore:
    """
    单变体凭据存储：按需刷新 + 单飞（并发请求共享一次刷新）。

    刷新策略：access token 进入过期余量（默认 5 分钟）或已过期才刷新；
    刷新失败但旧 token 尚未过期时继续使用旧 token，避免刷新端点抖动
    打断可用会话。
    """

    def __init__(self, path: Path, expected_region: str,
                 refresh_func=None, refresh_margin_ms: int = 5 * 60 * 1000):
        self._path = Path(path)
        self._expected_region = expected_region
        self._refresh_func = refresh_func
        self._refresh_margin_ms = refresh_margin_ms
        self._inflight: Optional[Any] = None

    @property
    def path(self) -> Path:
        return self._path

    def current(self) -> Optional[WorkBuddyCredential]:
        """读取已存凭据（不刷新）；跨区域凭据拒绝使用并给出可诊断错误。"""
        credential = read_credential_file(self._path)
        if credential is None:
            return None
        region = realm_of(credential)
        if region != self._expected_region:
            label = "WorkBuddy AI" if region == "global" else "WorkBuddy (CN)"
            raise ValueError(
                f"{self._path} 内的凭据属于 {label}，与当前实例区域不符；"
                f"请为当前区域重新登录，或移除该文件"
            )
        return credential

    def status(self) -> Dict[str, Any]:
        """只读登录摘要；永不抛错。"""
        try:
            credential = self.current()
            if credential is None:
                return {"state": "signed-out"}
            result: Dict[str, Any] = {
                "state": "signed-in",
                "expiresAtMs": credential.expires_at_ms,
                "region": realm_of(credential),
                "uid": credential.uid,
            }
            if credential.refresh_expires_at_ms:
                result["refreshExpiresAtMs"] = credential.refresh_expires_at_ms
            if credential.nickname:
                result["nickname"] = credential.nickname
            if credential.domain:
                result["domain"] = credential.domain
            return result
        except Exception as error:  # noqa: BLE001 - 状态接口不抛错
            return {"state": "signed-out", "reason": str(error)}

    def save(self, credential: WorkBuddyCredential) -> None:
        """持久化登录/刷新得到的凭据；跨区域凭据在边界处拒绝。"""
        region = realm_of(credential)
        if region != self._expected_region:
            raise ValueError(
                f"拒绝为当前实例存储 {'WorkBuddy AI' if region == 'global' else 'WorkBuddy (CN)'} 凭据"
            )
        write_credential_file(self._path, credential)

    def import_document(self, text: str) -> WorkBuddyCredential:
        """导入 workbuddy.json（跨工具布局）；区域不符直接拒绝。"""
        credential = parse_own_document(text)
        if credential is None:
            raise ValueError("文档中没有可用凭据（需要包含 accessToken，与 workbuddy.json 格式一致）")
        region = realm_of(credential)
        if region != self._expected_region:
            label = "WorkBuddy AI" if region == "global" else "WorkBuddy (CN)"
            raise ValueError(f"该文档属于 {label}，请在对应区域的实例中导入")
        self.save(credential)
        return credential

    def logout(self) -> None:
        """删除本区域凭据（不动缓存文件）。"""
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass

    def needs_refresh(self, credential: WorkBuddyCredential) -> bool:
        if credential.expires_at_ms <= 0:
            return True
        return time.time() * 1000 + self._refresh_margin_ms >= credential.expires_at_ms

    async def resolve(self) -> WorkBuddyCredential:
        """取可用凭据；需要刷新时执行（同一时刻只有一个刷新在飞）。"""
        import asyncio
        credential = self.current()
        if credential is None:
            raise PermissionError("尚未登录 WorkBuddy；请在插件详情页生成登录链接并完成授权")
        if not self.needs_refresh(credential):
            return credential
        if self._inflight is None:
            self._inflight = asyncio.ensure_future(self._refresh_now(credential))
            try:
                result = await self._inflight
            finally:
                self._inflight = None
            return result
        return await self._inflight

    async def _refresh_now(self, credential: WorkBuddyCredential) -> WorkBuddyCredential:
        if not credential.refresh_token:
            if credential.expires_at_ms > time.time() * 1000 + 30_000:
                return credential
            raise PermissionError("访问令牌已过期且没有刷新令牌；请重新登录")
        if self._refresh_func is None:
            if credential.expires_at_ms > time.time() * 1000 + 30_000:
                return credential
            raise PermissionError("访问令牌已过期且未配置刷新流程；请重新登录")
        try:
            outcome = await self._refresh_func(credential)
        except Exception as error:  # noqa: BLE001
            if credential.expires_at_ms > time.time() * 1000 + 30_000:
                return credential
            raise PermissionError(f"令牌刷新失败且访问令牌已过期（{error}）；请重新登录") from error
        refreshed = WorkBuddyCredential(
            access_token=outcome.get("accessToken") or credential.access_token,
            refresh_token=outcome.get("refreshToken") or credential.refresh_token,
            expires_at_ms=(int(time.time() * 1000 + outcome["expiresInSec"] * 1000)
                           if outcome.get("expiresInSec") else credential.expires_at_ms),
            refresh_expires_at_ms=credential.refresh_expires_at_ms,
            domain=outcome.get("domain") or credential.domain,
            region=credential.region,
            uid=credential.uid,
            enterprise_id=credential.enterprise_id,
            nickname=credential.nickname,
        )
        self.save(refreshed)
        return refreshed
