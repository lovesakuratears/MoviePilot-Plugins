# WorkBuddy连接器（WorkBuddyConnect）

把 **WorkBuddy（国内版）/ WorkBuddy AI（国际版）** 的模型桥接为 **OpenAI 兼容接口**，
让 MoviePilot 智能助手直接使用 GLM、DeepSeek、Kimi、MiniMax 等模型；同时提供
登录、额度、模型目录、每日签到等管理能力。

> 协议实现移植自 [masknull/dsh-workbuddy-connect](https://github.com/masknull/dsh-workbuddy-connect)（MIT），
> 仅为个人学习研究使用；依赖 WorkBuddy 客户端接口（非官方开放 API），上游更新后可能失效。
> 使用者需遵守 WorkBuddy 服务条款，与腾讯 / WorkBuddy / DeepSeek 无关联。

## 功能

- **登录即用**：详情页生成授权链接，浏览器完成登录；访问令牌自动续期
- **区域二选一**：国内版（WorkBuddy）/ 国际版（WorkBuddy AI），账号与积分互不混用；
  需要双区域并存时用「虚拟分身」再开一个实例，分别登录
- **OpenAI 兼容端点**：`/v1/chat/completions`（流式 SSE 透传 / 非流式聚合）与 `/v1/models`，
  供智能助手 `LLM_BASE_URL` 直接接入
- **额度查询**：个人资源包明细 + 国内版企业周期额度
- **每日自动签到**：自定义时刻（默认 10:00 北京时间），支持手动补签与消息通知
- **智能体工具**：`workbuddy_query_credits` / `workbuddy_daily_checkin` / `workbuddy_list_models`，
  对话中即可查额度、签到、看模型
- **模型目录**：实时目录 → 上次缓存 → 内置快照三级降级；支持隐藏指定模型

## 接入智能助手

在「设定 → 系统 → 基础设置 → 智能助手」中填写：

| 字段 | 值 |
| --- | --- |
| 启用智能助手 | 开 |
| LLM提供商 | `openai`（OpenAI 兼容） |
| LLM基础URL | `http://127.0.0.1:3000/api/v1/plugin/WorkBuddyConnect/v1`（端口按部署调整，详情页会给出准确值） |
| LLM API密钥 | 插件设置页的「访问密钥」（首次保存自动生成） |
| LLM模型名称 | 详情页模型表中的任意 ID，如 `glm-5.2`、`deepseek-v4-pro` |

可选：`LLM_MAX_CONTEXT_TOKENS` 按模型上下文设置（单位 K）；支持图片输入的模型可打开
`LLM_SUPPORT_IMAGE_INPUT`。

## 使用

1. 插件市场安装（或按仓库 README 手动安装）后启用插件，选择区域版本；
2. 打开插件**详情页** → 「生成登录链接」→ 浏览器打开链接完成授权 →
   「我已完成授权」（或等待 1 分钟内自动确认）；
3. 详情页可查看额度明细、模型列表，并一键刷新 / 签到 / 退出；
4. 消息渠道中可用 `/wb_status`（查状态与额度）、`/wb_checkin`（立即签到）。

凭据导入：`POST /api/v1/plugin/WorkBuddyConnect/import` 提交 `workbuddy.json`
（workbuddy2api / workbuddy-cliproxy 的跨工具格式）全文即可，跨区域文档会被拒绝。

## 端点

| 路径 | 方法 | 认证 | 说明 |
| --- | --- | --- | --- |
| `/v1/chat/completions` | POST | Bearer 访问密钥 | OpenAI 兼容聊天 |
| `/v1/models` | GET | Bearer 访问密钥 | OpenAI 兼容模型列表 |
| `/login/begin` | POST | 宿主登录态 | 发起设备授权登录 |
| `/login/poll` | POST | 宿主登录态 | 轮询登录确认 |
| `/status` | GET | 宿主登录态 | 完整状态 |
| `/checkin` | POST | 宿主登录态 | 立即签到 |
| `/catalog/refresh` | POST | 宿主登录态 | 刷新模型目录 |
| `/credits/refresh` | POST | 宿主登录态 | 刷新额度 |
| `/logout` | POST | 宿主登录态 | 退出登录 |
| `/import` | POST | 宿主登录态 | 导入凭据文档 |

OpenAI 兼容端点声明 `allow_anonymous` 并在端点内校验 `Authorization: Bearer <访问密钥>`——
OpenAI SDK 只会携带 Bearer 头，无法使用宿主的 `X-API-KEY` 认证通道；密钥在插件设置页
生成与更换，请勿泄露给不受信方。

## 数据文件

插件数据目录（不要写回源码目录）：

```
<data>/
├── .workbuddy-auth.json        # 国内版凭据
├── .workbuddy-ai-auth.json     # 国际版凭据
└── state/
    ├── catalog-cn.json         # 国内版目录缓存
    └── catalog-global.json     # 国际版目录缓存
```

凭据与缓存分离存放，清缓存不会影响登录态。

## 已知限制

- 依赖 WorkBuddy 客户端接口（非官方开放 API），上游改动可能需要跟进适配
- 国际版登录（`www.workbuddy.ai`）在部分网络不可达；国内版不受影响
- 国际版模型目录来自 App 文档接口（按 User-Agent 分流），属私有实现；失败时降级到
  上次缓存 / 内置快照并在详情页标注来源
- 聊天请求恒为流式（上游拒绝非流式）；`stream=false` 的调用方由本插件服务端聚合
- 仅验证 MoviePilot V3（`system_version >= 3.0.0`）

## 免责声明

仅供个人学习研究使用；因使用产生的任何后果（账号限制、额度清空、服务中断等）
由使用者自行承担。请勿商用或超出个人合理使用范围。
