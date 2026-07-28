# Tasks

- [x] Task 1: 创建插件基础结构
  - [x] 创建 `plugins.v2/subscriptionreminder/` 目录
  - [x] 创建 `__init__.py`，定义 `SubscriptionReminder` 类，继承 `_PluginBase`
  - [x] 设置插件元信息：`plugin_name`="订阅上映提醒"、`plugin_desc`="定时检查已订阅影视的上映日期，在即将播出前发送通知提醒"、`plugin_icon`="douban.png"、`plugin_version`="1.0.0"、`plugin_author`、`plugin_config_prefix`="subscriptionreminder_"
  - [x] 创建 `package.v2.json`，包含插件名称、描述、标签、版本历史
  - [x] 实现 `init_plugin`、`get_state`、`stop_service` 基础生命周期方法
  - [x] 实现 `__update_config` 持久化所有配置字段到数据库
  - [x] 在 `MoviePilot-Plugins/package.v2.json` 中注册插件

- [x] Task 2: 实现配置表单 UI（全抄 doubansync 的 get_form 布局）
  - [x] 参照 doubansync 的 `get_form()` 实现 Vuetify 表单：VForm → VRow(12, md=4/6) → VCol 响应式结构
  - [x] 第一行 VRow（md=4 × 3）：启用插件 VSwitch、发送通知 VSwitch、立即运行一次 VSwitch
  - [x] 第二行 VRow（md=6 × 2）：刷新间隔(小时) VTextField、提醒提前天数 VTextField
  - [x] 第三行 VRow（md=6 × 2）：提醒星期 VSelect（周一~周日）、提醒时间 VTextField(HH:MM)
  - [x] 第四行 VRow（md=4 × 2）：开播前24h提醒 VSwitch、清理历史记录 VSwitch
  - [x] 正确设置所有配置项默认值（enabled:False, notify:True, onlyonce:False, refresh_hours:6, days:7, weekday:"周五", push_time:"20:00", remind_24h:True, clear:False）

- [x] Task 3: 实现订阅数据获取与上映日期查询（三级回退 + 智能刷新）
  - [x] 实现 `__get_all_subscriptions` 方法：通过 `SubscribeOper().list()` 获取所有活跃订阅
  - [x] 实现 `__get_release_date_by_tmdb` 方法：通过 `tmdbid` 查询 TMDB API，提取 `first_air_date`/`release_date` 和 `poster_path`
  - [x] 实现 `__get_release_date_by_douban` 方法：通过 `doubanid` 抓取豆瓣页面，正则提取首播/上映日期
  - [x] 实现 `__get_release_date_by_bing` 方法：搜索 `"{标题} 定档时间"`，从搜索结果摘要提取日期
  - [x] 实现 `__get_release_date` 统一入口：TMDB 优先 → 豆瓣回退 → Bing 最后手段
  - [x] 实现 `_is_date_precise` 判断方法：检查日期是否为 YYYY-MM-DD 格式（精确到日）
  - [x] 实现上映日期缓存：`_release_date_cache`，精确日期永久锁定不刷新，非精确日期下次继续查询

- [x] Task 4: 实现订阅变更感知（新增订阅立即处理）
  - [x] 实现 `_known_subscriptions` 集合：记录上次刷新时已知的所有订阅 ID（tmdbid 或 doubanid）
  - [x] 在 `__run_refresh` 中对比当前订阅列表与 `_known_subscriptions`，识别新增订阅
  - [x] 新增订阅立即调用 `__get_release_date` 获取上映日期
  - [x] 将新增订阅结果加入 `_reminder_history`（历史记录）
  - [x] 刷新完成后更新 `_known_subscriptions` 并持久化

- [x] Task 5: 实现每日定时刷新服务（自定义间隔）
  - [x] 实现 `get_service()` 注册 IntervalTrigger 定时刷新服务（按配置的 `refresh_hours` 小时）
  - [x] 实现 `__run_refresh` 方法：
    - [x] 获取所有订阅，对比 `_known_subscriptions` 识别新增
    - [x] 遍历所有订阅，跳过已有精确日期（YYYY-MM-DD）的订阅
    - [x] 仅对日期未知/不精确的订阅调用 `__get_release_date`
    - [x] 新增订阅立即获取日期并加入历史记录
    - [x] 若发现新的精确日期，检查并注册 24h 提醒
  - [x] API 调用限流：每个订阅之间 0.5 秒间隔，单次最多 50 条
  - [x] 首次启用时延迟 1 分钟后执行首次刷新

- [x] Task 6: 实现每周定时汇总提醒服务（下周无上映不通知）
  - [x] 在 `get_service()` 中注册每周 CronTrigger 提醒服务（按配置的星期几+时间）
  - [x] 实现 `__run_weekly_reminder` 方法：
    - [x] 从缓存读取所有订阅的上映日期
    - [x] 筛选上映日期在"未来 N 天"内的条目
    - [x] 按上映日期升序排列
    - [x] 若有符合条件的条目 → 调用 `__send_weekly_notification` 发送汇总通知
    - [x] 若无符合条件的条目 → 静默跳过，记录日志，不发送通知
  - [x] 实现 `__send_weekly_notification` 方法：格式化通知文本（📺 + 标题 + 日期 + 链接），链接优先豆瓣其次 TMDB，包含海报图片

- [x] Task 7: 实现开播前24小时提醒
  - [x] 在 `__run_refresh` 中：若开启 `remind_24h`，对每个有精确日期（YYYY-MM-DD）且尚未注册提醒的订阅，调用 `__schedule_24h_reminder`
  - [x] 实现 `__schedule_24h_reminder` 方法：通过 APScheduler DateTrigger 注册一次性任务
  - [x] 实现 `__send_24h_reminder` 方法：发送 `⏰ {标题} 距开播还有24小时！` 通知
  - [x] 提醒时间已过时跳过，不重复注册（通过 `_reminded_subscriptions` 集合去重）

- [x] Task 8: 实现历史记录页面（抄 doubansync 的 get_page + 升级动效 + 日期状态区分）
  - [x] 参照 doubansync 的 `get_page()` 实现：`grid gap-3 grid-info-card` 布局
  - [x] 空数据时显示"暂无数据"（`text-center`）
  - [x] 数据按加入时间降序排序
  - [x] 每条记录使用 VCard 水平卡片：
    - [x] VDialogCloseBtn（删除单条记录）
    - [x] 水平布局 d-flex justify-space-start flex-nowrap flex-row
    - [x] 左侧：VImg（height=120, width=80, aspect-ratio=2/3, cover, shadow ring-gray-500）
    - [x] 右侧：VCardTitle（可点击跳转链接）、VCardText（上映日期 - 精确日期绿色/预计日期黄色/未知灰色）、VCardText（订阅来源）、VCardText（加入时间）
  - [x] **升级动效**：卡片添加 CSS transition（hover: transform translateY(-2px) + box-shadow 加深）
  - [x] 海报图片添加 border-radius 圆角

- [x] Task 9: 实现远程命令与 API
  - [x] 实现 `get_command()` 远程命令 `/subscription_reminder`（触发刷新检查）
  - [x] 实现 `get_api()` 暴露 `/delete_history` 和 `/clear_history` API
  - [x] 实现"立即运行一次"开关：`init_plugin` 中检测并立即触发刷新
  - [x] 实现"清理历史记录"开关：保存后清空历史数据、缓存、已知订阅列表并重置开关

# Task Dependencies
- [Task 2] 可与 [Task 3] 并行
- [Task 4] 依赖 [Task 3]
- [Task 5] 依赖 [Task 3], [Task 4]
- [Task 6] 依赖 [Task 5]
- [Task 7] 依赖 [Task 5]
- [Task 8] 依赖 [Task 5]
- [Task 9] 依赖 [Task 5], [Task 6]