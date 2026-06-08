# Knowledge — 领域知识库模块

> **Bug Patterns + Lock Rules + Subsystem Graph**

包含 Linux 内核领域的结构化知识，为根因分析、补丁检索和报告生成提供领域上下文。

---

## 目录

1. [模块架构](#1-模块架构)
2. [子模块说明](#2-子模块说明)
3. [知识覆盖范围](#3-知识覆盖范围)
4. [使用指南](#4-使用指南)

---

## 1. 模块架构

```
src/knowledge/
├── __init__.py                # 模块入口 — 统一导出所有公共 API
├── bug_patterns/__init__.py   # ★ Bug 模式知识库
├── lock_rules/__init__.py     # ★ 锁规则知识库
├── subsystem_graph/__init__.py # ★ 子系统关系图
└── README.md                  # 本文档
```

---

## 2. 子模块说明

### 2.1 bug_patterns — Bug 模式知识库

**职责**: 定义 Linux 内核常见 Bug 类型的结构化知识。

**覆盖的 Bug 模式 (9 种)**:

| Bug 类型 | 严重程度 | 类别 |
|----------|---------|------|
| `use_after_free` | CRITICAL | memory |
| `deadlock` | HIGH | concurrency |
| `null_pointer` | HIGH | memory |
| `race_condition` | HIGH | concurrency |
| `buffer_overflow` | CRITICAL | memory |
| `memory_leak` | MEDIUM | memory |
| `double_free` | CRITICAL | memory |
| `rcu_stall` | HIGH | concurrency |
| `oom` | CRITICAL | memory |
| `stack_overflow` | HIGH | memory |

**每种 Bug 模式包含**:
- 典型症状 (用于自动匹配)
- 常见原因
- 修复模式 (5种)
- 搜索关键词 (用于检索)
- 检测工具推荐 (KASAN, LOCKDEP, etc.)
- 相关子系统
- 内核配置选项建议

**核心 API**:
```python
from src.knowledge import get_bug_pattern, search_bug_by_symptom

# 获取模式定义
pattern = get_bug_pattern("use_after_free")

# 根据症状自动匹配 Bug 类型
matches = search_bug_by_symptom("KASAN: use-after-free in kfree_skb")
```

### 2.2 lock_rules — 锁规则知识库

**职责**: 定义 Linux 内核锁机制的使用规则和常见死锁模式。

**锁类型覆盖 (6 种)**:
- `spinlock` — 自旋锁 (不可睡眠)
- `mutex` — 互斥锁 (可睡眠)
- `rwsem` — 读写信号量
- `rcu` — RCU 同步机制
- `rwlock` — 读写自旋锁
- `seqlock` — 顺序锁

**死锁模式 (5 种)**:
1. ABBA Deadlock — 锁获取顺序不一致
2. Recursive Lock — 重复获取不可重入锁
3. Interrupt Deadlock — 中断上下文竞争
4. Sleep-in-Atomic — 持 spinlock 时睡眠
5. Lock Inversion — 不同优先级上下文锁顺序

**核心 API**:
```python
from src.knowledge import analyze_lock_usage, match_deadlock_pattern

# 分析调用栈中的锁使用
analysis = analyze_lock_usage(call_trace)
print(analysis["potential_issues"])

# 匹配 lockdep 报告
patterns = match_deadlock_pattern(lockdep_msg)
```

### 2.3 subsystem_graph — 子系统关系图

**职责**: 定义 Linux 内核子系统间的依赖、层级和调用关系。

**子系统定义 (12 个)**:
mm, fs, net, block, kernel, drivers, arch, bpf, security, kvm, rcu, cgroup

**三种关系类型**:
- **层级关系** (父子): kernel → rcu, cgroup, bpf, irq
- **耦合关系** (紧耦合): mm ↔ fs, block, kernel
- **调用关系** (API): fs → mm, block, security

**核心 API**:
```python
from src.knowledge import get_related_subsystems

# 获取检索时应扩展的子系统
related = get_related_subsystems("mm")
# → ["arch", "block", "fs", "kernel", "mm", "page_alloc", "slab", ...]
```

---

## 3. 知识覆盖范围

| 维度 | 数量 | 说明 |
|------|------|------|
| Bug 模式 | 10 种 | 覆盖内核最高频崩溃类型 |
| 锁类型 | 6 种 | 覆盖所有内核锁原语 |
| 死锁模式 | 5 种 | 覆盖 LOCKDEP 主要报告类型 |
| 锁获取顺序规则 | 8 条 | 覆盖 mm/fs/net/kernel |
| 子系统 | 12 个 | 覆盖内核主要子系统 |
| 修复模式 | 8 种 | lock / refcount / RCU / null check 等 |

---

## 4. 使用指南

### 4.1 为 LLM 提供上下文

```python
from src.knowledge import (
    generate_bug_context_for_llm,
    generate_lock_context_for_llm,
    generate_subsystem_context_for_llm,
)

# 注入 Bug 模式知识到 LLM prompt
bug_context = generate_bug_context_for_llm("use_after_free")

# 注入锁分析上下文
lock_context = generate_lock_context_for_llm(call_trace)

# 注入子系统上下文
subsys_context = generate_subsystem_context_for_llm("mm")
```

### 4.2 增强检索

```python
from src.knowledge import get_search_keywords, get_related_subsystems

# 获取 Bug 类型的搜索关键词
keywords = get_search_keywords("use_after_free")
# → ["use after free", "kfree", "dangling pointer", "kref_get", ...]

# 扩展检索的子系统范围
subsystems = get_related_subsystems("mm")
# → ["arch", "block", "fs", "kernel", "mm", ...]
```
