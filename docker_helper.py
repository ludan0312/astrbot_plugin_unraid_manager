# unraid_manager/docker_helper.py
import asyncio
import json
import shutil
from typing import List, Dict
from astrbot.api import logger


class DockerHelper:
    """Docker管理助手 - 通过docker.sock获取实时资源数据"""
    
    def __init__(self, socket_path: str = "/var/run/docker.sock"):
        self.socket_path = socket_path
        self._semaphore = asyncio.Semaphore(5)  # 限制并发数，避免资源耗尽
    
    async def _docker_api_call(self, endpoint: str) -> any:
        """通过Unix Socket调用Docker API（使用exec避免shell注入）"""
        try:
            # 检查curl是否可用
            curl_path = shutil.which("curl")
            if not curl_path:
                logger.error("curl命令未找到")
                return None
            
            # 使用exec而非shell，避免命令注入
            cmd = [
                curl_path, "-s", "--unix-socket", self.socket_path,
                f"http://localhost{endpoint}"
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # 设置超时，防止无限等待
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=10.0
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                logger.error(f"Docker API调用超时: {endpoint}")
                return None
            
            if proc.returncode != 0:
                err_msg = stderr.decode()[:200] if stderr else "未知错误"
                logger.error(f"Docker API调用失败: {err_msg}")
                return None
            
            try:
                return json.loads(stdout.decode())
            except json.JSONDecodeError as e:
                logger.error(f"JSON解析失败: {e}")
                return None
            
        except Exception as e:
            logger.error(f"Docker helper错误: {e}")
            return None
    
    async def _get_single_container_stats(self, container: Dict) -> Dict:
        """获取单个容器的统计信息"""
        cid = container.get("Id", "")
        name = container.get("Names", [""])[0].lstrip("/")
        
        async with self._semaphore:
            stats = await self._docker_api_call(f"/containers/{cid}/stats?stream=false")
        
        if not stats:
            return {
                "id": cid,
                "name": name,
                "cpu_percent": 0.0,
                "memory_usage": 0,
                "memory_limit": 1,
                "status": container.get("State", ""),
                "image": container.get("Image", "")
            }
        
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
        
        return {
            "id": cid,
            "name": name,
            "cpu_percent": round(cpu_percent, 2),
            "memory_usage": memory_stats.get("usage", 0),
            "memory_limit": memory_stats.get("limit", 1),
            "status": container.get("State", ""),
            "image": container.get("Image", "")
        }
    
    async def get_containers_stats(self) -> List[Dict]:
        """获取所有容器的实时资源统计（并发拉取）"""
        try:
            # 获取容器列表
            containers = await self._docker_api_call("/containers/json")
            if not containers:
                return []
            
            # 并发拉取所有容器stats
            tasks = [self._get_single_container_stats(c) for c in containers]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 过滤掉异常结果
            stats_list = []
            for r in results:
                if isinstance(r, Exception):
                    logger.error(f"获取容器stats失败: {r}")
                else:
                    stats_list.append(r)
            
            return stats_list
            
        except Exception as e:
            logger.error(f"获取Docker stats失败: {e}")
            return []
    
    async def get_container_logs(self, container_name: str, tail: int = 50) -> str:
        """获取容器日志（只读，使用exec避免注入）"""
        try:
            # 检查docker命令是否可用
            docker_path = shutil.which("docker")
            if not docker_path:
                return "错误：docker命令未找到"
            
            # 参数校验
            tail = max(1, min(tail, 1000))  # 限制范围1-1000
            
            # 使用exec而非shell，避免命令注入
            cmd = [docker_path, "logs", f"--tail={tail}", container_name]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # 设置超时
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=15.0
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return "错误：获取日志超时"
            
            # 检查返回码和stderr
            if proc.returncode != 0:
                err_msg = stderr.decode()[-500:] if stderr else "未知错误"
                logger.error(f"获取容器日志失败: {err_msg}")
                return f"获取日志失败: {err_msg}"
            
            output = stdout.decode()[-2000:]  # 限制返回长度
            return output if output else "(无日志输出)"
            
        except Exception as e:
            logger.error(f"获取容器日志异常: {e}")
            return f"获取日志失败: 内部错误"
