# Core.LinuxCommit

> **Linux Kernel Crash → Root Cause → Patch Matching System**

基于 RAG (Retrieval-Augmented Generation) + Linux Kernel Debugging + LLM 的自动化内核补丁匹配系统。

---

## 1. 项目愿景

在复杂的 Linux 内核运维场景中，当发生内核宕机（Kernel Crash）时，传统的排查方式依赖专家经验，耗时且低效。本项目旨在通过自动化手段，实现从**宕机现象解析**到**根因分析**，再到**补丁精准推荐**的全链路闭环，显著提升内核故障的修复效率。

## 2. 核心架构

系统的核心逻辑分为 **离线数据治理** 与 **在线分析检索** 两个阶段：

### 2.1 整体流程图
```text
                        Linux Kernel Crash Analysis AI
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                            │
        ▼                            ▼                            ▼
    日志理解模块                  向量检索模块                 补丁推理模块
        │                            │                            │
 ┌──────┼──────┐              ┌──────┼──────┐             ┌──────┼──────┐
 │      │      │              │      │      │             │      │      │
 ▼      ▼      ▼              ▼      ▼      ▼             ▼      ▼      ▼
dmesg  vmcore RootCause    Milvus  Recall Rerank      LLM   Prompt Report
解析    解析    抽象        向量库  TopK   重排        分析   工程   生成
        │
        ▼
 Kernel Expert Knowledge
```

## 3. 项目目录结构

```text
core-linuxcommit/
├── src/                        # 源代码根目录
│   ├── api/                    # FastAPI 接口层
│   │   ├── routers/            # 路由定义 (analyze, tasks, results)
│   │   ├── schemas/            # Pydantic 数据模型 (Request/Response)
│   │   ├── middleware/         # 异常处理、日志拦截中间件
│   │   └── dependencies/       # 鉴权、数据库连接等依赖
│   ├── analyzer/               # 宕机日志/vmcore 解析核心
│   │   ├── dmesg/              # dmesg 正则解析与 Call Trace 提取
│   │   ├── vmcore/             # 基于 drgn 的 vmcore 对象提取
│   │   ├── rootcause/          # 根因抽象模型逻辑
│   │   └── pipeline/           # 分析流水线编排
│   ├── collector/              # 离线数据采集 (Git Mining)
│   │   ├── git/                # PyDriller 仓库遍历
│   │   ├── parser/             # Commit Diff/Message 解析
│   │   └── subsystem/          # 内核子系统识别逻辑
│   ├── indexer/                # 向量化与索引
│   │   ├── embedding/          # BGE-M3 模型调用
│   │   ├── milvus/             # Milvus 向量存取封装
│   │   └── pipeline/           # 索引构建流水线
│   ├── retriever/              # 检索与重排 (核心逻辑)
│   │   ├── recall/             # Milvus 向量召回 (Top-K)
│   │   ├── rerank/             # BGE-Reranker-v2 精准排序
│   │   ├── filter/             # 基于版本/子系统的规则过滤
│   │   └── pipeline/           # 检索流水线
│   ├── generator/              # 报告生成
│   │   ├── llm/                # DeepSeek/Qwen 接口封装
│   │   ├── prompt/             # 提示词工程 (RAG Prompt)
│   │   └── report/             # Markdown/JSON 报告格式化
│   ├── knowledge/              # 内核专家知识库
│   │   ├── bug_patterns/       # 典型 Bug 模式映射
│   │   ├── lock_rules/         # 锁依赖语义规则
│   │   └── subsystem_graph/    # 子系统交互图谱
│   ├── models/                 # SQLAlchemy/Pydantic 全局模型
│   ├── services/               # 业务逻辑编排层 (Orchestration)
│   └── common/                 # 通用工具类
│       ├── exceptions/         # 自定义业务异常
│       ├── logging/            # Loguru 统一日志配置
│       └── utils/              # 辅助函数
├── frontend/                   # React + Ant Design Pro 前端
├── configs/                    # 配置文件 (.env, config.yaml)
├── data/                       # 本地持久化数据与缓存
├── docker/                     # Dockerfile 与 Compose 配置
├── scripts/                    # 运维与初始化脚本
├── tests/                      # Pytest 单元测试与集成测试
└── requirements.txt            # 项目依赖
```

## 4. 技术栈

| 领域 | 技术选型 |
| :--- | :--- |
| **Backend** | Python 3.12, FastAPI, SQLAlchemy, PostgreSQL |
| **AI / LLM** | DeepSeek-R1, Qwen2.5 |
| **Embedding** | BGE-M3 (支持多模态语义) |
| **Rerank** | BGE-Reranker-v2 |
| **Vector DB** | Milvus |
| **Kernel Tooling** | drgn, PyDriller, crash |
| **Infrastructure** | Docker, Redis (Cache) |

## 5. 检索算法亮点

1.  **语义非对称性解决**: 通过 Root Cause Abstraction 模块，将繁杂的宕机日志抽象为结构化的内核概念（Kernel Concept），消除日志与补丁描述之间的表述鸿沟。
2.  **四阶段检索架构**:
    *   **Rule Filter**: 基于子系统与内核版本的硬过滤。
    *   **Milvus Recall**: 快速召回语义相关的 Top-100 Commit。
    *   **BGE Rerank**: 对候选集进行精准深度排序。
    *   **LLM Judge**: 利用大模型从因果关联角度进行最终评分。
3.  **专家知识融合**: 引入内核专家经验库（Knowledge Base），辅助识别锁竞争、UAF、空指针等典型内存错误。

## 6. 开发规范

*   **Type Hints**: 所有函数必须标注类型。
*   **Logging**: 统一使用 `loguru`，禁止使用 `print()`。
*   **Exception**: 业务异常需继承 `BaseBusinessException`。
*   **Format**: 遵循 Black (代码格式) 与 Ruff (静态检查)。

---
*© 2026 Core.LinuxCommit Project Team*
