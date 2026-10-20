# 我们的免费模型（OurFreeModel）

把 [dsh-our-free-model](https://github.com/Ebony-Vinyl/dsh-our-free-model) 的**免费模型车道**
迁移为 MoviePilot V3 插件：免登录、免 API Key、免注册，即可将前沿开源/免费模型
接入 **MoviePilot 智能助手（Agent）**。

- MoviePilot：<https://movie-pilot.org/> · 插件开发文档（V3）：<https://github.com/jxxghp/MoviePilot-Plugins/blob/main/docs/Plugin_Development.md>
- 源项目（MIT）：<https://github.com/Ebony-Vinyl/dsh-our-free-model>
- 本插件仓库：<https://github.com/lovesakuratears/MoviePilot-Plugins>

## 功能

- **免密车道**：OpenCode 免密车道（opencode.ai 公共池，`Bearer public`）+
  Kilo 免费池（api.kilo.ai，`isFree: true`），均无需账号与密钥；
- **OpenAI 兼容接口**：`GET /v1/models`、`POST /v1/chat/completions`，
  流式 SSE chunk 与非流式聚合（chat.completion）都支持，智能助手
  `LLM_BASE_URL` 直接指向本插件即完成接入；
- **三线协议透明翻译**：chat / responses（muse-spark）/ messages（union-alpha）
  三种上游线协议自动路由，调用方只见 OpenAI Chat 一种形态；
- **免密闸门完整移植**：会话 ID 降序时间编码铸造（升序即 403）、v2 网关指纹头、
  `read`/`shell` 工具闸门逐字定义（改写即 403）、`tool_choice: "none"` 禁发；
- **思考强度档位**：声明了档位菜单的模型可传 `reasoning_effort`
  （off/low/medium/high/max…），未声明的模型自动回退输出预算；
- **智能体工具 ×3**：`ourfree_list_models`（列模型）、`ourfree_switch_model`
  （切换默认模型）、`ourfree_status`（插件状态）；
- **目录自动刷新**：每小时跟随上游实时清单（内置能力表 + 在线清单合流，
  联网失败时降级为缓存 / 内置兜底清单）。

## 架构对照

```
dsh-our-free-model (JavaScript / DSH)         ourfreemodel (Python / MoviePilot V3)
─────────────────────────────────────         ─────────────────────────────────────────
src/upstream.js   会话铸造/指纹头/工具闸门  →   wire.py（纯函数，含会话存储）
src/catalog.js    免费清单+能力表+Kilo 目录 →   catalog.py（能力表/档位/预算）
src/messages.js   消息→三线协议形态         →   translate.py（请求侧翻译）
src/stream.js     三线 SSE 归一             →   translate.py（StreamAssembler）
src/kilo.js       Kilo 出网                 →   lanes.py（LaneClient）
src/forward.js    loopback OpenAI 监听器    →   get_api(): /v1/chat/completions + /v1/models
src/effort.js     思考档位→请求补丁         →   catalog.effort_patch_for / budget_for
client.js 十一页 UI / EAC / 升级 / 公告     →   （DSH 专属，不迁移）
—（DSH 扩展点）                            →   get_agent_tools() 智能体工具 ×3
```

关键决策：

1. **接入 Agent 的通道是 OpenAI 兼容端点。** MoviePilot 智能助手的 LLM 由
   `LLM_PROVIDER / LLM_BASE_URL / LLM_API_KEY / LLM_MODEL` 配置（见
   [智能助手文档](https://wiki.movie-pilot.org/agent)），支持任意 OpenAI 兼容服务。
   本插件把免费车道桥接为 `/v1/chat/completions` + `/v1/models`，直接挂在宿主
   FastAPI 上（`/api/v1/plugin/OurFreeModel/v1`）。
2. **上游一律流式拉取，输出形态由调用方决定。** 免密车道只放行 `stream:true`；
   请求方要流式则归一为 OpenAI chunk SSE 透出，否则服务端聚合为 chat.completion
   （含 tool_calls / reasoning_content / usage 归并）。
3. **鉴权双轨。** OpenAI 端点自管 `Bearer <访问密钥>`（OpenAI SDK 只发 Bearer 头）；
   管理端点走宿主 `bear` 认证，供详情页按钮调用。
4. **只迁免费车道。** 源项目里 EAC 付费协付通道、十三个白嫖账号渠道、升级/公告/
   本地网关等 DSH 专属能力不在迁移范围；自带 API Key 的聚合渠道请用其它插件。
5. **纯逻辑与 I/O 分离。** `wire / catalog / translate` 无宿主依赖，
   `tests/v3/ourfreemodel` 可脱离 MoviePilot 运行。

## 目录结构

```
ourfreemodel/
├── __init__.py        # 主类 OurFreeModel：生命周期 / API / 表单 / 详情页 / 服务
├── wire.py            # 会话铸造、网关指纹头、read/shell 闸门（逐字定义）
├── catalog.py         # 免费清单构建、能力表、思考档位、输出预算
├── translate.py       # OpenAI Chat ↔ 三线协议请求翻译 + SSE 归一（StreamAssembler）
├── lanes.py           # 车道 HTTP 客户端（OpenCode 免密 / Kilo 免费池）
├── agent_tools.py     # MoviePilot 智能体工具（延迟导入 MoviePilotTool）
└── README.md          # 本文件
```

## 安装

方式一（推荐）：把它作为插件市场源。仓库
[lovesakuratears/MoviePilot-Plugins](https://github.com/lovesakuratears/MoviePilot-Plugins)
保持本目录结构，MoviePilot「插件市场」添加仓库地址（只读 `main` 分支），
安装「我们的免费模型」。

方式二（手动）：将 `plugins.v3/ourfreemodel/` 拷入 MoviePilot 插件加载目录
（与其它插件同级），将 `icons/Ourfree_A.png` 放入图标目录，并把 `package.v3.json`
条目并入市场索引，然后在插件页安装启用。

## 智能助手接入（速查）

```
AI_AGENT_ENABLE=true
LLM_PROVIDER=openai
LLM_BASE_URL=http://127.0.0.1:3000/api/v1/plugin/OurFreeModel/v1
LLM_API_KEY=<插件设置页「访问密钥」>
LLM_MODEL=deepseek-v4.1-flash-free
```

插件详情页会显示完整的四行配置与当前模型目录。常用模型：

| 模型 ID | 说明 |
| --- | --- |
| `deepseek-v4.1-flash-free` | DeepSeek V4.1 Flash，1M 上下文，可调思考档位 |
| `glm-5.3-flash-free` | GLM 5.3 Flash，1M 上下文 |
| `mimo-v2.6-flash-free` | MiMo V2.6 Flash（小米），视觉 + 思考 |
| `space-bunny-free` | Space Bunny，524K 输出上限 |
| `nemotron-3.5-super-vl-free` | Nemotron 3.5 Super VL，视觉 + 思考 |
| `kilo-auto/free`（Kilo 车道） | Kilo 自动路由免费池 |

（以上为内置能力表已知 ID；实际以 `/v1/models` 在线清单为准。）

## 开发与测试

```bash
python -m compileall plugins.v3/ourfreemodel            # 编译门禁
python tests/v3/ourfreemodel/test_ourfreemodel.py       # 纯逻辑用例
# 在 MoviePilot 开发环境内：
#   ../MoviePilot/.venv/bin/python -m pytest tests/v3/ourfreemodel
```

## 协议要点（移植自源项目，实测口径）

- **免密车道**：`POST https://opencode.ai/inference/v1/chat/completions`，
  `Authorization: Bearer public`，UA `opencode/latest/2.0.26/cli`，
  须同时携带 `x-opencode-session` / `x-opencode-session-id` /
  `x-session-affinity` / `x-session-id`；**不带** `x-opencode-request`（v1 专用头，带了即 403）。
- **会话 ID**：`ses_` + 12 hex + 14 base62，hex 部分必须是降序时间编码
  `~(ts_ms << 12 | counter)`（counter 1–63，低 12 位 `0xfc0–0xfff`）；
  一个对话固定映射一个稳定上游会话（额度按会话记账，每请求新铸 ID 会 429）。
- **工具闸门**：带 `tools` 的请求必须**逐字**声明 `read` / `shell` 两个工具定义
  （描述与 schema 与 OpenCode v2.0.26 CLI 一致，改写即 403）；调用方同名工具自动
  改名 `<name>_client[N]` 并在响应侧还原；**绝不下发** `tool_choice: "none"`。
- **端点路由**：muse-spark 系列走 `/inference/v1/responses`，`union-alpha` 走
  `/inference/v1/messages`（Anthropic 形态），其余走 `/chat/completions`。
- **Kilo 车道**：`GET https://api.kilo.ai/api/gateway/models`（只取 `isFree: true`），
  `POST …/chat/completions`，无指纹闸门、无凭据。
- **思考档位**：`effortPatch` 用 `$effort` 占位替换后合并进请求体
  （如 `reasoning_effort: "high"`）；关闭档走 `effortOffPatch`
  （如 `reasoning_effort: "none"` / `reasoning: {enabled: false}`）。

## 免责声明

仅供个人学习研究使用；免费车道来自上游公开免密网关，**不限量 ≠ 无限速**
（上游 429 限速随时可能出现）。Kilo 免费池上游明示提示词可能被记录并用于改进
服务，请勿用于涉密内容。上游条款自负；与 OpenCode / Kilo / MoviePilot /
DeepSeek / 小米 / 智谱 等均无隶属关系。使用者需遵守各上游服务条款，
因使用产生的一切后果由使用者自行承担。MIT License（协议移植部分）。
