"""
WorkBuddy 双区域（国内版 / 国际版）常量与描述符。

上游为同一套客户端框架的两个区域部署，差异集中在：网关域名、计费域名、
签到域名、模型目录接口、聊天路径与请求头细节。本模块把所有区域差异收敛为
数据常量，其余模块不再携带 if-else 分支。

协议细节移植自 dsh-workbuddy-connect（MIT）的 src/variants.ts / src/upstream.ts
/ src/login.ts / src/checkin.ts，实测口径保持一致。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# 区域标识
# ---------------------------------------------------------------------------

REGION_CN = "cn"
REGION_GLOBAL = "global"
REGIONS: Tuple[str, ...] = (REGION_CN, REGION_GLOBAL)

REGION_LABELS: Dict[str, str] = {
    REGION_CN: "WorkBuddy（国内版）",
    REGION_GLOBAL: "WorkBuddy AI（国际版）",
}

# ---------------------------------------------------------------------------
# 上游域名
# ---------------------------------------------------------------------------

# 国内版聊天网关（同时服务登录与刷新）
CN_CHAT_BASE = "https://copilot.tencent.com"
# 国内版计费/站点域名（Origin 与 Referer 也使用它）
CN_BILLING_BASE = "https://www.codebuddy.cn"
# 国内版每日签到域名
CN_CHECKIN_BASE = "https://www.workbuddy.cn"
# 国际版统一域名（聊天、计费、签到、登录）
GLOBAL_BASE = "https://www.workbuddy.ai"
# 国际版网关要求 X-Domain 恒为该值，与签发会话的主机无关
GLOBAL_DOMAIN = "www.workbuddy.ai"

# ---------------------------------------------------------------------------
# 聊天与目录路径
# ---------------------------------------------------------------------------

# 两个区域共用的聊天路径
CHAT_PATH = "/v2/chat/completions"
# 国际版优先走 console 路径，404/405 时回落到共用路径
GLOBAL_CONSOLE_CHAT_PATH = "/console/chat/completions"
# 国内版模型目录（官方 CLI 同款接口）
CN_CATALOG_PATH = "/console/enterprises/personal/models"
# 国际版模型目录（App 主进程文档接口，按 User-Agent 分流）
GLOBAL_CATALOG_PATH = "/v3/config"

# ---------------------------------------------------------------------------
# 登录（设备授权）路径
# ---------------------------------------------------------------------------

AUTH_STATE_PATH = "/v2/plugin/auth/state?platform=CLI"
# auth/token 在浏览器半程未完成时返回业务码 11217（HTTP 仍为 200）
LOGIN_PENDING_CODE = 11217
# 登录接口的 CLI 身份（与聊天 UA 无关）
LOGIN_USER_AGENT = "CLI/2.63.2 CodeBuddy/2.63.2"


def auth_token_path(state: str) -> str:
    """轮询登录结果的路径。"""
    return f"/v2/plugin/auth/token?state={state}"


def login_account_path(state: str) -> str:
    """登录完成后读取账号身份的路径。"""
    return f"/v2/plugin/login/account?state={state}"


# ---------------------------------------------------------------------------
# 刷新与计费路径
# ---------------------------------------------------------------------------

REFRESH_PATH = "/v2/plugin/auth/token/refresh"
# 个人计费：国内版带 /v2 前缀，国际版先试无前缀写法
BILLING_METER_PATH = "/v2/billing/meter/get-user-resource"
BILLING_METER_PATH_GLOBAL = "/billing/meter/get-user-resource"
# 仅国内版企业账号走的周期额度接口
ENTERPRISE_USAGE_PATH = "/v2/billing/meter/get-enterprise-user-usage"
# 每日签到（两个区域同路径，域名不同）
CHECKIN_PATH = "/v2/billing/meter/daily-checkin"

# 个人计费请求体的固定产品码
BILLING_PRODUCT_CODE = "p_tcaca"

# ---------------------------------------------------------------------------
# 客户端身份常量
# ---------------------------------------------------------------------------

# 刷新 / 目录 / 计费共用的 CLI 形态 User-Agent
CLIENT_UA = "CLI/2.63.2 CodeBuddy/2.63.2"
# 归因与计费头携带的客户端版本
CLIENT_VERSION = "2.63.2"
# 上游归因用的客户端名（桌面产品名，而非网关名）
WORKBUDDY_CLIENT_NAME = "WorkBuddy"
# 聊天 UA 的内置回退版本：读不到本机安装的桌面端时使用（形态要求，非时效承诺）
FALLBACK_CN_APP_VERSION = "5.5.6"
FALLBACK_GLOBAL_APP_VERSION = "5.5.2"

# 请求超时（毫秒）：登录为交互式轮询，其余为普通 JSON 调用
LOGIN_TIMEOUT_MS = 30_000
JSON_TIMEOUT_MS = 30_000
CHECKIN_TIMEOUT_MS = 15_000
# 上游失败响应体采样上限
ERROR_BODY_LIMIT = 4096

# 国际版网关要求首条消息是 system；缺省时前置的最小提示词
INTERNATIONAL_SYSTEM_PROMPT = "You are a helpful assistant."


@dataclass(frozen=True)
class Variant:
    """一个 WorkBuddy 产品变体（区域）的完整描述。"""

    id: str
    """插件内部标识，如 workbuddy / workbuddy-ai。"""
    display_name: str
    region: str
    """所属区域：cn / global。"""
    auth_filename: str
    """凭据文件名（位于插件数据目录根部）。"""
    catalog_filename: str
    """模型目录缓存文件名（位于 state/ 子目录）。"""

    def login_base(self) -> str:
        """登录与聊天所用的网关地址。"""
        return GLOBAL_BASE if self.region == REGION_GLOBAL else CN_CHAT_BASE

    def login_origin(self) -> str:
        """登录请求的 Origin / Referer 域。"""
        return GLOBAL_BASE if self.region == REGION_GLOBAL else CN_BILLING_BASE

    def chat_base(self) -> str:
        """聊天网关地址。"""
        return self.login_base()

    def billing_base(self) -> str:
        """计费接口地址。"""
        return GLOBAL_BASE if self.region == REGION_GLOBAL else CN_BILLING_BASE

    def checkin_base(self) -> str:
        """每日签到地址（国内版独立域名为 www.workbuddy.cn）。"""
        return GLOBAL_BASE if self.region == REGION_GLOBAL else CN_CHECKIN_BASE

    def chat_paths(self) -> List[str]:
        """聊天候选路径，按优先级排列。"""
        if self.region == REGION_GLOBAL:
            return [GLOBAL_CONSOLE_CHAT_PATH, CHAT_PATH]
        return [CHAT_PATH]

    def billing_meter_paths(self) -> List[str]:
        """个人计费候选路径，按优先级排列。"""
        if self.region == REGION_GLOBAL:
            return [BILLING_METER_PATH_GLOBAL, BILLING_METER_PATH]
        return [BILLING_METER_PATH]

    def accept_language(self) -> str:
        """上游期望的 Accept-Language。"""
        return "en-US" if self.region == REGION_GLOBAL else "zh-CN"

    def fallback_app_version(self) -> str:
        """聊天 UA 的内置回退版本号。"""
        return FALLBACK_GLOBAL_APP_VERSION if self.region == REGION_GLOBAL else FALLBACK_CN_APP_VERSION

    def product_token(self) -> str:
        """聊天 UA 中的产品段。"""
        return "WorkBuddy AI" if self.region == REGION_GLOBAL else "WorkBuddy"


CN_VARIANT = Variant(
    id="workbuddy",
    display_name="WorkBuddy",
    region=REGION_CN,
    auth_filename=".workbuddy-auth.json",
    catalog_filename="catalog-cn.json",
)

AI_VARIANT = Variant(
    id="workbuddy-ai",
    display_name="WorkBuddy AI",
    region=REGION_GLOBAL,
    auth_filename=".workbuddy-ai-auth.json",
    catalog_filename="catalog-global.json",
)

VARIANTS: Tuple[Variant, ...] = (CN_VARIANT, AI_VARIANT)


def variant_for_region(region: str) -> Variant:
    """按区域标识取变体，未识别一律回落国内版。"""
    return AI_VARIANT if region == REGION_GLOBAL else CN_VARIANT


@dataclass
class LoginAttempt:
    """一次进行中的登录尝试。"""

    state: str
    auth_url: str
    region: str
    cookies: Dict[str, str] = field(default_factory=dict)
    created_at: float = 0.0
