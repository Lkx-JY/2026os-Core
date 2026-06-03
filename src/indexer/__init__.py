"""索引与向量检索核心模块

负责数据的向量化编码、存储以及高效检索。
整合了以下功能：
- embedding: 基于 BGE-M3 的文本向量化
- milvus: Milvus 向量数据库操作封装
- pipeline: 离线索引与在线查询流水线
"""

from .embedding import encode_text, get_encoder
from .milvus import get_milvus_client
from .pipeline import index_commits, get_query_vector

__all__ = [
    'encode_text',
    'get_encoder',
    'get_milvus_client',
    'index_commits',
    'get_query_vector',
]
