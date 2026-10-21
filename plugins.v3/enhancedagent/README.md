# EnhancedAgent（AI助手增强）

为 MoviePilot 内置 Agent 提供**侧边栏全页入口**：流式对话、工具调用卡片与多会话管理。
会话能力完全复用内置 Agent 接口，插件不复制业务逻辑（桥接层集中在 `bridge.py`）。

> 基于 MoviePilot V3 插件机制（Vue 联邦渲染 + `get_sidebar_nav` 侧栏路由）实现，
> 除 `bridge.py` 外不依赖 `app.*` 内部模块；`bridge.py` 集中桥接内置 Agent 会话接口，
> 随 MoviePilot 版本演进可能需要跟进适配。

## 功能

- **侧边栏全页入口**：「AI助手增强」全页路由（Vue 联邦组件，`get_sidebar_nav`）
- **SSE 流式对话**：fetch + ReadableStream 自解析，事件协议与内置 Agent 一致
  （start/delta/tool/thinking/attachment/choice/done/error）
- **工具调用卡片**：执行中/完成/失败生命周期、思考状态、选择卡片
- **多会话管理**：新建 / 切换 / 重命名 / 删除 / 运行态徽标 / 停止任务

## 安装

### 本地源安装（推荐）

1. 将本仓库注册为本地插件源：系统设置 `PLUGIN_LOCAL_REPO_PATHS` 指向仓库根目录
   （含 `package.v3.json` 的目录，相对路径以 MoviePilot 根目录解析）。
2. 插件市场选择「本地」，安装并启用 `EnhancedAgent`。
3. 验证：`GET /api/v1/plugin/sidebar_nav` 出现「AI助手增强」；侧边栏点击进入全页。

### 手动安装

将 `plugins.v3/enhancedagent/` 整目录拷贝到 MoviePilot 插件目录下的
`plugins.v3/enhancedagent/`，重启后在插件页启用。注意 `dist/` 为运行时必需的
联邦构建产物（`remoteEntry.js` 等），必须随插件一起部署，不可只拷贝源码。

## 接入速查

| 步骤 | 操作 |
| --- | --- |
| 1 | 启用插件后，主界面左侧导航栏出现「AI助手增强」（`mdi-robot-happy`） |
| 2 | 点击进入全页聊天：输入即流式输出，工具调用以卡片呈现 |
| 3 | 左侧会话列表：新建（生成 client UUID）/ 切换 / 重命名 / 删除 / 停止运行中任务 |
| 4 | `done` 后展示消息快照自动回写，刷新页面历史仍在 |

## 端点

| 路径 | 方法 | 认证 | 说明 |
| --- | --- | --- | --- |
| `/sse_ticket` | POST | 宿主登录态（Bearer） | 签发一次性短时效 SSE 票据 |
| `/stream` | POST | 票据（query `ticket`） | 流式对话（转发内置 Agent SSE） |
| `/sessions` | GET | 宿主登录态 | 历史会话列表（分页） |
| `/sessions/{id}` | GET | 宿主登录态 | 会话详情（含展示消息、处理中状态） |
| `/sessions/{id}/display` | PUT | 宿主登录态 | 保存展示消息快照（可携带标题） |
| `/sessions/{id}` | DELETE | 宿主登录态 | 删除会话 |
| `/sessions/{id}/stop` | POST | 宿主登录态 | 停止会话任务 |
| `/sessions_busy` | POST | 宿主登录态 | 批量查询会话运行态 |

以上端点挂载于 `/api/v1/plugin/enhancedagent/` 前缀下。

## 协议要点

- **配置双通道**：vue 模式由远程 `Config` 组件渲染；`get_form()` 同时提供 vuetify
  兜底表单（启用开关），宿主回落 vuetify 渲染（旧版前端/远程组件加载失败）时
  设置页仍有可用配置项，不会空白。
- **桥接边界**：`bridge.py` 是插件唯一允许 `import app.*` 内部实现的模块
  （`app.api.endpoints.agent`、`app.application.messaging.chat` 等），其余文件
  只依赖 V3 稳定 SDK（`app.sdk.plugin`）。`system_version` 声明 `>=3.0.0`。
- **SSE 鉴权**：浏览器 fetch 不便携带鉴权头，流式接口采用一次性短时效票据——
  先 `POST .../sse_ticket`（`auth: bear`）换票，再以
  `POST .../stream?ticket=...`（`allow_anonymous`）无凭据消费。
  票据一次性消费、120 秒过期，插件停用/重载时清空。
- **会话模型**：会话创建约定为前端生成 client UUID 作为 seed 传入 `/stream`，
  服务端派生稳定 server id，`start` 事件回传；展示消息与内置面板共用
  `AgentChatMessage` 结构，`PUT display` 为全量覆盖，建议单客户端写入、写前 GET 合并。

## 目录结构

```text
enhancedagent/
├── __init__.py        # 插件类 EnhancedAgent（vue 渲染模式 + 侧栏导航 + 桥接 API）
├── bridge.py          # 桥接端点（唯一 import app.* 内部实现的文件）
├── src/               # 前端工程（Vite + @originjs/vite-plugin-federation）
│   ├── package.json
│   ├── vite.config.js
│   └── src/{components,composables}
└── dist/assets/       # 联邦构建产物（remoteEntry.js 等，运行时必需）
```

## 构建前端产物

```bash
cd src
npm install
npm run build     # 产物输出到 dist/（remoteEntry.js 位于 dist/assets/）
```

构建后确认 `dist/assets/remoteEntry.js` 存在（与 `get_render_mode()` 返回的
`("vue", "dist/assets")` 一致）。开发时可 `npm run dev`（vite build --watch），
配合 `PLUGIN_LOCAL_REPO_PATHS` 与 `PLUGIN_AUTO_RELOAD` 热更新。

## 已知限制

- **侧栏入口有缓存**：宿主前端缓存 `plugin/sidebar_nav` 结果，启用插件或变更入口后
  需**刷新页面**才会显示/消失「AI助手增强」入口（宿主行为，非插件可控制）
- `bridge.py` 依赖 `app.api.*` / `app.application.*` 内部实现（非公开 SDK），
  MoviePilot 核心重构后可能需要跟进适配；后续版本计划下沉到 `app.sdk`
- `PUT display` 全量覆盖展示快照，与内置面板并发写入可能互踩（约定单客户端写入）
- 挂起/待交互会话无独立服务端状态位，以 pending choice + `updated_at` 近似展示
- 调优面板（上下文窗口/压缩参数）、会话归档、附件、斜杠命令等见 PRD 二期
- 仅验证 MoviePilot V3（`system_version >= 3.0.0`）

## 版本

- v1.0.2：设置界面修复——vue shared 去 singleton（对齐宿主 `shared:['vue','vuetify']`
  契约，修复远程组件运行异常导致的保存不生效/界面异常）；Config 重写为 Vuetify
  组件树（官方示例风格）；AppPage props 宽松化与布局贴合宿主容器。
- v1.0.1：修复设置页空白（get_form 补 vuetify 兜底表单）；PostCSS 剔除 vuetify
  全局 CSS；Config 补空值防护与 switch 事件。
- v1.0.0：侧边栏全页入口、SSE 流式对话（一次性票据鉴权）、工具卡片、多会话管理。

## 免责声明

本插件按现状提供，仅供个人学习研究使用。`bridge.py` 桥接 MoviePilot 内部接口，
属非公开实现，升级 MoviePilot 可能导致插件失效或行为异常；因使用产生的任何后果
（数据丢失、服务中断、账号限制等）由使用者自行承担。请勿用于生产环境或商用场景。
