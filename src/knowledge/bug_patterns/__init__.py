"""Bug 模式知识库 — Bug Pattern Knowledge Base

包含 Linux 内核常见 Bug 类型的结构化知识，为根因分析和补丁检索提供领域知识。

知识来源:
- Linux 内核邮件列表 (LKML) 中的常见 Bug 模式
- syzkaller 发现的 Bug 类型分布
- 内核安全公告 (CVE) 中的漏洞模式
- 专家经验总结的 Bug 特征与修复模式

设计要点:
- 每种 Bug 模式包含: 典型症状、常见原因、修复模式、搜索关键词
- 与 analyzer/rootcause 的 28 条专家规则互补
- 为 LLM 分析提供 Few-shot 示例和领域上下文
"""

from typing import List, Dict, Any, Optional


# ============================================================================
# Bug 模式定义
# ============================================================================

# 每种 Bug 模式的结构化定义
BUG_PATTERNS: Dict[str, Dict[str, Any]] = {
    "use_after_free": {
        "name": "Use-After-Free (UAF)",
        "severity": "CRITICAL",
        "category": "memory",
        "typical_symptoms": [
            "KASAN: use-after-free in ...",
            "list_del corruption / list_add corruption (freed object still on list)",
            "slab poisoning detected",
            "use-after-free Write/Read in kmalloc-xxx",
            "GPF (General Protection Fault) at freed address",
        ],
        "common_causes": [
            "Race condition between kfree() and concurrent access",
            "Missing reference count increment before queuing work",
            "Error path frees object while it's still in use",
            "RCU callback frees object but reader still holds RCU lock",
            "Module unload frees memory still referenced by kernel",
        ],
        "fix_patterns": [
            "Add refcount (kref_get/kref_put) before use",
            "Add RCU grace period (synchronize_rcu) before free",
            "Move kfree to release callback",
            "Add proper locking around object lifecycle",
            "Use kfree_rcu instead of kfree for RCU-protected objects",
        ],
        "search_keywords": [
            "use after free", "kfree", "dangling pointer",
            "kref_get", "kref_put", "synchronize_rcu",
            "kfree_rcu", "refcount_inc", "refcount_dec",
        ],
        "detection_tools": ["KASAN", "SLUB_DEBUG", "KFENCE"],
        "related_subsystems": ["mm", "net", "fs", "kernel", "rcu"],
        "kernel_config_options": [
            "CONFIG_KASAN=y",
            "CONFIG_SLUB_DEBUG=y",
            "CONFIG_KFENCE=y",
        ],
    },

    "deadlock": {
        "name": "Deadlock (Spinlock/Mutex)",
        "severity": "HIGH",
        "category": "concurrency",
        "typical_symptoms": [
            "NMI watchdog: BUG: soft lockup - CPU stuck",
            "INFO: task xxx blocked for more than N seconds",
            "lockdep splat: possible circular locking dependency detected",
            "spin_lock already locked by ...",
            "Hung task detector: blocked tasks",
        ],
        "common_causes": [
            "ABBA deadlock: two locks acquired in different order",
            "Spinlock held during schedule()/sleep",
            "Interrupt context acquires a lock already held by process context",
            "Recursive lock acquisition (spin_lock on already held lock)",
            "Missing unlock on error path",
        ],
        "fix_patterns": [
            "Fix lock ordering (consistent acquisition order)",
            "Use spin_lock_irqsave in interrupt context",
            "Replace spin_lock with mutex if sleeping is needed",
            "Add lockdep annotations for correct ordering",
            "Reduce critical section size (lock hold time)",
        ],
        "search_keywords": [
            "deadlock", "spin_lock", "mutex_lock", "lock ordering",
            "lockdep", "circular locking", "ABBA",
            "spin_lock_irqsave", "spin_unlock_irqrestore",
        ],
        "detection_tools": ["LOCKDEP", "LOCK_STAT", "NMI watchdog"],
        "related_subsystems": ["kernel", "mm", "fs", "net", "block", "drivers"],
        "kernel_config_options": [
            "CONFIG_PROVE_LOCKING=y",
            "CONFIG_DEBUG_LOCKDEP=y",
            "CONFIG_LOCK_STAT=y",
        ],
    },

    "null_pointer": {
        "name": "NULL Pointer Dereference",
        "severity": "HIGH",
        "category": "memory",
        "typical_symptoms": [
            "BUG: unable to handle kernel NULL pointer dereference at 0x00000000",
            "Oops: 0000 [#1] SMP",
            "Unable to handle kernel paging request at virtual address 0x00000000",
            "RIP: some_function+N/m",
        ],
        "common_causes": [
            "Missing NULL check after allocation failure",
            "Function returns NULL on error but caller doesn't check",
            "Data structure not yet initialized",
            "Race condition: pointer set to NULL while in use",
            "kzalloc/kcalloc returning NULL under memory pressure",
        ],
        "fix_patterns": [
            "Add NULL pointer check before dereference",
            "Add error handling for allocation failures",
            "Use ERR_PTR/IS_ERR for error propagation",
            "Initialize data structures before use",
            "Add proper locking for pointer updates",
        ],
        "search_keywords": [
            "NULL pointer", "null dereference", "null check",
            "IS_ERR", "ERR_PTR", "PTR_ERR",
            "if (!ptr)", "if (IS_ERR_OR_NULL",
        ],
        "detection_tools": ["KASAN", "UBSAN", "SMAP"],
        "related_subsystems": ["kernel", "drivers", "mm", "fs", "net"],
        "kernel_config_options": [
            "CONFIG_KASAN=y",
            "CONFIG_UBSAN=y",
        ],
    },

    "race_condition": {
        "name": "Race Condition / Data Race",
        "severity": "HIGH",
        "category": "concurrency",
        "typical_symptoms": [
            "Intermittent crash / data corruption under load",
            "KCSAN: data-race in ...",
            "lockdep: inconsistent lock state",
            "RCU stall due to missing synchronization",
            "Counter / statistic mismatch under concurrent access",
        ],
        "common_causes": [
            "Missing lock for shared data access",
            "Check-then-act race (TOCTOU - Time of Check to Time of Use)",
            "Missing memory barrier between CPU writes",
            "Incorrect use of RCU (missing rcu_read_lock)",
            "Per-CPU variable access without preemption disable",
        ],
        "fix_patterns": [
            "Add spinlock/mutex around critical sections",
            "Use atomic operations (atomic_inc/dec/read)",
            "Add memory barriers (smp_mb, smp_wmb, smp_rmb)",
            "Use RCU APIs correctly (rcu_read_lock/rcu_assign_pointer)",
            "Use WRITE_ONCE/READ_ONCE for shared variables",
        ],
        "search_keywords": [
            "race condition", "data race", "concurrent",
            "spin_lock", "atomic_inc", "atomic_read",
            "rcu_read_lock", "synchronize_rcu", "smp_mb",
            "WRITE_ONCE", "READ_ONCE", "memory barrier",
        ],
        "detection_tools": ["KCSAN", "LOCKDEP", "syzkaller"],
        "related_subsystems": ["kernel", "mm", "net", "fs", "drivers"],
        "kernel_config_options": [
            "CONFIG_KCSAN=y",
            "CONFIG_PROVE_LOCKING=y",
        ],
    },

    "buffer_overflow": {
        "name": "Buffer Overflow / Out-of-Bounds",
        "severity": "CRITICAL",
        "category": "memory",
        "typical_symptoms": [
            "KASAN: slab-out-of-bounds Write/Read in ...",
            "KASAN: stack-out-of-bounds in ...",
            "KASAN: global-out-of-bounds in ...",
            "fortify: detected buffer overflow",
            "PaX: size overflow detected",
        ],
        "common_causes": [
            "Off-by-one error in buffer size calculation",
            "Unbounded strcpy/strcat/sprintf usage",
            "User-supplied length not validated",
            "Integer overflow in size calculation",
            "Missing bounds check on array index",
        ],
        "fix_patterns": [
            "Add bounds checking before copy/write",
            "Replace strcpy with strscpy/strlcpy",
            "Replace sprintf with snprintf/scnprintf",
            "Validate user-supplied length against buffer size",
            "Use flex arrays instead of fixed-size arrays",
        ],
        "search_keywords": [
            "buffer overflow", "out of bounds", "strscpy",
            "snprintf", "bounds check", "overflow",
            "off by one", "strncpy", "memcpy",
        ],
        "detection_tools": ["KASAN", "FORTIFY_SOURCE", "UBSAN"],
        "related_subsystems": ["fs", "net", "drivers", "kernel"],
        "kernel_config_options": [
            "CONFIG_KASAN=y",
            "CONFIG_FORTIFY_SOURCE=y",
            "CONFIG_UBSAN_BOUNDS=y",
        ],
    },

    "memory_leak": {
        "name": "Memory Leak",
        "severity": "MEDIUM",
        "category": "memory",
        "typical_symptoms": [
            "kmemleak: unreferenced object ...",
            "kmalloc-xxx: memory leak detected",
            "Slow memory growth over time (OOM after days of uptime)",
            "slabtop showing unusual slab growth",
            "/proc/meminfo showing increasing SUnreclaim",
        ],
        "common_causes": [
            "Missing kfree on error path",
            "Forgetting to call put_*() after get_*()",
            "Allocation in loop without corresponding free",
            "Module unload without freeing resources",
            "Reference count leak (extra get without put)",
        ],
        "fix_patterns": [
            "Add missing kfree/put in error paths",
            "Use goto-based error unwinding for cleanup",
            "Add __must_check annotation to allocation functions",
            "Use devm_* (managed) allocations in drivers",
            "Add leak detection assertions in module exit",
        ],
        "search_keywords": [
            "memory leak", "kmemleak", "kfree",
            "missing free", "resource leak", "unfreed",
            "goto", "error path", "cleanup",
        ],
        "detection_tools": ["KMEMLEAK", "KASAN", "slabtop"],
        "related_subsystems": ["mm", "net", "fs", "drivers"],
        "kernel_config_options": [
            "CONFIG_DEBUG_KMEMLEAK=y",
            "CONFIG_DEBUG_KMEMLEAK_DEFAULT_OFF=n",
        ],
    },

    "double_free": {
        "name": "Double Free",
        "severity": "CRITICAL",
        "category": "memory",
        "typical_symptoms": [
            "KASAN: double-free in kmalloc-xxx",
            "slab: double free detected in cache 'xxx'",
            "kernel BUG at mm/slub.c:xxx",
            "list_del corruption (freed object still on list)",
            "Poison overwritten (freed memory was modified)",
        ],
        "common_causes": [
            "Error path frees same object twice",
            "Concurrent kfree from two threads",
            "Object freed by both release callback and caller",
            "Reference count drops below zero and object freed twice",
            "Module use-after-free triggering false double-free detection",
        ],
        "fix_patterns": [
            "Set pointer to NULL after kfree",
            "Add proper refcounting before free",
            "Add locking for kfree paths",
            "Centralize free in destructor function",
            "Check for NULL before kfree (defensive)",
        ],
        "search_keywords": [
            "double free", "double-free", "kfree(NULL)",
            "refcount_dec_and_test", "kref_put",
            "pointer NULL after free", "kzfree",
        ],
        "detection_tools": ["KASAN", "SLUB_DEBUG", "KFENCE"],
        "related_subsystems": ["mm", "net", "drivers"],
        "kernel_config_options": [
            "CONFIG_KASAN=y",
            "CONFIG_SLUB_DEBUG=y",
        ],
    },

    "rcu_stall": {
        "name": "RCU Stall / Grace Period Stall",
        "severity": "HIGH",
        "category": "concurrency",
        "typical_symptoms": [
            "INFO: rcu_sched detected stalls on CPUs/tasks",
            "rcu_preempt detected expedited stalls",
            "Tasks blocked waiting for RCU grace period",
            "System freeze during synchronize_rcu",
        ],
        "common_causes": [
            "RCU read-side critical section too long",
            "Preemption disabled while holding rcu_read_lock",
            "synchronize_rcu called from non-sleepable context",
            "Missing rcu_read_unlock on error path",
            "Too many call_rcu callbacks pending",
        ],
        "fix_patterns": [
            "Reduce RCU read-side critical section length",
            "Move heavy work outside rcu_read_lock/rcu_read_unlock",
            "Use call_rcu instead of synchronize_rcu where possible",
            "Add missing rcu_read_unlock in error paths",
            "Use rcu_barrier to drain pending callbacks",
        ],
        "search_keywords": [
            "rcu stall", "synchronize_rcu", "call_rcu",
            "rcu_read_lock", "rcu_read_unlock", "rcu_barrier",
            "rcu grace period", "rcu_expedited",
        ],
        "detection_tools": ["RCU_STALL", "PROVE_RCU", "lockdep"],
        "related_subsystems": ["rcu", "kernel", "mm", "net"],
        "kernel_config_options": [
            "CONFIG_PROVE_RCU=y",
            "CONFIG_RCU_CPU_STALL_TIMEOUT=60",
        ],
    },

    "oom": {
        "name": "Out of Memory (OOM)",
        "severity": "CRITICAL",
        "category": "memory",
        "typical_symptoms": [
            "Out of memory: Killed process ... (oom_score_adj=...",
            "Kernel panic - not syncing: Out of memory and no killable processes",
            "page allocation failure: order:N, mode:...",
            "system almost out of memory during heavy reclaim",
        ],
        "common_causes": [
            "Genuine memory shortage (high memory pressure)",
            "Memory leak causing slow exhaustion",
            "High-order allocation failure under fragmentation",
            "Memory cgroup limit too low",
            "Slab cache growing unboundedly",
        ],
        "fix_patterns": [
            "Fix memory leak in the leaking component",
            "Use __GFP_RETRY_MAYFAIL instead of __GFP_NORETRY",
            "Increase vm.min_free_kbytes",
            "Use kvmalloc for large allocations (fallback to vmalloc)",
            "Tune OOM killer / memory cgroup settings",
        ],
        "search_keywords": [
            "out of memory", "OOM", "page allocation failure",
            "kvmalloc", "__GFP_RETRY_MAYFAIL", "min_free_kbytes",
            "memory reclaim", "memory cgroup", "vmalloc",
        ],
        "detection_tools": ["OOM killer", "kmemleak", "vmstat", "meminfo"],
        "related_subsystems": ["mm", "kernel"],
        "kernel_config_options": [
            "CONFIG_MEMCG=y",
            "CONFIG_COMPACTION=y",
        ],
    },

    "stack_overflow": {
        "name": "Kernel Stack Overflow",
        "severity": "HIGH",
        "category": "memory",
        "typical_symptoms": [
            "BUG: stack guard page was hit at ...",
            "Kernel stack overflow - potential crash",
            "do_IRQ: stack overflow: ...",
            "Stack frame size > 2048 bytes warning",
        ],
        "common_causes": [
            "Deep recursion (e.g., nested filesystem operations)",
            "Large on-stack variables (arrays > 1KB)",
            "Heavy function call chain (many small stack frames)",
            "Interrupt stacking on already-deep stack",
        ],
        "fix_patterns": [
            "Move large variables from stack to heap (kmalloc)",
            "Convert recursion to iteration",
            "Increase CONFIG_FRAME_WARN to catch large frames",
            "Use kmalloc for large temporary buffers",
            "Optimize call chain depth",
        ],
        "search_keywords": [
            "stack overflow", "stack guard", "kmalloc",
            "recursion", "on-stack", "large array",
            "FRAME_WARN", "stack frame",
        ],
        "detection_tools": ["CONFIG_VMAP_STACK", "CONFIG_FRAME_WARN"],
        "related_subsystems": ["kernel", "fs", "mm"],
        "kernel_config_options": [
            "CONFIG_VMAP_STACK=y",
            "CONFIG_FRAME_WARN=2048",
        ],
    },
}


# ============================================================================
# Bug 模式查询接口
# ============================================================================

def get_bug_pattern(bug_type: str) -> Optional[Dict[str, Any]]:
    """获取指定 Bug 类型的完整模式定义

    Args:
        bug_type: Bug 类型标识 (如 "use_after_free")

    Returns:
        Bug 模式字典，未找到时返回 None
    """
    if bug_type in BUG_PATTERNS:
        return dict(BUG_PATTERNS[bug_type])

    # 模糊匹配
    bug_lower = bug_type.lower().replace(" ", "_")
    if bug_lower in BUG_PATTERNS:
        return dict(BUG_PATTERNS[bug_lower])

    for key, pattern in BUG_PATTERNS.items():
        if key in bug_lower or bug_lower in key:
            return dict(pattern)

    return None


def get_fix_patterns(bug_type: str) -> List[str]:
    """获取指定 Bug 类型的修复模式列表

    Args:
        bug_type: Bug 类型

    Returns:
        修复模式描述列表
    """
    pattern = get_bug_pattern(bug_type)
    if pattern:
        return pattern.get("fix_patterns", [])
    return []


def get_search_keywords(bug_type: str) -> List[str]:
    """获取指定 Bug 类型的搜索关键词

    用于构造向量检索查询。

    Args:
        bug_type: Bug 类型

    Returns:
        关键词列表
    """
    pattern = get_bug_pattern(bug_type)
    if pattern:
        return pattern.get("search_keywords", [])
    return []


def get_detection_tools(bug_type: str) -> List[str]:
    """获取检测指定 Bug 类型推荐的内核工具

    Args:
        bug_type: Bug 类型

    Returns:
        检测工具名列表 (KASAN, LOCKDEP, etc.)
    """
    pattern = get_bug_pattern(bug_type)
    if pattern:
        return pattern.get("detection_tools", [])
    return []


def list_bug_patterns(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出所有 Bug 模式

    Args:
        category: 可选过滤 — "memory" / "concurrency"

    Returns:
        Bug 模式列表
    """
    patterns = []
    for key, pattern in BUG_PATTERNS.items():
        if category and pattern.get("category") != category:
            continue
        patterns.append({"bug_type": key, **pattern})
    return patterns


def search_bug_by_symptom(symptom_text: str) -> List[Dict[str, Any]]:
    """根据症状文本搜索匹配的 Bug 模式

    用于快速判断崩溃属于哪种 Bug 类型。

    Args:
        symptom_text: 症状描述 (如 dmesg panic 消息)

    Returns:
        匹配的 Bug 模式列表，按匹配度排序
    """
    results = []
    text_lower = symptom_text.lower()

    for bug_type, pattern in BUG_PATTERNS.items():
        score = 0
        matched_symptoms = []

        for symptom in pattern.get("typical_symptoms", []):
            # 检查症状关键词是否在文本中
            symptom_words = symptom.lower().split()
            match_count = sum(1 for w in symptom_words if w in text_lower)
            if match_count >= len(symptom_words) * 0.5:
                score += match_count
                matched_symptoms.append(symptom)

        if score > 0:
            results.append({
                "bug_type": bug_type,
                "name": pattern.get("name", bug_type),
                "match_score": score,
                "matched_symptoms": matched_symptoms,
                "pattern": pattern,
            })

    results.sort(key=lambda x: -x["match_score"])
    return results


def generate_bug_context_for_llm(bug_type: str) -> str:
    """生成用于 LLM 的 Bug 模式上下文文本

    将结构化知识转为 LLM 易于理解的文本描述。

    Args:
        bug_type: Bug 类型

    Returns:
        格式化的上下文文本
    """
    pattern = get_bug_pattern(bug_type)
    if not pattern:
        return f"Bug type '{bug_type}' not found in knowledge base."

    lines = [
        f"## {pattern['name']} ({bug_type})",
        f"**Severity**: {pattern['severity']}",
        f"**Category**: {pattern['category']}",
        f"",
        f"### Typical Symptoms",
    ]
    for s in pattern.get("typical_symptoms", []):
        lines.append(f"- {s}")
    lines.append("")

    lines.append("### Common Causes")
    for c in pattern.get("common_causes", []):
        lines.append(f"- {c}")
    lines.append("")

    lines.append("### Fix Patterns")
    for f in pattern.get("fix_patterns", []):
        lines.append(f"- {f}")
    lines.append("")

    lines.append("### Detection Tools")
    lines.append(", ".join(pattern.get("detection_tools", [])))
    lines.append("")

    lines.append("### Related Subsystems")
    lines.append(", ".join(pattern.get("related_subsystems", [])))

    return "\n".join(lines)


__all__ = [
    # 知识库
    "BUG_PATTERNS",
    # 查询接口
    "get_bug_pattern",
    "get_fix_patterns",
    "get_search_keywords",
    "get_detection_tools",
    "list_bug_patterns",
    "search_bug_by_symptom",
    "generate_bug_context_for_llm",
]
