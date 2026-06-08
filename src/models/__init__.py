"""全局数据模型 — Global Data Models

定义跨模块使用的基础数据结构。

包含:
- SQLAlchemy ORM 模型 (如需要持久化到 PostgreSQL)
- Pydantic 模型 (用于 API 请求/响应验证)
- 通用枚举类型
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from enum import Enum


# ============================================================================
# 枚举类型
# ============================================================================

class BugSeverity(str, Enum):
    """Bug 严重程度"""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNCERTAIN = "UNCERTAIN"


class AnalysisMode(str, Enum):
    """分析模式"""
    RULE_ONLY = "rule_only"
    HYBRID = "hybrid"
    LLM_ONLY = "llm_only"


class RetrievalStrategy(str, Enum):
    """检索策略"""
    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"


class BackendType(str, Enum):
    """向量库后端"""
    MILVUS = "milvus"
    FAISS = "faiss"
    AUTO = "auto"


class IndexType(str, Enum):
    """向量索引类型"""
    FLAT = "FLAT"
    IVF_FLAT = "IVF_FLAT"
    HNSW = "HNSW"


# ============================================================================
# 配置模型
# ============================================================================

@dataclass
class ModelConfig:
    """模型配置"""
    embedding: str = "BAAI/bge-m3"
    reranker: str = "BAAI/bge-reranker-v2-m3"
    llm: str = "deepseek-chat"


@dataclass
class DatabaseConfig:
    """数据库配置"""
    type: str = "milvus"
    path: str = "data/vector_db"
    dim: int = 1024
    host: str = "localhost"
    port: str = "19530"
    collection_name: str = "linux_commits"


@dataclass
class CollectionConfig:
    """数据收集配置"""
    repo_path: str = ""
    batch_size: int = 100
    limit: int = 10000
    only_fix_commits: bool = True
    since: Optional[str] = None


@dataclass
class AppConfig:
    """应用完整配置"""
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    collection: CollectionConfig = field(default_factory=CollectionConfig)


# ============================================================================
# API 请求/响应模型
# ============================================================================

@dataclass
class DiagnosisRequest:
    """诊断请求"""
    dmesg_content: Optional[str] = None
    vmcore_path: Optional[str] = None
    vmlinux_path: Optional[str] = None
    use_llm: bool = False
    model_name: str = "deepseek-chat"
    retrieval_mode: str = "standard"
    top_k: int = 100


@dataclass
class DiagnosisResponse:
    """诊断响应"""
    status: str = "pending"
    report_id: str = ""
    root_cause: str = ""
    bug_type: str = ""
    severity: str = "UNCERTAIN"
    confidence: float = 0.0
    causal_chain: List[str] = field(default_factory=list)
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    total_time_ms: float = 0.0
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "report_id": self.report_id,
            "root_cause": self.root_cause,
            "bug_type": self.bug_type,
            "severity": self.severity,
            "confidence": self.confidence,
            "causal_chain": self.causal_chain,
            "recommendations": self.recommendations,
            "total_time_ms": self.total_time_ms,
            "error_message": self.error_message,
        }


@dataclass
class BatchDiagnosisRequest:
    """批量诊断请求"""
    dmesg_list: List[str] = field(default_factory=list)
    use_llm: bool = False
    top_k: int = 50


@dataclass
class BatchDiagnosisResponse:
    """批量诊断响应"""
    total: int = 0
    completed: int = 0
    failed: int = 0
    results: List[DiagnosisResponse] = field(default_factory=list)
    total_time_ms: float = 0.0


@dataclass
class IndexProgress:
    """索引进度"""
    total: int = 0
    indexed: int = 0
    failed: int = 0
    current_batch: int = 0
    total_batches: int = 0
    elapsed_seconds: float = 0.0
    vectors_per_second: float = 0.0

    @property
    def progress_pct(self) -> float:
        return (self.indexed / self.total * 100) if self.total > 0 else 0.0

    @property
    def eta_seconds(self) -> float:
        if self.vectors_per_second > 0:
            remaining = self.total - self.indexed
            return remaining / self.vectors_per_second
        return 0.0


# ============================================================================
# 兼容 gRPC / REST 的 Pydantic 模型 (可选)
# ============================================================================

if TYPE_CHECKING:
    from pydantic import BaseModel, Field as PydanticField
    __pydantic_available__ = True
else:
    try:
        from pydantic import BaseModel, Field as PydanticField
        __pydantic_available__ = True
    except ImportError:
        __pydantic_available__ = False
        class BaseModel: pass
        def PydanticField(*args, **kwargs): return None

class DiagnosisRequestPydantic(BaseModel):
    """诊断请求 (Pydantic)"""
    dmesg_content: Optional[str] = PydanticField(None, description="dmesg log content")
    vmcore_path: Optional[str] = PydanticField(None, description="vmcore file path")
    vmlinux_path: Optional[str] = PydanticField(None, description="vmlinux file path")
    use_llm: bool = PydanticField(False, description="Enable LLM-enhanced analysis")
    model_name: str = PydanticField("deepseek-chat", description="LLM model name")
    retrieval_mode: str = PydanticField("standard", description="fast/standard/deep")
    top_k: int = PydanticField(100, ge=1, le=500, description="Number of candidates to retrieve")

class RecommendationPydantic(BaseModel):
    """补丁推荐 (Pydantic)"""
    rank: int
    commit_hash: str
    subject: str
    subsystem: str
    bug_type: str
    final_score: float
    rank_reason: str
    vector_score: float = 0.0
    reranker_score: float = 0.0
    llm_judge_score: float = 0.0

class DiagnosisResponsePydantic(BaseModel):
    """诊断响应 (Pydantic)"""
    status: str
    report_id: str
    root_cause: str
    bug_type: str
    severity: str
    confidence: float
    causal_chain: List[str] = []
    recommendations: List[RecommendationPydantic] = []
    total_time_ms: float = 0.0
    error_message: str = ""


__all__ = [
    # 枚举
    "BugSeverity",
    "AnalysisMode",
    "RetrievalStrategy",
    "BackendType",
    "IndexType",
    # 配置
    "ModelConfig",
    "DatabaseConfig",
    "CollectionConfig",
    "AppConfig",
    # API 模型
    "DiagnosisRequest",
    "DiagnosisResponse",
    "BatchDiagnosisRequest",
    "BatchDiagnosisResponse",
    "IndexProgress",
    # Pydantic 模型 (可选)
    "DiagnosisRequestPydantic",
    "RecommendationPydantic",
    "DiagnosisResponsePydantic",
]
