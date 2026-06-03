# Indexer 模块

负责将 Linux Commit 数据和宕机分析结果进行向量化编码，并管理向量数据库。

## 模块架构

```text
indexer/
├── __init__.py       # 模块入口，整合所有子模块
├── embedding/        # 向量编码模块 (BGE-M3)
├── milvus/           # Milvus 向量库封装
└── pipeline/         # 索引与检索流水线
```

## 功能说明

### 1. 向量编码 (Embedding)

- **BGE-M3 支持**: 采用 `BAAI/bge-m3` 模型，支持多模态语义理解，能够有效跨越宕机现象（dmesg/vmcore）与补丁方案（Commit Message）之间的表述鸿沟。
- **自适应编码**: 自动根据输入数据的类型（`CommitInfo` 或 `RootCauseResult`）提取核心语义信息进行编码。

### 2. 向量库管理 (Milvus)

- **高效索引**: 封装了 Milvus 的连接、集合创建及向量插入操作。
- **相似度检索**: 支持 Top-K 向量检索，为后续的补丁匹配提供候选集。

### 3. 流水线编排 (Pipeline)

- **离线索引**: 批量处理 `collector` 收集到的 Commit 数据，构建全量向量索引。
- **在线查询**: 将 `analyzer` 输出的根因抽象结果实时转换为查询向量。

## 使用示例

### 离线构建索引
```python
from src.indexer import index_commits

# 对收集到的 commits 进行向量化存储
index_commits(all_commits)
```

### 在线查询向量
```python
from src.indexer import get_query_vector

# 将宕机分析结果转换为查询向量
query_vector = get_query_vector(root_cause_result)
```

## 检索算法亮点符合度

- **语义理解能力**: 利用 BGE-M3 深度语义模型，区分表面关键词相似与深层因果关联。
- **功能完整性**: 实现了从特征提取结果到向量空间映射的完整链路。
- **可维护性**: 采用延迟加载和单例模式，优化了资源占用与初始化速度。
