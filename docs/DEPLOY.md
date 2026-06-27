# project3136859-388917 部署文档

> Linux Kernel Crash → Root Cause → Patch Matching System

---

## 目录

- [1. 环境要求](#1-环境要求)
- [2. 快速开始 (Demo 模式)](#2-快速开始-demo-模式)
- [3. 全量数据库部署](#3-全量数据库部署)
- [4. LLM 配置](#4-llm-配置)
- [5. 验证部署](#5-验证部署)
- [6. 常见问题](#6-常见问题)
- [7. 项目结构](#7-项目结构)

---

## 1. 环境要求

| 依赖 | 最低版本 | 用途 |
|------|---------|------|
| Python | 3.10+ | 后端服务 |
| pip | 21.0+ | 包管理 |
| curl | 7.0+ | 下载全量数据 |
| zstd | 1.4+ | 解压数据包 |
| Node.js | 18+ | 前端构建（可选，dist/ 已包含构建产物） |
| 磁盘空间 | ≥ 5 GB | 索引存储（Demo: 80MB / 全量: 3.1 GB） |
| 内存 | ≥ 4 GB | Embedding 模型 + FAISS 索引 |

### 安装系统依赖

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install -y python3 python3-pip python3-venv curl zstd

# CentOS / RHEL
sudo yum install -y python3 python3-pip curl zstd
```

---

## 2. 快速开始 (Demo 模式)

Demo 模式使用项目内置的轻量数据（9,990 条 commit），无需额外下载。

```bash
# 1. 克隆项目
git clone <repo-url>
cd project3136859-388917

# 2. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动服务
python -m src.main
```

访问 http://localhost:8000/api/docs 查看 API 文档。

> **注意**: Demo 数据已内置于 `data/` 目录，首次启动自动加载（约 5 秒预热）。

### 2.1 Demo 与全量模式切换

项目默认使用内置的 Demo 数据（`data/`，9,990 条）。部署全量数据后，通过环境变量切换：

```bash
# Demo 模式（默认，无需设置）
python -m src.main

# 全量模式（需先下载全量数据）
export FAISS_INDEX_PATH=./data_full/faiss_index
python -m src.main

# 切回 Demo 模式
unset FAISS_INDEX_PATH
python -m src.main
```

启动日志中会显示当前使用的数据量：

```
✓ 向量库就绪: 9,990 条    ← Demo 模式
✓ 向量库就绪: 312,632 条  ← 全量模式
```

---

## 3. 全量数据库部署

全量数据库包含 **312,632 条**经过版本标注的 Linux Kernel commit，覆盖内核版本 4.9 ~ 6.13，向量维度 1024（BGE-M3）。

| 指标 | Demo (data/) | 全量 (data_full/) |
|------|-------------|------------------|
| Commit 数 | 9,990 | **312,632** |
| 存储大小 | ~80 MB | **~3.1 GB** |
| 内核版本覆盖 | 4.9 ~ 6.13 | 4.9 ~ 6.13 |
| 版本标注 | 部分 | **全部** |
| Top-3 预期命中率 | 基准 | **显著提升** |

### 3.1 一键部署（详细部署可参考scripts/目录下的DEPLOY.md文件）

```bash
# 在项目根目录执行
bash scripts/download_data_full.sh ./data_full
```

脚本自动完成：下载 → gzip 校验 → 解压 → 就绪。

### 3.2 启动（全量模式）

```bash
# 设置全量数据路径
export FAISS_INDEX_PATH=./data_full/faiss_index

# 启动
source venv/bin/activate
python -m src.main
```

预期输出：
```
FAISS 模式 (已有 312632 条数据, path=data_full/faiss_index)
  ✓ Embedding 模型就绪 (3.2s)
  ✓ 向量库就绪: 312,632 条 (5.1s)
  ✓ Reranker 模型就绪 (6.8s)
预热完成，总耗时 6.8s
API server ready to accept requests
```

---

## 4. LLM 配置

系统支持三种 LLM 模式：

### 4.1 免费本地模型 (Ollama) — 推荐

```bash
# 安装 Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 下载模型
ollama pull qwen2.5:7b

# 启动服务（Ollama 默认监听 localhost:11434）
# 无需额外配置，系统自动检测
```

### 4.2 自带 API Key

在前端界面选择"使用我自己的 API Key"，支持：
- DeepSeek (`https://api.deepseek.com/v1`)
- OpenAI (`https://api.openai.com/v1`)
- Qwen (`https://dashscope.aliyuncs.com/compatible-mode/v1`)

### 4.3 无 LLM (规则引擎降级)

不配置任何 LLM 时，系统使用专家规则引擎生成报告，核心检索功能不受影响。

---

## 5. 验证部署

### 5.1 健康检查

```bash
curl http://localhost:8000/health
```

预期响应：
```json
{
  "status": "healthy",
  "service": "project3136859-388917 API",
  "version": "1.0.0",
  "uptime_seconds": 12.3,
  "memory_mb": 452.1
}
```

### 5.2 提交测试分析

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "log_content": "BUG: unable to handle kernel NULL pointer dereference at 0000000000000028\nCall Trace:\n [<ffffffff81234567>] list_del+0x12/0x30\n [<ffffffff81345678>] __slab_free+0xab/0x2c0",
    "log_type": "dmesg",
    "top_k": 5,
    "enable_llm_explanation": false
  }'
```

预期响应：
```json
{
  "task_id": "task_xxxxxxxxxxxx",
  "status": "running",
  "created_at": "2026-06-27T..."
}
```

### 5.3 查询分析结果

```bash
curl http://localhost:8000/api/v1/analyze/{task_id}
```

### 5.4 前端访问

浏览器打开 http://localhost:8000，或使用已构建的前端：

```bash
cd frontend
npm install    #安装依赖
npm run dev    # 开发模式
# 或
npm run build  # 生产构建 → dist/
```

---

## 6. 常见问题

### Q: 下载中断了怎么办？

脚本支持断点续传，直接重新运行即可：
```bash
bash scripts/download_data_full.sh
```

### Q: 磁盘空间不足？

清理已下载的压缩包后重新部署：
```bash
rm -f data_full/data_full_v1.0.tar.zst
bash scripts/download_data_full.sh
```

### Q: FAISS 索引加载失败？

```bash
# 检查数据文件完整性
ls -lh data_full/faiss_index.*

# 重建环境变量
export FAISS_INDEX_PATH=$(pwd)/data_full/faiss_index

# 重启服务
python -m src.main
```

### Q: 内存不足？

BGE-M3 Embedding 模型约 2GB，Reranker 约 1.5GB。如内存不足：
```bash
# 使用 CPU only（默认）
export CUDA_VISIBLE_DEVICES=""
# 或降低 FAISS 搜索精度
export FAISS_NPROBE=8  # 默认 32，降低可减少内存占用
```

### Q: 如何确认使用的是全量数据？

查看启动日志中的向量数：
```
✓ 向量库就绪: 312,632 条  ← 全量
✓ 向量库就绪: 9,990 条   ← Demo
```

或通过 API：
```bash
curl http://localhost:8000/api/v1/stats | python3 -m json.tool | grep total_commits
```

---

## 7. 项目结构

```
project3136859-388917/
├── scripts/
│   └── download_data_full.sh    ← 全量数据部署脚本
├── src/
│   ├── analyzer/                 ← 宕机日志解析 + 根因分析
│   ├── retriever/                ← 向量检索 + 重排 + 过滤
│   ├── indexer/                  ← Embedding + FAISS/Milvus
│   ├── generator/                ← LLM 报告生成
│   ├── api/                      ← FastAPI 路由 + 中间件
│   ├── collector/                ← Git 仓库采集
│   ├── knowledge/                ← 内核领域知识库
│   └── main.py                   ← 服务入口
├── data/                         ← Demo 数据 (9,990 条)
├── data_full/                    ← 全量数据 (部署后, 312,632 条)
├── frontend/                     ← Vue3 前端
├── configs/                      ← YAML 配置文件
├── tests/                        ← 测试用例
├── docs/
│   └── DEPLOY.md                 ← 本文档
└── requirements.txt
```

---

## 附录: 数据来源说明

全量数据基于 [Linux Kernel Git](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git) 仓库构建：

| 步骤 | 工具 | 说明 |
|------|------|------|
| Commit 采集 | PyDriller | 提取 commit message、diff、作者、日期 |
| 子系统标注 | 路径映射 + 关键词 | 20+ 内核子系统分类 |
| Bug 类型标注 | 正则 + LLM | 21 种 Bug 类型 |
| 版本标注 | 提交日期推断 | 映射到内核 release date |
| 向量编码 | BGE-M3 | 1024 维，增强文本（Title + Subsystem + BugType + Diff Summary） |
| 索引 | FAISS IndexIVFFlat | IP 度量，IVF 聚类，L2 归一化 |
