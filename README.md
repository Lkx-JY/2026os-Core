# Linux 内核宕机自动诊断与补丁匹配系统

> **Linux Kernel Crash → Root Cause → Patch Matching System**
>
> 基于 RAG (Retrieval-Augmented Generation) + 内核领域知识 + LLM 的自动化内核补丁匹配系统。
> 输入 dmesg/vmcore 宕机日志，自动识别根因并从百万级 Linux kernel commit 中精准匹配修复补丁。

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3.x-brightgreen.svg)](https://vuejs.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 目录

- [1. 项目背景](#1-项目背景)
- [2. 核心架构](#2-核心架构)
- [3. 技术创新点](#3-技术创新点)
- [4. 技术栈](#4-技术栈)
- [5. 项目结构](#5-项目结构)
- [6. 快速开始](#6-快速开始)
  - [6.5 部署文档](#65-部署文档)
  - [6.6 项目文档](#66-项目文档)
  - [6.7 Docker 部署](#67-docker-部署)
- [7. API 文档](#7-api-文档)
- [8. 前端界面](#8-前端界面)
- [9. 开发指南](#9-开发指南)
- [10. 性能指标](#10-性能指标)

---

## 1. 项目背景

### 问题场景

Linux 内核宕机（Kernel Crash）是云计算和数据中心运维的核心痛点。当系统发生 hardlockup、hungtask、内存错误等故障时：

- **传统人工分析** 需要数小时甚至数天，依赖资深内核专家
- **Linux 内核 Git 仓库** 包含 30+ 年演进历史、累计超过 100 万次 commit、涉及上万名开发者
- **宕机日志与补丁描述** 存在语义鸿沟 — 日志呈现运行时错误现象，补丁描述代码层修复逻辑
- 从海量 commit 中定位修复补丁效率极低，容易遗漏关键信息

### 解决方案

Linux 内核宕机自动诊断与补丁匹配系统 构建了 **四阶段检索增强生成 (RAG) 流水线**：

```text
宕机日志 (dmesg/vmcore)
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Phase 1: 特征提取                                    │
│  正则 + LLM → CrashFeature (子系统/错误类型/调用栈)     │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  Phase 2: 根因抽象 (28 条专家规则 + 4 层分层分析)      │
│  CrashFeature → RootCauseResult                      │
│  ★ 对称 Root Cause Embedding 核心创新                 │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  Phase 3: 向量检索 (Milvus/FAISS Top-100 Recall)     │
│  Rule Filter → BGE Rerank → LLM Judge               │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  Phase 4: 报告生成                                    │
│  Top-N 补丁推荐 + 相关性评分 + LLM 解释               │
└─────────────────────────────────────────────────────┘
```

---

## 2. 核心架构

系统分为 **离线数据治理** 和 **在线分析检索** 两个阶段：

### 2.1 离线阶段 — Commit 知识库构建

```text
Linux Kernel Git Repo (145 万+ commits)
    │
    ▼ PyDriller 流式遍历 (O(1) 内存)
┌─────────────────────────────────────────┐
│ 结构化提取                               │
│ · commit_id / subject / body            │
│ · subsystem (28 个子系统)                │
│ · bug_type (21 种 Bug 类型)              │
│ · diff 语义分析 (锁/RCU/refcount)        │
│ · Fixes: / Cc: stable 标签解析           │
└───────────────┬─────────────────────────┘
                ▼
┌─────────────────────────────────────────┐
│ ★ 对称 Root Cause 分析                   │
│ CommitRootCauseBuilder 轻量引擎 (3层)    │
│ 生成与在线侧结构对称的 embedding 文本     │
│ → 消除 "现象 vs 补丁" 语义鸿沟            │
└───────────────┬─────────────────────────┘
                ▼
┌─────────────────────────────────────────┐
│ BGE-M3 向量编码 (1024 维)                │
│ → Milvus Lite / FAISS 向量库存储         │
└─────────────────────────────────────────┘
```

### 2.2 在线阶段 — 宕机诊断与补丁匹配

```text
用户提交: dmesg 日志 / vmcore 文件
    │
    ▼
┌──────────────────────────────────┐
│ 1. Feature Extraction            │
│    dmesg: 20+ Panic 模式正则      │
│    vmcore: drgn 内核对象提取      │
│    → CrashFeature                │
└────────────┬─────────────────────┘
             ▼
┌──────────────────────────────────┐
│ 2. Root Cause Abstraction        │
│    28 条专家规则 + 4 层分层推断   │
│    + LLM 协同推理 (可选)         │
│    → RootCauseResult             │
│    → retrieval_query (6层融合)   │
└────────────┬─────────────────────┘
             ▼
┌──────────────────────────────────┐
│ 3. Four-Stage Retrieval          │
│    ┌─ Recall: 向量 Top-100       │
│    ├─ Filter: 子系统/版本/类型   │
│    ├─ Rerank: BGE-Reranker-v2   │
│    └─ LLM Judge: 因果关联评分   │
│    → Top-N Matched Patches      │
└────────────┬─────────────────────┘
             ▼
┌──────────────────────────────────┐
│ 4. Report Generation             │
│    Markdown/JSON 报告 + LLM 解释  │
│    含因果链 + 评分依据            │
└──────────────────────────────────┘
```

---

## 3. 技术创新点

### 3.1 对称 Root Cause Embedding ⭐ 核心创新

这是解决 **"宕机现象 ≠ commit 描述"语义鸿沟** 的关键设计：

```text
离线侧 (Commit)                          在线侧 (宕机日志)
     │                                         │
CommitInfo (已提取的结构化特征)          dmesg → CrashFeature
     │                                         │
     ▼                                         ▼
CommitRootCauseBuilder.build()         RootCauseAnalyzer.analyze()
(3层轻量: 模板查表+Diff规则+置信度)     (4层: 专家规则+调用栈+类型抽象+兜底)
     │                                         │
     ▼                                         ▼
build_commit_embedding_text()          build_retrieval_query()
(与 retrieval_query 结构对称)          (6层语义融合)
     │                                         │
     ▼                                         ▼
  BGE-M3 编码 → Milvus             BGE-M3 编码 → Milvus Search
```

两端输出**结构对称的 embedding 文本**（相同的字段格式和语义层次），确保检索时 query 和 document 在相同的语义空间中。离线侧使用轻量级 CommitRootCauseBuilder (3-5ms/commit) 以支持百万级数据索引，在线侧使用完整 RootCauseAnalyzer (~100ms) 以保证分析精度。

### 3.2 四阶段检索架构

| 阶段 | 方法 | 作用 | 候选集 |
|------|------|------|--------|
| **Recall** | Milvus/FAISS 向量检索 | 快速召回语义相关 commit | Top-100 |
| **Filter** | 子系统/版本/Bug类型硬过滤 | 剔除不相关候选 | ~50-80 |
| **Rerank** | BGE-Reranker-v2 Cross-encoder | 深度语义匹配重排 | Top-20 |
| **LLM Judge** | LLM 因果关联评分 | 最终精准排序 | Top-3~5 |

### 3.3 领域知识深度融合

- **28 条专家规则**: 覆盖 NULL pointer / UAF / deadlock / race condition 等
- **10 种 Bug 模式**: 完整知识图谱 (症状 → 根因 → 修复模式 → 检测工具)
- **6 种锁类型 + 5 种死锁模式 + 8 条锁排序规则**
- **7 个子系统交互图**: 层级关系 + 耦合关系 + 调用关系

### 3.4 多模态输入支持

- **dmesg 文本日志**: 20+ Panic 模式正则 + LLM 深度分析 + Call Trace 提取
- **vmcore 内存镜像**: drgn 调试器集成，寄存器/内核对象/调用栈重建
- **问题描述**: 自然语言描述 → LLM 特征提取

---

## 4. 技术栈

| 领域 | 技术选型 | 说明 |
|:---|:---|:---|
| **后端框架** | Python 3.12 + FastAPI | 异步高性能 API |
| **大语言模型** | DeepSeek / Qwen / OpenAI 兼容 + Ollama 本地 | 用户可选付费 API 或免费本地模型 |
| **Embedding** | BGE-M3 (BAAI/bge-m3) | 1024 维，中英双语，8192 tokens |
| **Reranker** | BGE-Reranker-v2-m3 | Cross-encoder 深度语义匹配 |
| **向量数据库** | Milvus Lite + FAISS | 双后端，自动降级 |
| **Git 挖掘** | PyDriller | 流式遍历，O(1) 内存 |
| **内核调试** | drgn | vmcore 解析，内核对象提取 |
| **前端** | Vue 3 + Element Plus + ECharts  |
| **状态管理** | Pinia | 前端分析/搜索状态 |
| **基础设施** | Docker Compose | App + Milvus + Redis 一键部署 |
| **缓存** | Redis | 任务状态 + 查询缓存 |

---

## 5. 项目结构

```text
project3136859-388917/
├── src/                            # Python 后端源代码
│   ├── api/                        # FastAPI 接口层
│   │   ├── routers/                # analyze / search / stats 路由
│   │   ├── schemas/                # Pydantic 请求/响应模型 (requests/entities/responses)
│   │   ├── middleware/             # CORS / 计时 / 限流 / 日志中间件
│   │   ├── dependencies/           # 依赖注入 (配置加载)
│   │   └── storage/                # Redis 任务存储
│   ├── analyzer/                   # 宕机分析核心
│   │   ├── dmesg/                  # dmesg 日志正则解析 (20+ Panic 模式 + LLM 深度分析)
│   │   ├── vmcore/                 # vmcore drgn 解析
│   │   ├── drgn/                   # drgn 调试器集成
│   │   ├── rootcause/              # 根因抽象 (28 条专家规则 + LLM 协同推理)
│   │   ├── models/                 # CrashFeature / RootCauseResult
│   │   ├── pipeline/               # 分析流水线编排
│   │   └── commit_rules.py         # ★ Commit 根因分析轻量引擎 (离线索引路径)
│   ├── collector/                  # 离线 Commit 采集
│   │   ├── git/                    # PyDriller 流式仓库遍历 (O(1) 内存)
│   │   ├── parser/                 # Commit message/diff 解析
│   │   ├── subsystem/              # 子系统识别 (28 个)
│   │   ├── bugtype/                # Bug 类型识别 (21 种)
│   │   ├── analysis/               # 锁/RCU/refcount 高级分析
│   │   └── models/                 # CommitInfo / QueryResult 数据模型
│   ├── indexer/                    # 向量化与索引
│   │   ├── embedding/              # BGE-M3 编码器 (GPU 加速 + 多模型支持)
│   │   ├── milvus/                 # Milvus + FAISS 双后端
│   │   └── pipeline/               # ★ 对称 Root Cause Embedding 流水线
│   ├── retriever/                  # 在线检索核心
│   │   ├── recall/                 # 向量召回 (Milvus/FAISS Top-K)
│   │   ├── filter/                 # 子系统/版本/类型规则过滤
│   │   ├── rerank/                 # BGE-Reranker-v2 + LLM Judge
│   │   └── pipeline/               # fast/standard/deep 三种检索模式
│   ├── generator/                  # 报告生成
│   │   ├── llm/                    # DeepSeek/Qwen/OpenAI 统一接口 + Ollama 本地
│   │   ├── prompt/                 # 场景化 Prompt 模板 + Few-shot 示例
│   │   └── report/                 # Markdown/JSON 报告格式化
│   ├── knowledge/                  # 内核领域知识库
│   │   ├── bug_patterns/           # 10 种 Bug 模式知识图谱
│   │   ├── lock_rules/             # 6 锁类型 + 5 死锁模式 + 8 条排序规则
│   │   └── subsystem_graph/        # 12 子系统交互关系 (层级/耦合/调用)
│   ├── services/                   # 业务逻辑编排 (端到端在线诊断)
│   ├── models/                     # 全局数据模型 (枚举 + 配置 + API 模型)
│   └── common/                     # 公共基础设施
│       ├── exceptions/             # 层次化异常类体系 (6 大类 20+ 异常)
│       ├── logging/                # loguru 统一日志 (结构化 + 性能计时)
│       ├── utils/                  # 工具函数 (文本/哈希/数值/批处理/调试)
│       ├── config.py               # 统一配置中心 (环境变量 + YAML)
│       └── taxonomy.py             # Bug 类型标准分类体系 (跨模块标准化)
├── frontend/                       # Vue 3 前端
│   └── src/
│       ├── views/                  # Dashboard / CrashAnalysis / KnowledgeBase / History
│       ├── components/             # AppLayout
│       ├── api/                    # Axios API 客户端
│       ├── stores/                 # Pinia 状态管理
│       ├── router/                 # Vue Router 路由
│       ├── styles/                 # 暗色专业主题样式
│       └── utils/                  # 格式化 / 错误处理
├── scripts/                        # 运维脚本
│   ├── start-dev.sh                # 一键启动 (后端 + 前端)
│   └── index_all_commits.py        # 全量 Commit 索引 (断点续跑)
├── configs/                        # 配置文件
│   └── config.yaml                 # 统一应用配置 (LLM/Milvus/Redis/Server)
├── docker/                         # Docker 部署
│   ├── Dockerfile                  # Python 3.12-slim
│   └── docker-compose.yml          # App + Milvus + Redis
├── tests/                          # 测试
│   ├── conftest.py                 # Pytest fixtures
│   ├── fixtures/                   # 9 种宕机日志样本
│   ├── test_integration.py         # 端到端集成测试
│   ├── test_analyzer.py            # 分析器单元测试
│   ├── test_collector.py           # 采集器单元测试
│   ├── test_commit_rules.py        # Commit 规则引擎测试
│   ├── test_indexer.py             # 索引器单元测试
│   └── test_retriever.py           # 检索器单元测试
├── .env.example                    # 环境变量模板
├── requirements.txt                # Python 依赖
└── README.md                       # 本文档
```

---

## 6. 快速开始

### 6.1 环境要求

- **Python**: 3.12+
- **Node.js**: 18+ (前端开发)
- **Git**: 2.x
- **Ollama** (推荐): 免费本地大模型，用户无需 API Key 即可使用 LLM 分析
- **Linux 内核仓库**: 本地 clone (用于 Commit 采集)
- **GPU** (可选): CUDA 兼容 GPU 可大幅加速 Embedding 编码

### 6.2 安装

```bash
# 1. 克隆项目
git clone <repo-url>
cd project3136859-388917

# 2. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装 Ollama (推荐 — 免费本地大模型)
curl -fsSL https://ollama.com/install.sh | sh
# 或 snap: sudo snap install ollama
ollama pull qwen2.5:7b     # 下载模型 (~4.7GB，仅首次)
ollama serve &              # 启动 Ollama 后台服务

# 5. 配置环境变量 (可选)
cp .env.example .env
# ★ API Key 不再强制要求 — 用户可在 Web 前端自行提供，或使用 Ollama 免费模型

# 6. 安装前端依赖
cd frontend && npm install && cd ..
```

### 6.3 索引 Linux 内核 Commit

```bash
# 确认 Linux 内核仓库路径
ls /path/to/linux/.git

# 先小规模测试 (1000 条)
python scripts/index_all_commits.py \
  --repo-path /path/to/linux \
  --limit 1000

# 确认流程无误后，大规模索引 (建议 10 万起步)
python scripts/index_all_commits.py \
  --repo-path /path/to/linux \
  --limit 100000 \
  --batch-size 1000

# 如需断点续跑:
python scripts/index_all_commits.py \
  --repo-path /path/to/linux \
  --limit 100000 \
  --resume
```

### 6.4 启动服务（详细见docs/DEPLOY.md）

```bash
# 方式 1: 一键启动脚本 (后端 + 前端)
bash scripts/start-dev.sh

# 方式 2: 分别启动
# 终端 1 — 后端
python -m src.main

# 终端 2 — 前端
cd frontend && npm run dev
```

服务启动后：
- **前端界面**: http://localhost:5173
- **API 文档**: http://localhost:8000/api/docs (Swagger)
- **健康检查**: http://localhost:8000/health

> **关于数据**: 项目内置了 Demo 数据（`data/`，9,990 条），启动即可使用。
> 如需更高检索精度，可部署全量数据库（312,632 条），详见下方部署文档。

### 6.5 部署文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 完整部署指南 | [`docs/DEPLOY.md`](docs/DEPLOY.md) | 环境要求、Demo/全量模式、LLM配置、常见问题 |
| 全量数据部署 | [`scripts/DEPLOY.md`](scripts/DEPLOY.md) | 123云盘直链下载全量数据库的详细步骤 |
| 全量数据快速部署 | [`data_full/DEPLOY.md`](data_full/DEPLOY.md) | 全量数据的快速部署说明 |

### 6.6 项目文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 设计方案文档 | [`2026年全国大学生计算机系统能力大赛-操作系统设计赛：宕机upstream patch匹配设计方案文档.docx`](2026年全国大学生计算机系统能力大赛-操作系统设计赛：宕机upstream%20patch匹配设计方案文档.docx) | 大赛设计方案文档 |
| 项目测试结果的功能、性能、创新性分析文档 | [`2026年全国大学生计算机系统能力大赛-操作系统设计赛：2026年全国大学生计算机系统能力大赛-操作系统设计赛：项目测试结果的功能、性能、创新性分析文档.docx`](2026年全国大学生计算机系统能力大赛-操作系统设计赛：2026年全国大学生计算机系统能力大赛-操作系统设计赛：项目测试结果的功能、性能、创新性分析文档.docx) | 大赛测试方案文档 |
| 作品进展汇报 | [`Linux内核宕机自动诊断与补丁匹配系统_作品进展汇报幻灯片汇报.pptx`](Linux内核宕机自动诊断与补丁匹配系统_作品进展汇报幻灯片汇报.pptx) | 作品进展汇报幻灯片 |

### 6.7 Docker 部署

```bash
cd docker
docker-compose up -d
# 启动 App + Milvus + Redis 三个服务
```

---

## 7. API 文档

### 7.1 核心接口

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| `POST` | `/api/v1/analyze` | 提交宕机日志，异步分析，返回 task_id |
| `GET` | `/api/v1/analyze/{task_id}` | 查询分析任务状态与结果 |
| `GET` | `/api/v1/analyze?page=1&page_size=20` | 列出历史分析任务 |
| `POST` | `/api/v1/search` | 搜索补丁知识库 |
| `GET` | `/api/v1/search/{commit_id}` | 获取单个 Commit 详情 |
| `GET` | `/api/v1/search/subsystems/list` | 列出所有子系统 |
| `GET` | `/api/v1/search/bug-types/list` | 列出所有 Bug 类型 |
| `GET` | `/api/v1/stats` | 获取系统概览统计 |

### 7.2 使用示例

#### 提交宕机日志分析

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "log_content": "BUG: unable to handle kernel NULL pointer dereference at 0000000000000008\n...",
    "log_type": "dmesg",
    "kernel_version": "6.1.0",
    "top_k": 5,
    "enable_llm_explanation": true
  }'
```

响应:
```json
{
  "task_id": "task_a1b2c3d4e5f6",
  "status": "running",
  "created_at": "2026-06-22T10:00:00Z"
}
```

#### 查询分析结果

```bash
curl http://localhost:8000/api/v1/analyze/task_a1b2c3d4e5f6
```

响应:
```json
{
  "task_id": "task_a1b2c3d4e5f6",
  "status": "completed",
  "progress": 1.0,
  "result": {
    "analysis_mode": "real",
    "root_cause": {
      "root_cause": "null_pointer_dereference",
      "subsystem": "mm",
      "confidence": 0.92,
      "summary": "空指针解引用，未做有效性检查即访问指针成员",
      "key_symptoms": ["NULL pointer dereference", "unable to handle kernel NULL pointer"]
    },
    "matched_patches": [
      {
        "rank": 1,
        "commit": {
          "commit_id": "a1b2c3d4e5f6...",
          "title": "mm: fix NULL pointer dereference in slub allocator",
          "subsystem": "mm",
          "bug_type": "null_pointer"
        },
        "relevance_score": 0.95,
        "match_reason": "该补丁在 slub 分配器中添加空指针检查，直接修复了崩溃路径"
      }
    ],
    "elapsed_ms": 1850
  }
}
```

#### 搜索补丁

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "NULL pointer dereference in memory management",
    "top_k": 10,
    "subsystem": "mm",
    "page": 1,
    "page_size": 20
  }'
```

---

## 8. 前端界面

| 页面 | 路由 | 功能 |
|:---|:---|:---|
| **Dashboard** | `/` | 系统仪表盘 — 统计概览、图表、快速入口 |
| **CrashAnalysis** | `/analyze` | 宕机日志分析 — 提交日志，查看分析进度和结果 |
| **KnowledgeBase** | `/knowledge` | 补丁知识库 — 搜索/浏览已索引的 Commit |
| **History** | `/history` | 分析历史 — 查看/管理历史分析记录 |

### 前端特性

- **暗色专业主题**: 针对运维/内核开发者场景
- **实时轮询**: 提交分析后自动轮询任务状态 (1.5s 间隔)
- **Diff 语法高亮**: 补丁 Diff 预览 highlight.js 高亮
- **响应式布局**: 支持桌面端和平板端
- **API 代理**: Vite 开发服务器自动代理 `/api` 到后端

---

## 9. 开发指南

### 9.1 代码规范

| 规范 | 工具 | 说明 |
|:---|:---|:---|
| **类型注解** | mypy / built-in | 所有函数必须标注参数和返回类型 |
| **日志** | loguru | 统一使用 `logger.info/warning/error`，禁止 `print()` |
| **异常** | BaseBusinessException | 业务异常继承统一基类 |
| **格式化** | Black | 代码自动格式化 |
| **静态检查** | Ruff | 代码质量检查 |

### 9.2 运行测试

```bash
# 安装测试依赖
pip install pytest pytest-asyncio pytest-cov

# 运行集成测试 (跳过 LLM)
SKIP_API_KEY_CHECK=1 python tests/test_integration.py

# 运行全部测试
SKIP_API_KEY_CHECK=1 python -m pytest tests/ -v

# 生成覆盖率报告
SKIP_API_KEY_CHECK=1 python -m pytest tests/ --cov=src --cov-report=html
```

### 9.3 添加新的 Bug 模式

编辑 `src/knowledge/bug_patterns/__init__.py`:

```python
BUG_PATTERNS["new_bug_type"] = {
    "name": "New Bug Type",
    "severity": "HIGH",
    "symptoms": ["symptom1", "symptom2"],
    "root_causes": ["cause1", "cause2"],
    "fix_patterns": ["pattern1", "pattern2"],
    "detection_tools": ["KASAN", "lockdep"],
    "kernel_configs": ["CONFIG_DEBUG_..."],
}
```

### 9.4 添加新的专家规则

编辑 `src/analyzer/rootcause/__init__.py`，在 `EXPERT_RULES` 中添加新规则。

---

## 10. 性能指标

### 目标指标

| 指标 | 目标值 | 说明 |
|:---|:---|:---|
| **Top-3 命中率** | ≥ 60% | 基于 Fixes: 标签的 ground truth 测试 |
| **检索延迟** | < 3s (standard) / < 100ms (fast) | 端到端查询延迟 |
| **Commit 索引量** | 100 万+ | 支持全量 Linux kernel commit |
| **API 响应** | < 500ms | 统计/搜索接口响应时间 |
| **内存占用** | < 8GB | 含 FAISS 索引驻留 |
| **并发支持** | 50+ QPS | FastAPI 异步处理 |

### 检索模式对比

| 模式 | Recall | Filter | Rerank | LLM Judge | 延迟 |
|:---|:---|:---|:---|:---|:---|
| **fast** | ✅ Top-50 | ✅ | ❌ | ❌ | < 100ms |
| **standard** | ✅ Top-100 | ✅ | ✅ BGE | ❌ | < 1s |
| **deep** | ✅ Top-200 | ✅ | ✅ BGE | ✅ LLM | 2-10s |

---

## 11. 容错与降级设计

系统在多个层面实现了自动降级，确保在各种环境下都能提供基本服务：

| 组件 | 主方案 | 降级方案 | 触发条件 |
|:---|:---|:---|:---|
| **向量库** | Milvus Lite | FAISS 本地索引 | Milvus 不可用 |
| **LLM** | DeepSeek API（用户自备 Key）| Ollama 本地模型 → 规则引擎 | 用户未提供 Key / API 超时 |
| **Embedding** | BGE-M3 真实向量 | Mock 随机向量 | 模型权重未下载 |
| **任务存储** | Redis | 内存字典 + 线程锁 | Redis 连接失败 |
| **API 数据** | 真实向量检索 | Mock 数据降级 | 向量库为空 |

---

## 许可证

MIT License

---
