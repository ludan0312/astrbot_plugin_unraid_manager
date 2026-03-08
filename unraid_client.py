# unraid_manager/unraid_client.py
import asyncio
import aiohttp
import json
import os
from typing import Optional, Dict, Any, List
from astrbot.api import logger


class UnraidClient:
    """Unraid GraphQL API客户端"""
    
    def __init__(self, host: str = None, port: int = 80, api_key: str = None):
        self.unraid_host = host or os.getenv("UNRAID_HOST", "http://your-unraid-ip")
        self.unraid_port = port or int(os.getenv("UNRAID_PORT", "80"))
        self.api_key = api_key or os.getenv("UNRAID_API_KEY", "")
        
        self.base_url = f"{self.unraid_host}:{self.unraid_port}"
        self.graphql_endpoint = f"{self.base_url}/graphql"
        self.session: Optional[aiohttp.ClientSession] = None
        
        self.queries = {
            "array_status": """
                query {
                    array {
                        state
                        capacity {
                            disks {
                                free
                                used
                                total
                            }
                        }
                        disks {
                            name
                            size
                            status
                            temp
                        }
                    }
                }
            """,
            "system_info": """
                query {
                    info {
                        os {
                            platform
                            distro
                            release
                            uptime
                        }
                        cpu {
                            manufacturer
                            brand
                            cores
                            threads
                        }
                    }
                }
            """,
            "docker_containers": """
                query {
                    dockerContainers {
                        id
                        names
                        state
                        status
                        autoStart
                    }
                }
            """
        }
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建HTTP会话"""
        if self.session is None or self.session.closed:
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.api_key
            }
            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self.session
    
    async def _query(self, query_name: str, variables: Dict = None) -> Optional[Dict]:
        """执行GraphQL查询"""
        try:
            session = await self._get_session()
            query = self.queries.get(query_name, "")
            
            payload = {
                "query": query,
                "variables": variables or {}
            }
            
            async with session.post(self.graphql_endpoint, json=payload) as resp:
                text = await resp.text()
                
                if resp.status != 200:
                    logger.error(f"GraphQL HTTP错误: {resp.status} - {text[:200]}")
                    return None
                
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON解析失败: {e}, 返回: {text[:500]}")
                    return None
                
                if "errors" in data:
                    logger.error(f"GraphQL错误: {data['errors']}")
                    return None
                
                result = data.get("data")
                if not isinstance(result, dict):
                    logger.error(f"返回数据不是字典: {type(result)} - {str(result)[:200]}")
                    return None
                    
                return result
                
        except asyncio.TimeoutError:
            logger.error(f"查询 {query_name} 超时")
            return None
        except Exception as e:
            logger.error(f"查询 {query_name} 异常: {e}")
            return None
    
    async def get_array_status(self) -> Optional[Dict]:
        """获取阵列状态"""
        result = await self._query("array_status")
        if isinstance(result, dict):
            return result
        logger.error(f"get_array_status 返回类型错误: {type(result)}")
        return None
    
    async def get_system_info(self) -> Optional[Dict]:
        """获取系统信息（包含内存）"""
        result = await self._query("system_info")
        return result if isinstance(result, dict) else None
    
    async def get_docker_containers(self) -> List[Dict]:
        """获取Docker容器列表（注意：部分Unraid版本GraphQL不支持此字段，建议直接使用Docker Socket）"""
        logger.warning("GraphQL dockerContainers 可能不可用，请直接使用 Docker Socket 获取容器列表")
        return []
    
    async def get_memory_info(self) -> Dict[str, int]:
        """获取内存信息（通过读取/proc/meminfo）"""
        try:
            loop = asyncio.get_event_loop()
            
            def _read_meminfo():
                with open('/proc/meminfo', 'r') as f:
                    return f.read()
            
            content = await asyncio.wait_for(loop.run_in_executor(None, _read_meminfo), timeout=5.0)
            
            mem_total = 0
            mem_available = 0
            
            for line in content.split('\n'):
                if line.startswith('MemTotal:'):
                    mem_total = int(line.split()[1]) * 1024  # KB to bytes
                elif line.startswith('MemAvailable:'):
                    mem_available = int(line.split()[1]) * 1024
            
            mem_used = mem_total - mem_available
            
            return {
                "total": mem_total,
                "used": mem_used,
                "free": mem_available
            }
        except Exception as e:
            logger.error(f"读取内存信息失败: {e}")
            return {"total": 0, "used": 0, "free": 0}
    
    async def close(self):
        """关闭连接"""
        if self.session and not self.session.closed:
            await self.session.close()