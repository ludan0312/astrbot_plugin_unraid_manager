# unraid_manager/docker_helper.py
import asyncio
import json
from typing import List, Dict, Any
from astrbot.api import logger


class DockerHelper:
    """Docker管理助手 - 通过docker.sock获取实时资源数据"""
    
    def __init__(self, socket_path: str = "/var/run/docker.sock"):
        self.socket_path = socket_path
    
    async def _docker_api_call(self, endpoint: str) -> Any:
        """通过Unix Socket调用Docker API"""
        try:
            # 使用aiohttp的UnixConnector或直接shell调用
            # 这里使用docker命令行作为最稳定的方式
            cmd = f"curl -s --unix-socket {self.socket_path} http://localhost{endpoint}"
            
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                logger.error(f"Docker API调用失败: {stderr.decode()}")
                return None
            
            return json.loads(stdout.decode())
            
        except Exception as e:
            logger.error(f"Docker helper错误: {e}")
            return None
    
    async def get_containers_stats(self) -> List[Dict]:
        """获取所有容器的实时资源统计"""
        try:
            # 获取容器列表
            containers = await self._docker_api_call("/containers/json")
            if not containers:
                return []
            
            stats_list = []
            for container in containers:
                cid = container.get("Id", "")
                # 获取单个容器stats（非流式）
                stats = await self._docker_api_call(f"/containers/{cid}/stats?stream=false")
                if stats:
                    # 解析stats数据
                    cpu_stats = stats.get("cpu_stats", {})
                    memory_stats = stats.get("memory_stats", {})
                    prev_cpu_stats = stats.get("precpu_stats", {})
                    
                    # 正确计算CPU使用率（基于时间差）
                    cpu_percent = 0.0
                    cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - \
                               prev_cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
                    system_delta = cpu_stats.get("system_cpu_usage", 0) - \
                                  prev_cpu_stats.get("system_cpu_usage", 0)
                    
                    if system_delta > 0 and cpu_delta > 0:
                        online_cpus = cpu_stats.get("online_cpus", 
                                     len(cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])))
                        if online_cpus == 0:
                            online_cpus = 1
                        cpu_percent = (cpu_delta / system_delta) * online_cpus * 100
                    
                    stats_list.append({
                        "id": cid,
                        "name": container.get("Names", [""])[0].lstrip("/"),
                        "cpu_percent": round(cpu_percent, 2),
                        "memory_usage": memory_stats.get("usage", 0),
                        "memory_limit": memory_stats.get("limit", 1),
                        "status": container.get("State", ""),
                        "image": container.get("Image", "")
                    })
            
            return stats_list
            
        except Exception as e:
            logger.error(f"获取Docker stats失败: {e}")
            return []
    
    async def get_container_logs(self, container_name: str, tail: int = 50) -> str:
        """获取容器日志（只读）"""
        try:
            # 使用docker命令（已通过sock挂载）
            cmd = f"docker logs --tail {tail} {container_name} 2>&1"
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            return stdout.decode()[-2000:]  # 限制返回长度
            
        except Exception as e:
            return f"获取日志失败: {e}"