# Unraid Manager

Unraid 服务器安全管理插件，提供只读监控功能，支持自然语言交互。

---

## 功能特性

| 特性 | 说明 |
|------|------|
| **安全优先** | 只读 API，禁止停止阵列/格式化等危险操作 |
| **温度监控** | 实时磁盘温度，超过阈值自动告警 |
| **容器监控** | Docker CPU/内存占用实时统计 |
| **自然语言** | 支持"硬盘温度多少"、"阵列状态怎么样"等口语化查询 |
| **GraphQL** | 基于 Unraid 官方 API |
| **本地部署** | 容器内 Unix Socket 通信 |

---

## 安装要求

- AstrBot v4.0+
- Unraid 6.12+（开启 GraphQL API）
- AstrBot 容器需挂载 `/var/run/docker.sock`

---

## 配置说明

在 AstrBot 插件配置中设置：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `unraid_host` | Unraid 服务器地址 | `http://your-unraid-ip` |
| `unraid_port` | WebUI 端口 | `80` |
| `api_key` | GraphQL API 密钥 | 从环境变量读取 |
| `temp_threshold` | 磁盘温度告警阈值(°C) | `45` |

**环境变量方式（推荐）**：
```bash
UNRAID_HOST=http://your-unraid-ip
UNRAID_PORT=80
UNRAID_API_KEY=your_api_key_here
```

---

## 使用方式

### 自然语言查询

直接发送以下类型的消息即可触发：

| 查询意图 | 示例消息 |
|----------|----------|
| 阵列状态 | "阵列状态"、"硬盘状态"、"服务器怎么样" |
| 磁盘温度 | "硬盘温度"、"磁盘热不热"、"温度多少" |
| Docker 监控 | "docker 状态"、"容器资源"、"docker 占用" |
| 硬件信息 | "硬件信息"、"系统信息"、"CPU 信息" |

### 显式指令

```
/unraid array    - 阵列详细状态
/unraid temp     - 磁盘温度监控
/unraid docker   - Docker 资源监控
/unraid hardware - 系统硬件信息
/unraid help     - 显示帮助信息
```

---

## 安全声明

本插件仅执行只读操作，**禁止**以下危险行为：
- 停止/启动阵列
- 格式化磁盘
- 修改配置
- 删除文件

---

## 故障排查

**问题：Docker 监控无数据**
- 检查容器是否挂载 `/var/run/docker.sock`

**问题：阵列状态显示 0GB**
- 检查 API 密钥权限是否包含 `admin` 或 `guest`
- 检查 Unraid 版本是否 6.12+ 且已启用 GraphQL API

**问题：自然语言无响应**
- 确保消息包含关键词：unraid、阵列、硬盘、磁盘、服务器、docker、容器、硬件

---

## 技术架构

```
AstrBot Plugin
├── main.py          # 命令处理与自然语言识别
├── unraid_client.py # GraphQL API 客户端
├── docker_helper.py # Docker Socket 通信
└── _conf_schema.json # 配置定义
```

---

## 作者

- **Author**: ludan
- **Version**: 1.0.0
- **License**: MIT
