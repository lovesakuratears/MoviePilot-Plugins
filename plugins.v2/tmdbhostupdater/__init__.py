from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime, timedelta
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
import requests

from app.core.event import eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType
from app.utils.ip import IpUtils
from app.utils.system import SystemUtils


class TmdbHostUpdater(_PluginBase):
    plugin_name = "TMDB Host更新"
    plugin_desc = "定时从CheckTMDB获取最新TMDB hosts，自动更新系统hosts文件，解决TMDB无法访问问题。"
    plugin_icon = "hosts.png"
    plugin_version = "1.0.7"
    plugin_author = "lovesakuratears"
    author_url = "https://github.com/cnwikee/CheckTMDB"
    plugin_config_prefix = "tmdbhostupdater_"
    plugin_order = 11
    auth_level = 1

    _enabled = False
    _interval = 6
    _ipv4_url = "https://raw.githubusercontent.com/cnwikee/CheckTMDB/main/Tmdb_host_ipv4"
    _ipv6_url = "https://raw.githubusercontent.com/cnwikee/CheckTMDB/main/Tmdb_host_ipv6"
    _github_mirror = "https://gh-proxy.com/"
    _enable_ipv6 = False
    _clear_on_stop = False
    _last_update_time = ""
    _last_update_status = ""
    _current_hosts = ""
    _manual_hosts = ""

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled", False)
            self._interval = float(config.get("interval", 6))
            self._ipv4_url = config.get("ipv4_url", self._ipv4_url)
            self._ipv6_url = config.get("ipv6_url", self._ipv6_url)
            self._github_mirror = config.get("github_mirror", self._github_mirror) or "https://gh-proxy.com/"
            self._enable_ipv6 = config.get("enable_ipv6", False)
            self._clear_on_stop = config.get("clear_on_stop", False)
            self._last_update_time = config.get("last_update_time", "")
            self._last_update_status = config.get("last_update_status", "")
            self._current_hosts = config.get("current_hosts", "")
            self._manual_hosts = config.get("manual_hosts", "")

        # 加载时从系统 hosts 读取完整内容，让手动编辑框显示真实 hosts 便于直观编辑
        system_hosts_content = self.__read_system_hosts_text()
        if system_hosts_content and system_hosts_content != self._manual_hosts:
            self._manual_hosts = system_hosts_content
            # 持久化到配置，确保表单能显示当前系统 hosts 内容
            self.__save_config()

        if not self._enabled and self._clear_on_stop and self._current_hosts:
            self.__clear_system_hosts()
            self._current_hosts = ""
            self._manual_hosts = self.__read_system_hosts_text()
            self.__save_config()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/tmdbhost_update",
                "event": EventType.PluginAction,
                "desc": "更新TMDB Hosts",
                "category": "插件命令",
                "data": {
                    "action": "tmdbhost_update"
                }
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/update",
                "endpoint": self.__api_update,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即更新TMDB Hosts",
                "description": "手动触发一次TMDB hosts更新",
            },
            {
                "path": "/save_manual",
                "endpoint": self.__api_save_manual,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "保存手动编辑的Hosts",
                "description": "验证并保存用户手动编辑的hosts内容到系统hosts文件",
            },
            {
                "path": "/status",
                "endpoint": self.__api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取更新状态",
                "description": "获取当前hosts更新状态和列表",
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        services = [
            {
                "id": f"{self.__class__.__name__}.Update",
                "name": "TMDB Host定时更新",
                "trigger": IntervalTrigger(hours=self._interval),
                "func": self.__run_update,
                "kwargs": {},
            }
        ]
        if not self._last_update_time:
            services.append({
                "id": f"{self.__class__.__name__}.FirstRun",
                "name": "TMDB Host首次更新",
                "trigger": DateTrigger(run_date=datetime.now() + timedelta(minutes=1)),
                "func": self.__run_update,
                "kwargs": {},
            })
        return services

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
                                            'text': '数据来源：CheckTMDB项目 (https://github.com/cnwikee/CheckTMDB)。'
                                                    '容器运行则更新容器内hosts，非宿主机！'
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
                                            'model': 'enable_ipv6',
                                            'label': '启用IPv6',
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
                                            'model': 'interval',
                                            'label': '更新间隔（小时）',
                                            'type': 'number',
                                            'min': 0.5,
                                            'step': 0.5,
                                            'placeholder': '默认6小时'
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
                                            'model': 'clear_on_stop',
                                            'label': '停用清理Hosts',
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
                                            'model': 'ipv4_url',
                                            'label': 'IPv4 Hosts地址',
                                            'placeholder': 'IPv4 hosts文件URL'
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
                                            'model': 'ipv6_url',
                                            'label': 'IPv6 Hosts地址',
                                            'placeholder': 'IPv6 hosts文件URL'
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
                                        'component': 'VAutocomplete',
                                        'props': {
                                            'model': 'github_mirror',
                                            'label': 'GitHub加速镜像',
                                            'placeholder': '选择或输入镜像地址（含末尾斜杠）',
                                            'items': [
                                                'https://gh-proxy.com/',
                                                'https://ghproxy.net/',
                                                'https://github.akams.cn/',
                                                'https://hub.fastgit.xyz',
                                                'https://kkgithub.com',
                                                'https://hub.nuaa.cf',
                                                'https://github.com.cnpmjs.org'
                                            ],
                                            'clearable': True,
                                            'hint': '留空则不使用镜像，主URL失败时还会自动尝试 jsdelivr CDN',
                                            'persistent-hint': True
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
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'manual_hosts',
                                            'label': '手动编辑Hosts（完整 /etc/hosts 内容，每行一条：IP 域名，# 开头为注释）',
                                            'rows': 15,
                                            'auto-grow': True,
                                            'placeholder': '示例：\n127.0.0.1 localhost\n::1 localhost ip6-localhost ip6-loopback\n# TmdbHostUpdaterPlugin\n13.224.0.42 api.themoviedb.org'
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
                                    'class': 'text-right'
                                },
                                'content': [
                                    {
                                        'component': 'VBtn',
                                        'props': {
                                            'color': 'success',
                                            'variant': 'flat',
                                            'block': True,
                                            'prependIcon': 'mdi-content-save'
                                        },
                                        'events': {
                                            'click': {
                                                'api': 'plugin/TmdbHostUpdater/save_manual',
                                                'method': 'post',
                                                'params': {}
                                            }
                                        },
                                        'text': '保存并应用到系统'
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "interval": 6,
            "ipv4_url": "https://raw.githubusercontent.com/cnwikee/CheckTMDB/main/Tmdb_host_ipv4",
            "ipv6_url": "https://raw.githubusercontent.com/cnwikee/CheckTMDB/main/Tmdb_host_ipv6",
            "github_mirror": "",
            "enable_ipv6": False,
            "clear_on_stop": False,
            "last_update_time": "",
            "last_update_status": "",
            "current_hosts": "",
            "manual_hosts": ""
        }

    def get_page(self) -> List[dict]:
        status_text = "未更新"
        status_type = "warning"
        if self._last_update_status == "success":
            status_text = f"更新成功 - {self._last_update_time}"
            status_type = "success"
        elif self._last_update_status == "failed":
            status_text = f"更新失败 - {self._last_update_time}"
            status_type = "error"

        hosts_text = self._current_hosts or "暂无数据，请点击右上角\"立即更新\"按钮获取"

        return [
            {
                'component': 'VCard',
                'props': {
                    'variant': 'tonal',
                    'class': 'mb-4'
                },
                'content': [
                    {
                        'component': 'VCardText',
                        'content': [
                            {
                                'component': 'VRow',
                                'props': {
                                    'align': 'center'
                                },
                                'content': [
                                    {
                                        'component': 'VCol',
                                        'props': {
                                            'cols': 12,
                                            'md': 8
                                        },
                                        'content': [
                                            {
                                                'component': 'VAlert',
                                                'props': {
                                                    'type': status_type,
                                                    'variant': 'tonal',
                                                    'text': f'最后更新：{status_text}'
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'VCol',
                                        'props': {
                                            'cols': 12,
                                            'md': 4,
                                            'class': 'text-right'
                                        },
                                        'content': [
                                            {
                                                'component': 'VBtn',
                                                'props': {
                                                    'color': 'primary',
                                                    'variant': 'flat',
                                                },
                                                'events': {
                                                    'click': {
                                                        'api': 'plugin/TmdbHostUpdater/update',
                                                        'method': 'post',
                                                        'params': {}
                                                    }
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VIcon',
                                                        'props': {
                                                            'start': True
                                                        },
                                                        'text': 'mdi-refresh'
                                                    },
                                                    '立即更新'
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                'component': 'VCard',
                'props': {
                    'variant': 'tonal'
                },
                'content': [
                    {
                        'component': 'VCardTitle',
                        'text': '当前生效的Hosts'
                    },
                    {
                        'component': 'VCardText',
                        'content': [
                            {
                                'component': 'pre',
                                'props': {
                                    'class': 'text-body-2 pa-2',
                                    'style': 'white-space: pre-wrap; word-break: break-all; max-height: 480px; overflow-y: auto;'
                                },
                                'text': hosts_text
                            }
                        ]
                    }
                ]
            }
        ]

    def stop_service(self):
        if self._clear_on_stop and self._current_hosts:
            self.__clear_system_hosts()
            self._current_hosts = ""
            self._last_update_time = ""
            self._last_update_status = ""
            self.__save_config()

    @eventmanager.register(EventType.PluginAction)
    def on_plugin_action(self, event):
        event_data = event.event_data or {}
        if event_data.get("action") != "tmdbhost_update":
            return
        if not self._enabled:
            return
        self.__run_update()

    @eventmanager.register(EventType.PluginReload)
    def reload(self, event):
        plugin_id = event.event_data.get("plugin_id")
        if not plugin_id:
            return
        if plugin_id != self.__class__.__name__:
            return
        return self.init_plugin(self.get_config())

    def __build_url(self, url: str) -> str:
        if not self._github_mirror:
            return url
        mirror = self._github_mirror.rstrip('/')
        if "raw.githubusercontent.com" in url:
            return url.replace("https://raw.githubusercontent.com", mirror + "/raw.githubusercontent.com")
        elif "github.com" in url and "blob" in url:
            return url.replace("https://github.com", mirror + "/github.com")
        return url

    def __fetch_hosts(self, url: str) -> Optional[str]:
        real_url = self.__build_url(url)
        urls_to_try = [real_url]

        # 主 URL 失败时尝试 jsdelivr CDN 备用（仅当 URL 来自 raw.githubusercontent.com 且未配置镜像时）
        if "raw.githubusercontent.com" in real_url and not self._github_mirror:
            stripped = real_url.replace("https://raw.githubusercontent.com/", "")
            parts = stripped.split("/", 3)
            if len(parts) == 4:
                user, repo, branch, path = parts
                fallback = f"https://cdn.jsdelivr.net/gh/{user}/{repo}@{branch}/{path}"
                if fallback not in urls_to_try:
                    urls_to_try.append(fallback)

        last_err = None
        for try_url in urls_to_try:
            try:
                logger.info(f"获取TMDB hosts: {try_url}")
                response = requests.get(try_url, timeout=15)
                response.raise_for_status()
                return response.text
            except Exception as e:
                last_err = e
                logger.warning(f"获取TMDB hosts失败 [{try_url}]: {str(e)}")

        logger.error(f"所有URL尝试均失败: {str(last_err)}")
        return None

    def __parse_hosts(self, content: str) -> List[str]:
        hosts = []
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                ip = parts[0]
                if IpUtils.is_ipv4(ip) or ":" in ip:
                    hosts.append(line)
        return hosts

    def __get_hosts_path(self) -> str:
        if SystemUtils.is_windows():
            return r"c:\windows\system32\drivers\etc\hosts"
        return '/etc/hosts'

    def __read_system_hosts_text(self) -> str:
        """读取系统hosts文件完整内容"""
        hosts_path = self.__get_hosts_path()
        try:
            with open(hosts_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"读取系统hosts失败：{str(e)}")
            return ""

    def __clear_system_hosts(self):
        hosts_path = self.__get_hosts_path()
        try:
            with open(hosts_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                if line.strip() == "# TmdbHostUpdaterPlugin":
                    break
                new_lines.append(line)
            with open(hosts_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            logger.info("TMDB Hosts已从系统hosts中清除")
        except Exception as err:
            logger.error(f"清除系统hosts文件失败：{str(err) or '请检查权限'}")

    def __add_hosts_to_system(self, hosts: List[str]) -> bool:
        if not hosts:
            return False
        hosts_path = self.__get_hosts_path()
        try:
            with open(hosts_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                if line.strip() == "# TmdbHostUpdaterPlugin":
                    break
                new_lines.append(line)
            if new_lines and not new_lines[-1].endswith('\n'):
                new_lines[-1] += '\n'
            if new_lines and new_lines[-1].strip() != '':
                new_lines.append('\n')
            new_lines.append("# TmdbHostUpdaterPlugin\n")
            for host in hosts:
                new_lines.append(host + '\n')
            with open(hosts_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            logger.info(f"更新系统hosts文件成功，共{len(hosts)}条记录")
            return True
        except Exception as err:
            logger.error(f"更新系统hosts文件失败：{str(err) or '请检查权限'}")
            return False

    def __run_update(self):
        try:
            logger.info("开始更新TMDB Hosts")

            all_hosts = []

            ipv4_content = self.__fetch_hosts(self._ipv4_url)
            if ipv4_content:
                ipv4_hosts = self.__parse_hosts(ipv4_content)
                all_hosts.extend(ipv4_hosts)
                logger.info(f"获取IPv4 hosts: {len(ipv4_hosts)}条")

            if self._enable_ipv6 and self._ipv6_url:
                ipv6_content = self.__fetch_hosts(self._ipv6_url)
                if ipv6_content:
                    ipv6_hosts = self.__parse_hosts(ipv6_content)
                    all_hosts.extend(ipv6_hosts)
                    logger.info(f"获取IPv6 hosts: {len(ipv6_hosts)}条")

            if not all_hosts:
                logger.error("未获取到任何hosts数据")
                self._last_update_status = "failed"
                self._last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.__save_config()
                return False

            success = self.__add_hosts_to_system(all_hosts)

            self._last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if success:
                self._last_update_status = "success"
                self._current_hosts = '\n'.join(all_hosts)
                # 定时更新只修改了插件管理的部分，重新读取完整系统 hosts 同步到编辑框
                self._manual_hosts = self.__read_system_hosts_text()
                logger.info("TMDB Hosts更新完成")
            else:
                self._last_update_status = "failed"
                logger.error("TMDB Hosts更新失败")

            self.__save_config()
            return success

        except Exception as e:
            logger.error(f"更新TMDB Hosts异常: {str(e)}")
            self._last_update_status = "failed"
            self._last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.__save_config()
            return False

    def __save_config(self):
        self.update_config({
            "enabled": self._enabled,
            "interval": self._interval,
            "ipv4_url": self._ipv4_url,
            "ipv6_url": self._ipv6_url,
            "github_mirror": self._github_mirror,
            "enable_ipv6": self._enable_ipv6,
            "clear_on_stop": self._clear_on_stop,
            "last_update_time": self._last_update_time,
            "last_update_status": self._last_update_status,
            "current_hosts": self._current_hosts,
            "manual_hosts": self._manual_hosts
        })

    def __api_update(self):
        if not self._enabled:
            return {"code": 1, "message": "插件未启用"}
        success = self.__run_update()
        if success:
            return {"code": 0, "message": "更新成功", "data": {"status": self._last_update_status, "time": self._last_update_time}}
        else:
            return {"code": 1, "message": "更新失败", "data": {"status": self._last_update_status, "time": self._last_update_time}}

    def __api_save_manual(self):
        """保存用户手动编辑的hosts：校验格式后整段覆盖写入系统hosts文件"""
        content = self._manual_hosts or ""
        if not content.strip():
            return {"code": 1, "message": "内容为空，拒绝保存（清空hosts请使用停用清理选项）"}

        ok, msg, valid_lines = self.__validate_hosts(content)
        if not ok:
            return {"code": 1, "message": f"格式校验失败：{msg}"}

        # 整段覆盖写入系统 hosts 文件
        hosts_path = self.__get_hosts_path()
        try:
            with open(hosts_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(valid_lines))
                if not valid_lines or not valid_lines[-1].endswith('\n'):
                    f.write('\n')
            self._last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._last_update_status = "success"
            # current_hosts 记录插件相关的条目（标记行之后的内容）
            plugin_section = []
            in_section = False
            for line in valid_lines:
                if line.strip() == "# TmdbHostUpdaterPlugin":
                    in_section = True
                    continue
                if in_section:
                    plugin_section.append(line)
            self._current_hosts = '\n'.join(plugin_section)
            self.__save_config()
            logger.info(f"手动Hosts已保存，共{len(valid_lines)}行")
            return {"code": 0, "message": f"保存成功，已写入{len(valid_lines)}行到系统hosts"}
        except Exception as err:
            self._last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._last_update_status = "failed"
            self.__save_config()
            return {"code": 1, "message": f"写入系统hosts失败：{str(err) or '请检查权限'}"}

    @staticmethod
    def __validate_hosts(content: str) -> Tuple[bool, str, List[str]]:
        """校验hosts格式：每行为空、# 注释、或 'IP 域名 [域名...]'
        允许 IPv4、IPv6（含 ::1 / fe00:: 等本地地址）作为IP
        """
        valid_lines = []
        lines = content.split('\n')
        for i, raw_line in enumerate(lines, 1):
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith('#'):
                valid_lines.append(stripped)
                continue
            parts = stripped.split()
            if len(parts) < 2:
                return False, f"第{i}行字段不足（应为：IP 域名）：{raw_line}", []
            ip = parts[0]
            # IPv4 校验或 IPv6 校验（含冒号即为 IPv6，覆盖 ::1 / fe00:: 等格式）
            if not (IpUtils.is_ipv4(ip) or ":" in ip):
                return False, f"第{i}行IP格式错误：{ip}", []
            for name in parts[1:]:
                if not name or any(c in name for c in [' ', '\t']):
                    return False, f"第{i}行域名格式错误：{name}", []
            valid_lines.append(stripped)
        return True, "", valid_lines

    def __api_status(self):
        return {
            "code": 0,
            "data": {
                "enabled": self._enabled,
                "last_update_time": self._last_update_time,
                "last_update_status": self._last_update_status,
                "current_hosts": self._current_hosts,
                "interval": self._interval
            }
        }
