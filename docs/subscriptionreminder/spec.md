# 订阅上映提醒 - 规格说明

## Why
现有的 `doubansync` 和 `doubanupcoming` 插件聚焦于"发现新内容"（榜单推送、豆瓣想看同步），但缺少对已添加订阅的"上映前提醒"功能。用户已通过 MoviePilot 订阅了影视，但不知道何时上映，需要一个插件定期扫描所有订阅，获取上映日期，在即将播出前发送通知提醒。

## What Changes
- 新增 `SubscriptionReminder` 插件（插件名：订阅上映提醒），基于 MoviePilot V2 框架
- 查询 MoviePilot 订阅系统中所有已添加的订阅（通过 `SubscribeOper`）
- 对每个订阅获取上映日期：TMDB API（优先）→ 豆瓣页面抓取（回退）→ Bing 浏览器搜索（最后手段）
- **智能刷新策略**：已有精确到日（YYYY-MM-DD）的上映日期不再重复刷新；仅对日期未知或仅有年月的订阅持续刷新
- **订阅变更感知**：监测到新增订阅时立即获取上映日期并加入历史记录，在插件 UI 中展示
- **每日定时刷新**：支持自定义间隔（小时），持续检查日期未知的订阅
- 每周固定时间发送"下周上映"汇总通知，列出即将播出的订阅条目
- 支持自定义通知时间（周几 + 几点）
- 支持自定义提前提醒天数（默认提前 7 天，即下周上映的内容）
- 支持开播前 24 小时单独提醒（可选开关）
- **下周无上映不发送通知**（静默跳过，不打扰用户）
- **UI 全抄 doubansync**：配置表单布局、历史记录页面（VCard 水平卡片 + VDialogCloseBtn），在此基础上优化升级美观度、添加 hover 动效
- 复用 `doubanupcoming` 插件中已有的 TMDB 匹配、豆瓣详情抓取、Bing 搜索基础设施
- **不对 `doubansync` 做改造**：`doubansync` 的职责是同步豆瓣"想看"数据并自动添加订阅，与"订阅后上映提醒"是不同的功能阶段，强行改造会混淆职责

## Impact
- Affected specs: 无（新增插件）
- Affected code: `plugins.v2/subscriptionreminder/__init__.py`, `plugins.v2/subscriptionreminder/package.v2.json`, `MoviePilot-Plugins/package.v2.json`

## ADDED Requirements

### Requirement: 插件注册与生命周期
系统 SHALL 作为一个 MoviePilot V2 插件注册，名称为"订阅上映提醒"，支持启用/禁用、配置持久化、APScheduler 定时服务调度。

#### Scenario: 插件启用
- **WHEN** 用户在配置中开启"启用插件"开关并保存
- **THEN** 插件注册以下定时服务：
  - 每日定时刷新服务（按配置的间隔小时数循环执行，仅刷新日期未知的订阅）
  - 每周汇总提醒服务（按配置的星期几+时间）
- **AND** 如果开启了"开播前24小时提醒"，该提醒在刷新中自动检测并注册

#### Scenario: 插件禁用
- **WHEN** 用户关闭"启用插件"开关
- **THEN** 插件停止所有定时服务，不再发送通知

#### Scenario: 配置持久化
- **WHEN** 用户修改任意配置项并保存
- **THEN** 配置通过 `update_config()` 持久化到 MoviePilot 数据库，重启后恢复

### Requirement: 智能刷新策略（精确日期锁定）
系统 SHALL 采用智能刷新策略：已有精确到日（YYYY-MM-DD）的上映日期不再重复刷新，仅对日期未知或仅有年月的订阅继续查询。

#### Scenario: 精确日期不再刷新
- **WHEN** 某订阅已有上映日期且格式为 YYYY-MM-DD（精确到日）
- **THEN** 系统在后续刷新中跳过该订阅，不再查询 API
- **AND** 该日期视为"已确认"，保持不变

#### Scenario: 日期未知或仅有年月时继续刷新
- **WHEN** 某订阅的上映日期为空、仅有年份（YYYY）、或仅有年月（YYYY-MM）
- **THEN** 系统在每次刷新中继续查询 TMDB/豆瓣/Bing
- **AND** 一旦获取到精确到日的日期，立即锁定不再刷新

#### Scenario: 每日定时刷新
- **WHEN** 插件启用且配置了刷新间隔（默认 6 小时）
- **THEN** 系统通过 APScheduler IntervalTrigger 每 N 小时执行一次刷新任务
- **AND** 刷新任务遍历所有订阅，仅对"日期未知/不精确"的订阅获取上映日期
- **AND** 若发现新的精确上映日期，自动注册开播前 24 小时提醒（若开启）

#### Scenario: 刷新间隔自定义
- **WHEN** 用户修改刷新间隔配置（如 1/3/6/12/24 小时）
- **THEN** 系统停止旧定时任务，按新间隔重新注册

### Requirement: 订阅变更感知（新增订阅立即处理）
系统 SHALL 在每次刷新时检测新增订阅，立即获取其上映日期并加入历史记录/UI。

#### Scenario: 检测新增订阅
- **WHEN** 系统执行刷新任务
- **THEN** 系统对比当前订阅列表与上次刷新的订阅列表（通过 `_known_subscriptions` 记录）
- **AND** 识别出新增的订阅（之前未记录过的 `tmdbid` 或 `doubanid`）

#### Scenario: 新增订阅立即获取上映日期
- **WHEN** 检测到新增订阅
- **THEN** 系统立即调用三级回退（TMDB → 豆瓣 → Bing）获取上映日期
- **AND** 将结果添加到历史记录（`_reminder_history`）
- **AND** 若获取到精确日期，加入 `_release_date_cache` 并锁定
- **AND** 插件 UI（`get_page`）中立即展示新增的订阅记录

#### Scenario: 更新已知订阅列表
- **WHEN** 刷新完成
- **THEN** 系统更新 `_known_subscriptions` 为当前所有订阅的 ID 集合
- **AND** 持久化保存

### Requirement: 订阅数据获取
系统 SHALL 查询 MoviePilot 订阅系统中所有已添加的订阅，获取每个订阅的基本信息和上映日期。

#### Scenario: 获取所有订阅
- **WHEN** 系统执行刷新或提醒任务
- **THEN** 系统通过 `SubscribeOper().list()` 获取所有活跃订阅
- **AND** 提取每个订阅的 `tmdbid`、`doubanid`、`name`（标题）、`year`（年份）、`type`（媒体类型）等字段

#### Scenario: 获取上映日期 - TMDB 优先
- **WHEN** 订阅有 `tmdbid`
- **THEN** 系统通过 MediaChain 或 TMDB API 直接查询该 TMDB ID 的详情
- **AND** 提取 `first_air_date`（电视剧）或 `release_date`（电影）作为上映日期
- **AND** 提取 `poster_path` 用于通知海报

#### Scenario: 获取上映日期 - 豆瓣回退
- **WHEN** 订阅有 `doubanid` 但无 TMDB ID 或 TMDB 查询无上映日期
- **THEN** 系统抓取豆瓣详情页 `https://movie.douban.com/subject/{douban_id}/`
- **AND** 从 HTML 中提取"首播"或"上映日期"字段
- **AND** 正则匹配日期格式（YYYY-MM-DD）

#### Scenario: 获取上映日期 - 浏览器搜索最后手段
- **WHEN** TMDB 和豆瓣均无法获取上映日期
- **THEN** 系统通过 Bing 搜索 `"{标题} 定档时间"` 或 `"{标题} 播出时间"`
- **AND** 从搜索结果摘要中提取日期信息
- **AND** 若仍未获取到，标记为"日期未知"，下次刷新继续尝试

### Requirement: 每周上映提醒通知
系统 SHALL 在用户配置的每周固定时间，发送即将上映的订阅汇总通知。**下周无上映则不发送通知。**

#### Scenario: 每周汇总通知
- **WHEN** 到达用户配置的每周提醒时间（如：每周五 20:00）
- **THEN** 系统：
  1. 从缓存读取所有订阅的上映日期
  2. 筛选上映日期在"未来 N 天内"的条目（N 由用户配置，默认 7 天）
  3. 按上映日期升序排列
  4. 若有符合条件的条目 → 发送汇总通知
  5. 若无符合条件的条目 → **静默跳过，不发送任何通知**

#### Scenario: 通知格式
- **WHEN** 系统发送每周汇总通知
- **THEN** 通知格式如下：
  ```
  📺 上映提醒（{开始日期} ~ {结束日期}）
  
  共 {N} 部订阅影视即将上映：
  
  🎞 {标题} ({年份})
  📅 上映日期：{YYYY-MM-DD}
  🔗 链接
  
  ...
  ```
- **AND** 通知包含 TMDB 海报图片（有则显示）
- **AND** 链接优先使用豆瓣链接（`douban_url`），其次使用 TMDB 链接

#### Scenario: 下周无上映
- **WHEN** 未来 N 天内没有订阅影视上映
- **THEN** 系统不发送任何通知（静默跳过）
- **AND** 记录日志：`下周无订阅影视上映，跳过通知`

### Requirement: 开播前24小时提醒（可选）
系统 SHALL 支持在订阅影视开播前 24 小时发送单独提醒通知。

#### Scenario: 设置24小时提醒
- **WHEN** 用户开启"开播前24小时提醒"开关
- **AND** 刷新时检测到某订阅影视的上映日期精确到天（YYYY-MM-DD）
- **THEN** 系统计算开播前 24 小时的时间点
- **AND** 通过 APScheduler DateTrigger 注册一次性定时任务
- **AND** 任务触发时发送提醒通知：`⏰ {标题} 距开播还有24小时！`

#### Scenario: 提醒时间已过
- **WHEN** 计算出的提醒时间已晚于当前时间
- **THEN** 系统跳过提醒注册，不重复提醒

### Requirement: UI 配置表单（抄 doubansync 布局）
系统 SHALL 提供 Vuetify 表单，**布局完全参照 doubansync 的 `get_form()`**：VForm → VRow → VCol 的响应式结构（cols=12, md=4/6），在此基础上优化美观。

#### Scenario: 配置表单布局
- **WHEN** 用户打开插件配置页面
- **THEN** 显示以下配置项（参照 doubansync 的 VRow/VCol 布局）：

| 配置项 | 组件类型 | 默认值 | 说明 |
|--------|---------|--------|------|
| 启用插件 | VSwitch | false | 开关 |
| 发送通知 | VSwitch | true | 是否发送通知 |
| 立即运行一次 | VSwitch | false | 立即执行一次刷新 |
| 刷新间隔(小时) | VTextField(number) | 6 | 每隔几小时刷新日期未知的订阅 |
| 提醒提前天数 | VTextField(number) | 7 | 提前多少天提醒（默认7天=下周） |
| 提醒星期 | VSelect | "周五" | 每周几发送汇总提醒（周一~周日） |
| 提醒时间 | VTextField | "20:00" | HH:MM 格式 |
| 开播前24h提醒 | VSwitch | true | 是否开播前24小时单独提醒 |
| 清理历史记录 | VSwitch | false | 保存后清理所有提醒历史 |

### Requirement: 历史记录页面（抄 doubansync 的 get_page + 升级动效）
系统 SHALL 提供 `get_page()` 页面，**完全参照 doubansync 的 VCard 水平卡片布局**，展示所有已追踪的订阅及其上映日期。新增订阅经刷新后自动出现在 UI 中。

#### Scenario: 历史记录展示（VCard 水平卡片）
- **WHEN** 用户查看插件详情页面
- **THEN** 使用 `grid gap-3 grid-info-card` 布局（同 doubansync）
- **AND** 每条记录使用 VCard 水平卡片：
  - 左上角 `VDialogCloseBtn` 关闭按钮（可删除单条记录）
  - 水平布局 `d-flex justify-space-start flex-nowrap flex-row`：
    - 左侧：海报缩略图（`VImg`，height=120, width=80, aspect-ratio=2/3, cover, shadow ring-gray-500）
    - 右侧：标题（`VCardTitle`，可点击跳转链接）、上映日期（`VCardText`）、订阅来源（`VCardText`）、加入时间（`VCardText`）
- **AND** 卡片添加 hover 动效（轻微上浮+阴影加深，增强视觉反馈）

#### Scenario: 新增订阅自动展示
- **WHEN** 刷新检测到新增订阅并获取到上映日期
- **THEN** 该订阅立即出现在 `get_page()` 的历史记录列表中
- **AND** 按加入时间降序排列（最新加入的在前）

#### Scenario: 日期状态区分
- **WHEN** 用户查看历史记录
- **THEN** 已确认精确日期（YYYY-MM-DD）的条目显示具体日期（绿色标记）
- **AND** 仅有年月（YYYY-MM）的条目显示"预计 {年月}"（黄色标记）
- **AND** 日期未知的条目显示"日期待定"（灰色标记）

#### Scenario: 升级美观度
- **WHEN** 用户查看历史记录页面
- **THEN** 卡片添加 CSS transition 动效：hover 时 `transform: translateY(-2px)` + `box-shadow` 加深
- **AND** 海报图片添加 `border-radius` 圆角
- **AND** 整体配色与 doubansync 风格一致但更精致

#### Scenario: 历史记录为空
- **WHEN** 没有任何提醒记录
- **THEN** 页面显示"暂无数据"（同 doubansync 的 `text-center` 样式）

### Requirement: 性能与限流
系统 SHALL 控制 API 调用频率，避免 CPU 峰值和请求过载。

#### Scenario: API 调用限流
- **WHEN** 系统遍历订阅获取上映日期
- **THEN** 每个订阅之间间隔 0.5 秒（避免 TMDB/豆瓣 API 限流）
- **AND** 单次最多处理 50 条订阅（超出部分下次刷新再处理）
- **AND** 已有精确日期的订阅直接跳过，不消耗 API 配额

#### Scenario: 上映日期缓存
- **WHEN** 系统获取到某订阅的上映日期
- **THEN** 将日期缓存到 `_release_date_cache` 中
- **AND** 精确到日的日期永久锁定，不再刷新
- **AND** 仅有年月或未知的日期在下次刷新时继续查询

## 关于 doubansync 改造的可行性分析

**结论：不建议改造 `doubansync`，建议创建独立插件。**

原因：
1. **职责分离**：`doubansync` 的职责是"同步豆瓣想看 → 自动添加订阅"，属于订阅创建阶段；本需求是"监控已有订阅 → 上映前提醒"，属于订阅后续阶段。两个功能阶段不同，强行合并会导致插件职责混乱
2. **基础设施缺失**：`doubansync` 没有上映日期获取、定时提醒、通知汇总等基础设施，需要大量新增代码，相当于重写
3. **复用策略**：`doubanupcoming` 插件已有完善的 TMDB 匹配（`__try_tmdb_match`）、豆瓣详情抓取（`__fetch_douban_detail`）、Bing 搜索（`__fetch_dingdang_time`）等基础设施，新插件可以直接复用这些方法或参考其实现
4. **用户选择权**：独立插件让用户可以选择性启用"订阅提醒"功能，不影响已有的豆瓣同步流程
5. **UI 借鉴**：新插件的 UI（get_form 和 get_page）完全参照 doubansync 的成熟布局，保证风格一致性和用户体验

## 版本历史

### v1.0.0 (初始版本)
- 订阅上映日期查询（TMDB → 豆瓣 → Bing 三级回退）
- 智能刷新策略：精确日期锁定不再刷新，仅刷新日期未知的订阅
- 订阅变更感知：新增订阅立即获取日期并加入 UI
- 每日定时刷新（自定义小时间隔）
- 每周汇总提醒通知（下周无上映不发送通知）
- 开播前24小时单独提醒
- 可配置提醒时间和提前天数
- UI 全抄 doubansync（VCard 水平卡片 + grid 布局），hover 动效升级
- 上映日期缓存与限流机制