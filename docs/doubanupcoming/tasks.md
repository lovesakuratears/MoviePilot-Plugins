# Tasks

- [x] Task 1: 创建插件基础结构
  - [x] 创建 `plugins.v2/doubanupcoming/` 目录
  - [x] 创建 `__init__.py`，定义 `DoubanUpcoming` 类，继承 `_PluginBase`
  - [x] 设置插件元信息：`plugin_name`、`plugin_desc`、`plugin_icon`、`plugin_version`、`plugin_author`、`plugin_config_prefix`
  - [x] 创建 `package.v2.json`，包含插件名称、描述、标签、版本历史
  - [x] 实现 `init_plugin`、`get_state`、`stop_service` 基础生命周期方法
  - [x] 实现 `__save_config` 持久化所有配置字段到数据库

- [x] Task 2: 实现配置表单 UI (`get_form`)
  - [x] 实现 Vuetify 表单：启用开关、数据源多选（即将上映/实时热门）、地区多选（中国大陆/海外）、推送数量输入、剔除短剧开关、排序方式选择、推送时间输入、清除历史开关、豆瓣UID、豆瓣想看开关
  - [x] 正确设置所有配置项默认值
  - [x] 使用 `VRow`/`VCol` 响应式布局

- [x] Task 3: 实现 RSSHub 数据获取与解析
  - [x] 实现 `__fetch_coming` 方法 + 豆瓣页面抓取补充数据
  - [x] 实现 `__fetch_hot` 方法
  - [x] 实现多数据源合并去重（按 `douban_id`）

- [x] Task 4: 实现定时推送服务
  - [x] 实现 `get_service()` 注册每日定时推送服务
  - [x] 实现 `__run_push` 方法

- [x] Task 5: 实现富媒体通知
  - [x] 实现 `__send_douban_notification` 方法，包含播放平台、四个交互按钮
  - [x] 通知格式：🎞 标题 / ✨ 评分 / 👾 主演 / 播出时间 / 播放平台 / 🔗 链接 / 🍿 简介
  - [x] 交互按钮：查看详情、搜预告、有兴趣、无兴趣
  - [x] 实现通知去重

- [x] Task 6: 实现交互按钮 API
  - [x] 实现 `/detail`、`/interest`、`/not_interest` API
  - [x] TMDB 匹配 > 豆瓣订阅 > 本地追踪 三级回退

- [x] Task 7: 实现去重与历史记录
  - [x] `_pushed_items` 持久化存储
  - [x] `get_page()` 历史记录页面（感兴趣展开/不感兴趣折叠）
  - [x] 清除历史记录改为开关（保存设置后执行，自动关闭）

- [x] Task 8: 实现本地追踪每日刷新
  - [x] 12小时间隔刷新 + 搜索定档时间 + 尝试豆瓣订阅

- [x] Task 9: 实现地区筛选与短剧过滤

- [x] Task 10: 插件重命名为"刷豆瓣助手"（v1.1.0）

- [x] Task 11: 豆瓣想看功能
  - [x] 豆瓣UID输入 + 豆瓣想看开关
  - [x] `__fetch_douban_wish` + `__process_douban_wish`
  - [x] get_service() 注册豆瓣想看刷新服务

- [x] Task 12: 豆瓣页面抓取补充数据
  - [x] 实现 `__fetch_douban_detail` 抓取豆瓣详情页
  - [x] 提取海报、评分、集数、单集片长、首播日期、季数、简介
  - [x] 在 `__fetch_coming` 中调用补充数据

- [x] Task 13: 豆瓣订阅实现
  - [x] 实现 `__try_douban_subscribe` 三级回退策略
  - [x] Subscribe.add_rss_subscribe > SubscribeChain.add > Subscribe.add_subscribe

- [x] Task 14: 开播前24小时提醒
  - [x] 实现 `__set_release_reminder` 通过 APScheduler DateTrigger 注册
  - [x] 实现 `__send_reminder_notification` 发送提醒通知
  - [x] 在 `__subscribe_tmdb` 中自动调用

- [x] Task 15: 播放平台搜索
  - [x] 实现 `__fetch_streaming_platform` 通过Bing搜索平台信息
  - [x] 实现 `__fetch_dingdang_time` 搜索定档时间
  - [x] 在通知中显示播放平台
  - [x] 在追踪刷新中搜索定档时间

- [x] Task 16: 搜预告按钮
  - [x] 通知中增加"搜预告"按钮，跳转抖音搜索

- [x] Task 17: 版本更新至 v1.2.0
  - [x] 更新 `plugin_version` 和 `package.v2.json` 版本历史

- [x] Task 18: 修复 v1.3.0 通知与控制
  - [x] 修复插件未启用时立即执行开关仍运行（`init_plugin` 中判断 `_enabled`）
  - [x] 修复豆瓣想看列表 RSS 地址（改用官方 feed `https://www.douban.com/feed/people/{uid}/interests`）
  - [x] 修复播放平台搜索误判（仅提取 Bing 搜索结果摘要文本匹配）
  - [x] 新增"停止"按钮：点击后清空 `_current_queue`、结束本轮推送
  - [x] 通知按钮改用 `buttons` + `callback_data` 格式
  - [x] `message_action` 兼容多种 callback_data 格式
  - [x] 播放平台搜索优先从 TMDB `watch/providers` 获取，无结果回退 Bing
  - [x] 版本更新至 v1.3.0

- [x] Task 19: 修复 v1.4.0 启用速度与订阅
  - [x] 修复 TMDB 导入路径（`from app.chain.tmdb import TmdbChain`）
  - [x] 修复订阅 `mtype` 必须为 `MediaType` 枚举（`'str' object has no attribute 'value'`）
  - [x] 新增"自动订阅想看"开关（默认关闭）
  - [x] 启用速度优化：仅对前 `push_count` 条抓取豆瓣详情
  - [x] 首次想看处理延迟 10 分钟，且仅当自动订阅开启时触发
  - [x] 修复播放平台行前置空格问题
  - [x] 播放平台搜索改用 `TmdbChain`
  - [x] 版本更新至 v1.4.0

- [x] Task 20: 重构 v1.5.0 UI 卡片式布局
  - [x] `get_page()` 改为 VListItem + 海报 + 评分卡片式布局
  - [x] 推送记录保存海报/评分/年份/类型等详情
  - [x] 优化空状态展示（大图标 + 提示文字）
  - [x] 版本更新至 v1.5.0

- [x] Task 21: 重构 v1.6.0 网格卡片布局与通知格式
  - [x] 修复清除历史记录开关：清除后调用 `__save_config()` 持久化重置
  - [x] 修复通知重复推送：`get_service` 中判断 `not self._run_immediately`
  - [x] `get_page()` 重构为 `VGrid` 网格卡片布局（xs 2 / sm 3 / md 4 / lg 5 / xl 6）
  - [x] 卡片显示预计播出日期（无则显示推送时间）
  - [x] 通知文本调整：评分行由播放平台代替（带 ✨ 前缀），保留简介
  - [x] 通知链接优先使用 TMDB 链接（无则豆瓣）
  - [x] 通知海报优先使用 TMDB 海报（无则豆瓣）
  - [x] 同步更新 `package.v2.json`（插件目录与根目录）与 `plugin_version`
  - [x] 版本更新至 v1.6.0