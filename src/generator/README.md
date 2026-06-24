# Generator — 报告生成模块

> **LLM Interface + Prompt Engineering + Report Generation**

负责将诊断结果和补丁检索结果整合为可读的诊断报告。是整个系统"从数据到洞察"的最后一公里。

---

## 目录

1. [模块架构](#1-模块架构)
2. [子模块说明](#2-子模块说明)
3. [数据流](#3-数据流)
4. [使用指南](#4-使用指南)

---

## 1. 模块架构

```
src/generator/
├── __init__.py            # 模块入口 — 统一导出所有公共 API
├── llm/__init__.py        # ★ LLM 接口 — DeepSeek/Qwen/OpenAI 统一调用
├── prompt/__init__.py     # ★ Prompt 工程 — 场景模板 + Few-shot 示例
├── report/__init__.py     # ★ 报告生成引擎 — Markdown/JSON/HTML
└── README.md              # 本文档
```

---

## 2. 子模块说明

### 2.1 llm — LLM 接口层

**职责**: 提供统一的大模型调用接口。

**核心实现**:

| 功能 | 说明 |
|------|------|
| **LLMClient** | 统一 LLM 客户端，支持多模型切换 |
| **chat()** | 标准对话接口，支持重试和指数退避 |
| **chat_stream()** | 流式输出，用于实时反馈 |
| **structured_output()** | 强制 JSON 输出，自动提取和解析 |
| **降级策略** | API 不可用时返回本地推理结果 |
| **使用统计** | Token 计数和调用次数追踪 |

**支持的模型**:
- DeepSeek (deepseek-chat) — 用户自备 API Key
- Qwen (qwen-plus / qwen-max) — 用户自备 API Key
- OpenAI 兼容 API — 用户自备 API Key
- Ollama 本地模型 (qwen2.5:7b / llama3 等) — ★ 免费，无需 API Key
- 自动降级: API 不可用或用户未提供 Key → 自动切换到 Ollama 本地模型

### 2.2 prompt — Prompt 工程

**职责**: 为不同场景构造高质量的大模型提示词。

**核心模板**:

| 模板 | 用途 |
|------|------|
| `build_diagnosis_report_prompt()` | 诊断报告生成 |
| `build_patch_explanation_prompt()` | 补丁与崩溃的因果解释 |
| `build_causal_reasoning_prompt()` | LLM Judge 因果评分 |
| `build_root_cause_analysis_prompt()` | 根因分析增强 |

**Few-shot 示例**: 包含 UAF 和 Deadlock 两个内核崩溃的完整分析示例。

### 2.3 report — 报告生成引擎

**职责**: 将诊断和检索结果整合为结构化报告。

**核心功能**:

| 功能 | 说明 |
|------|------|
| **DiagnosisReport** | 完整诊断报告数据结构 |
| **ReportGenerator** | 报告生成器，支持 LLM 增强 |
| **to_markdown()** | 生成 Markdown 格式报告 |
| **to_json()** | 生成 JSON 格式报告 |
| **generate_patch_comparison_table()** | 补丁对比 Markdown 表格 |

**报告结构**: 摘要 → 崩溃概况 → 根因诊断 → 补丁推荐 → 预防措施

---

## 3. 数据流

```
RootCauseResult + RetrievalResult
            │
            ▼
┌─────────────────────┐
│ ReportGenerator     │
│  .generate()        │
└────────┬────────────┘
         │
         ├──→ [可选] LLM 增强摘要
         ├──→ [可选] LLM 详细分析
         ├──→ [可选] LLM 补丁解释
         │
         ▼
┌─────────────────────┐
│ DiagnosisReport     │
│  .to_markdown()     │ → 终端 / 文件
│  .to_json()         │ → API 响应
│  .to_dict()         │ → 下游处理
└─────────────────────┘
```

---

## 4. 使用指南

### 4.1 基本用法

```python
from src.generator import generate_report

# 一站式报告生成
markdown = generate_report(
    root_cause_result=analysis,
    retrieval_result=retrieval,
    dmesg_content=dmesg_log,
    use_llm=False,
    output_format="markdown",
)
print(markdown)
```

### 4.2 LLM 增强报告

```python
from src.generator import ReportGenerator

gen = ReportGenerator(use_llm=True, model_name="deepseek-chat")
report = gen.generate(
    root_cause_result=analysis,
    retrieval_result=retrieval,
    dmesg_content=dmesg_log,
)
print(report.to_markdown())
```

### 4.3 补丁对比表

```python
from src.generator import generate_patch_comparison_table

table = generate_patch_comparison_table(
    retrieval_result.ranked_items_to_dict(),
    include_reason=True,
)
print(table)
```

### 4.4 直接调用 LLM

```python
from src.generator.llm import get_llm_client

llm = get_llm_client()
response = llm.chat(
    "Explain this kernel crash: BUG: spinlock already unlocked",
    system_prompt="You are a Linux kernel expert.",
)
```
