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
│   │   ├── routers/            # 路由定义 (analyze, search, stats)
│   │   ├── schemas/            # Pydantic 数据模型 (Request/Response)
│   │   ├── middleware/         # 异常处理、日志拦截中间件
│   │   └── dependencies/       # 鉴权、数据库连接等依赖
│   ├── analyzer/               # 宕机日志/vmcore 解析核心
│   │   ├── dmesg/              # dmesg 正则解析与 Call Trace 提取
│   │   ├── vmcore/             # 基于 drgn 的 vmcore 对象提取
│   │   ├── drgn/               # drgn 调试工具封装
│   │   ├── rootcause/          # 根因抽象模型逻辑
│   │   ├── models/             # 分析结果数据模型
│   │   └── pipeline/           # 分析流水线编排
│   ├── collector/              # 离线数据采集 (Git Mining)
│   │   ├── git/                # PyDriller 仓库遍历
│   │   ├── parser/             # Commit Diff/Message 解析
│   │   ├── subsystem/          # 内核子系统识别逻辑
│   │   ├── analysis/           # 高级特征分析（锁、RCU、refcount）
│   │   ├── bugtype/            # Bug 类型识别
│   │   └── models/             # CommitInfo/FileChangeInfo 数据模型
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
├── frontend/                   # Vue 3 + Element Plus 前端 (Vite 构建)
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

## 6. 前端架构

### 6.1 技术选型

| 领域 | 技术 |
|------|------|
| **框架** | Vue 3 (Composition API) |
| **UI 组件库** | Element Plus (暗色主题) |
| **构建工具** | Vite 6 |
| **状态管理** | Pinia + pinia-plugin-persistedstate |
| **路由** | Vue Router 4 |
| **HTTP 客户端** | Axios (请求/响应拦截、自动重试) |
| **图表** | ECharts 5 + vue-echarts |
| **Markdown 渲染** | marked |
| **代码高亮** | highlight.js |
| **时间处理** | dayjs |

### 6.2 页面结构

| 路由 | 页面 | 说明 |
|------|------|------|
| `/` | Dashboard | 系统仪表盘 — 统计概览、图表、快速入口 |
| `/analyze` | CrashAnalysis | 宕机日志分析 — 提交日志、查看分析进度和结果 |
| `/knowledge` | KnowledgeBase | 补丁知识库 — 搜索/浏览百万级 Commit |
| `/history` | History | 分析历史 — 查看/管理历史分析记录 |

### 6.3 前端特性

- **暗色专业主题**: 针对运维/内核开发者场景的暗色 UI
- **实时轮询**: 提交分析后自动轮询任务状态 (1.5s 间隔)
- **状态持久化**: 最近 10 条分析结果缓存在 localStorage
- **响应式布局**: 支持桌面端和平板端
- **API 代理**: Vite 开发服务器自动代理 `/api` 到后端
- **速率限制提示**: 请求过频时自动弹出提示
- **代码分割**: 生产构建按模块拆分 vendor chunks
- **Diff 语法高亮**: 补丁 Diff 预览高亮显示

### 6.4 前端启动

```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 开发模式启动 (默认 http://localhost:5173)
npm run dev

# 生产构建
npm run build

# 预览生产构建
npm run preview
```

### 6.5 与后端 API 的连接

前端通过 Vite 代理连接到后端 FastAPI 服务:

```
开发环境:
  浏览器 → Vite Dev Server (:5173) → FastAPI (:8000)
  /api/* 请求自动代理到 http://127.0.0.1:8000

生产环境:
  浏览器 → Nginx → 静态文件 (Vue dist)
                 → /api/* → FastAPI (:8000)
```

前端 API 客户端配置在 `frontend/src/api/client.js`:
- 自动添加请求追踪 ID (`X-Request-ID`)
- 统一错误处理 (429/500/网络错误自动通知)
- 30 秒请求超时

## 7. 开发规范

*   **Type Hints**: 所有函数必须标注类型。
*   **Logging**: 统一使用 `loguru`，禁止使用 `print()`。
*   **Exception**: 业务异常需继承 `BaseBusinessException`。
*   **Format**: 遵循 Black (代码格式) 与 Ruff (静态检查)。

---
*© 2026 Core.LinuxCommit Project Team*
