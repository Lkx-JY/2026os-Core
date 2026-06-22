"""Redis 任务存储 — 用于跨进程/多实例共享任务状态."""

import json
import os
from typing import Optional
from datetime import datetime

import redis
from pydantic import BaseModel

from ...common.logging import get_logger

logger = get_logger()


class RedisTaskStore:
    """基于 Redis 的任务状态存储

    特性:
    - 跨进程共享任务状态
    - 服务重启后任务数据不丢失
    - 支持分布式部署
    - 自动过期清理 (24小时)
    """

    TASK_PREFIX = "task:"
    TASK_TTL = 86400  # 24小时过期

    def __init__(self, redis_url: str = None):
        """初始化 Redis 连接

        Args:
            redis_url: Redis 连接 URL，格式: redis://host:port/db
                      如果为 None，从配置文件读取
        """
        self._redis: Optional[redis.Redis] = None
        self._redis_url = redis_url or self._load_redis_url()
        self._connected = False

    def _load_redis_url(self) -> str:
        """从配置文件加载 Redis URL"""
        try:
            import yaml
            config_paths = [
                "configs/config.yaml",
                os.path.join(os.path.dirname(__file__), "../../../configs/config.yaml"),
            ]
            for path in config_paths:
                if os.path.isfile(path):
                    with open(path, "r", encoding="utf-8") as f:
                        config = yaml.safe_load(f)
                        redis_config = config.get("redis", {})
                        host = redis_config.get("host", "localhost")
                        port = redis_config.get("port", 6379)
                        db = redis_config.get("db", 0)
                        return f"redis://{host}:{port}/{db}"
        except Exception:
            pass
        return "redis://localhost:6379/0"

    def _get_connection(self) -> Optional[redis.Redis]:
        """懒加载 Redis 连接"""
        if self._redis is None:
            try:
                self._redis = redis.from_url(
                    self._redis_url,
                    decode_responses=True,  # 自动解码 JSON 字符串
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
                # 测试连接
                self._redis.ping()
                self._connected = True
            except redis.ConnectionError:
                self._redis = None
                self._connected = False
        return self._redis

    @property
    def is_connected(self) -> bool:
        """检查 Redis 连接状态"""
        self._get_connection()
        return self._connected

    def save_task(self, task_id: str, data: dict) -> bool:
        """保存任务数据

        Args:
            task_id: 任务 ID
            data: 任务数据字典

        Returns:
            是否保存成功
        """
        conn = self._get_connection()
        if conn is None:
            return False

        try:
            key = f"{self.TASK_PREFIX}{task_id}"
            # 序列化 datetime 对象
            serializable_data = self._serialize_data(data)
            conn.setex(key, self.TASK_TTL, json.dumps(serializable_data))
            return True
        except Exception as e:
            logger.error(f"Failed to save task {task_id}: {e}")
            return False

    def get_task(self, task_id: str) -> Optional[dict]:
        """获取任务数据

        Args:
            task_id: 任务 ID

        Returns:
            任务数据字典，不存在则返回 None
        """
        conn = self._get_connection()
        if conn is None:
            return None

        try:
            key = f"{self.TASK_PREFIX}{task_id}"
            data = conn.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception:
            return None

    def update_task(self, task_id: str, updates: dict) -> bool:
        """更新任务部分数据

        Args:
            task_id: 任务 ID
            updates: 要更新的字段字典

        Returns:
            是否更新成功
        """
        current = self.get_task(task_id)
        if current is None:
            return False

        current.update(updates)
        return self.save_task(task_id, current)

    def delete_task(self, task_id: str) -> bool:
        """删除任务

        Args:
            task_id: 任务 ID

        Returns:
            是否删除成功
        """
        conn = self._get_connection()
        if conn is None:
            return False

        try:
            key = f"{self.TASK_PREFIX}{task_id}"
            conn.delete(key)
            return True
        except Exception:
            return False

    def list_tasks(self, pattern: str = "*") -> list[str]:
        """列出所有任务 ID

        Args:
            pattern: 匹配模式，默认所有任务

        Returns:
            任务 ID 列表
        """
        conn = self._get_connection()
        if conn is None:
            return []

        try:
            keys = conn.keys(f"{self.TASK_PREFIX}{pattern}")
            return [key.replace(self.TASK_PREFIX, "") for key in keys]
        except Exception:
            return []

    def _serialize_data(self, data: dict) -> dict:
        """递归序列化数据中的 datetime / Pydantic BaseModel 对象

        处理嵌套结构中的:
        - datetime → ISO 8601 字符串
        - BaseModel → model_dump() 后递归序列化
        - list → 递归处理每个元素
        - dict → 递归处理每个值
        """
        result = {}
        for key, value in data.items():
            result[key] = self._serialize_value(value)
        return result

    def _serialize_value(self, value):
        """递归序列化单个值"""
        if isinstance(value, BaseModel):
            return self._serialize_data(value.model_dump())
        elif isinstance(value, datetime):
            return value.isoformat()
        elif isinstance(value, list):
            return [self._serialize_value(item) for item in value]
        elif isinstance(value, dict):
            return self._serialize_data(value)
        else:
            return value


# ── 全局单例 ────────────────────────────────────────

_task_store: Optional[RedisTaskStore] = None


def get_task_store(redis_url: str = "redis://localhost:6379/0") -> RedisTaskStore:
    """获取任务存储单例

    Args:
        redis_url: Redis 连接 URL

    Returns:
        RedisTaskStore 实例
    """
    global _task_store
    if _task_store is None:
        _task_store = RedisTaskStore(redis_url)
    return _task_store


def fallback_to_memory() -> dict:
    """内存存储回退 — 当 Redis 不可用时使用"""
    return {}


__all__ = [
    "RedisTaskStore",
    "get_task_store",
    "fallback_to_memory",
]
