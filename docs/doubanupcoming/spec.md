# 刷豆瓣助手 - 规格说明

## Why
MoviePilot 缺少面向豆瓣影视的"一条龙"订阅推送功能。利用 RSSHub 豆瓣路由获取即将播出和热门影视数据，同时支持通过豆瓣 UID 获取用户"想看"列表并自动订阅未上映条目，省去手动打开豆瓣的过程。

## What Changes
- 新增 `DoubanUpcoming` 插件（插件名：刷豆瓣助手），基于 MoviePilot V2 框架
- 通过 RSSHub (`https://rsshub.ddsrem.com`) 获取豆瓣影视数据
- **榜单数据源**：即将上映 (`/douban/tv/coming`)、实时热门 (`/douban/list/tv_real_time_hotest`)
- **豆瓣想看**：通过豆瓣 UID 获取用户"想看"列表（豆瓣官方 feed `https://www.douban.com/feed/people/{uid}/interests`），仅对未上映条目自动订阅（需开启"自动订阅想看"开关），无法订阅则走本地追踪等待
- **"我想看"从榜单中剥离**，榜单数据源仅保留"即将上映"和"实时热门"
- 富媒体通知：图片（TMDB 海报优先）+ 标题年份 + 播放平台（代替评分行）+ 主演信息 + 播出时间 + TMDB 链接 + 简介 + 链接按钮（查看详情、搜预告）+ 交互按钮（有兴趣、无兴趣、停止）
- "有兴趣"按钮：TMDB 匹配订阅（优先）> 豆瓣订阅 > 本地追踪
- "无兴趣"按钮：跳过当前，推送下一条
- "停止"按钮：结束本轮推送，清空队列
- "查看详情"按钮：点击跳转豆瓣页面
- "搜预告"按钮：点击跳转抖音搜索《xxx》预告
- **开播前24小时提醒**：订阅成功后自动注册APScheduler定时任务，在开播前24小时发送提醒通知
- **播放平台搜索**：通过 TMDB `watch/providers` API 获取（优先），无结果回退 Bing 搜索
- **豆瓣页面抓取**：对即将播出前 N 条条目抓取豆瓣详情页，补充海报图片、评分、集数、单集片长、精确播出日期（仅对即将推送的条目抓取，减少启用时间）
- **豆瓣订阅**：通过 MoviePilot Subscribe API（SubscribeChain/add_subscribe）实现豆瓣数据源订阅
- Vuetify 表单 UI：数据源、地区、推送数量、短剧过滤、排序、推送时间、清除历史开关、豆瓣UID、豆瓣想看开关、自动订阅想看开关
- 已推送条目去重（跨天），历史记录页面以网格卡片布局展示（感兴趣展开/不感兴趣折叠）
- 定时推送 + 本地追踪条目每日刷新
- 修复 TMDB 订阅 mtype 必须是 `MediaType` 枚举而非字符串（解决 `'str' object has no attribute 'value'` 错误）
- 修复清除历史记录开关后自动重置默认状态（保存配置持久化）
- 修复立即执行与首次推送定时任务重复执行（避免通知一次性推送两条）
- 播放平台搜索改用 `TmdbChain` 而非 `TmdbHelper`

## Impact
- Affected specs: 无（新增插件）
- Affected code: `plugins.v2/doubanupcoming/__init__.py`, `plugins.v2/doubanupcoming/package.v2.json`, `package.v2.json`

## ADDED Requirements

### Requirement: 插件注册与生命周期
系统 SHALL 作为一个 MoviePilot V2 插件注册，名称为"刷豆瓣助手"，支持启用/禁用、配置持久化、APScheduler 定时服务调度。

#### Scenario: 插件启用
- **WHEN** 用户在配置中开启"启用插件"开关并保存
- **THEN** 插件注册每日定时推送服务（按配置的推送时间），以及本地追踪刷新服务
- **AND** 如果开启了"豆瓣想看"，注册豆瓣想看每 12 小时刷新服务
- **AND** 如果开启了"自动订阅想看"，注册延迟 10 分钟的首次想看处理任务

#### Scenario: 插件禁用
- **WHEN** 用户关闭"启用插件"开关
- **THEN** 插件停止所有定时服务，不再推送

#### Scenario: 配置持久化
- **WHEN** 用户修改任意配置项并保存
- **THEN** 配置通过 `__save_config()` 持久化到 MoviePilot 数据库，重启后恢复
- **AND** 清除历史记录开关执行后会被自动重置为 false（保存到持久化）

#### Scenario: 立即执行开关
- **WHEN** 用户开启"立即执行一次"开关并保存
- **THEN** 插件在 `init_plugin` 中立即执行一次推送，重置开关为 false 并保存
- **AND** `get_service` 中不再添加首次推送定时任务，避免重复执行

### Requirement: RSSHub 数据获取与解析（榜单）
系统 SHALL 通过 RSSHub 获取豆瓣影视榜单数据，支持两种数据源。

#### Scenario: 获取即将上映数据
- **WHEN** 用户选择数据源为"即将上映"
- **THEN** 系统请求 `https://rsshub.ddsrem.com/douban/tv/coming/{sortBy}/{count}`
  - `sortBy`: `hot`（热度）或 `time`（时间），由用户配置的排序方式决定
  - `count`: 由用户配置的推送数量决定（默认 10，最大 20）

#### Scenario: 获取实时热门数据
- **WHEN** 用户选择数据源为"实时热门"
- **THEN** 系统请求 `https://rsshub.ddsrem.com/douban/list/tv_real_time_hotest`

#### Scenario: RSS 条目解析
- **WHEN** 系统解析一条 RSS item
- **THEN** 提取以下字段：
  - `title`：影视标题
  - `douban_id`：从 `<link>` 中提取豆瓣 subject ID
  - `douban_url`：豆瓣详情页链接
  - `year`：从 category 解析年份
  - `region`：从 category 解析地区
  - `genres`：从 category 解析类型
  - `director`：从 category 解析导演
  - `actors`：从 category 解析演员
  - `rating`：评分
  - `image_url`：海报图片
  - `summary`：简介
  - `wish_count`：想看人数（即将上映路由有）

#### Scenario: 多数据源合并去重
- **WHEN** 用户同时选择多个榜单数据源
- **THEN** 系统分别请求各数据源，按 `douban_id` 去重合并，再按配置排序

#### Scenario: 详情抓取优化（减少启用时间）
- **WHEN** 系统从即将上映获取 20 条数据
- **THEN** 系统仅对前 `push_count` 条（即将推送的）抓取豆瓣详情页
- **AND** 其余条目仅保留 RSS 原始数据，不做详情请求
- **AND** 详情抓取失败不会阻塞主流程，记录警告日志后继续

### Requirement: 豆瓣想看（用户 Want-to-Watch）
系统 SHALL 通过豆瓣 UID 获取用户"想看"列表，仅对未上映条目自动处理（需开启"自动订阅想看"开关）。

#### Scenario: 获取豆瓣想看列表
- **WHEN** 用户填写了豆瓣 UID 且开启了"豆瓣想看"开关
- **THEN** 系统请求豆瓣官方 feed：`https://www.douban.com/feed/people/{uid}/interests`
- **AND** 解析条目，仅保留"想看"状态（"看过"/"在看"状态跳过）
- **AND** 从 title 中提取实际标题（`《xxx》`格式或"想看"后的文本）
- **AND** 提取 douban_id、image_url、summary、rating 等字段

#### Scenario: 自动订阅未上映条目（需开启开关）
- **WHEN** 获取到用户想看列表中的条目
- **AND** 开启了"自动订阅想看"开关
- **AND** 该条目尚未上映
- **THEN** 系统尝试 TMDB 匹配订阅（优先）
- **AND** 若 TMDB 匹配成功且有精确时间 → 添加订阅 + 日历
- **AND** 若 TMDB 匹配成功但无精确时间 → 保存到本地追踪
- **AND** 若 TMDB 匹配失败 → 豆瓣订阅（`SubscribeChain.add`）→ 失败则保存到本地追踪
- **AND** 记录到 `pushed_items` 中，interest=True

#### Scenario: 自动订阅开关关闭
- **WHEN** 用户关闭"自动订阅想看"开关
- **THEN** 系统仅获取想看列表，不进行任何订阅/追踪操作
- **AND** 仅记录到 `pushed_items` 中供用户参考

#### Scenario: 豆瓣想看开关关闭
- **WHEN** 用户关闭"豆瓣想看"开关
- **THEN** 系统不获取用户想看列表，仅处理榜单数据

### Requirement: 推送通知格式
系统 SHALL 以富媒体格式发送通知，格式严格如下：

```
[图片/海报：TMDB 海报优先（https://image.tmdb.org/t/p/w500/{poster_path}），无则使用豆瓣海报]

🎞 {标题} ({年份}) {季数信息}
✨ 播放平台：{平台名称}    ← 评分行由播放平台代替
👾 主演：{年份} / {地区} / {类型} / {导演} / {演员}
播出时间：{首播日期}({地区})首播 / 共{集数}集 / 单集片长{分钟}分钟
🔗 链接：{TMDB链接}    ← 优先使用 TMDB 链接（https://www.themoviedb.org/{tv|movie}/{id}），无则豆瓣链接

🍿 简介：
{简介内容}

[链接按钮] [查看详情(豆瓣)] [搜预告(抖音搜索)]
[交互按钮] [有兴趣] [无兴趣] [停止]
```

#### Scenario: 通知格式渲染
- **WHEN** 系统推送一条豆瓣影视信息
- **THEN** 使用 `post_message` 发送，mtype 为 `NotificationType.Plugin`
- **AND** 通知包含图片（TMDB 海报 URL 优先）、格式化文本
- **AND** `actions` 参数包含查看详情、搜预告两个链接按钮
- **AND** `buttons` 参数包含有兴趣、无兴趣、停止三个回调按钮

#### Scenario: 通知去重
- **WHEN** 同一条目需要再次通知
- **THEN** 跳过（参考已有 `_last_notify_title` 机制）

### Requirement: 交互按钮 - 查看详情
系统 SHALL 在用户点击"查看详情"后，跳转到豆瓣该影视页面。

### Requirement: 交互按钮 - 有兴趣
系统 SHALL 在用户点击"有兴趣"后，按优先级执行：TMDB 匹配订阅 > 豆瓣订阅 > 本地追踪。

#### Scenario: TMDB 匹配成功且有精确时间
- **WHEN** 用户点击"有兴趣"
- **AND** 系统通过标题+年份搜索 TMDB，匹配到条目
- **AND** 该 TMDB 条目有精确的首播/定档日期（如 2026-07-30）
- **THEN** 系统添加 TMDB 订阅（`mtype` 必须是 `MediaType.TV` 或 `MediaType.MOVIE` 枚举，而非字符串）
- **AND** 在 MoviePilot 日历中添加该影视
- **AND** 在开播前 24 小时发送提醒通知

#### Scenario: TMDB 匹配成功但无精确时间
- **WHEN** 用户点击"有兴趣"
- **AND** TMDB 匹配成功
- **AND** 但仅有年份或月份信息
- **THEN** 系统保存到本地追踪记录（`_tracking_items`）
- **AND** 每天固定时间刷新该记录，重新查询 TMDB，直到获得精确时间后自动订阅

#### Scenario: TMDB 匹配失败，尝试豆瓣订阅
- **WHEN** 用户点击"有兴趣"
- **AND** TMDB 搜索无匹配结果
- **THEN** 系统尝试通过 `SubscribeChain.add(source="douban")` 添加豆瓣订阅
- **AND** 若豆瓣订阅成功，记录为已订阅

#### Scenario: TMDB 和豆瓣订阅均失败
- **WHEN** 用户点击"有兴趣"
- **AND** TMDB 匹配失败且豆瓣订阅也失败
- **THEN** 系统保存到本地追踪记录（`_tracking_items`）
- **AND** 每天固定时间刷新，直到 TMDB 出现该条目可订阅

### Requirement: 交互按钮 - 无兴趣
系统 SHALL 在用户点击"无兴趣"后，跳过当前条目，立即推送下一条待推送条目。

### Requirement: 交互按钮 - 停止
系统 SHALL 在用户点击"停止"后，结束本轮推送，清空当前推送队列。

#### Scenario: 点击停止
- **WHEN** 用户点击"停止"
- **THEN** 系统清空 `_current_queue`
- **AND** 标记当前条目为已推送（interest=None）
- **AND** 后续条目不再推送
- **AND** 返回提示信息"已停止本轮推送"

### Requirement: 按钮回调兼容性
系统 SHALL 兼容多种 callback_data 格式，确保按钮点击能正常响应。

#### Scenario: callback_data 格式解析
- **WHEN** 用户点击按钮触发 MessageAction 事件
- **THEN** 系统尝试以下格式解析：
  1. `[PLUGIN]插件名|action|douban_id`（标准格式）
  2. `插件名|action|douban_id`（简写格式）
  3. `action|douban_id`（最简格式）
- **AND** 仅处理本插件的回调（plugin_id 匹配）
- **AND** 不匹配的回调直接返回，不影响其他插件

### Requirement: 去重机制
系统 SHALL 确保已推送过的条目不再重复推送。

#### Scenario: 跨天去重
- **WHEN** 系统在新一天获取数据后筛选待推送条目
- **THEN** 系统排除所有历史已推送的条目（`_pushed_items` 中记录，无论感兴趣与否）
- **AND** 从剩余未推送条目中按配置数量选取推送

#### Scenario: 每日推送流程
- **WHEN** 每日推送时间到达
- **THEN** 系统：
  1. 获取榜单数据源数据并合并去重
  2. 仅对前 push_count 条抓取豆瓣详情页（性能优化）
  3. 排除已推送的历史条目
  4. 应用地区筛选、短剧过滤
  5. 按配置排序
  6. 取前 N 条（配置的推送数量）逐条推送
  7. 如果开启了豆瓣想看，同步处理想看列表

### Requirement: UI 配置表单
系统 SHALL 提供 Vuetify 表单进行配置。

#### Scenario: 配置表单布局
- **WHEN** 用户打开插件配置页面
- **THEN** 显示以下配置项：

| 配置项 | 组件类型 | 默认值 | 说明 |
|--------|---------|--------|------|
| 启用插件 | VSwitch | false | 开关 |
| 数据来源（榜单） | VSelect(multiple) | ["即将上映"] | 即将上映 / 实时热门 |
| 豆瓣UID | VTextField | "" | 用于获取用户想看列表 |
| 豆瓣想看 | VSwitch | false | 开启后获取用户想看列表 |
| 自动订阅想看 | VSwitch | false | 开启后自动订阅想看列表中的未上映条目 |
| 地区筛选 | VSelect(multiple) | ["中国大陆", "海外"] | 中国大陆 / 海外 |
| 每轮推送条数 | VTextField(number) | 10 | 最大 20 |
| 剔除短剧 | VSwitch | false | 单集片长 ≤ 10 分钟 |
| 排序方式 | VSelect | "热度" | 热度 / 时间 |
| 每日推送时间 | VTextField(time) | "09:00" | HH:MM 格式 |
| 清除历史记录 | VSwitch | false | 开启后保存设置即清除所有历史记录，执行后自动关闭并保存 |
| 立即执行一次 | VSwitch | false | 开启后保存设置即触发首次推送，执行后自动关闭 |

### Requirement: 历史记录页面（网格卡片布局）
系统 SHALL 提供 `get_page()` 页面展示历史记录，参考官方豆瓣想看插件样式，使用网格卡片布局。

#### Scenario: 感兴趣记录展示（网格卡片）
- **WHEN** 用户查看历史记录页面
- **THEN** 显示所有"感兴趣"的记录，使用 `VGrid` 响应式网格布局
- **AND** xs 屏幕每行 2 列、sm 3 列、md 4 列、lg 5 列、xl 6 列
- **AND** 每张卡片包含：
  - 海报缩略图（`VImg`，aspect 1.4）
  - 标题（白色字体，海报底部覆盖）
  - 类型（白色半透明）
  - 时间（白色半透明，优先显示预计播出日期，否则显示推送时间）
  - 右上角关闭按钮
  - 底部"订阅"按钮（跳转豆瓣链接）

#### Scenario: 不感兴趣记录折叠
- **WHEN** 用户查看历史记录页面
- **THEN** "不感兴趣"的记录默认折叠在 `VExpansionPanel` 中
- **AND** 用户可点击展开查看
- **AND** 展开后也以网格卡片形式展示

#### Scenario: 历史记录为空
- **WHEN** 没有任何历史推送记录
- **THEN** 页面显示大图标 `mdi-movie-open` + "暂无推送记录" + 提示文字

### Requirement: 本地追踪刷新
系统 SHALL 每天定时刷新本地追踪记录。

#### Scenario: 每日刷新本地追踪
- **WHEN** 每天固定时间到达（每 12 小时间隔刷新）
- **THEN** 系统遍历 `_tracking_items` 中所有记录
- **AND** 对每条记录尝试 TMDB 搜索匹配
- **AND** 若匹配成功且有精确时间 → 自动订阅 + 日历提醒 + 从追踪列表移除
- **AND** 若匹配成功但无精确时间 → 保留，次日继续
- **AND** 若匹配失败 → 保留，次日继续

### Requirement: 开播前24小时提醒
系统 SHALL 在成功订阅后，自动注册开播前24小时提醒通知。

#### Scenario: 设置提醒
- **WHEN** TMDB订阅成功且开播日期精确到日（如 2026-07-30）
- **THEN** 系统计算开播前24小时的时间点
- **AND** 通过 APScheduler DateTrigger 注册一次性定时任务
- **AND** 任务触发时发送提醒通知："距开播还有24小时，记得准时观看！"

#### Scenario: 提醒时间已过
- **WHEN** 计算出的提醒时间已晚于当前时间
- **THEN** 系统跳过提醒注册，记录日志

### Requirement: 播放平台搜索
系统 SHALL 在通知中显示播放平台信息，优先从 TMDB `watch/providers` API 获取，无结果回退 Bing 搜索。

#### Scenario: 从 TMDB 获取播放平台
- **WHEN** TMDB 匹配成功
- **THEN** 系统请求 TMDB `watch/providers` API
- **AND** 解析返回结果，识别腾讯视频/爱奇艺/优酷/芒果TV/B站/Netflix等平台
- **AND** 将结果加入通知文本

#### Scenario: 从 Bing 搜索回退
- **WHEN** TMDB `watch/providers` 无结果
- **THEN** 系统搜索Bing："《xxx》哪个平台播出"
- **AND** 仅提取搜索结果摘要文本（`<p class="b_lineclamp...">`）进行关键词匹配
- **AND** 解析结果加入通知文本

#### Scenario: 平台未知
- **WHEN** Bing 搜索也未找到平台信息
- **THEN** 通知中不显示播放平台行

### Requirement: 豆瓣页面抓取补充数据
系统 SHALL 对即将上映条目抓取豆瓣详情页，补充RSS数据中缺失的字段。

#### Scenario: 抓取豆瓣详情页
- **WHEN** 系统从 RSSHub 获取到即将上映条目
- **AND** 该条目在前 push_count 条中（即即将推送）
- **THEN** 系统请求 `https://movie.douban.com/subject/{douban_id}/`
- **AND** 解析HTML提取：海报图片、评分、集数、单集片长、首播日期、季数、简介、类型、导演、主演
- **AND** 将提取的数据合并到条目信息中
- **AND** 图片提取使用多组正则匹配以适配豆瓣页面变化

#### Scenario: 抓取失败
- **WHEN** 豆瓣页面请求失败或解析异常
- **THEN** 系统记录警告日志，使用RSS中的原始数据继续推送
- **AND** 不影响其他条目的抓取和推送

### Requirement: 豆瓣订阅
系统 SHALL 通过 MoviePilot SubscribeChain 实现豆瓣数据源订阅。

#### Scenario: 豆瓣订阅
- **WHEN** TMDB匹配失败，尝试豆瓣订阅
- **THEN** 系统通过 `SubscribeChain().add(..., source="douban")` 添加订阅
- **AND** 失败则保存到本地追踪
- **AND** 记录为已订阅

#### Scenario: 豆瓣订阅成功
- **WHEN** 豆瓣订阅成功
- **THEN** 记录为已订阅
- **AND** 若豆瓣页面有精确播出日期，在MoviePilot日历中添加该影视
- **AND** 在开播前24小时发送提醒通知

### Requirement: 搜预告按钮
系统 SHALL 在通知中提供"搜预告"按钮，点击跳转抖音搜索预告片。

#### Scenario: 点击搜预告
- **WHEN** 用户点击"搜预告"按钮
- **THEN** 跳转到抖音搜索页面：`https://www.douyin.com/search/{标题}%20预告`
- **AND** 标题会移除括号内容（如年份）

## Resolved Questions
- [x] "豆瓣想看"数据源：使用豆瓣官方 feed `https://www.douban.com/feed/people/{uid}/interests`，比 RSSHub 更稳定
- [x] "即将上映"路由的 RSS 数据中缺少海报图片、评分、集数、单集片长、精确播出日期：已通过 `__fetch_douban_detail` 抓取豆瓣页面补充
- [x] 豆瓣订阅功能在 MoviePilot 中是否有现成 API：通过 `SubscribeChain().add(source="douban")` 实现
- [x] 通知中的交互按钮，MoviePilot 的通知系统是否支持按钮回调：支持，通过 `actions` 参数传递 `url` 实现链接按钮，`buttons` 参数传递 `callback_data` 实现回调按钮
- [x] 插件中是否需要显示"豆瓣"品牌图标：已设置 `plugin_icon = "douban.png"`，图标文件已下载到插件目录
- [x] TMDB 导入路径错误：使用 `from app.chain.tmdb import TmdbChain` 而非 `from app.utils.tmdb import TmdbHelper`
- [x] 订阅 mtype 错误（`'str' object has no attribute 'value'`）：`mtype` 必须是 `MediaType.TV` 或 `MediaType.MOVIE` 枚举
- [x] 启用时间过长：仅对前 push_count 条抓取详情，减少网络请求；想看首次处理延迟到 10 分钟
- [x] 通知按钮点击无反应：兼容多种 callback_data 格式
- [x] 通知一次性推送两条：立即执行时不再添加首次推送定时任务
- [x] 清除历史记录开关不恢复默认：清除后调用 `__save_config()` 持久化
- [x] UI 风格：使用网格卡片布局（VGrid + VCard），参考官方豆瓣想看插件
- [x] 通知格式：评分行由播放平台代替（带 ✨ 前缀），保留简介；链接优先使用 TMDB 链接，海报优先使用 TMDB 海报

## 版本历史

### v1.6.0 (2026-07-27)
- 修复清除历史记录后设置开关不恢复默认状态
- 修复通知一次性推送两条（立即执行与定时任务重复）
- 重构首页UI为网格卡片布局（参考官方豆瓣想看插件样式）
- 时间显示优先显示预计播出日期
- 通知格式调整：评分行由播放平台代替（带 ✨ 前缀），保留简介
- 通知链接优先使用 TMDB 链接（无则豆瓣）
- 通知海报优先使用 TMDB 海报（无则豆瓣）

### v1.5.0
- 重构UI界面为卡片式布局（VListItem+海报+评分）
- 推送记录保存海报/评分/年份/类型等详情
- 优化空状态展示

### v1.4.0
- 修复TMDB导入路径错误（改用TmdbChain）
- 修复订阅mtype应为MediaType枚举
- 修复通知按钮点击无反应
- 新增自动订阅想看开关（默认关闭）
- 优化启用速度（仅推送条目请求详情）

### v1.3.0
- 修复插件未启用时立即执行开关仍运行的问题
- 修复豆瓣想看列表RSS地址错误（改用官方feed）
- 修复播放平台搜索误判问题（优先TMDB获取）
- 新增停止按钮结束本轮推送
- 通知按钮改用buttons+callback_data格式支持回调

### v1.2.0
- 新增开播前24小时提醒
- 新增播放平台搜索（Bing）
- 新增豆瓣页面抓取补充海报/评分/集数/日期
- 新增豆瓣订阅（MoviePilot API）
- 新增通知搜预告按钮（跳转抖音）
- 清除历史记录改为开关
- 新增立即执行一次

### v1.1.0
- 插件重命名为"刷豆瓣助手"
- 新增豆瓣UID和豆瓣想看功能
- 榜单数据源精简为即将上映和实时热门

### v1.0.0
- 初始版本
- 支持RSSHub数据获取、富媒体通知推送、TMDB/豆瓣订阅、本地追踪
