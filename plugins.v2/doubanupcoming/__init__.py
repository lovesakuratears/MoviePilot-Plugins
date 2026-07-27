import json
import re
from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime, timedelta
import requests
import xml.etree.ElementTree as ET
from html import unescape

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType, MediaType


class DoubanUpcoming(_PluginBase):
    plugin_name = "刷豆瓣助手"
    plugin_desc = "省去打开豆瓣的过程，提供一条龙订阅推送服务。定时获取豆瓣即将播出/热门影视榜单，支持通过豆瓣UID获取想看列表并自动订阅未上映条目。"
    plugin_icon = "douban.png"
    plugin_version = "1.9.0"
    plugin_author = "lovesakuratears"
    author_url = "https://github.com/lovesakuratears/MoviePilot-Plugins"
    plugin_config_prefix = "doubanupcoming_"
    plugin_order = 20
    auth_level = 1

    _enabled = False
    _data_sources = ["即将上映"]
    _regions = ["中国大陆", "海外"]
    _push_count = 10
    _filter_short = False
    _sort_by = "hot"
    _push_time = "09:00"
    _douban_uid = ""
    _enable_wish = False
    _auto_subscribe_wish = False
    _clear_history = False
    _run_immediately = False
    _pushed_items = "{}"
    _tracking_items = "[]"
    _current_queue = "[]"
    _last_notify_title = ""
    _wish_last_processed = ""

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled", False)
            self._data_sources = config.get("data_sources", ["即将上映"])
            self._regions = config.get("regions", ["中国大陆", "海外"])
            self._push_count = int(config.get("push_count", 10))
            self._filter_short = config.get("filter_short", False)
            self._sort_by = config.get("sort_by", "hot")
            self._push_time = config.get("push_time", "09:00")
            self._douban_uid = config.get("douban_uid", "")
            self._enable_wish = config.get("enable_wish", False)
            self._auto_subscribe_wish = config.get("auto_subscribe_wish", False)
            self._clear_history = config.get("clear_history", False)
            self._run_immediately = config.get("run_immediately", False)
            # 如果开启了清除历史，执行清除后重置开关
            if self._clear_history:
                self._pushed_items = "{}"
                self._current_queue = "[]"
                self._tracking_items = "[]"
                self._clear_history = False
                self.__save_config()
                logger.info("已清除所有历史记录")
            else:
                self._pushed_items = config.get("pushed_items", "{}")
            self._tracking_items = config.get("tracking_items", "[]")
            self._current_queue = config.get("current_queue", "[]")
            self._last_notify_title = config.get("last_notify_title", "")

            # 如果开启了立即执行，重置开关并触发推送（仅在插件启用时执行）
            if self._run_immediately:
                self._run_immediately = False
                if not self._enabled:
                    logger.info("插件未启用，跳过立即执行")
                else:
                    logger.info("检测到立即执行开关，正在触发首次推送...")
                    self.__run_push()

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self):
        pass

    def __save_config(self):
        self.update_config({
            "enabled": self._enabled,
            "data_sources": self._data_sources,
            "regions": self._regions,
            "push_count": self._push_count,
            "filter_short": self._filter_short,
            "sort_by": self._sort_by,
            "push_time": self._push_time,
            "douban_uid": self._douban_uid,
            "enable_wish": self._enable_wish,
            "auto_subscribe_wish": self._auto_subscribe_wish,
            "clear_history": self._clear_history,
            "run_immediately": self._run_immediately,
            "pushed_items": self._pushed_items,
            "tracking_items": self._tracking_items,
            "current_queue": self._current_queue,
            "last_notify_title": self._last_notify_title
        })

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '数据来源：RSSHub (https://rsshub.ddsrem.com)。推送豆瓣榜单影视信息，支持通过豆瓣UID获取想看列表自动订阅，省去打开豆瓣的过程。'
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
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'filter_short',
                                            'label': '剔除短剧（单集≤10分钟）',
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
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'data_sources',
                                            'label': '数据来源（榜单）',
                                            'items': ["即将上映", "实时热门"],
                                            'chips': True,
                                            'multiple': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'regions',
                                            'label': '地区筛选',
                                            'items': ["中国大陆", "海外"],
                                            'chips': True,
                                            'multiple': True,
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
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'density': 'compact',
                                            'text': '填写豆瓣UID后开启"豆瓣想看"，系统将自动获取你的想看列表，仅对未上映条目自动订阅。'
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
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'douban_uid',
                                            'label': '豆瓣UID',
                                            'placeholder': '填写豆瓣用户ID'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enable_wish',
                                            'label': '豆瓣想看',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'auto_subscribe_wish',
                                            'label': '自动订阅想看',
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
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'push_count',
                                            'label': '每轮推送条数',
                                            'type': 'number',
                                            'min': 1,
                                            'max': 20,
                                            'placeholder': '默认10条'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'sort_by',
                                            'label': '排序方式',
                                            'items': [
                                                {"title": "热度", "value": "hot"},
                                                {"title": "时间", "value": "time"}
                                            ],
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
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'push_time',
                                            'label': '每日推送时间',
                                            'placeholder': 'HH:MM 格式，默认09:00'
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
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'clear_history',
                                            'label': '清除历史记录（保存设置后生效，执行后自动关闭）',
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
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'run_immediately',
                                            'label': '立即执行一次（保存后立即触发推送，不等待定时时间，执行后自动关闭）',
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "data_sources": ["即将上映"],
            "regions": ["中国大陆", "海外"],
            "push_count": 10,
            "filter_short": False,
            "sort_by": "hot",
            "push_time": "09:00",
            "douban_uid": "",
            "enable_wish": False,
            "auto_subscribe_wish": False,
            "clear_history": False,
            "run_immediately": False
        }

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面：网格布局，感兴趣/不感兴趣分组，不感兴趣折叠
        """
        pushed = {}
        try:
            pushed = json.loads(self._pushed_items or "{}")
        except Exception:
            pass

        if not pushed:
            return [
                {
                    'component': 'div',
                    'text': '暂无数据',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]

        interested_items = []
        not_interested_items = []

        for douban_id, info in pushed.items():
            entry = {
                "douban_id": douban_id,
                "title": info.get("title", ""),
                "time": info.get("time", ""),
                "release_date": info.get("release_date", ""),
                "interest": info.get("interest"),
                "image_url": info.get("image_url", ""),
                "genres": info.get("genres", ""),
            }
            if info.get("interest") is True:
                interested_items.append(entry)
            elif info.get("interest") is False:
                not_interested_items.append(entry)

        interested_items.sort(key=lambda x: x.get("time", ""), reverse=True)
        not_interested_items.sort(key=lambda x: x.get("time", ""), reverse=True)

        def build_card(item):
            """构建单张水平卡片"""
            title = item.get("title", "")
            douban_id = item.get("douban_id", "")
            image_url = item.get("image_url", "")
            genres = item.get("genres", "")
            release_date = item.get("release_date", "")
            time_str = item.get("time", "")
            # 优先显示上映时间
            display_time = release_date if release_date else time_str
            interest = item.get("interest")
            action = "感兴趣" if interest is True else "不感兴趣" if interest is False else ""

            return {
                'component': 'VCard',
                'content': [
                    {
                        "component": "VDialogCloseBtn",
                        "props": {
                            'innerClass': 'absolute top-0 right-0',
                        },
                        'events': {
                            'click': {
                                'api': 'plugin/DoubanUpcoming/delete_history_item',
                                'method': 'get',
                                'params': {
                                    'douban_id': douban_id,
                                    'apikey': settings.API_TOKEN
                                }
                            }
                        },
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
                                            'src': image_url,
                                            'height': 120,
                                            'width': 80,
                                            'aspect-ratio': '2/3',
                                            'class': 'object-cover shadow ring-gray-500',
                                            'cover': True
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
                                                    'href': f"https://movie.douban.com/subject/{douban_id}",
                                                    'target': '_blank'
                                                },
                                                'text': title
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'pa-0 px-2'
                                        },
                                        'text': f'类型：{genres}' if genres else '类型：暂无'
                                    },
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'pa-0 px-2'
                                        },
                                        'text': f'上映：{display_time}' if display_time else '上映：暂无'
                                    },
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'pa-0 px-2'
                                        },
                                        'text': f'操作：{action}' if action else ''
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }

        def build_grid(items):
            """将卡片排列成网格，每行最多4个（lg=3即4列）"""
            rows = []
            for i in range(0, len(items), 4):
                row_items = items[i:i + 4]
                cols = []
                for item in row_items:
                    cols.append({
                        'component': 'VCol',
                        'props': {'cols': 12, 'sm': 6, 'md': 4, 'lg': 3},
                        'content': [build_card(item)]
                    })
                rows.append({
                    'component': 'VRow',
                    'content': cols
                })
            return rows

        page = []

        # 感兴趣 section
        if interested_items:
            page.append({
                'component': 'div',
                'props': {'class': 'd-flex align-center mb-4'},
                'content': [
                    {'component': 'VIcon', 'props': {'icon': 'mdi-heart', 'color': 'red', 'size': '24', 'class': 'me-2'}},
                    {'component': 'div', 'props': {'class': 'text-h5 font-weight-bold'}, 'text': '感兴趣'},
                    {'component': 'VChip', 'props': {'size': 'small', 'class': 'ms-2', 'color': 'primary', 'variant': 'tonal'}, 'text': f'{len(interested_items)} 条'},
                ]
            })
            page.extend(build_grid(interested_items))

        # 不感兴趣 section（折叠隐藏）
        if not_interested_items:
            page.append({
                'component': 'div',
                'props': {'class': 'd-flex align-center mb-4 mt-6'},
                'content': [
                    {'component': 'VIcon', 'props': {'icon': 'mdi-heart-off', 'color': 'grey', 'size': '24', 'class': 'me-2'}},
                    {'component': 'div', 'props': {'class': 'text-h5 font-weight-bold'}, 'text': '不感兴趣'},
                    {'component': 'VChip', 'props': {'size': 'small', 'class': 'ms-2', 'variant': 'tonal'}, 'text': f'{len(not_interested_items)} 条'},
                ]
            })
            page.append({
                'component': 'VExpansionPanels',
                'props': {'variant': 'accordion'},
                'content': [{
                    'component': 'VExpansionPanel',
                    'content': [
                        {
                            'component': 'VExpansionPanelTitle',
                            'props': {'class': 'px-0'},
                            'content': [
                                {'component': 'span', 'props': {'class': 'text-body-2 text-medium-emphasis'}, 'text': '点击展开查看'}
                            ]
                        },
                        {
                            'component': 'VExpansionPanelText',
                            'props': {'class': 'px-0 pb-0'},
                            'content': build_grid(not_interested_items)
                        }
                    ]
                }]
            })

        return page

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        services = [
            {
                "id": f"{self.__class__.__name__}.DailyPush",
                "name": "刷豆瓣助手每日推送",
                "trigger": "cron",
                "func": self.__run_push,
                "kwargs": {"hour": self._push_time.split(":")[0], "minute": self._push_time.split(":")[1]}
            }
        ]
        # 首次运行：如果还没推送过且没有开启立即执行，1分钟后执行首次推送
        # 如果已开启立即执行，init_plugin 中已经执行过，不需要再添加定时任务
        if (not self._pushed_items or self._pushed_items == "{}") and not self._run_immediately:
            services.append({
                "id": f"{self.__class__.__name__}.FirstRun",
                "name": "刷豆瓣助手首次推送",
                "trigger": DateTrigger(run_date=datetime.now() + timedelta(minutes=1)),
                "func": self.__run_push,
                "kwargs": {}
            })
        # 本地追踪每日刷新
        services.append({
            "id": f"{self.__class__.__name__}.TrackingRefresh",
            "name": "豆瓣本地追踪刷新",
            "trigger": "interval",
            "func": self.__refresh_tracking,
            "kwargs": {"hours": 12}
        })
        # 豆瓣想看刷新服务（如果开启）
        if self._enable_wish and self._douban_uid:
            services.append({
                "id": f"{self.__class__.__name__}.WishRefresh",
                "name": "豆瓣想看列表刷新",
                "trigger": "interval",
                "func": self.__process_douban_wish,
                "kwargs": {"hours": 12}
            })
            # 仅在开启自动订阅时，首次启动延迟10分钟后执行首次想看处理
            if self._auto_subscribe_wish:
                services.append({
                    "id": f"{self.__class__.__name__}.WishFirstRun",
                    "name": "豆瓣想看首次处理",
                    "trigger": DateTrigger(run_date=datetime.now() + timedelta(minutes=10)),
                    "func": self.__process_douban_wish,
                    "kwargs": {}
                })
        return services

    @staticmethod
    def get_api() -> List[Dict[str, Any]]:
        return [
            {
                "path": "/push",
                "endpoint": DoubanUpcoming.__api_push,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "手动触发推送",
                "description": "立即执行一次豆瓣即将播出推送",
            },
            {
                "path": "/clear_history",
                "endpoint": DoubanUpcoming.__api_clear_history,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清除历史记录",
                "description": "清空所有已推送记录",
            },
            {
                "path": "/delete_history_item",
                "endpoint": DoubanUpcoming.__api_delete_history_item,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "删除单条历史记录",
                "description": "删除指定豆瓣ID的推送历史记录",
            },
            {
                "path": "/detail",
                "endpoint": DoubanUpcoming.__api_detail,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "获取豆瓣链接",
                "description": "获取指定豆瓣条目的详情页链接",
            },
            {
                "path": "/interest",
                "endpoint": DoubanUpcoming.__api_interest,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "有兴趣",
                "description": "标记为感兴趣，尝试TMDB/豆瓣订阅",
            },
            {
                "path": "/not_interest",
                "endpoint": DoubanUpcoming.__api_not_interest,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "无兴趣",
                "description": "标记为不感兴趣，推送下一条",
            },
            {
                "path": "/stop",
                "endpoint": DoubanUpcoming.__api_stop,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "停止推送",
                "description": "停止本轮继续推送，结束当前推送队列",
            },
        ]

    def __fetch_coming(self, sort_by: str = "hot", count: int = 10) -> List[Dict]:
        url = f"https://rsshub.ddsrem.com/douban/tv/coming/{sort_by}/{count}"
        results = []
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            items = root.findall('.//item')
            for item in items:
                try:
                    title = item.findtext('title', '').strip()
                    link = item.findtext('link', '').strip()
                    description = item.findtext('description', '').strip()
                    category = item.findtext('category', '').strip()

                    douban_id = ''
                    m = re.search(r'/subject/(\d+)/', link)
                    if m:
                        douban_id = m.group(1)

                    parts = [p.strip() for p in category.split(' / ')]
                    year = parts[0] if len(parts) > 0 else ''
                    region = parts[1] if len(parts) > 1 else ''
                    genres = parts[2] if len(parts) > 2 else ''
                    director = parts[3] if len(parts) > 3 else ''
                    actors = parts[4] if len(parts) > 4 else ''

                    wish_count = ''
                    summary = ''
                    m = re.search(r'想看人数：(\d+)[，,]?(.*)', description)
                    if m:
                        wish_count = m.group(1)
                        summary = m.group(2).strip()

                    results.append({
                        "title": title,
                        "douban_id": douban_id,
                        "douban_url": link,
                        "year": year,
                        "region": region,
                        "genres": genres,
                        "director": director,
                        "actors": actors,
                        "rating": "",
                        "image_url": "",
                        "summary": summary,
                        "wish_count": wish_count,
                        "episode_count": "",
                        "episode_duration": "",
                        "release_date": "",
                        "season_info": "",
                    })
                except Exception as e:
                    logger.warning(f"解析 coming 条目失败: {e}")
                    continue

            logger.info(f"__fetch_coming 获取到 {len(results)} 条数据")

            # 只对前 push_count 条（即将推送的）抓取详情，减少网络请求
            detail_count = min(self._push_count if hasattr(self, '_push_count') else 10, len(results))
            for i in range(detail_count):
                item = results[i]
                douban_id = item.get("douban_id", "")
                if douban_id:
                    try:
                        detail = self.__fetch_douban_detail(douban_id)
                        if detail:
                            if detail.get("image_url"):
                                item["image_url"] = detail["image_url"]
                            if detail.get("rating"):
                                item["rating"] = detail["rating"]
                            if detail.get("episode_count"):
                                item["episode_count"] = detail["episode_count"]
                            if detail.get("episode_duration"):
                                item["episode_duration"] = detail["episode_duration"]
                            if detail.get("release_date"):
                                item["release_date"] = detail["release_date"]
                            if detail.get("season_info"):
                                item["season_info"] = detail["season_info"]
                            if detail.get("summary") and not item.get("summary"):
                                item["summary"] = detail["summary"]
                            if detail.get("genres") and not item.get("genres"):
                                item["genres"] = detail["genres"]
                            if detail.get("director") and not item.get("director"):
                                item["director"] = detail["director"]
                            if detail.get("actors") and not item.get("actors"):
                                item["actors"] = detail["actors"]
                    except Exception as e:
                        logger.warning(f"获取 {item.get('title')} 详情失败: {e}")

        except Exception as e:
            logger.error(f"__fetch_coming 请求失败: {e}")
        return results

    def __fetch_hot(self) -> List[Dict]:
        url = "https://rsshub.ddsrem.com/douban/list/tv_real_time_hotest"
        results = []
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            items = root.findall('.//item')
            for item in items:
                try:
                    title = item.findtext('title', '').strip()
                    link = item.findtext('link', '').strip()
                    desc_raw = item.findtext('description', '').strip()

                    douban_id = ''
                    m = re.search(r'/subject/(\d+)/', link)
                    if not m:
                        m = re.search(r'/movie/(\d+)', link)
                    if m:
                        douban_id = m.group(1)

                    desc = unescape(desc_raw)

                    ps = re.findall(r'<p>(.*?)</p>', desc, re.DOTALL)

                    rating = ''
                    year = ''
                    region = ''
                    genres = ''
                    director = ''
                    actors = ''

                    if len(ps) >= 2:
                        rating = ps[1].strip()
                    if len(ps) >= 3:
                        parts = [p.strip() for p in ps[2].split(' / ')]
                        year = parts[0] if len(parts) > 0 else ''
                        region = parts[1] if len(parts) > 1 else ''
                        genres = parts[2] if len(parts) > 2 else ''
                        director = parts[3] if len(parts) > 3 else ''
                        actors = parts[4] if len(parts) > 4 else ''

                    image_url = ''
                    m = re.search(r'<img\s+src="([^"]+)"', desc)
                    if m:
                        image_url = m.group(1)

                    results.append({
                        "title": title,
                        "douban_id": douban_id,
                        "douban_url": link,
                        "year": year,
                        "region": region,
                        "genres": genres,
                        "director": director,
                        "actors": actors,
                        "rating": rating,
                        "image_url": image_url,
                        "summary": "",
                        "wish_count": "",
                    })
                except Exception as e:
                    logger.warning(f"解析 hot 条目失败: {e}")
                    continue
            logger.info(f"__fetch_hot 获取到 {len(results)} 条数据")
        except Exception as e:
            logger.error(f"__fetch_hot 请求失败: {e}")
        return results

    def __fetch_wish(self) -> List[Dict]:
        url = "https://rsshub.ddsrem.com/douban/recommended/tv"
        results = []
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            items = root.findall('.//item')
            for item in items:
                try:
                    title = item.findtext('title', '').strip()
                    link = item.findtext('link', '').strip()
                    desc_raw = item.findtext('description', '').strip()

                    douban_id = ''
                    m = re.search(r'/subject/(\d+)/', link)
                    if not m:
                        m = re.search(r'/movie/(\d+)', link)
                    if m:
                        douban_id = m.group(1)

                    desc = unescape(desc_raw)

                    ps = re.findall(r'<p>(.*?)</p>', desc, re.DOTALL)

                    rating = ''
                    year = ''
                    region = ''
                    genres = ''
                    director = ''
                    actors = ''

                    if len(ps) >= 2:
                        rating = ps[1].strip()
                    if len(ps) >= 3:
                        parts = [p.strip() for p in ps[2].split(' / ')]
                        year = parts[0] if len(parts) > 0 else ''
                        region = parts[1] if len(parts) > 1 else ''
                        genres = parts[2] if len(parts) > 2 else ''
                        director = parts[3] if len(parts) > 3 else ''
                        actors = parts[4] if len(parts) > 4 else ''

                    image_url = ''
                    m = re.search(r'<img\s+src="([^"]+)"', desc)
                    if m:
                        image_url = m.group(1)

                    results.append({
                        "title": title,
                        "douban_id": douban_id,
                        "douban_url": link,
                        "year": year,
                        "region": region,
                        "genres": genres,
                        "director": director,
                        "actors": actors,
                        "rating": rating,
                        "image_url": image_url,
                        "summary": "",
                        "wish_count": "",
                    })
                except Exception as e:
                    logger.warning(f"解析 wish 条目失败: {e}")
                    continue
            logger.info(f"__fetch_wish 获取到 {len(results)} 条数据")
        except Exception as e:
            logger.error(f"__fetch_wish 请求失败: {e}")
        return results

    def __fetch_douban_wish(self) -> List[Dict]:
        """通过豆瓣UID获取用户想看列表（使用豆瓣官方 feed）"""
        if not self._douban_uid or not self._enable_wish:
            return []

        url = f"https://www.douban.com/feed/people/{self._douban_uid}/interests"
        results = []
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            items = root.findall('.//item')
            for item in items:
                try:
                    title_raw = item.findtext('title', '').strip()
                    link = item.findtext('link', '').strip()
                    desc_raw = item.findtext('description', '').strip()

                    # 豆瓣官方 feed 的 title 格式："用户名 想看/看过/在看 《标题》"
                    # 只保留"想看"状态的条目
                    if '想看' not in title_raw:
                        continue

                    # 从 title 中提取实际标题
                    title = title_raw
                    title_match = re.search(r'《(.+?)》', title_raw)
                    if title_match:
                        title = title_match.group(1)
                    else:
                        # 尝试从 "想看" 后面提取
                        parts = title_raw.split('想看')
                        if len(parts) > 1:
                            title = parts[-1].strip()

                    douban_id = ''
                    m = re.search(r'/subject/(\d+)/', link)
                    if not m:
                        m = re.search(r'/movie/(\d+)', link)
                    if m:
                        douban_id = m.group(1)

                    desc = unescape(desc_raw)

                    # 提取年份
                    year = ''
                    year_match = re.search(r'(\d{4})', title)
                    if year_match:
                        year = year_match.group(1)

                    # 提取图片
                    image_url = ''
                    m = re.search(r'<img\s+src="([^"]+)"', desc)
                    if m:
                        image_url = m.group(1)

                    # 提取简介
                    summary = ''
                    ps = re.findall(r'<p>(.*?)</p>', desc, re.DOTALL)
                    for p_text in ps:
                        p_text = re.sub(r'<[^>]+>', '', p_text).strip()
                        if p_text and len(p_text) > 20:
                            summary = p_text
                            break

                    # 提取评分（豆瓣 feed 中评论文本格式："推荐: 8.0" 等）
                    rating = ''
                    rating_match = re.search(r'推荐[：:]\s*(\d+\.?\d*)', desc)
                    if rating_match:
                        rating = rating_match.group(1)
                    else:
                        rating_match = re.search(r'(\d+\.?\d*)\s*分', desc)
                        if rating_match:
                            rating = rating_match.group(1)

                    results.append({
                        "title": title,
                        "douban_id": douban_id,
                        "douban_url": link,
                        "year": year,
                        "region": "",
                        "genres": "",
                        "director": "",
                        "actors": "",
                        "rating": rating,
                        "image_url": image_url,
                        "summary": summary,
                        "wish_count": "",
                        "source": "douban_wish",
                    })
                except Exception as e:
                    logger.warning(f"解析豆瓣想看条目失败: {e}")
                    continue
            logger.info(f"__fetch_douban_wish 获取到 {len(results)} 条数据")
        except Exception as e:
            logger.error(f"__fetch_douban_wish 请求失败: {e}")
        return results

    def __fetch_douban_detail(self, douban_id: str) -> Dict[str, Any]:
        """获取影视详情：优先从 TMDB 官方 API 获取元数据，豆瓣 HTML 抓取仅作备用（参照 doubansync）"""
        detail = {
            "image_url": "",
            "rating": "",
            "episode_count": "",
            "episode_duration": "",
            "release_date": "",
            "season_info": "",
            "summary": "",
            "genres": "",
            "director": "",
            "actors": "",
        }
        if not douban_id:
            return detail

        # --- 优先方案：从 TMDB 获取元数据（参照 doubansync 的 mediainfo.get_poster_image()） ---
        try:
            tmdb_info = self.__try_tmdb_match({"douban_id": douban_id})
            if tmdb_info:
                # 海报
                if tmdb_info.get("poster_path"):
                    detail["image_url"] = f"https://image.tmdb.org/t/p/w500{tmdb_info.get('poster_path')}"
                # 简介
                if tmdb_info.get("overview"):
                    detail["summary"] = tmdb_info["overview"][:500]
                # 播出日期
                first_air = tmdb_info.get("first_air_date", "") or ""
                if first_air and len(first_air) >= 10:
                    detail["release_date"] = first_air
                # 集数/季数（TMDB 返回的可能是完整 media info，尝试提取）
                if tmdb_info.get("number_of_episodes"):
                    detail["episode_count"] = str(tmdb_info["number_of_episodes"])
                if tmdb_info.get("number_of_seasons"):
                    detail["season_info"] = f"S{int(tmdb_info['number_of_seasons']):02d}"
                if tmdb_info.get("episode_run_time"):
                    runtimes = tmdb_info["episode_run_time"]
                    if isinstance(runtimes, list) and runtimes:
                        detail["episode_duration"] = str(runtimes[0])
                    elif isinstance(runtimes, (int, float)):
                        detail["episode_duration"] = str(runtimes)
                # 类型（TMDB 返回的是 genre_ids 或 genres 列表，后续从豆瓣补充中文名）
                logger.debug(f"从TMDB获取到 {douban_id} 的元数据: date={detail['release_date']}, episodes={detail['episode_count']}")
        except Exception as e:
            logger.debug(f"从TMDB获取元数据失败 ({douban_id}): {e}")

        # --- 回退方案：从豆瓣 HTML 补充 TMDB 缺失的数据 ---
        url = f"https://movie.douban.com/subject/{douban_id}/"
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            html = resp.text

            # 海报（TMDB 未获取到时从豆瓣补充）
            if not detail["image_url"]:
                img_match = re.search(r'<img\s+[^>]*src="([^"]+)"[^>]*title="点击看更多海报"', html)
                if not img_match:
                    img_match = re.search(r'<a\s+class="nbgnbg"[^>]*>\s*<img\s+src="([^"]+)"', html)
                if not img_match:
                    img_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
                if img_match:
                    detail["image_url"] = img_match.group(1)

            # 评分（仅豆瓣有）
            rating_match = re.search(r'<strong\s+class="ll\s+rating_num"[^>]*>([\d.]+)</strong>', html)
            if rating_match:
                detail["rating"] = rating_match.group(1)

            # 简介（TMDB 未获取到时从豆瓣补充）
            if not detail["summary"]:
                summary_match = re.search(r'<span\s+property="v:summary"[^>]*>(.*?)</span>', html, re.DOTALL)
                if not summary_match:
                    summary_match = re.search(r'<span\s+class="all\s+hidden">(.*?)</span>', html, re.DOTALL)
                if not summary_match:
                    summary_match = re.search(r'<div\s+id="link-report"[^>]*>.*?<span[^>]*>(.*?)</span>', html, re.DOTALL)
                if summary_match:
                    summary = re.sub(r'<[^>]+>', '', summary_match.group(1)).strip()
                    detail["summary"] = summary[:500] if summary else ""

            # 详细信息区域（豆瓣特有：集数、片长、日期、类型、导演、演员）
            info_match = re.search(r'<div\s+id="info"[^>]*>(.*?)</div>', html, re.DOTALL)
            if info_match:
                info_html = info_match.group(1)

                # 集数（TMDB 未获取到时从豆瓣补充）
                if not detail["episode_count"]:
                    ep_match = re.search(r'集数:</span>\s*(\d+)', info_html)
                    if ep_match:
                        detail["episode_count"] = ep_match.group(1)

                # 单集片长（TMDB 未获取到时从豆瓣补充）
                if not detail["episode_duration"]:
                    dur_match = re.search(r'单集片长:</span>\s*(\d+)\s*分钟', info_html)
                    if dur_match:
                        detail["episode_duration"] = dur_match.group(1)

                # 首播日期（TMDB 未获取到时从豆瓣补充）
                if not detail["release_date"]:
                    date_match = re.search(r'首播:</span>\s*<span[^>]*>([^<]+)', info_html)
                    if not date_match:
                        date_match = re.search(r'上映日期:</span>\s*<span[^>]*>([^<]+)', info_html)
                    if date_match:
                        raw_date = date_match.group(1).strip()
                        date_match2 = re.search(r'(\d{4}-\d{2}-\d{2})', raw_date)
                        if date_match2:
                            detail["release_date"] = date_match2.group(1)
                        else:
                            detail["release_date"] = raw_date

                # 季数（TMDB 未获取到时从豆瓣补充）
                if not detail["season_info"]:
                    season_match = re.search(r'季数:</span>\s*(\d+)', info_html)
                    if season_match:
                        detail["season_info"] = f"S{int(season_match.group(1)):02d}"

                # 类型（豆瓣中文名优先，TMDB 的 genre_ids 不够直观）
                genres_match = re.findall(r'<span\s+property="v:genre">([^<]+)</span>', info_html)
                if genres_match:
                    detail["genres"] = " / ".join(genres_match)

                # 导演（仅豆瓣有）
                dir_match = re.findall(r'<a\s+href="/celebrity/\d+/"[^>]*rel="v:directedBy"[^>]*>([^<]+)</a>', info_html)
                if dir_match:
                    detail["director"] = " / ".join(dir_match)

                # 主演（仅豆瓣有）
                actor_match = re.findall(r'<a\s+href="/celebrity/\d+/"[^>]*rel="v:starring"[^>]*>([^<]+)</a>', info_html)
                if actor_match:
                    detail["actors"] = " / ".join(actor_match[:5])

            logger.debug(f"__fetch_douban_detail 获取到 {douban_id} 的补充数据: rating={detail['rating']}, episodes={detail['episode_count']}, date={detail['release_date']}")
        except Exception as e:
            logger.debug(f"__fetch_douban_detail 豆瓣抓取失败 ({douban_id}): {e}")

        return detail

    def __process_douban_wish(self):
        """处理豆瓣想看列表：仅对未上映条目自动订阅（需开启自动订阅开关）"""
        if not self._enable_wish:
            return

        try:
            logger.info("开始处理豆瓣想看列表")
            items = self.__fetch_douban_wish()
            if not items:
                logger.info("豆瓣想看列表为空或无数据")
                return

            # 如果未开启自动订阅，则只记录历史不执行订阅/追踪操作
            if not self._auto_subscribe_wish:
                logger.info("未开启自动订阅，仅记录豆瓣想看列表历史")
                pushed = json.loads(self._pushed_items or "{}")
                for item in items:
                    douban_id = item.get("douban_id", "")
                    if not douban_id or douban_id in pushed:
                        continue
                    pushed[douban_id] = {
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "interest": True,
                        "title": item.get("title", ""),
                        "douban_url": item.get("douban_url", ""),
                        "source": "douban_wish",
                        "auto_subscribed": False,
                    }
                self._pushed_items = json.dumps(pushed, ensure_ascii=False)
                self.__save_config()
                logger.info(f"豆瓣想看记录完成：共记录 {len(items)} 条")
                return

            pushed = json.loads(self._pushed_items or "{}")
            processed_count = 0
            subscribed_count = 0
            tracked_count = 0

            for item in items:
                douban_id = item.get("douban_id", "")
                if not douban_id:
                    continue

                # 跳过已处理的条目
                if douban_id in pushed:
                    continue

                title = item.get("title", "")
                year = item.get("year", "")

                # 尝试 TMDB 匹配
                tmdb_matched = self.__try_tmdb_match(item)

                if tmdb_matched:
                    tmdb_info = tmdb_matched
                    first_air_date = tmdb_info.get("first_air_date", "") or tmdb_info.get("release_date", "")

                    if first_air_date and len(first_air_date) >= 10:
                        # 有精确时间：添加订阅
                        self.__subscribe_tmdb(tmdb_info)
                        pushed[douban_id] = {
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "interest": True,
                            "title": title,
                            "douban_url": item.get("douban_url", ""),
                            "source": "douban_wish",
                        }
                        subscribed_count += 1
                        logger.info(f"豆瓣想看自动订阅: {title}")
                    else:
                        # 无精确时间：本地追踪
                        self.__add_tracking(item, tmdb_info)
                        pushed[douban_id] = {
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "interest": True,
                            "title": title,
                            "douban_url": item.get("douban_url", ""),
                            "source": "douban_wish",
                        }
                        tracked_count += 1
                        logger.info(f"豆瓣想看加入追踪: {title}")
                else:
                    # TMDB 匹配失败，尝试豆瓣订阅
                    douban_subscribed = self.__try_douban_subscribe(item)
                    if douban_subscribed:
                        pushed[douban_id] = {
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "interest": True,
                            "title": title,
                            "douban_url": item.get("douban_url", ""),
                            "source": "douban_wish",
                        }
                        subscribed_count += 1
                    else:
                        # 保存到本地追踪
                        self.__add_tracking(item, None)
                        pushed[douban_id] = {
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "interest": True,
                            "title": title,
                            "douban_url": item.get("douban_url", ""),
                            "source": "douban_wish",
                        }
                        tracked_count += 1

                processed_count += 1

            self._pushed_items = json.dumps(pushed, ensure_ascii=False)
            self.__save_config()
            logger.info(f"豆瓣想看处理完成：共处理 {processed_count} 条，订阅 {subscribed_count} 条，追踪 {tracked_count} 条")

        except Exception as e:
            logger.error(f"豆瓣想看处理异常: {e}")

    def __fetch_all(self) -> List[Dict]:
        all_items = []
        seen_ids = set()

        if "即将上映" in self._data_sources:
            items = self.__fetch_coming(self._sort_by, self._push_count * 2)
            for item in items:
                did = item.get("douban_id", "")
                if did and did not in seen_ids:
                    seen_ids.add(did)
                    all_items.append(item)

        if "实时热门" in self._data_sources:
            items = self.__fetch_hot()
            for item in items:
                did = item.get("douban_id", "")
                if did and did not in seen_ids:
                    seen_ids.add(did)
                    all_items.append(item)

        return all_items

    def __apply_filters(self, items: List[Dict]) -> List[Dict]:
        """应用地区筛选和短剧过滤"""
        result = []
        for item in items:
            region = item.get("region", "")

            # 地区筛选
            include_china = "中国大陆" in self._regions
            include_overseas = "海外" in self._regions
            is_china = "中国大陆" in region

            if include_china and include_overseas:
                # 两个都选，全部保留
                pass
            elif include_china and not is_china:
                # 只选中国大陆，非中国大陆跳过
                continue
            elif include_overseas and is_china:
                # 只选海外，中国大陆跳过
                continue
            elif not include_china and not include_overseas:
                # 两个都没选，全部保留
                pass

            # 短剧过滤：如果开启剔除短剧，且已知单集片长 ≤ 10分钟
            # 注意：RSS数据中无单集片长字段，这里做个占位检查
            # 如果 item 中有 episode_duration 字段且 ≤ 10，则跳过
            if self._filter_short:
                duration = item.get("episode_duration", 0)
                if isinstance(duration, (int, float)) and 0 < duration <= 10:
                    continue

            result.append(item)

        return result

    def __run_push(self):
        """每日推送流程：获取数据 → 去重 → 筛选 → 排序 → 取前N条 → 逐条推送"""
        try:
            logger.info("开始豆瓣即将播出推送")

            # 1. 获取数据
            items = self.__fetch_all()
            if not items:
                logger.info("未获取到豆瓣数据，跳过推送")
                return

            # 2. 排除已推送
            pushed = json.loads(self._pushed_items or "{}")
            unpushed = [item for item in items if item.get("douban_id") not in pushed]

            if not unpushed:
                logger.info("所有条目均已推送过，跳过")
                return

            # 3. 应用筛选（地区、短剧 - 后续Task 9会完善）
            filtered = self.__apply_filters(unpushed)

            # 4. 取前N条
            selected = filtered[:self._push_count]

            # 5. 推送到队列并逐条推送
            self._current_queue = json.dumps(selected, ensure_ascii=False)
            if selected:
                first = selected[0]
                self.__send_douban_notification(first)
                # 记录已推送
                pushed[first.get("douban_id")] = {
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "interest": None,
                    "title": first.get("title", ""),
                    "douban_url": first.get("douban_url", ""),
                    "image_url": first.get("image_url", ""),
                    "rating": first.get("rating", ""),
                    "year": first.get("year", ""),
                    "genres": first.get("genres", ""),
                }
                self._pushed_items = json.dumps(pushed, ensure_ascii=False)
            else:
                logger.info("筛选后无可用条目")

            # 6. 处理豆瓣想看（如果开启）
            self.__process_douban_wish()

            self.__save_config()

        except Exception as e:
            logger.error(f"推送流程异常: {e}")

    def __send_douban_notification(self, item: Dict):
        """发送豆瓣影视通知"""
        title = item.get("title", "未知")
        year = item.get("year", "")
        douban_url = item.get("douban_url", "")
        rating = item.get("rating", "")
        region = item.get("region", "")
        genres = item.get("genres", "")
        director = item.get("director", "")
        actors = item.get("actors", "")
        summary = item.get("summary", "")
        image_url = item.get("image_url", "")

        # 通知去重
        douban_id = item.get("douban_id", "")
        if douban_id == self._last_notify_title:
            logger.info(f"通知已发送过，跳过重复: {title}")
            return

        # 构建季数信息
        season_info = item.get("season_info", "")
        if not season_info:
            season_match = re.search(r'(S\d+|\u7B2C[一二三四五六七八九十\d]+[\u5B63\u90E8])', title)
            if season_match:
                season_info = season_match.group(1)

        # 主演行
        cast_line = f"{year} / {region} / {genres} / {director} / {actors}" if year else ""

        # 播出时间
        release_date = item.get("release_date", "")
        episode_count = item.get("episode_count", "")
        episode_duration = item.get("episode_duration", "")

        broadcast_line = ""
        if release_date:
            broadcast_line = f"{release_date}({region})首播"
            if episode_count:
                broadcast_line += f" / 共{episode_count}集"
            if episode_duration:
                broadcast_line += f" / 单集片长{episode_duration}分钟"

        # 播放平台（优先从缓存的TMDB数据获取，否则调用接口）
        streaming_platform = item.get("streaming_platform", "")
        if not streaming_platform:
            streaming_platform = self.__fetch_streaming_platform(title, year)

        # 尝试匹配TMDB获取TMDB链接和海报
        tmdb_url = ""
        tmdb_image = image_url
        try:
            tmdb_matched = self.__try_tmdb_match(item)
            if tmdb_matched:
                tmdb_id = tmdb_matched.get("id", "")
                if tmdb_id:
                    media_type = "tv" if tmdb_matched.get("first_air_date") else "movie"
                    tmdb_url = f"https://www.themoviedb.org/{media_type}/{tmdb_id}"
                    # 优先使用TMDB的海报
                    if tmdb_matched.get("poster_path"):
                        tmdb_image = f"https://image.tmdb.org/t/p/w500{tmdb_matched.get('poster_path')}"
                    # 播放平台也优先从TMDB获取
                    if not streaming_platform:
                        tp_platform = tmdb_matched.get("streaming_platform", "")
                        if tp_platform:
                            streaming_platform = tp_platform
        except Exception:
            pass

        # 链接优先使用TMDB链接，否则使用豆瓣链接
        link_url = tmdb_url if tmdb_url else douban_url

        # 构建通知文本（评分行由播放平台代替）
        text_parts = []
        text_parts.append(f"🎞 {title} ({year}) {season_info}".strip())
        if streaming_platform:
            text_parts.append(f"✨ 播放平台：{streaming_platform}")
        if cast_line:
            text_parts.append(f"👾 主演：{cast_line}")
        if broadcast_line:
            text_parts.append(f"播出时间：{broadcast_line}")
        text_parts.append(f"🔗 链接：{link_url}")

        if summary:
            text_parts.append("")
            text_parts.append("🍿 简介：")
            text_parts.append(summary)

        notify_text = "\n".join(text_parts)

        # 构建抖音搜索预告链接
        search_title = re.sub(r'\s*\(.*?\)', '', title).strip()
        douyin_search_url = f"https://www.douyin.com/search/{requests.utils.quote(search_title)}%20预告"

        # 链接按钮（跳转外部链接）
        actions = [
            {"text": "查看详情", "url": douban_url},
            {"text": "搜预告", "url": douyin_search_url},
        ]

        # 交互按钮（回调按钮，支持按钮回调通知渠道）
        buttons = [
            [
                {"text": "有兴趣", "callback_data": f"[PLUGIN]{self.__class__.__name__}|interest|{douban_id}"},
                {"text": "无兴趣", "callback_data": f"[PLUGIN]{self.__class__.__name__}|not_interest|{douban_id}"},
                {"text": "停止", "callback_data": f"[PLUGIN]{self.__class__.__name__}|stop|{douban_id}"},
            ],
        ]

        # 发送通知
        try:
            self.post_message(
                mtype=NotificationType.Plugin,
                title=f"豆瓣 - {title}",
                text=notify_text,
                image=tmdb_image if tmdb_image else None,
                actions=actions,
                buttons=buttons
            )
            logger.info(f"已推送通知: {title}")
            self._last_notify_title = douban_id
        except Exception as e:
            logger.warning(f"发送通知失败: {e}")

    def __api_push(self):
        """手动触发推送"""
        if not self._enabled:
            return {"code": 1, "message": "插件未启用"}
        self.__run_push()
        return {"code": 0, "message": "推送已触发"}

    def __api_clear_history(self):
        """清除历史记录"""
        self._pushed_items = "{}"
        self._current_queue = "[]"
        self.__save_config()
        return {"code": 0, "message": "历史记录已清除"}

    def __api_delete_history_item(self, douban_id: str = ""):
        """删除单条历史记录"""
        if not douban_id:
            return {"code": 1, "message": "缺少douban_id参数"}
        try:
            pushed = json.loads(self._pushed_items or "{}")
            if douban_id in pushed:
                del pushed[douban_id]
                self._pushed_items = json.dumps(pushed, ensure_ascii=False)
                self.__save_config()
                return {"code": 0, "message": "已删除"}
            return {"code": 1, "message": "未找到该记录"}
        except Exception as e:
            return {"code": 1, "message": f"删除失败：{str(e)}"}

    def __api_detail(self, douban_id: str = ""):
        if not douban_id:
            return {"code": 1, "message": "缺少douban_id参数"}
        url = f"https://movie.douban.com/subject/{douban_id}/"
        return {"code": 0, "data": {"url": url}}

    def __api_interest(self, douban_id: str = ""):
        """处理'有兴趣'操作：订阅后推送下一条"""
        if not douban_id:
            return {"code": 1, "message": "缺少douban_id参数"}

        # 从当前队列中查找条目
        try:
            queue = json.loads(self._current_queue or "[]")
        except Exception:
            queue = []

        item = None
        for q in queue:
            if q.get("douban_id") == douban_id:
                item = q
                break

        if not item:
            return {"code": 1, "message": "未找到该条目"}

        title = item.get("title", "")
        year = item.get("year", "")

        logger.info(f"有兴趣: {title} ({year})")

        # 更新已推送记录（保留原有信息，更新interest状态）
        pushed = json.loads(self._pushed_items or "{}")
        existing = pushed.get(douban_id, {})
        pushed[douban_id] = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "interest": True,
            "title": title,
            "douban_url": item.get("douban_url", ""),
            "image_url": item.get("image_url", "") or existing.get("image_url", ""),
            "rating": item.get("rating", "") or existing.get("rating", ""),
            "year": item.get("year", "") or existing.get("year", ""),
            "genres": item.get("genres", "") or existing.get("genres", ""),
        }
        self._pushed_items = json.dumps(pushed, ensure_ascii=False)

        # 检测是否已存在订阅，避免重复
        if self.__check_subscription_exists(douban_id=douban_id, title=title):
            logger.info(f"订阅已存在，跳过: {title}")
            result = {"code": 0, "message": f"订阅已存在，跳过: {title}", "data": {"status": "already_subscribed"}}
        else:
            # 尝试 TMDB 匹配
            tmdb_matched = self.__try_tmdb_match(item)

            if tmdb_matched:
                tmdb_info = tmdb_matched
                first_air_date = tmdb_info.get("first_air_date", "")

                if first_air_date and len(first_air_date) >= 10:
                    self.__subscribe_tmdb(tmdb_info)
                    result = {"code": 0, "message": f"已通过TMDB订阅: {title}", "data": {"status": "subscribed", "tmdb": True}}
                else:
                    self.__add_tracking(item, tmdb_info)
                    result = {"code": 0, "message": f"已加入追踪列表（等待精确时间）: {title}", "data": {"status": "tracking", "tmdb": True}}
            else:
                douban_subscribed = self.__try_douban_subscribe(item)
                if douban_subscribed:
                    result = {"code": 0, "message": f"已通过豆瓣订阅: {title}", "data": {"status": "subscribed", "douban": True}}
                else:
                    self.__add_tracking(item, None)
                    result = {"code": 0, "message": f"已加入追踪列表（等待可订阅）: {title}", "data": {"status": "tracking", "tmdb": False}}

        self.__save_config()

        # 推送下一条（与 not_interest 逻辑一致）
        next_item = None
        for q in queue:
            if q.get("douban_id") not in pushed:
                next_item = q
                break

        if next_item:
            self.__send_douban_notification(next_item)
            pushed = json.loads(self._pushed_items or "{}")
            pushed[next_item.get("douban_id")] = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "interest": None,
                "title": next_item.get("title", ""),
                "douban_url": next_item.get("douban_url", ""),
                "image_url": next_item.get("image_url", ""),
                "rating": next_item.get("rating", ""),
                "year": next_item.get("year", ""),
                "genres": next_item.get("genres", ""),
            }
            self._pushed_items = json.dumps(pushed, ensure_ascii=False)
            self.__save_config()

        return result

    def __api_not_interest(self, douban_id: str = ""):
        """处理'无兴趣'操作"""
        if not douban_id:
            return {"code": 1, "message": "缺少douban_id参数"}

        # 更新已推送记录
        pushed = json.loads(self._pushed_items or "{}")
        try:
            queue = json.loads(self._current_queue or "[]")
        except Exception:
            queue = []

        item = None
        for q in queue:
            if q.get("douban_id") == douban_id:
                item = q
                break

        if item:
            existing = pushed.get(douban_id, {})
            pushed[douban_id] = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "interest": False,
                "title": item.get("title", ""),
                "douban_url": item.get("douban_url", ""),
                "image_url": item.get("image_url", "") or existing.get("image_url", ""),
                "rating": item.get("rating", "") or existing.get("rating", ""),
                "year": item.get("year", "") or existing.get("year", ""),
                "genres": item.get("genres", "") or existing.get("genres", ""),
            }

        self._pushed_items = json.dumps(pushed, ensure_ascii=False)
        self.__save_config()

        # 推送下一条
        next_item = None
        for q in queue:
            if q.get("douban_id") not in pushed:
                next_item = q
                break

        if next_item:
            self.__send_douban_notification(next_item)
            # 记录已推送
            pushed = json.loads(self._pushed_items or "{}")
            pushed[next_item.get("douban_id")] = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "interest": None,
                "title": next_item.get("title", ""),
                "douban_url": next_item.get("douban_url", ""),
                "image_url": next_item.get("image_url", ""),
                "rating": next_item.get("rating", ""),
                "year": next_item.get("year", ""),
                "genres": next_item.get("genres", ""),
            }
            self._pushed_items = json.dumps(pushed, ensure_ascii=False)
            self.__save_config()
            return {"code": 0, "message": f"已跳过，推送下一条: {next_item.get('title', '')}"}

        return {"code": 0, "message": "已跳过，无更多待推送条目"}

    def __api_stop(self, douban_id: str = ""):
        """停止本轮继续推送，清空当前推送队列"""
        # 清空当前队列
        self._current_queue = "[]"

        # 标记当前条目状态
        if douban_id:
            pushed = json.loads(self._pushed_items or "{}")
            if douban_id in pushed:
                pushed[douban_id]["stopped"] = True
                self._pushed_items = json.dumps(pushed, ensure_ascii=False)

        self.__save_config()
        logger.info("已停止本轮推送")
        return {"code": 0, "message": "已停止本轮推送"}

    @eventmanager.register(EventType.MessageAction)
    def message_action(self, event: Event):
        """处理消息按钮回调（有兴趣/无兴趣/停止）"""
        event_data = event.event_data
        if not event_data:
            return

        # 检查是否为本插件的回调
        plugin_id = event_data.get("plugin_id")
        if plugin_id != self.__class__.__name__:
            return

        # 获取回调数据
        channel = event_data.get("channel")
        source = event_data.get("source")
        userid = event_data.get("userid")
        original_message_id = event_data.get("original_message_id")
        original_chat_id = event_data.get("original_chat_id")

        callback_text = event_data.get("text", "")
        logger.debug(f"收到消息按钮回调: {callback_text}")

        # 解析 callback_data 格式: action|douban_id 或 [PLUGIN]DoubanUpcoming|action|douban_id
        parts = callback_text.split("|")
        if len(parts) < 2:
            logger.warning(f"无法解析回调数据: {callback_text}")
            return

        # 处理带 [PLUGIN] 前缀的情况
        if len(parts) >= 3 and parts[0].startswith("[PLUGIN]"):
            action = parts[1]
            douban_id = parts[2]
        else:
            action = parts[0]
            douban_id = parts[1] if len(parts) > 1 else ""

        if action == "有兴趣" or action == "interest":
            result = self.__api_interest(douban_id)
            if result.get("code") != 0:
                self.post_message(
                    channel=channel,
                    mtype=NotificationType.Plugin,
                    title="处理失败",
                    text=result.get("message", "操作失败"),
                    userid=userid,
                    original_message_id=original_message_id,
                    original_chat_id=original_chat_id
                )
        elif action == "无兴趣" or action == "not_interest":
            result = self.__api_not_interest(douban_id)
            # not_interest 会自动推送下一条通知
        elif action == "停止" or action == "stop":
            result = self.__api_stop(douban_id)
            self.post_message(
                channel=channel,
                mtype=NotificationType.Plugin,
                title="已停止推送",
                text="本轮推送已停止，不再继续推送下一条。",
                userid=userid,
                original_message_id=original_message_id,
                original_chat_id=original_chat_id
            )
        else:
            logger.debug(f"未知的回调动作: {action}")

    def __check_subscription_exists(self, douban_id: str = "", tmdb_id: int = None, title: str = "") -> bool:
        """检测是否已存在订阅，避免重复订阅"""
        try:
            from app.db.subscribe_oper import SubscribeOper
            sub_oper = SubscribeOper()
            if douban_id:
                exists = sub_oper.exists(doubanid=douban_id)
                if exists:
                    return True
            if tmdb_id:
                exists = sub_oper.exists(tmdbid=tmdb_id)
                if exists:
                    return True
            if title:
                exists = sub_oper.exists(name=title)
                if exists:
                    return True
            return False
        except Exception as e:
            logger.debug(f"检查订阅是否存在失败: {e}")
            return False

    def __try_tmdb_match(self, item: Dict) -> Optional[Dict]:
        """尝试通过标题+年份搜索TMDB，返回匹配结果字典（优先使用 MoviePilot 官方 MediaChain API，参照 doubansync）"""
        try:
            title = item.get("title", "")
            year = item.get("year", "")
            douban_id = item.get("douban_id", "")

            if not title:
                return None

            # --- 优先方案：使用 MoviePilot 官方 MediaChain API（参照 doubansync） ---
            try:
                from app.chain.media import MediaChain
                from app.core.metainfo import MetaInfo

                mediachain = MediaChain()

                # 通过豆瓣ID获取TMDB信息
                if douban_id:
                    try:
                        tmdbinfo = mediachain.get_tmdbinfo_by_doubanid(doubanid=douban_id, mtype=MediaType.TV)
                        if tmdbinfo:
                            return tmdbinfo
                        tmdbinfo = mediachain.get_tmdbinfo_by_doubanid(doubanid=douban_id, mtype=MediaType.MOVIE)
                        if tmdbinfo:
                            return tmdbinfo
                    except Exception:
                        pass

                # 通过标题+年份识别媒体
                try:
                    meta = MetaInfo(title=title, year=year)
                    mediainfo = mediachain.recognize_media(meta=meta)
                    if mediainfo and mediainfo.tmdb_id:
                        return {
                            "id": mediainfo.tmdb_id,
                            "name": mediainfo.title,
                            "title": mediainfo.title,
                            "first_air_date": str(mediainfo.year) if mediainfo.year else "",
                            "release_date": str(mediainfo.year) if mediainfo.year else "",
                            "poster_path": mediainfo.get_poster_image() or "",
                            "overview": mediainfo.overview or "",
                            "media_type": mediainfo.type.value if mediainfo.type else "",
                        }
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"MediaChain 匹配失败，回退到 TmdbChain 直接搜索: {e}")

            # --- 回退方案：使用 TmdbChain 直接搜索 TMDB ---
            try:
                from app.chain.tmdb import TmdbChain
                tmdbchain = TmdbChain()
            except Exception:
                return None

            # 优先通过豆瓣ID匹配
            if douban_id:
                try:
                    tmdbinfo = tmdbchain.tmdb_info(doubanid=douban_id, mtype=MediaType.TV)
                    if tmdbinfo:
                        return tmdbinfo
                    tmdbinfo = tmdbchain.tmdb_info(doubanid=douban_id, mtype=MediaType.MOVIE)
                    if tmdbinfo:
                        return tmdbinfo
                except Exception:
                    pass

            # 按标题搜索TV
            try:
                results = tmdbchain.search_tv(title=title, year=year)
                if results and results.get("results"):
                    first = results["results"][0]
                    result_year = (first.get("first_air_date", "") or "")[:4]
                    if not year or result_year == str(year):
                        return first
                    if first.get("name", "") == title:
                        return first
            except Exception:
                pass

            # 按标题搜索Movie
            try:
                results = tmdbchain.search_movie(title=title, year=year)
                if results and results.get("results"):
                    first = results["results"][0]
                    result_year = (first.get("release_date", "") or "")[:4]
                    if not year or result_year == str(year):
                        return first
                    if first.get("title", "") == title:
                        return first
            except Exception:
                pass

            return None
        except Exception as e:
            logger.debug(f"TMDB匹配失败: {e}")
            return None

    def __try_douban_subscribe(self, item: Dict) -> bool:
        """尝试豆瓣订阅：通过 SubscribeChain 添加订阅（先检测是否已存在）"""
        try:
            douban_id = item.get("douban_id", "")
            title = item.get("title", "")
            year = item.get("year", "")

            if not douban_id:
                return False

            # 检测是否已存在订阅
            if self.__check_subscription_exists(douban_id=douban_id, title=title):
                logger.info(f"豆瓣订阅已存在，跳过: {title}")
                return True  # 已存在也算成功

            logger.info(f"尝试豆瓣订阅: {title} ({douban_id})")

            try:
                from app.chain.subscribe import SubscribeChain
                sub_id, message = SubscribeChain().add(
                    title=title,
                    year=year,
                    mtype=MediaType.TV,
                    doubanid=douban_id,
                    exist_ok=True,
                )
                if sub_id:
                    logger.info(f"豆瓣订阅成功: {title}")
                    return True
                else:
                    logger.warning(f"豆瓣订阅失败: {title} - {message}")
                    return False
            except Exception as e:
                logger.warning(f"豆瓣订阅失败: {e}")
                return False

        except Exception as e:
            logger.warning(f"豆瓣订阅异常: {e}")
            return False

    def __set_release_reminder(self, tmdb_info: Dict, release_date: str):
        """设置开播前24小时提醒通知"""
        try:
            title = tmdb_info.get("name") or tmdb_info.get("title", "")
            tmdb_id = tmdb_info.get("id", "")

            if not release_date or len(release_date) < 10:
                logger.warning(f"无法设置提醒：缺少精确开播日期 ({title})")
                return

            # 计算提醒时间：开播前24小时
            release_dt = datetime.strptime(release_date, "%Y-%m-%d")
            reminder_dt = release_dt - timedelta(hours=24)

            # 如果提醒时间已过，跳过
            if reminder_dt <= datetime.now():
                logger.info(f"开播提醒时间已过，跳过: {title} ({release_date})")
                return

            # 注册一次性定时任务
            job_id = f"douban_reminder_{tmdb_id}_{release_date}"
            try:
                self._scheduler.add_job(
                    func=self.__send_reminder_notification,
                    trigger=DateTrigger(run_date=reminder_dt),
                    args=[title, tmdb_id, release_date],
                    id=job_id,
                    name=f"开播提醒 - {title}",
                    replace_existing=True,
                )
                logger.info(f"已设置开播前24小时提醒: {title} | 开播: {release_date} | 提醒: {reminder_dt}")
            except Exception as e:
                logger.warning(f"注册提醒任务失败: {e}")

        except Exception as e:
            logger.warning(f"设置开播提醒失败: {e}")

    def __send_reminder_notification(self, title: str, tmdb_id: str, release_date: str):
        """发送开播前24小时提醒通知"""
        try:
            notify_text = (
                f"🎞 {title}\n\n"
                f" 播出时间：{release_date}\n"
                f"⏰ 距开播还有24小时，记得准时观看！"
            )
            self.post_message(
                mtype=NotificationType.Plugin,
                title=f"开播提醒 - {title}",
                text=notify_text,
            )
            logger.info(f"已发送开播提醒通知: {title}")
        except Exception as e:
            logger.warning(f"发送开播提醒通知失败: {e}")

    def __fetch_streaming_platform_from_tmdb(self, title: str, year: str = "") -> str:
        """从 TMDB 获取播放平台信息（优先）"""
        if not title:
            return ""
        try:
            from app.chain.tmdb import TmdbChain
            from app.core.config import settings
            tmdbchain = TmdbChain()

            # 搜索 TV
            tv_results = tmdbchain.search_tv(title=title, year=year)
            media_type = "tv"
            search_results = []
            if tv_results and tv_results.get("results"):
                search_results = tv_results["results"]
            else:
                # 也搜索 Movie
                movie_results = tmdbchain.search_movie(title=title, year=year)
                if movie_results and movie_results.get("results"):
                    search_results = movie_results["results"]
                    media_type = "movie"

            if not search_results:
                return ""

            # 取第一个结果
            first = search_results[0]
            tmdb_id = first.get("id")
            if not tmdb_id:
                return ""

            # 验证标题是否匹配
            result_title = first.get("name", "") or first.get("title", "")
            result_year = first.get("first_air_date", "") or first.get("release_date", "")
            result_year = result_year[:4] if result_year else ""
            if result_title != title and result_year != str(year):
                return ""

            # 调用 TMDB watch providers API
            api_key = getattr(settings, "TMDB_API_KEY", "")
            if not api_key:
                return ""

            tmdb_domain = getattr(settings, "TMDB_DOMAIN", "api.themoviedb.org")
            provider_url = f"https://{tmdb_domain}/3/{media_type}/{tmdb_id}/watch/providers?api_key={api_key}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.get(provider_url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", {})
            if not results:
                return ""

            # 优先取中国大陆 (CN)，其次取美国 (US)，最后取全部结果中的 flatrate
            priority_regions = ["CN", "US"]
            provider_names = []
            provider_keywords_map = {
                "腾讯视频": ["Tencent Video", "tencent", "腾讯视频", "腾讯"],
                "爱奇艺": ["iQIYI", "iqiyi", "爱奇艺"],
                "优酷": ["Youku", "youku", "优酷"],
                "芒果TV": ["Mango TV", "mgtv", "芒果TV", "芒果"],
                "B站": ["Bilibili", "bilibili", "哔哩哔哩", "B站"],
                "Netflix": ["Netflix", "网飞", "奈飞"],
                "Disney+": ["Disney Plus", "Disney+", "迪士尼+"],
                "HBO": ["HBO Max", "HBO"],
                "Amazon": ["Amazon Prime Video", "Amazon Prime", "Prime Video", "亚马逊"],
                "Hulu": ["Hulu"],
                "Apple TV+": ["Apple TV Plus", "Apple TV+", "苹果tv+"],
                "Paramount+": ["Paramount Plus", "Paramount+", "派拉蒙+"],
            }

            for region in priority_regions:
                region_data = results.get(region, {})
                flatrate = region_data.get("flatrate", [])
                if flatrate:
                    for prov in flatrate:
                        prov_name = prov.get("provider_name", "")
                        # 匹配标准平台名
                        matched = False
                        for std_name, keywords in provider_keywords_map.items():
                            for kw in keywords:
                                if kw.lower() in prov_name.lower() or prov_name.lower() == kw.lower():
                                    if std_name not in provider_names:
                                        provider_names.append(std_name)
                                    matched = True
                                    break
                            if matched:
                                break
                        if not matched and prov_name:
                            provider_names.append(prov_name)
                    break

            if provider_names:
                result = " / ".join(provider_names)
                logger.info(f"播放平台(TMDB): {title} -> {result}")
                return result

            return ""
        except Exception as e:
            logger.debug(f"从 TMDB 获取播放平台失败 ({title}): {e}")
            return ""

    def __fetch_streaming_platform_from_web(self, title: str) -> str:
        """从网页搜索获取播放平台信息（回退方案）"""
        if not title:
            return ""
        try:
            search_query = f"{title} 哪个平台播出"
            search_url = f"https://www.bing.com/search?q={requests.utils.quote(search_query)}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(search_url, headers=headers, timeout=10)
            resp.raise_for_status()
            html = resp.text

            # 只提取搜索结果摘要文本，避免页面其他部分（广告、侧边栏等）的干扰
            # Bing 搜索结果摘要通常在 <p class="b_lineclamp..."> 或 <div class="b_caption"><p> 中
            snippets = re.findall(r'<p\s+class="b_lineclamp[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
            if not snippets:
                snippets = re.findall(r'<div\s+class="b_caption">.*?<p[^>]*>(.*?)</p>', html, re.DOTALL)

            # 合并所有摘要文本并清理 HTML 标签
            search_text = ' '.join(snippets)
            search_text = re.sub(r'<[^>]+>', '', search_text)
            search_text = unescape(search_text)

            if not search_text:
                logger.info(f"未找到搜索结果摘要: {title}")
                return ""

            # 在摘要文本中匹配平台关键词（而非整个 HTML 页面）
            platforms = []
            platform_keywords = {
                "腾讯视频": ["腾讯视频", "腾讯"],
                "爱奇艺": ["爱奇艺", "iqiyi", "IQIYI"],
                "优酷": ["优酷", "youku", "YOUKU"],
                "芒果TV": ["芒果TV", "芒果tv", "mgtv", "MGTV"],
                "B站": ["B站", "bilibili", "哔哩哔哩", "Bilibili"],
                "央视": ["CCTV", "央视"],
                "卫视": ["卫视"],
                "Netflix": ["Netflix", "网飞", "奈飞"],
                "Disney+": ["Disney+", "迪士尼+"],
                "HBO": ["HBO"],
                "Amazon": ["Amazon Prime", "亚马逊"],
                "Hulu": ["Hulu"],
            }

            for platform, keywords in platform_keywords.items():
                for kw in keywords:
                    if kw.lower() in search_text.lower():
                        if platform not in platforms:
                            platforms.append(platform)
                        break

            if platforms:
                result = " / ".join(platforms)
                logger.info(f"播放平台(网页): {title} -> {result}")
                return result

            logger.info(f"未找到播放平台信息: {title}")
            return ""
        except Exception as e:
            logger.warning(f"搜索播放平台失败 ({title}): {e}")
            return ""

    def __fetch_streaming_platform(self, title: str, year: str = "") -> str:
        """搜索播放平台信息（优先 TMDB，无结果则网页搜索回退）"""
        if not title:
            return ""
        # 优先从 TMDB 获取
        tmdb_result = self.__fetch_streaming_platform_from_tmdb(title, year)
        if tmdb_result:
            return tmdb_result
        # 回退到网页搜索
        return self.__fetch_streaming_platform_from_web(title)

    def __fetch_dingdang_time(self, title: str) -> str:
        """搜索定档时间（通过Bing搜索）"""
        if not title:
            return ""
        try:
            search_query = f"{title} 定档时间"
            search_url = f"https://www.bing.com/search?q={requests.utils.quote(search_query)}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(search_url, headers=headers, timeout=10)
            resp.raise_for_status()
            html = resp.text

            # 搜索日期格式
            date_patterns = [
                r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?)',
                r'定档[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?)',
                r'播出[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?)',
            ]
            for pattern in date_patterns:
                match = re.search(pattern, html)
                if match:
                    date_str = match.group(1)
                    logger.info(f"定档时间搜索结果: {title} -> {date_str}")
                    return date_str

            return ""
        except Exception as e:
            logger.warning(f"搜索定档时间失败 ({title}): {e}")
            return ""

    def __subscribe_tmdb(self, tmdb_info: Dict):
        """添加TMDB订阅（先检测是否已存在）"""
        try:
            tmdb_id = tmdb_info.get("id")
            title = tmdb_info.get("name") or tmdb_info.get("title", "")
            media_type = MediaType.TV if tmdb_info.get("first_air_date") else MediaType.MOVIE
            first_air_date = tmdb_info.get("first_air_date", "") or tmdb_info.get("release_date", "")
            year = first_air_date[:4] if first_air_date else ""

            # 检测是否已存在订阅
            if self.__check_subscription_exists(tmdb_id=tmdb_id, title=title):
                logger.info(f"TMDB订阅已存在，跳过: {title}")
                return

            logger.info(f"添加TMDB订阅: {title} (tmdb_id={tmdb_id}, type={media_type.value})")

            # 调用 SubscribeChain 添加订阅
            from app.chain.subscribe import SubscribeChain
            sub_id, message = SubscribeChain().add(
                title=title,
                year=year,
                mtype=media_type,
                tmdbid=tmdb_id,
                exist_ok=True,
            )
            if not sub_id:
                logger.warning(f"TMDB订阅失败: {title} - {message}")

            # 设置开播前24小时提醒
            if first_air_date and len(first_air_date) >= 10:
                self.__set_release_reminder(tmdb_info, first_air_date)
        except Exception as e:
            logger.warning(f"TMDB订阅失败: {e}")

    def __add_tracking(self, item: Dict, tmdb_info: Optional[Dict] = None):
        """保存到本地追踪记录"""
        try:
            tracking = json.loads(self._tracking_items or "[]")
            tracking.append({
                "douban_id": item.get("douban_id", ""),
                "title": item.get("title", ""),
                "year": item.get("year", ""),
                "douban_url": item.get("douban_url", ""),
                "added_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "tmdb_id": tmdb_info.get("id") if tmdb_info else None,
            })
            self._tracking_items = json.dumps(tracking, ensure_ascii=False)
            logger.info(f"已添加到追踪列表: {item.get('title', '')}")
        except Exception as e:
            logger.warning(f"添加追踪失败: {e}")

    def __refresh_tracking(self):
        """每日刷新本地追踪记录，检查是否有TMDB可订阅或精确时间出现"""
        try:
            tracking = json.loads(self._tracking_items or "[]")
            if not tracking:
                return

            logger.info(f"开始刷新本地追踪记录，共 {len(tracking)} 条")

            updated_tracking = []
            for item in tracking:
                try:
                    douban_id = item.get("douban_id", "")
                    title = item.get("title", "")

                    # 尝试 TMDB 匹配
                    tmdb_matched = self.__try_tmdb_match(item)

                    if tmdb_matched:
                        first_air_date = tmdb_matched.get("first_air_date", "") or tmdb_matched.get("release_date", "")

                        if first_air_date and len(first_air_date) >= 10:
                            # 有精确时间，自动订阅
                            self.__subscribe_tmdb(tmdb_matched)
                            logger.info(f"追踪记录已自动订阅: {title}")
                            # 发送通知
                            self.post_message(
                                mtype=NotificationType.Plugin,
                                title=f"豆瓣追踪 - {title} 已自动订阅",
                                text=f"🎞 {title}\n已通过TMDB匹配成功并自动添加订阅，开播日期：{first_air_date}"
                            )
                            # 不加入 updated_tracking（已订阅，移除）
                            continue
                        else:
                            # TMDB匹配但无精确时间，更新 tmdb_id
                            item["tmdb_id"] = tmdb_matched.get("id")
                            updated_tracking.append(item)
                            continue
                    else:
                        # TMDB 匹配失败，尝试搜索定档时间
                        dingdang_time = self.__fetch_dingdang_time(item.get("title", ""))
                        if dingdang_time:
                            # 找到定档时间，尝试解析日期
                            date_match = re.search(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})', dingdang_time)
                            if date_match:
                                y, m, d = date_match.group(1), date_match.group(2), date_match.group(3)
                                release_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
                                logger.info(f"追踪刷新找到定档时间: {title} -> {release_date}")
                                # 保存定档时间到 item
                                item["release_date"] = release_date

                        # 尝试豆瓣订阅
                        douban_subscribed = self.__try_douban_subscribe(item)
                        if douban_subscribed:
                            logger.info(f"追踪记录已通过豆瓣订阅: {title}")
                            self.post_message(
                                mtype=NotificationType.Plugin,
                                title=f"豆瓣追踪 - {title} 已订阅",
                                text=f"🎞 {title}\n已通过豆瓣订阅成功添加订阅"
                            )
                            continue  # 已订阅，移除

                        updated_tracking.append(item)

                except Exception as e:
                    logger.warning(f"刷新追踪条目失败 ({item.get('title', '')}): {e}")
                    updated_tracking.append(item)

            self._tracking_items = json.dumps(updated_tracking, ensure_ascii=False)
            self.__save_config()
            logger.info(f"追踪刷新完成，剩余 {len(updated_tracking)} 条")

        except Exception as e:
            logger.error(f"追踪刷新异常: {e}")
