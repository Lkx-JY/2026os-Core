# Analyzer — 宕机分析核心模块

> **Linux Kernel Crash Feature Extraction & Root Cause Abstraction**

负责从 `dmesg` 日志和 `vmcore` 文件中提取故障特征，并进行**根因抽象分析**，是连接"日志理解"与"补丁检索"的关键桥梁。

---

## 目录

1. [模块架构](#1-模块架构)
2. [子模块说明](#2-子模块说明)
3. [数据模型](#3-数据模型)
4. [根因分析流水线](#4-根因分析流水线)
5. [专家规则参考](#5-专家规则参考)
6. [使用指南](#6-使用指南)

---

## 1. 模块架构

```
src/analyzer/
├── __init__.py          # 模块入口 — 统一导出所有公共 API
├── models/__init__.py   # 数据模型 — CrashFeature & RootCauseResult
├── dmesg/__init__.py    # dmesg 日志解析 — 正则提取 Call Trace / Panic 消息
├── vmcore/__init__.py   # vmcore 解析 — 基于 drgn 的内核对象提取
├── drgn/__init__.py     # drgn 集成 (待实现)
├── rootcause/__init__.py # 根因抽象核心 — 20+ 专家规则 + 调用栈分析 + 修复模式推断
└── pipeline/__init__.py  # 流水线编排 — 串联特征提取 → 根因抽象
```

### 数据流

```
 dmesg 日志 / vmcore 文件
        │
        ▼
┌─────────────────┐
│  Phase 1: 特征提取 │  dmesg: 正则提取 Call Trace, Panic 消息
│  (dmesg/vmcore)   │  vmcore: drgn 提取内核对象、寄存器状态
└────────┬────────┘
         │  CrashFeature
         ▼
┌─────────────────┐
│  Phase 2: 根因抽象 │  Layer 1: 28 条专家规则精确匹配
│  (rootcause)      │  Layer 2: 调用栈结构分析
│                   │  Layer 3: Bug 类型通用抽象
│                   │  Layer 4: Panic 关键词兜底
└────────┬────────┘
         │  RootCauseResult (含 retrieval_query)
         ▼
     下游: Retriever / Generator
```

---

## 2. 子模块说明

### 2.1 dmesg — 日志解析

**职责**: 从非结构化 dmesg 文本中提取结构化特征。

**核心功能**:
- `extract_call_trace()`: 正则匹配 `[<hex>]` 格式的调用栈帧
- `extract_panic_msg()`: 提取 Kernel panic / Oops / BUG 消息
- `parse_dmesg()`: 一站式解析入口，返回 `CrashFeature`

**支持的 Panic 模式**: `Kernel panic - not syncing: ...`, `BUG: ...`, `Oops: ...`

### 2.2 vmcore — vmcore 解析

**职责**: 基于 drgn 从 vmcore 二进制文件中提取内核对象。

**状态**: ⚠️ 骨架完成，drgn 实际集成待实现

### 2.3 rootcause — 根因抽象 (★ 核心)

**职责**: 将 `CrashFeature` 转化为 `RootCauseResult`，包含根因诊断、因果链和检索查询。

**四层分层分析策略**:

| 层级 | 方法 | 置信度 | 说明 |
|------|------|--------|------|
| Layer 1 | 专家规则精确匹配 | 0.60~0.95 | 基于 28 条领域规则的 panic_pattern / keyword 匹配 |
| Layer 2 | 调用栈结构分析 | 0.50~0.65 | 从 Call Trace 中识别锁/内存/RCU/调度函数 |
| Layer 3 | Bug 类型通用抽象 | 0.40~0.55 | 基于 Collector 层识别的 bug_type 进行通用映射 |
| Layer 4 | Panic 关键词推断 | 0.40~0.50 | 从 Panic 消息中提取关键词进行兜底推断 |

**核心功能**:
- `abstract_root_cause(feature) → RootCauseResult`: 主入口
- `analyze_call_trace_structure(trace_lines) → Dict`: 调用栈结构分析 (4 类 × 89 个函数)
- `infer_fix_patterns(bug_type, trace_analysis, panic_msg) → Dict`: 修复模式推断 (5 种修复类型)
- `build_retrieval_query(feature, ...) → str`: 检索查询构造 (多层语义融合)
- `list_all_rules() → List[Dict]`: 列出所有已注册的专家规则
- `get_rule_by_id(rule_id) → Dict`: 按 ID 获取规则详情

### 2.4 pipeline — 流水线编排

**职责**: 串联特征提取和根因分析阶段。支持三种输入模式:
1. `vmcore + dmesg` (最优)
2. `vmcore only`
3. `dmesg only`

---

## 3. 数据模型

### CrashFeature

```python
@dataclass
class CrashFeature:
    call_trace: List[str]        # 调用栈帧列表
    subsystem: str               # 子系统 (mm, fs, net, kernel, drivers, arch...)
    bug_type: str                # Bug 类型 (21 种分类)
    kernel_version: str          # 内核版本
    modules: List[str]           # 已加载模块
    panic_msg: str               # Panic/Oops/BUG 消息原文
    extra_info: Dict             # 扩展信息
```

### RootCauseResult

```python
@dataclass
class RootCauseResult:
    crash_feature: CrashFeature  # 原始特征
    root_cause: str              # 根因诊断结论
    bug_type: str                # 识别的 Bug 类型
    causal_chain: List[str]      # 因果推理链
    score: float                 # 置信度 (0.0 ~ 1.0)
    reason: str                  # 诊断理由
    retrieval_query: str         # ★ 优化后的检索查询文本 (供 BGE-M3 编码)
    suggested_keywords: List[str] # ★ 建议搜索关键词
    extra_info: Dict             # ★ 扩展信息 (规则ID/严重程度/修复提示/调用栈分析)

    def get_severity_label() -> str:  # CRITICAL / HIGH / MEDIUM / LOW / UNCERTAIN
```

---

## 4. 根因分析流水线

```
用户输入 (dmesg / vmcore)
       │
       ▼
┌──────────────────────┐
│ Phase 1: parse_dmesg │  正则提取 Call Trace, Panic 消息
│         或            │
│         analyze_vmcore│  drgn 提取内核对象
└──────────┬───────────┘
           │ CrashFeature
           ▼
┌──────────────────────┐
│ Phase 2:             │
│ abstract_root_cause  │
│                      │
│ Step 0: 调用栈结构分析 │  ← 始终执行，提取锁/内存/RCU/调度函数
│ Step 1: 专家规则匹配   │  ← Layer 1 (0.60~0.95)
│ Step 2: 结构推断       │  ← Layer 2 (0.50~0.65) 降级
│ Step 3: Bug类型抽象   │  ← Layer 3 (0.40~0.55) 降级
│ Step 4: 关键词兜底     │  ← Layer 4 (0.40~0.50) 降级
│ Step 5: 因果链补充     │
│ Step 6: 修复模式推断   │  ← lock/refcount/RCU/null/bound 需求
│ Step 7: 检索查询构造   │  ← 输出 retrieval_query 供下游使用
└──────────┬───────────┘
           │ RootCauseResult
           ▼
    下游: Retriever / Generator
```

---

## 5. 专家规则参考

| ID | 规则名称 | Bug 类型 | 严重度 | 典型触发特征 |
|----|---------|---------|--------|-------------|
| R001 | Spinlock Deadlock | deadlock | 9 | `spin_lock` in call trace |
| R002 | Null Pointer Dereference | null_pointer | 8 | `unable to handle kernel NULL pointer dereference` |
| R003 | Use After Free (KASAN) | use_after_free | 9 | `KASAN: use-after-free in` |
| R004 | Mutex Deadlock | deadlock | 9 | `mutex_lock` + lockdep circular dependency |
| R005 | Double Free (KASAN) | double_free | 9 | `KASAN: double-free` |
| R006 | Out-Of-Bounds Access (KASAN) | out_of_bound | 9 | `KASAN: slab-out-of-bounds` |
| R007 | Memory Corruption (List) | memory_corruption | 8 | `list_del corruption` |
| R008 | Page Fault / Bad Area | memory_corruption | 8 | `unable to handle kernel paging request` |
| R009 | Out of Memory (OOM) | memory_leak | 7 | `Out of memory: Killed process` |
| R010 | Buffer Overflow | buffer_overflow | 8 | `buffer overflow` |
| R011 | Refcount Underflow/Overflow | use_after_free | 9 | `refcount_t: underflow` |
| R012 | Hardlockup (NMI Watchdog) | hang | **10** | `Watchdog detected hard LOCKUP on cpu` |
| R013 | Softlockup | hang | 8 | `BUG: soft lockup - CPU# stuck` |
| R014 | Hungtask | hang | 8 | `INFO: task blocked for more than 120 seconds` |
| R015 | RCU Stall / SRCU Stall | hang | 8 | `rcu_sched self-detected stall on CPU` |
| R016 | General Protection Fault | crash | 9 | `general protection fault:` |
| R017 | Machine Check Exception | crash | **10** | `Machine Check Exception` |
| R018 | Kernel BUG / BUG_ON | crash | 9 | `kernel BUG at` |
| R019 | Stack Overflow | buffer_overflow | 9 | `stack overflow` |
| R020 | Workqueue Stall | hang | 7 | `workqueue: stuck` |
| R021 | Division Error | crash | 7 | `divide error:` |
| R022 | UBSAN Undefined Behavior | crash | 7 | `UBSAN: shift-out-of-bounds` |
| R023 | Kernel Panic — Not Syncing | crash | **10** | `Kernel panic - not syncing:` |
| R024 | Kernel Oops | crash | 8 | `Oops:` |
| R025 | Bad Mode / Undefined Instruction | crash | 9 | `Bad mode in handler` |
| R026 | Data Abort / Alignment Fault | crash | 8 | `Unhandled fault: alignment fault` |
| R027 | Spectre / Meltdown Mitigation | security | 6 | `spectre` / `meltdown` / `retpoline` |
| R028 | IRQ / Interrupt Storm | hang | 7 | `irq N: nobody cared` |

### 严重程度

| 等级 | 分值 | 含义 |
|------|------|------|
| Critical | 10 | 系统无法恢复 — Hardlockup, MCE, Kernel Panic |
| Severe | 9 | 可能导致数据损坏或安全漏洞 — UAF, Double Free, GPF |
| High | 8 | 显著影响稳定性 — Softlockup, Hungtask, Page Fault |
| Medium-High | 7 | 需要及时修复 — OOM, Division Error, IRQ Storm |
| Medium | 6 | 建议修复 — Spectre 缓解 |

---

## 6. 使用指南

### 基本用法

```python
from src.analyzer import run_analysis_pipeline, list_all_rules

# 一站式流水线
dmesg_log = """
[  123.456] BUG: list_del corruption. prev->next should be ffffa000
[  123.457] Call Trace:
[  123.458]  [<ffffffff81234567>] __list_del_entry_valid+0x89/0x90
"""
result = run_analysis_pipeline(dmesg_content=dmesg_log)
print(result.root_cause)       # "Memory Corruption (List)"
print(result.score)            # 0.85
print(result.retrieval_query)  # 优化后的检索查询
```

### 分步调用

```python
from src.analyzer import parse_dmesg, abstract_root_cause

feature = parse_dmesg(dmesg_log)
result = abstract_root_cause(feature)
```

### 查看规则库

```python
from src.analyzer import list_all_rules, get_rule_by_id

rules = list_all_rules()          # 所有 28 条规则
rule = get_rule_by_id("R012")     # Hardlockup 规则详情
```

---
