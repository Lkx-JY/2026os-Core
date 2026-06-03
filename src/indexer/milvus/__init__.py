"""Milvus 向量库操作模块

负责向量数据的存储、索引建立和相似度检索。
"""

from typing import List, Dict, Any, Optional
import numpy as np


class MilvusClient:
    """Milvus 客户端封装"""
    
    def __init__(self, host: str = "localhost", port: str = "19530"):
        self.host = host
        self.port = port
        self.collection_name = "linux_commits"
        self._connected = False

    def connect(self):
        """建立连接"""
        if not self._connected:
            try:
                from pymilvus import connections
                connections.connect("default", host=self.host, port=self.port)
                self._connected = True
            except ImportError:
                print("Warning: pymilvus not installed. MilvusClient in mock mode.")
            except Exception as e:
                print(f"Error connecting to Milvus: {e}")

    def create_collection(self, dim: int = 1024):
        """创建集合和索引"""
        self.connect()
        # 实际实现中这里会定义 Schema 并创建 Collection
        pass

    def insert(self, data: List[Dict[str, Any]], vectors: np.ndarray):
        """插入向量和元数据"""
        self.connect()
        # 实际实现中这里会将数据批量插入 Milvus
        pass

    def search(self, query_vector: np.ndarray, top_k: int = 10) -> List[Dict[str, Any]]:
        """执行向量检索"""
        self.connect()
        # Mock 返回：在没有真实连接时返回空列表
        return []


# 全局单例客户端
_milvus_client = MilvusClient()

def get_milvus_client() -> MilvusClient:
    return _milvus_client
