"""索引流水线模块

负责将 Commit 数据或宕机分析结果转换为向量并存入/查询向量库。
"""

import numpy as np
from typing import List, Union, Any
from ..embedding import encode_text
from ..milvus import get_milvus_client


def prepare_embedding_text(data: Any) -> str:
    """将不同类型的数据转换为适合 embedding 的文本"""
    # 如果是 src.collector.models.CommitInfo
    if hasattr(data, "to_embedding_text"):
        return data.to_embedding_text()
    
    # 如果是 src.analyzer.models.RootCauseResult
    if hasattr(data, "root_cause"):
        return f"""Root Cause: {data.root_cause}
Reason: {data.reason}
Causal Chain: {' -> '.join(data.causal_chain)}
Panic Message: {data.crash_feature.panic_msg}
Subsystem: {data.crash_feature.subsystem}
Bug Type: {data.crash_feature.bug_type}"""

    return str(data)


def index_commits(commits: List[Any]):
    """离线流程：对 Commit 进行向量化并存入 Milvus"""
    if not commits:
        return
        
    texts = [prepare_embedding_text(c) for c in commits]
    vectors = encode_text(texts)
    
    client = get_milvus_client()
    # 准备元数据
    metadata = []
    for c in commits:
        if hasattr(c, "to_dict"):
            metadata.append(c.to_dict())
        else:
            metadata.append({"raw": str(c)})
            
    client.insert(metadata, vectors)


def get_query_vector(analysis_result: Any) -> np.ndarray:
    """在线流程：将分析结果转换为查询向量"""
    text = prepare_embedding_text(analysis_result)
    vector = encode_text([text])
    return vector[0]
