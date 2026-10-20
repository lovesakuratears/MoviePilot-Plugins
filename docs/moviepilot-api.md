# MoviePilot API 文档 (v0.1.0)

> 来源: https://api.movie-pilot.org/
> 抓取时间: 2026-07-28

---

## 1. login - 登录认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/login/access-token` | 获取token |
| GET | `/api/v1/login/wallpaper` | 登录页面电影海报 |
| GET | `/api/v1/login/wallpapers` | 登录页面电影海报列表 |

## 2. user - 用户管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/user/` | 所有用户 |
| PUT | `/api/v1/user/` | 更新用户 |
| POST | `/api/v1/user/` | 新增用户 |
| GET | `/api/v1/user/current` | 当前登录用户信息 |
| POST | `/api/v1/user/avatar/{user_id}` | 上传用户头像 |
| GET | `/api/v1/user/config/{key}` | 查询用户配置 |
| POST | `/api/v1/user/config/{key}` | 更新用户配置 |
| DELETE | `/api/v1/user/id/{user_id}` | 删除用户(按ID) |
| DELETE | `/api/v1/user/name/{user_name}` | 删除用户(按用户名) |
| GET | `/api/v1/user/{username}` | 用户详情 |

## 3. mfa - 双重验证

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/mfa/status/{username}` | 判断用户是否开启MFA |
| POST | `/api/v1/mfa/otp/generate` | 生成OTP验证URI |
| POST | `/api/v1/mfa/otp/verify` | 绑定并验证OTP |
| POST | `/api/v1/mfa/otp/disable` | 关闭OTP验证 |
| POST | `/api/v1/mfa/passkey/register/start` | 开始注册PassKey |
| POST | `/api/v1/mfa/passkey/register/finish` | 完成注册PassKey |
| POST | `/api/v1/mfa/passkey/authenticate/start` | 开始PassKey认证 |
| POST | `/api/v1/mfa/passkey/authenticate/finish` | 完成PassKey认证 |
| GET | `/api/v1/mfa/passkey/list` | 获取PassKey列表 |
| POST | `/api/v1/mfa/passkey/delete` | 删除PassKey |
| POST | `/api/v1/mfa/passkey/verify` | PassKey二次验证 |

## 4. site - 站点管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/site/` | 所有站点 |
| PUT | `/api/v1/site/` | 更新站点 |
| POST | `/api/v1/site/` | 新增站点 |
| GET | `/api/v1/site/cookiecloud` | CookieCloud同步 |
| GET | `/api/v1/site/reset` | 重置站点 |
| POST | `/api/v1/site/priorities` | 批量更新站点优先级 |
| GET | `/api/v1/site/cookie/{site_id}` | 更新站点Cookie&UA |
| POST | `/api/v1/site/userdata/{site_id}` | 更新站点用户数据 |
| GET | `/api/v1/site/userdata/{site_id}` | 查询某站点用户数据 |
| GET | `/api/v1/site/userdata/latest` | 查询所有站点最新用户数据 |
| GET | `/api/v1/site/test/{site_id}` | 连接测试 |
| GET | `/api/v1/site/icon/{site_id}` | 站点图标 |
| GET | `/api/v1/site/category/{site_id}` | 站点分类 |
| GET | `/api/v1/site/resource/{site_id}` | 站点资源 |
| GET | `/api/v1/site/domain/{site_url}` | 站点详情 |
| GET | `/api/v1/site/statistic/{site_url}` | 特定站点统计信息 |
| GET | `/api/v1/site/statistic` | 所有站点统计信息 |
| GET | `/api/v1/site/rss` | 所有订阅站点 |
| GET | `/api/v1/site/auth` | 查询认证站点 |
| POST | `/api/v1/site/auth` | 用户站点认证 |
| GET | `/api/v1/site/mapping` | 获取站点域名到名称的映射 |
| GET | `/api/v1/site/supporting` | 获取支持的站点列表 |
| GET | `/api/v1/site/{site_id}` | 站点详情 |
| DELETE | `/api/v1/site/{site_id}` | 删除站点 |

## 5. message - 消息

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/message/` | 接收用户消息 |
| GET | `/api/v1/message/` | 回调请求验证 |
| POST | `/api/v1/message/web` | 接收WEB消息 |
| GET | `/api/v1/message/web` | 获取WEB消息 |
| POST | `/api/v1/message/webpush/subscribe` | 客户端webpush通知订阅 |
| POST | `/api/v1/message/webpush/send` | 发送webpush通知 |

## 6. webhook - Webhook

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/webhook/` | Webhook消息响应 |
| POST | `/api/v1/webhook/` | Webhook消息响应 |

## 7. subscribe - 订阅管理 ⭐

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/subscribe/` | 查询所有订阅 |
| PUT | `/api/v1/subscribe/` | 更新订阅 |
| POST | `/api/v1/subscribe/` | 新增订阅 |
| GET | `/api/v1/subscribe/list` | 查询所有订阅（API_TOKEN） |
| PUT | `/api/v1/subscribe/status/{subid}` | 更新订阅状态 |
| GET | `/api/v1/subscribe/media/{mediaid}` | 查询订阅（按mediaid） |
| DELETE | `/api/v1/subscribe/media/{mediaid}` | 删除订阅（按mediaid） |
| GET | `/api/v1/subscribe/refresh` | 刷新订阅 |
| GET | `/api/v1/subscribe/reset/{subid}` | 重置订阅 |
| GET | `/api/v1/subscribe/check` | 刷新订阅TMDB信息 |
| GET | `/api/v1/subscribe/search` | 搜索所有订阅 |
| GET | `/api/v1/subscribe/search/{subscribe_id}` | 搜索订阅 |
| POST | `/api/v1/subscribe/seerr` | OverSeerr/JellySeerr通知订阅 |
| GET | `/api/v1/subscribe/history/{mtype}` | 查询订阅历史 |
| DELETE | `/api/v1/subscribe/history/{history_id}` | 删除订阅历史 |
| GET | `/api/v1/subscribe/popular` | 热门订阅（基于用户共享数据） |
| GET | `/api/v1/subscribe/user/{username}` | 用户订阅 |
| GET | `/api/v1/subscribe/files/{subscribe_id}` | 订阅相关文件信息 |
| POST | `/api/v1/subscribe/share` | 分享订阅 |
| DELETE | `/api/v1/subscribe/share/{share_id}` | 删除分享 |
| POST | `/api/v1/subscribe/fork` | 复用订阅 |
| GET | `/api/v1/subscribe/follow` | 查询已Follow的订阅分享人 |
| POST | `/api/v1/subscribe/follow` | Follow订阅分享人 |
| DELETE | `/api/v1/subscribe/follow` | 取消Follow订阅分享人 |
| GET | `/api/v1/subscribe/shares` | 查询分享的订阅 |
| GET | `/api/v1/subscribe/share/statistics` | 查询订阅分享统计 |
| GET | `/api/v1/subscribe/{subscribe_id}` | 订阅详情 |
| DELETE | `/api/v1/subscribe/{subscribe_id}` | 删除订阅 |

## 8. media - 媒体识别 ⭐

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/media/recognize` | 识别媒体信息（种子） |
| GET | `/api/v1/media/recognize2` | 识别种子媒体信息（API_TOKEN） |
| GET | `/api/v1/media/recognize_file` | 识别媒体信息（文件） |
| GET | `/api/v1/media/recognize_file2` | 识别文件媒体信息（API_TOKEN） |
| GET | `/api/v1/media/search` | 搜索媒体/人物信息 |
| POST | `/api/v1/media/scrape/{storage}` | 刮削媒体信息 |
| GET | `/api/v1/media/category/config` | 获取分类策略配置 |
| POST | `/api/v1/media/category/config` | 保存分类策略配置 |
| GET | `/api/v1/media/category` | 查询自动分类配置 |
| GET | `/api/v1/media/group/seasons/{episode_group}` | 查询剧集组季信息 |
| GET | `/api/v1/media/groups/{tmdbid}` | 查询媒体剧集组 |
| GET | `/api/v1/media/seasons` | 查询媒体季信息 |
| GET | `/api/v1/media/{mediaid}` | 查询媒体详情 |

## 9. search - 资源搜索 ⭐

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/search/last` | 查询搜索结果 |
| GET | `/api/v1/search/last/context` | 查询上次搜索上下文 |
| GET | `/api/v1/search/media/{mediaid}/stream` | 渐进式精确搜索资源 |
| GET | `/api/v1/search/media/{mediaid}` | 精确搜索资源 |
| GET | `/api/v1/search/title/stream` | 渐进式模糊搜索资源 |
| GET | `/api/v1/search/title` | 模糊搜索资源 |
| POST | `/api/v1/search/recommend` | AI推荐资源 |

## 10. douban - 豆瓣 ⭐⭐

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/douban/person/{person_id}` | 人物详情 |
| GET | `/api/v1/douban/person/credits/{person_id}` | 人物参演作品 |
| GET | `/api/v1/douban/credits/{doubanid}/{type_name}` | 豆瓣演员阵容 |
| GET | `/api/v1/douban/recommend/{doubanid}/{type_name}` | 豆瓣推荐电影/电视剧 |
| GET | `/api/v1/douban/{doubanid}` | 查询豆瓣详情 |

## 11. tmdb - TMDB ⭐⭐

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/tmdb/seasons/{tmdbid}` | TMDB所有季 |
| GET | `/api/v1/tmdb/similar/{tmdbid}/{type_name}` | 类似电影/电视剧 |
| GET | `/api/v1/tmdb/recommend/{tmdbid}/{type_name}` | 推荐电影/电视剧 |
| GET | `/api/v1/tmdb/collection/{collection_id}` | 系列合集详情 |
| GET | `/api/v1/tmdb/credits/{tmdbid}/{type_name}` | 演员阵容 |
| GET | `/api/v1/tmdb/person/{person_id}` | 人物详情 |
| GET | `/api/v1/tmdb/person/credits/{person_id}` | 人物参演作品 |
| GET | `/api/v1/tmdb/{tmdbid}/{season}` | TMDB季所有集 |

## 12. history - 历史记录

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/history/download` | 查询下载历史记录 |
| DELETE | `/api/v1/history/download` | 删除下载历史记录 |
| GET | `/api/v1/history/transfer` | 查询整理记录 |
| DELETE | `/api/v1/history/transfer` | 删除整理记录 |
| POST | `/api/v1/history/transfer/{history_id}/ai-redo` | 智能助手重新整理 |
| POST | `/api/v1/history/transfer/ai-redo` | 智能助手批量重新整理 |
| GET | `/api/v1/history/empty/transfer` | 清空整理记录 |

## 13. system - 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/system/img/{proxy}` | 图片代理 |
| GET | `/api/v1/system/cache/image` | 图片缓存 |
| GET | `/api/v1/system/global` | 查询非敏感系统设置 |
| GET | `/api/v1/system/global/user` | 查询用户相关系统设置 |
| GET | `/api/v1/system/env` | 查询系统配置 |
| POST | `/api/v1/system/env` | 更新系统配置 |
| GET | `/api/v1/system/usage/statistic` | 查询安装版本统计报表 |
| GET | `/api/v1/system/progress/{process_type}` | 实时进度 |
| GET | `/api/v1/system/setting/{key}` | 查询系统设置 |
| POST | `/api/v1/system/setting/{key}` | 更新系统设置 |
| GET | `/api/v1/system/message` | 实时消息 |
| GET | `/api/v1/system/logging` | 实时日志 |
| GET | `/api/v1/system/versions` | 查询Github所有Release版本 |
| GET | `/api/v1/system/ruletest` | 过滤规则测试 |
| GET | `/api/v1/system/nettest/targets` | 获取网络测试目标 |
| GET | `/api/v1/system/nettest` | 测试网络连通性 |
| GET | `/api/v1/system/modulelist` | 查询已加载的模块ID列表 |
| GET | `/api/v1/system/moduletest/{moduleid}` | 模块可用性测试 |
| GET | `/api/v1/system/restart` | 重启系统 |
| POST | `/api/v1/system/upgrade` | 升级并重启系统 |
| GET | `/api/v1/system/runscheduler` | 运行服务 |
| GET | `/api/v1/system/runscheduler2` | 运行服务（API_TOKEN） |

## 14. notification - 通知

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/notification/wechatclawbot/status` | 查询微信ClawBot登录状态 |
| POST | `/api/v1/notification/wechatclawbot/refresh` | 刷新微信ClawBot二维码 |
| POST | `/api/v1/notification/wechatclawbot/logout` | 退出微信ClawBot登录 |
| GET | `/api/v1/notification/wechatclawbot/test` | 测试微信ClawBot连通性 |
| POST | `/api/v1/notification/wechatclawbot/migrate` | 迁移微信ClawBot登录缓存 |

## 15. llm - 大语言模型

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/llm/models` | 获取LLM模型列表 |
| GET | `/api/v1/llm/providers` | 获取LLM提供商目录 |
| POST | `/api/v1/llm/provider-auth/start` | 启动LLM提供商授权 |
| GET | `/api/v1/llm/provider-auth/{session_id}` | 获取LLM提供商授权会话状态 |
| POST | `/api/v1/llm/provider-auth/{session_id}/poll` | 轮询LLM提供商授权会话 |
| DELETE | `/api/v1/llm/provider-auth/{provider_id}` | 断开LLM提供商授权 |
| GET | `/api/v1/llm/provider-auth/callback/{provider_id}` | LLM提供商OAuth回调 |
| POST | `/api/v1/llm/test` | 测试LLM调用 |

## 16. plugin - 插件管理 ⭐

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/plugin/` | 所有插件 |
| GET | `/api/v1/plugin/installed` | 已安装插件 |
| GET | `/api/v1/plugin/statistic` | 插件安装统计 |
| GET | `/api/v1/plugin/reload/{plugin_id}` | 重新加载插件 |
| GET | `/api/v1/plugin/install/{plugin_id}` | 安装插件 |
| GET | `/api/v1/plugin/remotes` | 获取插件联邦组件列表 |
| GET | `/api/v1/plugin/sidebar_nav` | 获取插件侧栏导航项 |
| GET | `/api/v1/plugin/form/{plugin_id}` | 获取插件表单页面 |
| GET | `/api/v1/plugin/page/{plugin_id}` | 获取插件数据页面 |
| GET | `/api/v1/plugin/dashboard/meta` | 获取所有插件仪表板元信息 |
| GET | `/api/v1/plugin/dashboard/{plugin_id}/{key}` | 获取插件仪表板配置 |
| GET | `/api/v1/plugin/dashboard/{plugin_id}` | 获取插件仪表板配置 |
| GET | `/api/v1/plugin/reset/{plugin_id}` | 重置插件配置及数据 |
| GET | `/api/v1/plugin/file/{plugin_id}/{filepath}` | 获取插件静态文件 |
| GET | `/api/v1/plugin/folders` | 获取插件文件夹配置 |
| POST | `/api/v1/plugin/folders` | 保存插件文件夹配置 |
| POST | `/api/v1/plugin/folders/{folder_name}` | 创建插件文件夹 |
| DELETE | `/api/v1/plugin/folders/{folder_name}` | 删除插件文件夹 |
| PUT | `/api/v1/plugin/folders/{folder_name}/plugins` | 更新文件夹中的插件 |
| POST | `/api/v1/plugin/clone/{plugin_id}` | 创建插件分身 |
| GET | `/api/v1/plugin/{plugin_id}` | 获取插件配置 |
| PUT | `/api/v1/plugin/{plugin_id}` | 更新插件配置 |
| DELETE | `/api/v1/plugin/{plugin_id}` | 卸载插件 |

## 17. download - 下载管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/download/` | 正在下载 |
| POST | `/api/v1/download/` | 添加下载（含媒体信息） |
| POST | `/api/v1/download/add` | 添加下载（不含媒体信息） |
| GET | `/api/v1/download/start/{hashString}` | 开始任务 |
| GET | `/api/v1/download/stop/{hashString}` | 暂停任务 |
| GET | `/api/v1/download/clients` | 查询可用下载器 |
| GET | `/api/v1/download/paths` | 查询可用下载路径 |
| DELETE | `/api/v1/download/{hashString}` | 删除下载任务 |

## 18. dashboard - 仪表板

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/dashboard/statistic` | 媒体数量统计 |
| GET | `/api/v1/dashboard/statistic2` | 媒体数量统计（API_TOKEN） |
| GET | `/api/v1/dashboard/storage` | 本地存储空间 |
| GET | `/api/v1/dashboard/storage2` | 本地存储空间（API_TOKEN） |
| GET | `/api/v1/dashboard/processes` | 进程信息 |
| GET | `/api/v1/dashboard/downloader` | 下载器信息 |
| GET | `/api/v1/dashboard/downloader2` | 下载器信息（API_TOKEN） |
| GET | `/api/v1/dashboard/schedule` | 后台服务 |
| GET | `/api/v1/dashboard/schedule2` | 后台服务（API_TOKEN） |
| GET | `/api/v1/dashboard/transfer` | 文件整理统计 |
| GET | `/api/v1/dashboard/cpu` | 获取当前CPU使用率 |
| GET | `/api/v1/dashboard/cpu2` | 获取当前CPU使用率（API_TOKEN） |
| GET | `/api/v1/dashboard/memory` | 获取当前内存使用量和使用率 |
| GET | `/api/v1/dashboard/memory2` | 获取当前内存使用量和使用率（API_TOKEN） |
| GET | `/api/v1/dashboard/network` | 获取当前网络流量 |
| GET | `/api/v1/dashboard/network2` | 获取当前网络流量（API_TOKEN） |

## 19. storage - 存储管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/storage/qrcode/{name}` | 生成二维码内容 |
| GET | `/api/v1/storage/auth_url/{name}` | 获取OAuth2授权URL |
| GET | `/api/v1/storage/check/{name}` | 二维码登录确认 |
| POST | `/api/v1/storage/save/{name}` | 保存存储配置 |
| GET | `/api/v1/storage/reset/{name}` | 重置存储配置 |
| POST | `/api/v1/storage/list` | 所有目录和文件 |
| POST | `/api/v1/storage/mkdir` | 创建目录 |
| POST | `/api/v1/storage/delete` | 删除文件或目录 |
| POST | `/api/v1/storage/download` | 下载文件 |
| POST | `/api/v1/storage/image` | 预览图片 |
| POST | `/api/v1/storage/rename` | 重命名文件或目录 |
| GET | `/api/v1/storage/usage/{name}` | 存储空间信息 |
| GET | `/api/v1/storage/transtype/{name}` | 支持的整理方式获取 |

## 20. transfer - 文件整理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/transfer/name` | 查询整理后的名称 |
| GET | `/api/v1/transfer/queue` | 查询整理队列 |
| DELETE | `/api/v1/transfer/queue` | 从整理队列中删除任务 |
| POST | `/api/v1/transfer/manual` | 手动转移 |
| POST | `/api/v1/transfer/episode-format/recommend` | 推荐集数定位模板 |
| GET | `/api/v1/transfer/now` | 立即执行下载器文件整理 |

## 21. mediaserver - 媒体服务器

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/mediaserver/play/{itemid}` | 在线播放 |
| GET | `/api/v1/mediaserver/exists` | 查询本地是否存在（数据库） |
| POST | `/api/v1/mediaserver/exists_remote` | 查询已存在的剧集信息（媒体服务器） |
| POST | `/api/v1/mediaserver/notexists` | 查询媒体库缺失信息（媒体服务器） |
| GET | `/api/v1/mediaserver/latest` | 最新入库条目 |
| GET | `/api/v1/mediaserver/playing` | 正在播放条目 |
| GET | `/api/v1/mediaserver/library` | 媒体库列表 |
| GET | `/api/v1/mediaserver/clients` | 查询可用媒体服务器 |

## 22. bangumi - Bangumi ⭐

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/bangumi/credits/{bangumiid}` | 查询Bangumi演职员表 |
| GET | `/api/v1/bangumi/recommend/{bangumiid}` | 查询Bangumi推荐 |
| GET | `/api/v1/bangumi/person/{person_id}` | 人物详情 |
| GET | `/api/v1/bangumi/person/credits/{person_id}` | 人物参演作品 |
| GET | `/api/v1/bangumi/{bangumiid}` | 查询Bangumi详情 |

## 23. discover - 探索发现 ⭐⭐

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/discover/source` | 获取探索数据源 |
| GET | `/api/v1/discover/bangumi` | 探索Bangumi |
| GET | `/api/v1/discover/douban_movies` | 探索豆瓣电影 |
| GET | `/api/v1/discover/douban_tvs` | 探索豆瓣剧集 |
| GET | `/api/v1/discover/tmdb_movies` | 探索TMDB电影 |
| GET | `/api/v1/discover/tmdb_tvs` | 探索TMDB剧集 |

## 24. recommend - 推荐 ⭐⭐

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/recommend/source` | 获取推荐数据源 |
| GET | `/api/v1/recommend/bangumi_calendar` | Bangumi每日放送 |
| GET | `/api/v1/recommend/douban_showing` | 豆瓣正在热映 |
| GET | `/api/v1/recommend/douban_movies` | 豆瓣电影 |
| GET | `/api/v1/recommend/douban_tvs` | 豆瓣剧集 |
| GET | `/api/v1/recommend/douban_movie_top250` | 豆瓣电影TOP250 |
| GET | `/api/v1/recommend/douban_tv_weekly_chinese` | 豆瓣国产剧集周榜 |
| GET | `/api/v1/recommend/douban_tv_weekly_global` | 豆瓣全球剧集周榜 |
| GET | `/api/v1/recommend/douban_tv_animation` | 豆瓣动画剧集 |
| GET | `/api/v1/recommend/douban_movie_hot` | 豆瓣热门电影 |
| GET | `/api/v1/recommend/douban_tv_hot` | 豆瓣热门电视剧 |
| GET | `/api/v1/recommend/tmdb_movies` | TMDB电影 |
| GET | `/api/v1/recommend/tmdb_tvs` | TMDB剧集 |
| GET | `/api/v1/recommend/tmdb_trending` | TMDB流行趋势 |

## 25. workflow - 工作流

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/workflow/` | 所有工作流 |
| POST | `/api/v1/workflow/` | 创建工作流 |
| GET | `/api/v1/workflow/plugin/actions` | 查询插件动作 |
| GET | `/api/v1/workflow/actions` | 所有动作 |
| GET | `/api/v1/workflow/event_types` | 获取所有事件类型 |
| POST | `/api/v1/workflow/share` | 分享工作流 |
| DELETE | `/api/v1/workflow/share/{share_id}` | 删除分享 |
| POST | `/api/v1/workflow/fork` | 复用工作流 |
| GET | `/api/v1/workflow/shares` | 查询分享的工作流 |
| POST | `/api/v1/workflow/{workflow_id}/run` | 执行工作流 |
| POST | `/api/v1/workflow/{workflow_id}/start` | 启用工作流 |
| POST | `/api/v1/workflow/{workflow_id}/pause` | 停用工作流 |
| POST | `/api/v1/workflow/{workflow_id}/reset` | 重置工作流 |
| GET | `/api/v1/workflow/{workflow_id}` | 工作流详情 |
| PUT | `/api/v1/workflow/{workflow_id}` | 更新工作流 |
| DELETE | `/api/v1/workflow/{workflow_id}` | 删除工作流 |

## 26. torrent - 种子管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/torrent/cache` | 获取种子缓存 |
| DELETE | `/api/v1/torrent/cache` | 清理种子缓存 |
| DELETE | `/api/v1/torrent/cache/{domain}/{torrent_hash}` | 删除指定种子缓存 |
| POST | `/api/v1/torrent/cache/refresh` | 刷新种子缓存 |
| POST | `/api/v1/torrent/cache/reidentify/{domain}/{torrent_hash}` | 重新识别种子 |

## 27. mcp - MCP协议

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/mcp` | MCP JSON-RPC端点 |
| DELETE | `/api/v1/mcp` | 终止MCP会话 |
| GET | `/api/v1/mcp/tools` | 列出所有可用工具 |
| POST | `/api/v1/mcp/tools/call` | 调用工具 |
| GET | `/api/v1/mcp/tools/{tool_name}` | 获取工具详情 |
| GET | `/api/v1/mcp/tools/{tool_name}/schema` | 获取工具参数Schema |

## 28. openai - OpenAI兼容

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/openai/v1/models` | OpenAI兼容模型列表 |
| POST | `/api/v1/openai/v1/chat/completions` | OpenAI兼容聊天补全 |
| POST | `/api/v1/openai/v1/responses` | OpenAI兼容响应 |

## 29. anthropic - Anthropic兼容

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/anthropic/v1/messages` | Anthropic兼容消息 |

## 30. servarr - Servarr

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/servarr/` | (待补充) |