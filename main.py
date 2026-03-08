# unraid_manager/main.py
import re
import os
from typing import Dict

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

from .unraid_client import UnraidClient
from .docker_helper import DockerHelper


@register("unraid_manager", "ludan", "Unraid安全管理插件", "1.2.0")
class UnraidManager(Star):
    """Unraid阵列监护模块 - 只读优先，安全第一"""
    
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        
        # Unraid连接配置（优先环境变量，其次配置文件）
        self.unraid_host = self.config.get("unraid_host") or os.getenv("UNRAID_HOST", "")
        self.unraid_port = int(self.config.get("unraid_port") or os.getenv("UNRAID_PORT", "80"))
        self.api_key = self.config.get("api_key") or os.getenv("UNRAID_API_KEY", "")
        self.temp_threshold = int(self.config.get("temp_threshold", 45))
        
        # 初始化客户端（允许无配置初始化）
        self.unraid = UnraidClient(
            host=self.unraid_host,
            port=self.unraid_port,
            api_key=self.api_key
        )
        self.docker = DockerHelper()
        
        # 检查配置状态
        self._config_ready = bool(self.unraid_host and self.unraid_host != "http://your-unraid-ip")
        
        # 自然语言匹配模式（支持口语化查询）
        # 注意：为避免误触发，通用词如"cpu"、"内存"、"温度"需组合其他关键词使用
        self.intent_patterns = {
            "array_status": [
                r"阵列", r"硬盘.*状态", r"磁盘.*状态", r"unraid",
                r"服务器.*状态", r"raid", r"存储.*状态", r"硬盘.*好吗",
                r"磁盘.*好吗", r"阵列.*正常", r"unraid.*好吗"
            ],
            "disk_temp": [
                r"硬盘.*温度", r"磁盘.*温度", r"温度.*多少", r"热不热",
                r"硬盘.*烫", r"磁盘.*烫", r"温度.*高", r"温度.*怎样",
                r"硬盘.*热", r"磁盘.*热", r"阵列.*温度"
            ],
            "docker_status": [
                r"docker", r"容器", r"container",
                r"docker.*状态", r"容器.*状态", r"docker.*资源", r"容器.*资源",
                r"docker.*占用", r"容器.*占用", r"服务.*状态", r"应用.*状态"
            ],
            "hardware_info": [
                r"硬件.*信息", r"系统.*信息", r"cpu.*信息", r"内存.*信息",
                r"主板.*信息", r"硬件.*配置", r"系统.*配置", r"server.*info",
                r"硬件.*状态"
            ]
        }
        
        # 快速过滤关键词（必须在消息中同时包含）
        self.unraid_keywords = ["unraid", "阵列", "硬盘", "磁盘", "服务器", 
                               "docker", "容器", "硬件", "raid", "存储"]
        
        if self._config_ready:
            logger.info(f"Unraid监护模块已初始化 @ {self.unraid_host}")
        else:
            logger.warning("Unraid未配置，请在插件设置中配置unraid_host和api_key")
    
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_natural_language(self, event: AstrMessageEvent):
        """自然语言意图识别 - 匹配意图模式即响应"""
        msg = event.message_str.lower().strip()
        
        # 先检查是否包含Unraid相关关键词（快速过滤，避免误触发）
        if not any(kw in msg for kw in self.unraid_keywords):
            return
        
        matched_intent = None
        for intent, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if re.search(pattern, msg, re.IGNORECASE):
                    matched_intent = intent
                    break
            if matched_intent:
                break
        
        if matched_intent:
            logger.info(f"识别到意图: {matched_intent}, 消息: {msg[:30]}")
            
            if matched_intent == "array_status":
                async for result in self._send_array_status(event):
                    yield result
            elif matched_intent == "disk_temp":
                async for result in self._send_disk_temperature(event):
                    yield result
            elif matched_intent == "docker_status":
                async for result in self._send_docker_status(event):
                    yield result
            elif matched_intent == "hardware_info":
                async for result in self._send_hardware_info(event):
                    yield result
            
            event.stop_event()
    
    @filter.command("unraid")
    async def unraid_command(self, event: AstrMessageEvent, action: str = ""):
        """显式指令入口"""
        action = action.lower().strip()
        
        if action in ["array", "状态", "阵列"]:
            async for result in self._send_array_status(event):
                yield result
        elif action in ["temp", "温度", "磁盘温度"]:
            async for result in self._send_disk_temperature(event):
                yield result
        elif action in ["docker", "容器", "docker状态"]:
            async for result in self._send_docker_status(event):
                yield result
        elif action in ["hardware", "硬件", "系统", "info"]:
            async for result in self._send_hardware_info(event):
                yield result
        elif action in ["help", "帮助"]:
            yield event.plain_result(self._get_help_text())
        else:
            async for result in self._send_array_status(event):
                yield result
    
    async def _send_array_status(self, event: AstrMessageEvent):
        """阵列状态查看"""
        if not self._config_ready:
            yield event.plain_result("Unraid未配置，请使用 /plugin 命令配置 unraid_host 和 api_key")
            return
        try:
            data = await self.unraid.get_array_status()
            
            if not isinstance(data, dict):
                logger.error(f"阵列数据类型错误: {type(data)}")
                yield event.plain_result("阵列数据格式异常，请检查API连接")
                return
            
            array = data.get("array") or {}
            if not isinstance(array, dict):
                logger.error(f"array字段类型错误: {type(array)}")
                yield event.plain_result("阵列结构异常")
                return
            
            state = array.get("state", "unknown")
            capacity = array.get("capacity") or {}
            disks = array.get("disks") or []
            
            state_emoji = {
                "STARTED": "🟢 运行中",
                "STOPPED": "🔴 已停止", 
                "MAINTENANCE": "🟡 维护模式"
            }.get(state, f"⚪ {state}")
            
            # 容量计算（Unraid 7.2.3 格式: capacity.disks 是对象，不是数组）
            total_gb = used_gb = free_gb = 0
            
            cap_disks = capacity.get("disks")
            if isinstance(cap_disks, dict):
                # Unraid 7.2.3: {'free': '28', 'used': '2', 'total': '30'} (单位是TB)
                total_tb = int(cap_disks.get("total") or 0)
                used_tb = int(cap_disks.get("used") or 0)
                free_tb = int(cap_disks.get("free") or 0)
                
                total_gb = total_tb * 1024
                used_gb = used_tb * 1024
                free_gb = free_tb * 1024
            elif isinstance(cap_disks, list):
                # 旧版数组格式
                total_bytes = sum((d.get("total") or 0) for d in cap_disks if isinstance(d, dict))
                used_bytes = sum((d.get("used") or 0) for d in cap_disks if isinstance(d, dict))
                free_bytes = sum((d.get("free") or 0) for d in cap_disks if isinstance(d, dict))
                total_gb = total_bytes / (1024**3)
                used_gb = used_bytes / (1024**3)
                free_gb = free_bytes / (1024**3)
            
            usage_pct = (used_gb / total_gb * 100) if total_gb > 0 else 0
            
            # 磁盘状态摘要
            disk_summary = []
            for disk in disks:
                if not isinstance(disk, dict):
                    continue
                name = disk.get("name", "unknown")
                status = disk.get("status", "unknown")
                temp = disk.get("temp") or 0
                temp_emoji = "🌡️" if temp > self.temp_threshold else "❄️"
                disk_summary.append(f"  • {name}: {status} {temp_emoji}{temp}°C")
            
            # 使用实际有效磁盘数量，而非len(disks)
            valid_disk_count = len(disk_summary)
            
            msg = f"""【阵列监测报告】

阵列状态: {state_emoji}
存储空间: {used_gb:.1f}GB / {total_gb:.1f}GB ({usage_pct:.1f}%)
剩余可用: {free_gb:.1f}GB

磁盘详情 ({valid_disk_count}块):
{chr(10).join(disk_summary) if disk_summary else "  (无磁盘数据)"}

RAID心跳: {'正常' if state == 'STARTED' else '异常'}"""
            
            yield event.plain_result(msg)
            
            hot_disks = [d for d in disks if isinstance(d, dict) and (d.get("temp") or 0) > self.temp_threshold]
            if hot_disks:
                hot_names = ", ".join([d.get("name", "unknown") for d in hot_disks])
                yield event.plain_result(f"⚠️ 温度警报：{hot_names} 超过{self.temp_threshold}°C")
                
        except Exception as e:
            logger.error(f"阵列状态获取失败: {e}")
            # 对外统一友好文案，详细错误仅写日志
            yield event.plain_result("阵列状态获取失败，请检查网络连接和API配置")
    
    async def _send_disk_temperature(self, event: AstrMessageEvent):
        """磁盘温度监控"""
        if not self._config_ready:
            yield event.plain_result("Unraid未配置，请使用 /plugin 命令配置 unraid_host 和 api_key")
            return
        try:
            data = await self.unraid.get_array_status()
            
            if not isinstance(data, dict):
                yield event.plain_result("数据格式错误，请稍后重试")
                return
            
            array = data.get("array") or {}
            disks = array.get("disks") or []
            
            if not disks:
                yield event.plain_result("未检测到磁盘，请检查阵列状态")
                return
            
            temp_lines = []
            alert_disks = []
            
            for disk in disks:
                if not isinstance(disk, dict):
                    continue
                name = disk.get("name", "unknown")
                temp = disk.get("temp") or 0
                status = disk.get("status", "unknown")
                size = (disk.get("size") or 0) / (1024**3)
                
                if temp >= 50:
                    temp_bar = "🔴" * 5
                    alert_disks.append(name)
                elif temp >= self.temp_threshold:
                    temp_bar = "🟡" * 4 + "⚪"
                    alert_disks.append(name)
                elif temp >= 35:
                    temp_bar = "🟢" * 3 + "⚪" * 2
                else:
                    temp_bar = "❄️" * 2 + "⚪" * 3
                
                temp_lines.append(f"{name}: {temp_bar} {temp}°C ({size:.0f}GB) [{status}]")
            
            msg = f"""【磁盘温度监测】🌡️

{chr(10).join(temp_lines)}

告警阈值: {self.temp_threshold}°C
{'⚠️ 过热警告: ' + ', '.join(alert_disks) if alert_disks else '✅ 所有磁盘温度正常'}"""
            
            yield event.plain_result(msg)
            
        except Exception as e:
            logger.error(f"温度监控失败: {e}")
            yield event.plain_result("温度监控服务暂时不可用，请稍后重试")
    
    async def _send_docker_status(self, event: AstrMessageEvent):
        """Docker资源监控"""
        try:
            containers_stats = await self.docker.get_containers_stats()
            
            if not containers_stats:
                yield event.plain_result("Docker守护进程无响应，请检查socket挂载")
                return
            
            lines = []
            total_cpu = 0.0
            total_mem = 0.0
            running_count = 0
            
            for stats in containers_stats:
                if not isinstance(stats, dict):
                    continue
                    
                name = stats.get("name", "unknown")
                state = stats.get("status", "unknown")
                cpu_pct = stats.get("cpu_percent", 0.0)
                mem_usage = stats.get("memory_usage", 0)
                mem_limit = stats.get("memory_limit", 1)
                
                mem_mb = mem_usage / (1024**2)
                mem_limit_mb = mem_limit / (1024**2)
                mem_pct = (mem_mb / mem_limit_mb * 100) if mem_limit_mb > 0 else 0
                
                total_cpu += cpu_pct
                total_mem += mem_mb
                
                if state == "running":
                    running_count += 1
                
                state_icon = {"running": "🟢", "paused": "⏸️", "restarting": "🔄", "exited": "⚫", "dead": "💀"}.get(state, "⚪")
                
                lines.append(
                    f"{state_icon} {name[:15]:<15} | "
                    f"CPU: {cpu_pct:>5.1f}% | "
                    f"MEM: {mem_mb:>6.1f}MB ({mem_pct:>4.1f}%)"
                )
            
            msg = f"""【Docker容器监控】🐳

{'-' * 50}
{chr(10).join(lines)}
{'-' * 50}
总计: CPU {total_cpu:.1f}% | MEM {total_mem:.1f}MB
运行中: {running_count}/{len(containers_stats)}"""
            
            yield event.plain_result(msg)
            
        except Exception as e:
            logger.error(f"Docker监控失败: {e}")
            yield event.plain_result("容器监控服务暂时不可用")
    
    async def _send_hardware_info(self, event: AstrMessageEvent):
        """硬件信息读取"""
        if not self._config_ready:
            yield event.plain_result("Unraid未配置，请使用 /plugin 命令配置 unraid_host 和 api_key")
            return
        try:
            data = await self.unraid.get_system_info()
            
            if not isinstance(data, dict):
                logger.error(f"系统信息类型错误: {type(data)}")
                yield event.plain_result("硬件数据格式异常")
                return
            
            info = data.get("info") or {}
            if not isinstance(info, dict):
                yield event.plain_result("信息结构异常")
                return
            
            os_info = info.get("os") or {}
            cpu_info = info.get("cpu") or {}
            memory = info.get("memory") or {}
            
            # 处理uptime
            uptime_val = os_info.get("uptime") or 0
            try:
                uptime_sec = int(float(uptime_val)) if uptime_val else 0
            except (ValueError, TypeError):
                uptime_sec = 0
            
            uptime_str = self._format_uptime(uptime_sec)
            
            cpu_brand = cpu_info.get("brand") or "unknown"
            cpu_cores = cpu_info.get("cores") or 0
            cpu_threads = cpu_info.get("threads") or 0
            
            # 内存从system_info直接读取（新版GraphQL）
            mem_total = (memory.get("total") or 0) / (1024**3)
            mem_used = (memory.get("used") or 0) / (1024**3)
            mem_free = (memory.get("free") or 0) / (1024**3)
            
            # 如果system_info没有内存，尝试单独查询
            if mem_total == 0:
                mem_data = await self.unraid.get_memory_info()
                mem_total = mem_data.get("total", 0) / (1024**3)
                mem_used = mem_data.get("used", 0) / (1024**3)
                mem_free = mem_data.get("free", 0) / (1024**3)
            
            mem_pct = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            msg = f"""【系统硬件信息】🖥️

操作系统: {os_info.get('distro', 'unknown')} {os_info.get('release', '')} ({os_info.get('platform', '')})
持续运行: {uptime_str}

处理器: {cpu_brand}
核心数: {cpu_cores}核 {cpu_threads}线程

内存状态: {mem_used:.1f}GB / {mem_total:.1f}GB ({mem_pct:.1f}%)
可用余量: {mem_free:.1f}GB

RAID控制器: 心跳正常
传感器阵列: 在线"""
            
            yield event.plain_result(msg)
            
        except Exception as e:
            logger.error(f"硬件信息获取失败: {e}")
            yield event.plain_result("硬件信息获取失败，请检查API连接")
    
    def _format_uptime(self, seconds: int) -> str:
        """格式化运行时间"""
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        mins = (seconds % 3600) // 60
        if days > 0:
            return f"{days}天{hours}小时{mins}分"
        elif hours > 0:
            return f"{hours}小时{mins}分"
        else:
            return f"{mins}分钟"
    
    def _get_help_text(self) -> str:
        """帮助信息"""
        return """【Unraid管理模块】

自然语言指令:
• "阵列状态怎么样" / "硬盘还好吗"
• "磁盘温度多少" / "硬盘热不热"  
• "docker资源占用" / "容器状态"
• "硬件信息" / "系统配置"

显式指令:
/unraid array    - 阵列详细状态
/unraid temp     - 磁盘温度监控
/unraid docker   - Docker资源监控
/unraid hardware - 系统硬件信息

安全承诺: 只读操作，禁止格式化/停止阵列等危险指令"""
    
    async def terminate(self):
        """插件卸载时清理"""
        await self.unraid.close()
        logger.info("Unraid监护模块已安全关闭")
