import json
import re
import time as _time
from datetime import datetime, timedelta
from typing import Optional, Any, List, Dict, Tuple

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app import schemas
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.db.subscribe_oper import SubscribeOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType, MediaType


class SubscriptionReminder(_PluginBase):
    # 插件名称
    plugin_name = "订阅上映提醒"
    # 插件描述
    plugin_desc = "定时检查已订阅影视的上映日期，在即将播出前发送通知提醒。"
    # 插件图标
    plugin_icon = "douban.png"
    # 插件版本
    plugin_version = "1.0.2"
    # 插件作者
    plugin_author = "lovesakuratears"
    # 作者主页
    author_url = "https://github.com/lovesakuratears/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "subscriptionreminder_"
    # 加载顺序
    plugin_order = 21
    # 可使用的用户级别
    auth_level = 1

    # 私有变量
    _scheduler: Optional[BackgroundScheduler] = None

    # 配置属性
    _enabled: bool = False
    _notify: bool = True
    _onlyonce: bool = False
    _refresh_hours: int = 6
    _days: int = 7
    _weekday: str = "周五"
    _push_time: str = "20:00"
    _remind_24h: bool = True
    _clear: bool = False
    _clearflag: bool = False

    # 状态数据
    _release_date_cache: dict = {}
    _known_subscriptions: set = set()
    _reminder_history: List[dict] = []
    _reminded_subscriptions: set = set()

    # 星期映射
    WEEKDAY_MAP = {
        "周一": "mon", "周二": "tue", "周三": "wed", "周四": "thu",
        "周五": "fri", "周六": "sat", "周日": "sun"
    }

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled", False)
            self._notify = config.get("notify", True)
            self._onlyonce = config.get("onlyonce", False)
            self._refresh_hours = int(config.get("refresh_hours", 6))
            self._days = int(config.get("days", 7))
            self._weekday = config.get("weekday", "周五")
            self._push_time = config.get("push_time", "20:00")
            self._remind_24h = config.get("remind_24h", True)
            self._clear = config.get("clear", False)

            # 加载缓存数据
            cache_str = config.get("release_date_cache", "{}")
            try:
                self._release_date_cache = json.loads(cache_str)
            except Exception:
                self._release_date_cache = {}

            known_str = config.get("known_subscriptions", "[]")
            try:
                self._known_subscriptions = set(json.loads(known_str))
            except Exception:
                self._known_subscriptions = set()

            history_str = config.get("reminder_history", "[]")
            try:
                self._reminder_history = json.loads(history_str)
            except Exception:
                self._reminder_history = []

            reminded_str = config.get("reminded_subscriptions", "[]")
            try:
                self._reminded_subscriptions = set(json.loads(reminded_str))
            except Exception:
                self._reminded_subscriptions = set()

            # 清理历史记录
            if self._clear:
                self._clearflag = True
                self._clear = False

        if self._enabled or self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)

            if self._onlyonce:
                logger.info("订阅上映提醒：立即运行一次")
                self._scheduler.add_job(
                    func=self.__run_refresh,
                    trigger='date',
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
                )

            if self._onlyonce or self._clear:
                self._onlyonce = False
                self._clearflag = self._clear
                self._clear = False
                self.__update_config()

            # 启动调度器
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self):
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("停止订阅上映提醒服务失败：%s" % str(e))

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "notify": self._notify,
            "onlyonce": self._onlyonce,
            "refresh_hours": self._refresh_hours,
            "days": self._days,
            "weekday": self._weekday,
            "push_time": self._push_time,
            "remind_24h": self._remind_24h,
            "clear": self._clear,
            "release_date_cache": json.dumps(self._release_date_cache, ensure_ascii=False),
            "known_subscriptions": json.dumps(list(self._known_subscriptions), ensure_ascii=False),
            "reminder_history": json.dumps(self._reminder_history, ensure_ascii=False),
            "reminded_subscriptions": json.dumps(list(self._reminded_subscriptions), ensure_ascii=False),
        })

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """配置表单：完全参照 doubansync 的 VForm → VRow → VCol 布局"""
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'enabled', 'label': '启用插件'}
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'notify', 'label': '发送通知'}
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'onlyonce', 'label': '立即运行一次'}
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'refresh_hours',
                                            'label': '刷新间隔(小时)',
                                            'type': 'number',
                                            'placeholder': '每隔几小时刷新日期未知的订阅'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'days',
                                            'label': '提醒提前天数',
                                            'type': 'number',
                                            'placeholder': '提前多少天提醒（默认7天=下周）'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'weekday',
                                            'label': '提醒星期',
                                            'items': ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'push_time',
                                            'label': '提醒时间',
                                            'placeholder': 'HH:MM 格式，默认20:00'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'remind_24h', 'label': '开播前24h提醒'}
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'clear', 'label': '清理历史记录'}
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "notify": True,
            "onlyonce": False,
            "refresh_hours": 6,
            "days": 7,
            "weekday": "周五",
            "push_time": "20:00",
            "remind_24h": True,
            "clear": False
        }

    def get_page(self) -> List[dict]:
        """历史记录页面：完全参照 doubansync 的 VCard 水平卡片 + grid 布局，升级 hover 动效"""
        # 处理清理标志
        if self._clearflag:
            self._reminder_history = []
            self._release_date_cache = {}
            self._known_subscriptions = set()
            self._reminded_subscriptions = set()
            self._clearflag = False
            self.__update_config()

        history = self._reminder_history
        if not history:
            return [
                {
                    'component': 'div',
                    'text': '暂无数据',
                    'props': {'class': 'text-center'}
                }
            ]

        # 按加入时间降序排序
        history = sorted(history, key=lambda x: x.get('added_time', ''), reverse=True)

        def get_date_status(release_date: str) -> Tuple[str, str]:
            """判断日期状态：精确（绿色）、预计（黄色）、未知（灰色）"""
            if not release_date:
                return "日期待定", "grey--text"
            if re.match(r'^\d{4}-\d{2}-\d{2}$', release_date):
                return release_date, "green--text text--darken-1"
            if re.match(r'^\d{4}-\d{2}$', release_date):
                return f"预计 {release_date}", "yellow--text text--darken-2"
            if re.match(r'^\d{4}$', release_date):
                return f"预计 {release_date}年", "yellow--text text--darken-2"
            return release_date, "grey--text"

        contents = []
        for item in history:
            title = item.get("title", "")
            poster = item.get("poster", "")
            release_date = item.get("release_date", "")
            douban_url = item.get("douban_url", "")
            tmdb_url = item.get("tmdb_url", "")
            source = item.get("source", "订阅")
            added_time = item.get("added_time", "")
            sub_id = item.get("sub_id", "")
            mtype = item.get("type", "")

            display_date, date_color = get_date_status(release_date)
            link_url = douban_url if douban_url else (tmdb_url if tmdb_url else "#")

            contents.append({
                'component': 'VCard',
                'props': {
                    'class': 'subscription-reminder-card',
                    'style': 'transition: transform 0.2s ease, box-shadow 0.2s ease;'
                },
                'content': [
                    {
                        "component": "VDialogCloseBtn",
                        "props": {'innerClass': 'absolute top-0 right-0'},
                        'events': {
                            'click': {
                                'api': 'plugin/SubscriptionReminder/delete_history',
                                'method': 'get',
                                'params': {
                                    'sub_id': sub_id,
                                    'apikey': settings.API_TOKEN
                                }
                            }
                        }
                    },
                    {
                        'component': 'div',
                        'props': {
                            'class': 'd-flex justify-space-start flex-nowrap flex-row',
                        },
                        'content': [
                            {
                                'component': 'div',
                                'content': [
                                    {
                                        'component': 'VImg',
                                        'props': {
                                            'src': poster if poster else 'https://img9.doubanio.com/f/frodo/18e2b616f8e3a9e3c7d6e3e3c7d6e3e3.jpg',
                                            'height': 120,
                                            'width': 80,
                                            'aspect-ratio': '2/3',
                                            'class': 'object-cover shadow ring-gray-500 rounded',
                                            'cover': True,
                                            'style': 'border-radius: 6px;'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'div',
                                'content': [
                                    {
                                        'component': 'VCardTitle',
                                        'props': {
                                            'class': 'ps-1 pe-5 break-words whitespace-break-spaces'
                                        },
                                        'content': [
                                            {
                                                'component': 'a',
                                                'props': {
                                                    'href': link_url,
                                                    'target': '_blank'
                                                },
                                                'text': title
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'VCardText',
                                        'props': {'class': 'pa-0 px-2'},
                                        'text': f'类型：{mtype}' if mtype else '类型：未知'
                                    },
                                    {
                                        'component': 'VCardText',
                                        'props': {'class': f'pa-0 px-2 {date_color} font-weight-medium'},
                                        'text': f'上映：{display_date}'
                                    },
                                    {
                                        'component': 'VCardText',
                                        'props': {'class': 'pa-0 px-2'},
                                        'text': f'来源：{source}'
                                    },
                                    {
                                        'component': 'VCardText',
                                        'props': {'class': 'pa-0 px-2'},
                                        'text': f'加入：{added_time}' if added_time else ''
                                    }
                                ]
                            }
                        ]
                    }
                ]
            })

        return [
            {
                'component': 'div',
                'props': {
                    'class': 'grid gap-3 grid-info-card',
                },
                'content': contents
            },
            {
                'component': 'style',
                'text': '''
                    .subscription-reminder-card:hover {
                        transform: translateY(-2px) !important;
                        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15) !important;
                    }
                '''
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """注册插件公共服务"""
        if not self._enabled:
            return []

        services = []

        # 每日定时刷新服务（按配置的间隔小时）
        services.append({
            "id": "SubscriptionReminder.Refresh",
            "name": "订阅上映提醒-每日刷新",
            "trigger": IntervalTrigger(hours=self._refresh_hours),
            "func": self.__run_refresh,
            "kwargs": {}
        })

        # 每周定时汇总提醒服务（按配置的星期几+时间）
        cron_day = self.WEEKDAY_MAP.get(self._weekday, "fri")
        try:
            hour = int(self._push_time.split(":")[0])
            minute = int(self._push_time.split(":")[1])
        except Exception:
            hour, minute = 20, 0

        services.append({
            "id": "SubscriptionReminder.WeeklyReminder",
            "name": "订阅上映提醒-每周汇总",
            "trigger": CronTrigger(day_of_week=cron_day, hour=hour, minute=minute),
            "func": self.__run_weekly_reminder,
            "kwargs": {}
        })

        # 首次运行：延迟1分钟后执行首次刷新
        services.append({
            "id": "SubscriptionReminder.FirstRun",
            "name": "订阅上映提醒-首次刷新",
            "trigger": DateTrigger(run_date=datetime.now() + timedelta(minutes=1)),
            "func": self.__run_refresh,
            "kwargs": {}
        })

        return services

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [{
            "cmd": "/subscription_reminder",
            "event": EventType.PluginAction,
            "desc": "触发订阅上映提醒刷新",
            "category": "订阅",
            "data": {"action": "subscription_reminder"}
        }]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/delete_history",
                "endpoint": self.delete_history,
                "methods": ["GET"],
                "summary": "删除单条提醒历史记录"
            },
            {
                "path": "/clear_history",
                "endpoint": self.clear_history,
                "methods": ["GET"],
                "summary": "清空所有提醒历史记录"
            }
        ]

    # ========== 订阅数据获取 ==========

    def __get_all_subscriptions(self) -> List[Dict]:
        """获取所有活跃订阅"""
        try:
            subs = SubscribeOper().list()
            result = []
            for sub in subs:
                result.append({
                    "id": getattr(sub, "id", None),
                    "name": getattr(sub, "name", ""),
                    "year": getattr(sub, "year", ""),
                    "type": getattr(sub, "type", ""),
                    "tmdbid": getattr(sub, "tmdbid", None),
                    "doubanid": getattr(sub, "doubanid", None),
                    "poster": getattr(sub, "poster", ""),
                })
            logger.info(f"获取到 {len(result)} 条活跃订阅")
            return result
        except Exception as e:
            logger.error(f"获取订阅列表失败: {e}")
            return []

    def _get_sub_uid(self, sub: Dict) -> str:
        """获取订阅的唯一标识"""
        tmdbid = sub.get("tmdbid")
        doubanid = sub.get("doubanid")
        if tmdbid:
            return f"tmdb:{tmdbid}"
        if doubanid:
            return f"douban:{doubanid}"
        return f"name:{sub.get('name', '')}"

    # ========== 上映日期查询（三级回退） ==========

    def __get_release_date_by_tmdb(self, sub: Dict) -> Optional[Dict]:
        """通过 TMDB API 获取上映日期和海报，支持类型筛选（TV/Movie/Anime）"""
        tmdbid = sub.get("tmdbid")
        doubanid = sub.get("doubanid")
        name = sub.get("name", "")
        year = sub.get("year", "")
        sub_type = sub.get("type", "")

        # 确定订阅的媒体类型（TV/Movie）
        target_mtype = self._get_sub_media_type(sub_type)

        try:
            from app.chain.media import MediaChain
            from app.core.metainfo import MetaInfo

            mediachain = MediaChain()
            mediainfo = None

            # 方案1：有 tmdbid，直接查询并验证类型
            if tmdbid:
                mediainfo = mediachain.recognize_media(
                    meta=MetaInfo(title=name, year=year),
                    tmdbid=tmdbid
                )
                if mediainfo and target_mtype:
                    media_type_str = self._get_media_type_str(mediainfo)
                    if media_type_str and media_type_str != target_mtype:
                        logger.info(
                            f"TMDB类型({media_type_str})与订阅类型({target_mtype})不匹配，"
                            f"尝试按类型重新搜索: {name}"
                        )
                        mediainfo = None  # 类型不匹配，丢弃

            # 方案2：无 tmdbid 或类型不匹配，通过豆瓣ID搜索（带类型筛选）
            if not mediainfo and doubanid and target_mtype:
                try:
                    mtype_enum = MediaType.TV if target_mtype == "tv" else MediaType.MOVIE
                    tmdbinfo = mediachain.get_tmdbinfo_by_doubanid(
                        doubanid=doubanid, mtype=mtype_enum
                    )
                    if tmdbinfo:
                        mediainfo = self._normalize_tmdb_result(tmdbinfo)
                        logger.debug(f"通过豆瓣ID({doubanid})+类型({target_mtype})匹配到TMDB: {name}")
                except Exception as e:
                    logger.debug(f"豆瓣ID+类型搜索TMDB失败 ({name}): {e}")

            # 方案3：名称搜索（带类型筛选）
            if not mediainfo and name and target_mtype:
                try:
                    meta = MetaInfo(title=name, year=year)
                    if target_mtype == "tv":
                        mediainfo = mediachain.recognize_media(meta=meta, mtype=MediaType.TV)
                    else:
                        mediainfo = mediachain.recognize_media(meta=meta, mtype=MediaType.MOVIE)
                    if mediainfo:
                        logger.debug(f"通过名称+类型({target_mtype})匹配到TMDB: {name}")
                except Exception as e:
                    logger.debug(f"名称+类型搜索TMDB失败 ({name}): {e}")

            if not mediainfo:
                return None

            result = {
                "release_date": "",
                "poster": "",
                "tmdb_url": "",
                "media_type": "",
            }

            # 获取上映日期
            if hasattr(mediainfo, 'first_air_date') and mediainfo.first_air_date:
                result["release_date"] = str(mediainfo.first_air_date)[:10]
                result["media_type"] = "tv"
            elif hasattr(mediainfo, 'release_date') and mediainfo.release_date:
                result["release_date"] = str(mediainfo.release_date)[:10]
                result["media_type"] = "movie"

            # 获取海报
            try:
                poster = mediainfo.get_poster_image()
                if poster:
                    result["poster"] = poster
            except Exception:
                pass

            # TMDB 链接
            if mediainfo.tmdb_id:
                if result["media_type"]:
                    result["tmdb_url"] = f"https://www.themoviedb.org/{result['media_type']}/{mediainfo.tmdb_id}"
                else:
                    result["tmdb_url"] = f"https://www.themoviedb.org/tv/{mediainfo.tmdb_id}"

            if result["release_date"]:
                logger.debug(f"TMDB获取到上映日期: {name} -> {result['release_date']} (类型: {result['media_type']})")
            return result

        except Exception as e:
            logger.debug(f"TMDB查询上映日期失败 ({name}): {e}")
            return None

    @staticmethod
    def _get_sub_media_type(sub_type) -> Optional[str]:
        """将订阅类型映射为 'tv' 或 'movie'"""
        if not sub_type:
            return None
        type_str = str(sub_type).lower()
        if hasattr(sub_type, 'value'):
            type_str = str(sub_type.value).lower()
        if type_str in ("tv", "电视剧", "剧集", "series"):
            return "tv"
        if type_str in ("movie", "电影", "film"):
            return "movie"
        return None

    @staticmethod
    def _get_media_type_str(mediainfo) -> Optional[str]:
        """从 mediainfo 提取媒体类型字符串"""
        if hasattr(mediainfo, 'type') and mediainfo.type:
            if hasattr(mediainfo.type, 'value'):
                return str(mediainfo.type.value).lower()
            return str(mediainfo.type).lower()
        if hasattr(mediainfo, 'first_air_date') and mediainfo.first_air_date:
            return "tv"
        if hasattr(mediainfo, 'release_date') and mediainfo.release_date:
            return "movie"
        return None

    @staticmethod
    def _normalize_tmdb_result(tmdbinfo) -> Any:
        """将 get_tmdbinfo_by_doubanid 返回的结果标准化为类 mediainfo 对象"""
        # 直接返回，大多数情况下 tmdbinfo 已经有兼容的属性
        return tmdbinfo

    def __get_release_date_by_douban(self, sub: Dict) -> Optional[str]:
        """通过豆瓣页面抓取上映日期"""
        doubanid = sub.get("doubanid")
        if not doubanid:
            return None

        try:
            url = f"https://movie.douban.com/subject/{doubanid}/"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            html = resp.text

            # 提取信息区域
            info_match = re.search(r'<div\s+id="info"[^>]*>(.*?)</div>', html, re.DOTALL)
            if info_match:
                info_html = info_match.group(1)

                # 首播日期
                date_match = re.search(r'首播:</span>\s*<span[^>]*>([^<]+)', info_html)
                if not date_match:
                    date_match = re.search(r'上映日期:</span>\s*<span[^>]*>([^<]+)', info_html)
                if date_match:
                    raw_date = date_match.group(1).strip()
                    date_match2 = re.search(r'(\d{4}-\d{2}-\d{2})', raw_date)
                    if date_match2:
                        logger.debug(f"豆瓣获取到上映日期: {sub.get('name')} -> {date_match2.group(1)}")
                        return date_match2.group(1)
                    return raw_date

            return None
        except Exception as e:
            logger.debug(f"豆瓣查询上映日期失败 ({sub.get('name')}, doubanid={doubanid}): {e}")
            return None

    def __get_release_date_by_bing(self, sub: Dict) -> Optional[str]:
        """通过 Bing 搜索获取上映日期（《xxx》定档）"""
        title = sub.get("name", "")
        if not title:
            return None

        try:
            search_query = f"《{title}》定档"
            search_url = f"https://www.bing.com/search?q={requests.utils.quote(search_query)}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.get(search_url, headers=headers, timeout=10)
            resp.raise_for_status()
            html = resp.text

            # 在搜索结果摘要中搜索日期
            date_patterns = [
                r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?)',
                r'定档[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?)',
                r'播出[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?)',
            ]
            for pattern in date_patterns:
                match = re.search(pattern, html)
                if match:
                    date_str = match.group(1)
                    # 标准化日期格式
                    normalized = re.sub(r'[年月]', '-', date_str)
                    normalized = re.sub(r'[日号]', '', normalized)
                    date_match = re.search(r'(\d{4}-\d{1,2}-\d{1,2})', normalized)
                    if date_match:
                        parts = date_match.group(1).split('-')
                        result = f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
                        logger.debug(f"Bing搜索获取到上映日期: {title} -> {result}")
                        return result

            return None
        except Exception as e:
            logger.debug(f"Bing搜索上映日期失败 ({title}): {e}")
            return None

    def __get_release_date(self, sub: Dict) -> Dict:
        """统一入口：豆瓣 > TMDB > Bing 三者全查，综合选最优日期
        规则：精确日期(YYYY-MM-DD)优先，同精度选距离系统时间更近的"""
        result = {
            "release_date": "",
            "poster": "",
            "tmdb_url": "",
            "douban_url": "",
            "media_type": "",
        }

        name = sub.get("name", "")

        # 1. 三者全查
        tmdb_result = self.__get_release_date_by_tmdb(sub)
        douban_date = self.__get_release_date_by_douban(sub)
        bing_date = self.__get_release_date_by_bing(sub)

        # 收集 TMDB 海报和链接
        if tmdb_result:
            result["poster"] = tmdb_result.get("poster", "")
            result["tmdb_url"] = tmdb_result.get("tmdb_url", "")
            result["media_type"] = tmdb_result.get("media_type", "")

        # 构建豆瓣链接
        doubanid = sub.get("doubanid")
        if doubanid:
            result["douban_url"] = f"https://movie.douban.com/subject/{doubanid}/"

        # 2. 收集所有候选日期，标注来源和精度
        today = datetime.now().date()
        candidates = []  # [(date_str, source_label, is_precise, days_diff)]

        def add_candidate(date_str: str, source: str):
            if not date_str:
                return
            is_precise = bool(re.match(r'^\d{4}-\d{2}-\d{2}$', date_str))
            # 计算与今天的天数差
            try:
                if is_precise:
                    dt = datetime.strptime(date_str, "%Y-%m-%d").date()
                elif re.match(r'^\d{4}-\d{2}$', date_str):
                    dt = datetime.strptime(date_str + "-01", "%Y-%m-%d").date()
                elif re.match(r'^\d{4}$', date_str):
                    dt = datetime.strptime(date_str + "-01-01", "%Y-%m-%d").date()
                else:
                    return
                diff = abs((dt - today).days)
                candidates.append((date_str, source, is_precise, diff))
            except ValueError:
                return

        # 豆瓣优先加入候选
        if douban_date:
            add_candidate(douban_date, "豆瓣")
        if tmdb_result and tmdb_result.get("release_date"):
            add_candidate(tmdb_result["release_date"], "TMDB")
        if bing_date:
            add_candidate(bing_date, "Bing")

        if not candidates:
            logger.info(f"未能获取上映日期: {name}")
            return result

        # 3. 选最优日期：精确优先，同精度选距离今天更近的
        precise_candidates = [c for c in candidates if c[2]]
        if precise_candidates:
            # 有精确日期，选距离今天最近的
            precise_candidates.sort(key=lambda x: x[3])
            best = precise_candidates[0]
        else:
            # 无精确日期，选距离今天最近的
            candidates.sort(key=lambda x: x[3])
            best = candidates[0]

        result["release_date"] = best[0]
        logger.info(f"获取到上映日期: {name} -> {best[0]} (来源: {best[1]}, 精确: {best[2]})")

        return result

    @staticmethod
    def _is_date_precise(date_str: str) -> bool:
        """判断日期是否为精确到日的格式（YYYY-MM-DD）"""
        if not date_str:
            return False
        return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', date_str))

    # ========== 智能刷新 ==========

    def __run_refresh(self):
        """每日定时刷新：获取所有订阅，仅刷新日期未知的订阅，检测新增订阅"""
        try:
            logger.info("开始执行订阅上映日期刷新...")

            # 获取所有活跃订阅
            subs = self.__get_all_subscriptions()
            if not subs:
                logger.info("无活跃订阅，跳过刷新")
                return

            # 构建当前订阅ID集合
            current_ids = set()
            for sub in subs:
                uid = self._get_sub_uid(sub)
                if uid:
                    current_ids.add(uid)

            # 检测新增订阅
            new_ids = current_ids - self._known_subscriptions
            if new_ids:
                logger.info(f"检测到 {len(new_ids)} 个新增订阅")

            # 遍历订阅，智能跳过已有精确日期的
            processed = 0
            max_per_run = 50
            for sub in subs:
                if processed >= max_per_run:
                    logger.info(f"已达到单次处理上限 {max_per_run}，剩余订阅下次刷新处理")
                    break

                uid = self._get_sub_uid(sub)
                if not uid:
                    continue

                # 检查缓存：已有精确日期则跳过
                cached = self._release_date_cache.get(uid, "")
                if self._is_date_precise(cached) and uid not in new_ids:
                    continue

                # 获取上映日期
                _time.sleep(0.5)  # API 限流
                date_info = self.__get_release_date(sub)
                processed += 1

                release_date = date_info.get("release_date", "")

                # 更新缓存
                if release_date:
                    self._release_date_cache[uid] = release_date

                # 更新或添加到历史记录
                sub_id = str(sub.get("id", ""))
                history_entry = {
                    "sub_id": sub_id,
                    "title": sub.get("name", ""),
                    "type": sub.get("type", ""),
                    "year": sub.get("year", ""),
                    "poster": date_info.get("poster", "") or sub.get("poster", ""),
                    "release_date": release_date,
                    "douban_url": date_info.get("douban_url", ""),
                    "tmdb_url": date_info.get("tmdb_url", ""),
                    "source": "订阅",
                    "added_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }

                # 查找是否已存在
                existing_idx = None
                for i, h in enumerate(self._reminder_history):
                    if h.get("sub_id") == sub_id:
                        existing_idx = i
                        break

                if existing_idx is not None:
                    self._reminder_history[existing_idx] = history_entry
                else:
                    self._reminder_history.append(history_entry)

                # 若获取到精确日期且开启了24h提醒，注册提醒
                if self._remind_24h and self._is_date_precise(release_date) and uid not in self._reminded_subscriptions:
                    self.__schedule_24h_reminder(sub, release_date)
                    self._reminded_subscriptions.add(uid)

            # 更新已知订阅列表
            self._known_subscriptions = current_ids

            # 持久化
            self.__update_config()
            logger.info(f"订阅上映日期刷新完成：处理 {processed} 条，缓存 {len(self._release_date_cache)} 条，"
                        f"历史 {len(self._reminder_history)} 条")

        except Exception as e:
            logger.error(f"订阅上映日期刷新异常: {e}")

    # ========== 每周汇总提醒 ==========

    def __run_weekly_reminder(self):
        """每周定时汇总提醒：筛选下周上映的订阅，发送汇总通知"""
        try:
            logger.info("开始执行每周上映提醒...")

            # 计算日期范围：今天 → 未来 N 天
            today = datetime.now().date()
            end_date = today + timedelta(days=self._days)

            # 筛选上映日期在范围内的订阅（精确日期 + 月份精度）
            upcoming = []
            for item in self._reminder_history:
                release_date = item.get("release_date", "")
                if not release_date:
                    continue

                try:
                    if self._is_date_precise(release_date):
                        rd = datetime.strptime(release_date, "%Y-%m-%d").date()
                        if today <= rd <= end_date:
                            upcoming.append(item)
                    elif re.match(r'^\d{4}-\d{2}$', release_date):
                        # 月份精度：取该月第一天判断
                        rd = datetime.strptime(release_date + "-01", "%Y-%m-%d").date()
                        if today <= rd <= end_date:
                            upcoming.append(item)
                except ValueError:
                    continue

            if not upcoming:
                logger.info("下周无订阅影视上映，跳过通知")
                return

            # 按上映日期升序排列
            upcoming.sort(key=lambda x: x.get("release_date", ""))

            # 发送通知
            if self._notify:
                self.__send_weekly_notification(upcoming, today, end_date)
            else:
                logger.info(f"通知已关闭，跳过发送。下周有 {len(upcoming)} 部即将上映")

        except Exception as e:
            logger.error(f"每周上映提醒异常: {e}")

    def __send_weekly_notification(self, items: List[Dict], start_date, end_date):
        """发送每周汇总通知：链接优先豆瓣，其次 TMDB；月份精度加（预计）标记"""
        n = len(items)
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        # 构建通知文本
        lines = [f"📺 上映提醒（{start_str} ~ {end_str}）", "", f"共 {n} 部订阅影视即将上映：", ""]

        for item in items:
            title = item.get("title", "")
            year = item.get("year", "")
            release_date = item.get("release_date", "")
            douban_url = item.get("douban_url", "")
            tmdb_url = item.get("tmdb_url", "")

            # 链接优先豆瓣，其次 TMDB
            link = douban_url if douban_url else (tmdb_url if tmdb_url else "")

            # 月份精度加"（预计）"标记
            if self._is_date_precise(release_date):
                date_display = release_date
            else:
                date_display = f"{release_date}（预计）"

            title_line = f"🎞 {title}"
            if year:
                title_line += f" ({year})"
            lines.append(title_line)
            lines.append(f"📅 上映日期：{date_display}")
            if link:
                lines.append(f"🔗 {link}")
            lines.append("")

        notify_text = "\n".join(lines)

        # 获取第一张海报
        first_poster = items[0].get("poster", "") if items else ""

        try:
            self.post_message(
                mtype=NotificationType.Plugin,
                title=f"📺 上映提醒（{start_str} ~ {end_str}）",
                text=notify_text,
                image=first_poster if first_poster else None,
            )
            logger.info(f"已发送每周上映提醒：{n} 部即将上映")
        except Exception as e:
            logger.error(f"发送每周上映提醒通知失败: {e}")

    # ========== 开播前24小时提醒 ==========

    def __schedule_24h_reminder(self, sub: Dict, release_date: str):
        """注册开播前24小时一次性提醒任务"""
        try:
            release_dt = datetime.strptime(release_date, "%Y-%m-%d")
            reminder_dt = release_dt - timedelta(hours=24)

            if reminder_dt <= datetime.now():
                logger.info(f"开播提醒时间已过，跳过: {sub.get('name')} ({release_date})")
                return

            sub_id = str(sub.get("id", ""))
            title = sub.get("name", "")
            job_id = f"sub_reminder_24h_{sub_id}_{release_date}"

            self._scheduler.add_job(
                func=self.__send_24h_reminder,
                trigger=DateTrigger(run_date=reminder_dt),
                args=[title, release_date],
                id=job_id,
                name=f"开播提醒 - {title}",
                replace_existing=True,
            )
            logger.info(f"已设置开播前24小时提醒: {title} | 开播: {release_date} | 提醒: {reminder_dt}")

        except Exception as e:
            logger.warning(f"注册24小时提醒任务失败 ({sub.get('name')}): {e}")

    def __send_24h_reminder(self, title: str, release_date: str):
        """发送开播前24小时提醒通知"""
        try:
            if not self._notify:
                return

            notify_text = (
                f"⏰ {title} 距开播还有24小时！\n\n"
                f"📅 播出时间：{release_date}\n"
                f"记得准时观看！"
            )
            self.post_message(
                mtype=NotificationType.Plugin,
                title=f"⏰ 开播提醒 - {title}",
                text=notify_text,
            )
            logger.info(f"已发送开播24小时提醒: {title}")
        except Exception as e:
            logger.warning(f"发送开播24小时提醒失败: {e}")

    # ========== API 处理 ==========

    def delete_history(self, sub_id: str, apikey: str):
        """删除单条提醒历史记录"""
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")

        self._reminder_history = [h for h in self._reminder_history if h.get("sub_id") != sub_id]
        self.__update_config()
        return schemas.Response(success=True, message="删除成功")

    def clear_history(self, apikey: str):
        """清空所有提醒历史记录"""
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")

        self._reminder_history = []
        self._release_date_cache = {}
        self._known_subscriptions = set()
        self._reminded_subscriptions = set()
        self.__update_config()
        return schemas.Response(success=True, message="历史记录已清空")

    # ========== 远程命令 ==========

    @eventmanager.register(EventType.PluginAction)
    def remote_refresh(self, event: Event):
        """远程命令触发刷新"""
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "subscription_reminder":
                return
            logger.info("收到命令，开始执行订阅上映提醒刷新...")
            self.post_message(
                channel=event.event_data.get("channel"),
                title="开始刷新订阅上映日期...",
                userid=event.event_data.get("user")
            )

        self.__run_refresh()

        if event:
            self.post_message(
                channel=event.event_data.get("channel"),
                title="订阅上映日期刷新完成！",
                userid=event.event_data.get("user")
            )