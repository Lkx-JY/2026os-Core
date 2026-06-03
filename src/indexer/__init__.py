"""索引与向量检索核心模块 — Indexing & Vector Retrieval Engine

负责数据的向量化编码、存储以及高效检索。
是整个系统"离线数据治理"与"在线语义检索"的基础设施层。

整合了以下功能:
- embedding: 基于 BGE-M3 的文本向量化 (批量编码 + GPU 加速)
- milvus: Milvus (生产) + FAISS (本地开发) 双后端向量数据库
- pipeline: 离线索引构建、增量更新、在线查询的流水线编排
"""

from .embedding import (
    BaseEncoder,
    BGEEncoder,
    get_encoder,
    reset_encoder,
    encode_text,
    encode_texts_batch,
    BGE_M3_DIM,
    MODEL_DIMENSIONS,
)
from .milvus import (
    MilvusClient,
    MilvusBackend,
    FAISSBackend,
    SearchResult,
    get_milvus_client,
    reset_milvus_client,
    BackendType,
)
from .pipeline import (
    prepare_embedding_text,
    prepare_commit_embedding_text,
    prepare_rootcause_embedding_text,
    index_commits,
    index_commits_incremental,
    get_query_vector,
    search_similar_commits,
    get_index_stats,
    get_index_count,
)

__all__ = [
    # Embedding
    "BaseEncoder",
    "BGEEncoder",
    "get_encoder",
    "reset_encoder",
    "encode_text",
    "encode_texts_batch",
    "BGE_M3_DIM",
    "MODEL_DIMENSIONS",
    # Milvus / Vector DB
    "MilvusClient",
    "MilvusBackend",
    "FAISSBackend",
    "SearchResult",
    "get_milvus_client",
    "reset_milvus_client",
    "BackendType",
    # Pipeline
    "prepare_embedding_text",
    "prepare_commit_embedding_text",
    "prepare_rootcause_embedding_text",
    "index_commits",
    "index_commits_incremental",
    "get_query_vector",
    "search_similar_commits",
    "get_index_stats",
    "get_index_count",
]
