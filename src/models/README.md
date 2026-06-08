# Models — 全局数据模型

> **Enums + Config Models + API Request/Response Models**

定义跨模块使用的基础数据结构。包含枚举类型、配置模型和 API 数据模型。

---

## 目录

1. [数据结构](#1-数据结构)
2. [配置模型](#2-配置模型)
3. [API 模型](#3-api-模型)
4. [使用指南](#4-使用指南)

---

## 1. 数据结构

### 枚举类型

| 枚举 | 值 | 用途 |
|------|-----|------|
| `BugSeverity` | CRITICAL / HIGH / MEDIUM / LOW / UNCERTAIN | Bug 严重程度分级 |
| `AnalysisMode` | rule_only / hybrid / llm_only | 分析模式选择 |
| `RetrievalStrategy` | fast / standard / deep | 检索策略 |
| `BackendType` | milvus / faiss / auto | 向量库后端 |
| `IndexType` | FLAT / IVF_FLAT / HNSW | 向量索引类型 |

### IndexProgress (索引进度)

进度追踪数据结构，支持:
- `progress_pct` — 百分比进度
- `eta_seconds` — 预估剩余时间
- `vectors_per_second` — 索引进度速率

---

## 2. 配置模型

### AppConfig — 应用完整配置

```python
@dataclass
class AppConfig:
    database: DatabaseConfig      # Milvus/FAISS 配置
    model: ModelConfig            # Embedding/Reranker/LLM 模型
    collection: CollectionConfig  # Git 仓库和收集参数
```

### 子配置

```python
@dataclass
class DatabaseConfig:
    type: str = "milvus"          # milvus / faiss
    path: str = "data/vector_db"  # 本地数据路径
    dim: int = 1024               # 向量维度
    host: str = "localhost"
    port: str = "19530"
    collection_name: str = "linux_commits"

@dataclass
class ModelConfig:
    embedding: str = "BAAI/bge-m3"
    reranker: str = "BAAI/bge-reranker-v2-m3"
    llm: str = "deepseek-chat"

@dataclass
class CollectionConfig:
    repo_path: str = ""           # Linux 内核 Git 仓库路径
    batch_size: int = 100         # 编码批量大小
    limit: int = 10000            # 最多收集 commit 数
    only_fix_commits: bool = True
```

---

## 3. API 模型

### 请求模型

```python
@dataclass
class DiagnosisRequest:
    dmesg_content: Optional[str]  # dmesg 日志
    vmcore_path: Optional[str]    # vmcore 路径
    vmlinux_path: Optional[str]   # vmlinux 路径
    use_llm: bool = False         # 是否启用 LLM
    model_name: str               # LLM 模型
    retrieval_mode: str           # fast/standard/deep
    top_k: int = 100              # 候选数量

@dataclass
class BatchDiagnosisRequest:
    dmesg_list: List[str]         # 批量 dmesg
    use_llm: bool = False
    top_k: int = 50
```

### 响应模型

```python
@dataclass
class DiagnosisResponse:
    status: str                   # pending/completed/error
    report_id: str
    root_cause: str
    bug_type: str
    severity: str
    confidence: float
    causal_chain: List[str]
    recommendations: List[Dict]   # 补丁推荐列表
    total_time_ms: float
    error_message: str
```

### Pydantic 模型 (可选)

当安装 `pydantic` 时会自动创建用于 FastAPI 的 Pydantic 模型：
- `DiagnosisRequestPydantic`
- `DiagnosisResponsePydantic`
- `RecommendationPydantic`

---

## 4. 使用指南

### 4.1 配置加载

```python
from src.models import AppConfig, DatabaseConfig, ModelConfig

config = AppConfig(
    database=DatabaseConfig(path="data/my_index", dim=1024),
    model=ModelConfig(embedding="BAAI/bge-m3"),
)
```

### 4.2 响应构造

```python
from src.models import DiagnosisResponse, BugSeverity

response = DiagnosisResponse(
    status="completed",
    report_id="LKR-20240608-0001",
    root_cause="Race condition in TCP receive path leading to UAF",
    bug_type="use_after_free",
    severity=BugSeverity.CRITICAL,
    confidence=0.85,
    recommendations=ranked_patches,
)

# API 返回
return response.to_dict()
```

### 4.3 索引进度追踪

```python
from src.models import IndexProgress

progress = IndexProgress(
    total=10000,
    indexed=5000,
    vectors_per_second=100.0,
)

print(f"Progress: {progress.progress_pct:.1f}%")
print(f"ETA: {progress.eta_seconds:.0f}s")
```
