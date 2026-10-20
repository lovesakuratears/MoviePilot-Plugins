# TMDB Host更新插件

定时从CheckTMDB项目获取最新的TMDB hosts列表，自动更新系统hosts文件，解决TMDB域名DNS污染导致无法访问的问题。

## 功能特性

- 🔄 定时自动更新TMDB hosts
- 🌐 支持IPv4和IPv6双栈
- 🚀 支持GitHub镜像加速
- ⚙️ 可配置更新间隔
- 👁️ 可视化查看当前生效hosts
- 🔌 一键手动更新
- 🧹 可选停用自动清理

## 数据来源

数据来自 [CheckTMDB](https://github.com/cnwikee/CheckTMDB) 项目，每日自动更新TMDB可用IP地址。

## 配置说明

### 基础配置

- **启用插件**：开启或关闭插件功能
- **启用IPv6**：是否同时获取和更新IPv6地址
- **更新间隔（小时）**：自动更新的时间间隔，默认6小时
- **停用清理Hosts**：停用插件时是否自动清除已写入的hosts

### 地址配置

- **IPv4 Hosts地址**：IPv4 hosts文件的URL，默认为CheckTMDB项目的IPv4地址
- **IPv6 Hosts地址**：IPv6 hosts文件的URL，默认为CheckTMDB项目的IPv6地址
- **GitHub镜像地址**：GitHub加速镜像地址，如 `https://ghproxy.com/`，国内访问GitHub困难时配置

## 使用说明

1. 安装插件后，进入插件配置页面
2. 开启"启用插件"开关
3. 根据需要配置更新间隔和其他选项
4. 如果GitHub访问缓慢，可配置GitHub镜像地址
5. 保存配置后，插件会在1分钟内执行首次更新
6. 在详情页可以查看当前生效的hosts和最后更新状态
7. 点击"立即更新"按钮可以手动触发更新

## 注意事项

- 容器运行时更新的是容器内的hosts文件，而非宿主机
- 插件仅管理由它添加的hosts条目，不会修改系统原有配置
- 如遇更新失败，请检查网络连接或配置GitHub镜像
- hosts数据来源于第三方项目，请自行验证可用性
