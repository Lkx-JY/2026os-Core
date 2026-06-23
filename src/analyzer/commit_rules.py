"""Commit Root Cause Builder — 轻量级 Commit 根因分析引擎

用于离线 Commit 索引路径，直接利用 Collector 已提取的结构化特征
(bug_type, subsystem, lock_added, refcount_fix, rcu_fix, diff_content)，
通过三层轻量分析替代 RootCauseAnalyzer 的 4 层重分析:

Layer 1: BUG_TEMPLATE 查表 — 25 种 bug_type → 根因描述 (<0.01ms)
Layer 2: DIFF_RULES 规则 — 25 条规则分析 diff 的 +/- 行 (1-3ms)
Layer 3: 置信度评估 + 轻量兜底 — 多维度评分 (<1ms)

Target: 3-5ms per commit (vs ~100ms for RootCauseAnalyzer.analyze())

设计原则:
- 完全独立于 RootCauseAnalyzer，零耦合 — 在线 Crash 路径不受影响
- BugType/subsystem 已由 Collector 确定 → 查表即可，无需推断
- lock_added/refcount_fix/rcu_fix 由 Collector 从 diff 提取 → 事实证据
- commit 没有 call_trace → 跳过所有调用栈分析逻辑
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple

from loguru import logger


# ============================================================================
# BUG_TEMPLATE — 25 种 BugType 的结构化根因描述 (覆盖 BugType 枚举全部值)
# ============================================================================

BUG_TEMPLATE: Dict[str, Dict[str, Any]] = {

    # ── 内存错误 (10 种) ──────────────────────────────────────────
    "null_pointer": {
        "root_cause": "Missing NULL validation — dereferencing uninitialized or failed-alloc pointer",
        "severity": 8,
        "typical_fix": "Add NULL check or error handling path before dereference",
        "subsystem_hint": {
            "drivers": "Driver probe error path missing NULL check after resource allocation",
            "fs": "Failed inode/dentry allocation not handled",
            "mm": "Page allocation failure path not guarded with NULL check",
            "net": "Socket buffer allocation failure not checked",
        },
    },
    "use_after_free": {
        "root_cause": "Object lifetime violation — memory accessed after deallocation",
        "severity": 9,
        "typical_fix": "Add reference counting (kref_get/kref_put) or RCU delayed free (kfree_rcu)",
        "subsystem_hint": {
            "mm": "Slab/Slub object lifecycle error in memory allocator path",
            "net": "Socket buffer or network packet lifecycle error after kfree_skb",
            "fs": "Inode/dentry cache lifecycle error after dput/iput",
            "drivers": "Device driver object freed while still referenced by workqueue or timer",
            "block": "Block IO request freed while still in flight",
        },
    },
    "double_free": {
        "root_cause": "Duplicate deallocation — same memory region freed twice",
        "severity": 9,
        "typical_fix": "NULL pointer after kfree, or reference count guard before free",
        "subsystem_hint": {
            "mm": "Slab double-free in memory management path",
            "net": "Double kfree_skb or duplicate packet free",
            "drivers": "Double put_device or double free_irq",
        },
    },
    "buffer_overflow": {
        "root_cause": "Buffer boundary violation — write exceeds allocated buffer size",
        "severity": 8,
        "typical_fix": "Replace strcpy/strcat with strscpy, or add size/bounds validation",
        "subsystem_hint": {
            "fs": "Pathname buffer overflow in filesystem operations",
            "net": "Network packet parsing buffer overflow",
            "drivers": "Firmware or configuration buffer overflow in driver",
        },
    },
    "out_of_bound": {
        "root_cause": "Array index out of bounds — index exceeds allocated range",
        "severity": 9,
        "typical_fix": "Add bounds check before array access or use array_index_nospec",
        "subsystem_hint": {},
    },
    "memory_corruption": {
        "root_cause": "Memory integrity violation — stale pointer, race condition, or buffer overflow causing data corruption",
        "severity": 8,
        "typical_fix": "Add proper synchronization (spin_lock/mutex) or fix pointer lifecycle",
        "subsystem_hint": {
            "mm": "Linked list corruption (list_del/list_add) in memory management structures",
            "net": "Network buffer corruption from concurrent access or DMA sync issue",
            "fs": "Filesystem metadata corruption from race condition",
        },
    },
    "memory_leak": {
        "root_cause": "Resource release missing — allocated memory never freed on all exit/error paths",
        "severity": 7,
        "typical_fix": "Add kfree/kref_put on error and cleanup goto paths",
        "subsystem_hint": {},
    },
    "use_before_init": {
        "root_cause": "Resource used before initialization — ordering violation in initialization sequence",
        "severity": 7,
        "typical_fix": "Reorder initialization or add dependency check before use",
        "subsystem_hint": {
            "drivers": "Driver hardware accessed before probe() completes initialization",
            "kernel": "Subsystem notifier called before infrastructure is ready",
        },
    },
    "uninitialized": {
        "root_cause": "Uninitialized variable or structure field used before assignment",
        "severity": 7,
        "typical_fix": "Initialize variable/structure at declaration or before first use",
        "subsystem_hint": {},
    },
    "stack_overflow": {
        "root_cause": "Kernel stack exhausted — excessive stack usage from recursion or large stack allocations",
        "severity": 9,
        "typical_fix": "Move large buffer from stack to heap (kmalloc), eliminate recursion, or use CONFIG_FRAME_WARN",
        "subsystem_hint": {
            "fs": "Deep filesystem recursion exhausting 8KB/16KB kernel stack",
            "drivers": "Large on-stack DMA descriptor or configuration structure",
        },
    },

    # ── 并发错误 (2 种) ───────────────────────────────────────────
    "deadlock": {
        "root_cause": "Lock ordering violation or circular dependency causing task hang",
        "severity": 9,
        "typical_fix": "Reorder lock acquisition, reduce lock granularity, or use try_lock with fallback",
        "subsystem_hint": {
            "mm": "Memory reclaim lock inversion (mmap_sem vs i_mutex)",
            "fs": "Filesystem lock ordering violation (i_mutex vs internal fs lock)",
            "block": "Block layer queue lock vs IO scheduler lock inversion",
            "drivers": "Driver spinlock held across scheduling point without irqsave",
            "net": "Network stack lock ordering between socket lock and device lock",
        },
    },
    "race_condition": {
        "root_cause": "Concurrent access without proper synchronization — data race between threads/IRQs",
        "severity": 8,
        "typical_fix": "Add spin_lock/mutex protection or use atomic operations (atomic_inc/atomic_cmpxchg)",
        "subsystem_hint": {
            "drivers": "Interrupt handler and process context race on device registers",
            "net": "Concurrent socket operations without lock_sock",
            "fs": "Parallel filesystem operations on shared inode without exclusion",
        },
    },

    # ── 系统挂起 (3 种) ───────────────────────────────────────────
    "hang": {
        "root_cause": "Task or CPU stalled — infinite loop, lost wakeup, or I/O blockage",
        "severity": 8,
        "typical_fix": "Add cond_resched(), schedule_timeout, or fix wakeup condition",
        "subsystem_hint": {
            "block": "Block IO hang — request indefinitely stuck in queue",
            "fs": "NFS/RPC hang — remote server unresponsive, no timeout",
            "kernel": "Hardlockup or hungtask in scheduler or interrupt path",
        },
    },
    "rcu_stall": {
        "root_cause": "RCU grace period stall — RCU read-side critical section too long or missing rcu_read_unlock",
        "severity": 8,
        "typical_fix": "Shorten RCU read section, add cond_resched(), or fix missing rcu_read_unlock",
        "subsystem_hint": {
            "kernel": "RCU callback processing blocked by long-running RCU reader",
            "net": "Network packet processing in RCU read section without resched point",
        },
    },
    "soft_lockup": {
        "root_cause": "Soft lockup — CPU stuck in kernel mode for too long without yielding",
        "severity": 8,
        "typical_fix": "Add cond_resched() in long loops, reduce lock hold time, or fix infinite loop condition",
        "subsystem_hint": {},
    },

    # ── 资源 (2 种) ───────────────────────────────────────────────
    "oom": {
        "root_cause": "Out of memory — system exhausted all available memory including swap",
        "severity": 7,
        "typical_fix": "Fix memory leak, limit cgroup memory, or optimize memory reclaim/reuse",
        "subsystem_hint": {
            "mm": "Memory allocator leak or excessive slab cache consumption",
        },
    },
    "resource_leak": {
        "root_cause": "Resource not released — file, socket, IRQ, DMA, or hardware resource leaked",
        "severity": 6,
        "typical_fix": "Add proper release (fput/sock_release/free_irq) on all exit and error paths",
        "subsystem_hint": {
            "drivers": "IRQ or DMA channel not freed on driver unload/error",
            "fs": "File descriptor leak in error path",
            "net": "Socket leak in connection error handling",
        },
    },

    # ── 安全 (1 种) ───────────────────────────────────────────────
    "security": {
        "root_cause": "Security vulnerability — exploitable memory access, privilege escalation, or information leak",
        "severity": 9,
        "typical_fix": "Validate user input, restrict privileges, fix memory access boundaries",
        "subsystem_hint": {},
    },

    # ── 泛型 (7 种) ───────────────────────────────────────────────
    "crash": {
        "root_cause": "Kernel crash — BUG_ON/WARN_ON/paging fault/GPF triggered by violated invariant",
        "severity": 8,
        "typical_fix": "Fix the violated invariant condition or add defensive check before assertion",
        "subsystem_hint": {},
    },
    "regression": {
        "root_cause": "Kernel regression — previously working functionality broken by recent change",
        "severity": 6,
        "typical_fix": "Revert the introducing commit or fix the changed logic",
        "subsystem_hint": {},
    },
    "performance": {
        "root_cause": "Performance degradation — suboptimal code path, excessive lock contention, or cache miss",
        "severity": 5,
        "typical_fix": "Optimize algorithm, reduce lock contention, add caching, or batch operations",
        "subsystem_hint": {},
    },
    "logic_error": {
        "root_cause": "Logic error — incorrect condition, calculation, state machine transition, or control flow",
        "severity": 7,
        "typical_fix": "Fix the incorrect logic condition, state transition, or calculation",
        "subsystem_hint": {},
    },
    "configuration": {
        "root_cause": "Configuration issue — incorrect Kconfig dependency, sysctl default, or device tree binding",
        "severity": 5,
        "typical_fix": "Fix Kconfig dependency, correct default value, or update device tree",
        "subsystem_hint": {},
    },
    "integer_overflow": {
        "root_cause": "Integer overflow or underflow in arithmetic, size calculation, or allocation",
        "severity": 8,
        "typical_fix": "Use size_add/size_mul/size_sub or check for overflow before arithmetic operations",
        "subsystem_hint": {},
    },
    "unknown": {
        "root_cause": "Undetermined root cause — insufficient structured information from Collector",
        "severity": 5,
        "typical_fix": "Analyze commit message and diff content for manual diagnosis",
        "subsystem_hint": {},
    },
}


# ============================================================================
# DIFF_RULES — 25 条轻量 Diff 规则 (分析 +/- 代码行的修复模式)
# ============================================================================

# 每条规则:
#   name:         规则 ID (L=锁, R=引用计数, C=RCU, M=内存, N=空指针, A=并发)
#   required_plus: 必须在新增行 (+) 中出现的模式列表 (AND — 每个都必须至少命中一次)
#   required_minus: 必须在删除行 (-) 中出现的模式列表 (AND)
#   optional_plus: 可选的加分模式 (OR — 命中 >= min_hits 个则加分)
#   min_hits:      optional_plus 至少需要命中的数量
#   message_hint:  commit message 中期望出现的关键词 (OR, 至少命中一个)
#   root_cause:    命中后输出的根因描述
#   fix_pattern:   命中后输出的修复模式

DIFF_RULES: List[Dict[str, Any]] = [

    # ═══════════════════════════════════════════════════════════════
    # 锁修复类 (8 条: L01-L08)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "L01",
        "required_plus": ["mutex_unlock(", "spin_unlock(", "up_write(", "up_read("],
        "required_minus": [],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["deadlock", "lockup", "stall", "hung", "lock", "unlock"],
        "root_cause": "Missing lock release causing deadlock or hung task — unlock added on exit/error path",
        "fix_pattern": "lock release (unlock) added on exit or error path",
    },
    {
        "name": "L02",
        "required_plus": ["spin_lock_irqsave(", "spin_lock_irq("],
        "required_minus": ["spin_lock("],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["interrupt", "irq", "softirq", "deadlock", "hardlockup", "irqsave"],
        "root_cause": "Missing irqsave — spin_lock used in interrupt-capable context causes hardlockup",
        "fix_pattern": "spin_lock replaced with spin_lock_irqsave for interrupt safety",
    },
    {
        "name": "L03",
        "required_plus": ["mutex_unlock(", "spin_unlock("],
        "required_minus": [],
        "optional_plus": ["goto ", "return -E", "return -ENOMEM", "return -EINVAL"],
        "min_hits": 1,
        "message_hint": ["error path", "goto", "cleanup", "missing unlock", "leak"],
        "root_cause": "Missing lock release on error/cleanup goto path — lock held during error return",
        "fix_pattern": "lock release added on error goto cleanup path",
    },
    {
        "name": "L04",
        "required_plus": ["cond_resched(", "schedule_timeout("],
        "required_minus": ["spin_lock("],
        "optional_plus": ["spin_unlock("],
        "min_hits": 0,
        "message_hint": ["scheduling while atomic", "sleeping function", "might_sleep", "atomic context"],
        "root_cause": "Scheduling while atomic — spinlock held across sleep point or cond_resched",
        "fix_pattern": "lock released before scheduling point to avoid atomic sleep",
    },
    {
        "name": "L05",
        "required_plus": ["mutex_trylock(", "spin_trylock("],
        "required_minus": ["mutex_lock(", "spin_lock("],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["contention", "trylock", "try_lock", "stall", "hang", "deadlock"],
        "root_cause": "Lock contention causing stall — blocking lock converted to trylock with fallback",
        "fix_pattern": "blocking lock replaced with trylock to avoid stall",
    },
    {
        "name": "L06",
        "required_plus": ["down_read(", "up_read("],
        "required_minus": ["down_write(", "up_write(", "mutex_lock("],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["read", "write lock", "rwlock", "downgrade", "contention", "performance"],
        "root_cause": "Excessive exclusive lock for read-only path — write lock downgraded to read lock",
        "fix_pattern": "write lock downgraded to read lock for read-only access path",
    },
    {
        "name": "L07",
        "required_plus": [],
        "required_minus": ["mutex_lock("],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["double lock", "recursive lock", "already locked", "deadlock"],
        "root_cause": "Duplicate lock acquisition — same context locks mutex twice causing recursive deadlock",
        "fix_pattern": "duplicate mutex_lock call removed to prevent recursive locking",
    },
    {
        "name": "L08",
        "required_plus": ["spin_lock(", "mutex_lock("],
        "required_minus": ["spin_lock(", "mutex_lock("],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["lock order", "ABBA", "lockdep", "circular", "ordering", "inversion"],
        "root_cause": "Lock ordering violation — ABBA deadlock between two lock classes (lockdep detected)",
        "fix_pattern": "lock acquisition order corrected to prevent ABBA deadlock",
    },

    # ═══════════════════════════════════════════════════════════════
    # 引用计数修复类 (4 条: R01-R04)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "R01",
        "required_plus": ["kref_put(", "refcount_dec("],
        "required_minus": [],
        "optional_plus": ["kref_put_and_test("],
        "min_hits": 0,
        "message_hint": ["leak", "refcount", "kref", "release", "put", "memory leak"],
        "root_cause": "Reference count leak — missing kref_put/refcount_dec on object release path",
        "fix_pattern": "reference count decrement (kref_put/refcount_dec) added on release path",
    },
    {
        "name": "R02",
        "required_plus": ["kref_get(", "refcount_inc("],
        "required_minus": [],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["use-after-free", "uaf", "kasan", "use after free"],
        "root_cause": "Use-after-free — object freed while still referenced, missing kref_get before use",
        "fix_pattern": "reference count increment (kref_get/refcount_inc) added to protect object lifetime",
    },
    {
        "name": "R03",
        "required_plus": ["refcount_add_not_zero(", "refcount_inc_not_zero("],
        "required_minus": ["refcount_inc(", "refcount_add("],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["overflow", "saturation", "refcount", "saturated"],
        "root_cause": "Reference count overflow — refcount_inc may overflow without saturation check",
        "fix_pattern": "safe refcount increment (refcount_inc_not_zero) used to prevent overflow",
    },
    {
        "name": "R04",
        "required_plus": ["get_device(", "put_device("],
        "required_minus": [],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["get", "put", "device", "refcount", "leak", "uaf"],
        "root_cause": "get/put pairing imbalance in device reference counting — lifecycle management error",
        "fix_pattern": "matched get_device/put_device pairing restored for device lifecycle",
    },

    # ═══════════════════════════════════════════════════════════════
    # RCU 修复类 (3 条: C01-C03)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "C01",
        "required_plus": ["rcu_read_lock(", "rcu_read_unlock("],
        "required_minus": [],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["use-after-free", "rcu", "uaf", "grace period", "rcu_dereference"],
        "root_cause": "RCU-protected pointer accessed without rcu_read_lock critical section",
        "fix_pattern": "RCU read-side critical section (rcu_read_lock/rcu_read_unlock) added",
    },
    {
        "name": "C02",
        "required_plus": ["synchronize_rcu(", "kfree_rcu(", "call_rcu("],
        "required_minus": ["kfree("],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["use-after-free", "rcu", "grace period", "uaf"],
        "root_cause": "Object freed without RCU grace period — RCU readers may still be accessing the object",
        "fix_pattern": "RCU delayed free (kfree_rcu/synchronize_rcu) added for safe deallocation",
    },
    {
        "name": "C03",
        "required_plus": ["cond_resched(", "rcu_read_unlock("],
        "required_minus": [],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["rcu stall", "rcu_sched", "stall", "rcu.*stall"],
        "root_cause": "RCU grace period stall — long-running RCU read critical section blocks grace period",
        "fix_pattern": "cond_resched or rcu_read_unlock added to shorten RCU read-side critical section",
    },

    # ═══════════════════════════════════════════════════════════════
    # 内存修复类 (5 条: M01-M05)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "M01",
        "required_plus": ["kfree("],
        "required_minus": [],
        "optional_plus": ["goto ", "return -E"],
        "min_hits": 0,
        "message_hint": ["memory leak", "kmemleak", "leak", "missing free", "missing kfree"],
        "root_cause": "Memory leak — missing kfree on error/cleanup goto path",
        "fix_pattern": "kfree added on error goto cleanup path to fix memory leak",
    },
    {
        "name": "M02",
        "required_plus": ["= NULL;", "= NULL)"],
        "required_minus": [],
        "optional_plus": ["kfree(", "put_device(", "kmem_cache_free("],
        "min_hits": 1,
        "message_hint": ["double free", "double-free", "kasan", "null"],
        "root_cause": "Potential double free — pointer not nullified after deallocation",
        "fix_pattern": "pointer set to NULL after deallocation to prevent double free",
    },
    {
        "name": "M03",
        "required_plus": ["kmalloc(", "kzalloc("],
        "required_minus": ["kmalloc(", "kzalloc("],
        "optional_plus": ["sizeof("],
        "min_hits": 0,
        "message_hint": ["overflow", "size", "buffer", "allocation", "too small"],
        "root_cause": "Incorrect allocation size — buffer too small for target structure causing overflow",
        "fix_pattern": "allocation size corrected (kmalloc/kzalloc with proper sizeof)",
    },
    {
        "name": "M04",
        "required_plus": ["kvmalloc(", "kvfree("],
        "required_minus": ["kmalloc(", "vmalloc("],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["vmalloc", "kmalloc", "fallback", "large", "contiguous", "allocation fail"],
        "root_cause": "Large contiguous allocation may fail under memory pressure — kvmalloc with fallback needed",
        "fix_pattern": "kvmalloc/kvfree used with vmalloc fallback for large allocations",
    },
    {
        "name": "M05",
        "required_plus": ["kmalloc(", "kzalloc("],
        "required_minus": [],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["stack overflow", "stack frame", "stack size", "too large", "on stack"],
        "root_cause": "Excessive stack usage — large on-stack buffer or deep recursion exhausting kernel stack",
        "fix_pattern": "large stack allocation replaced with kmalloc/kzalloc on heap",
    },

    # ═══════════════════════════════════════════════════════════════
    # 空指针/校验类 (3 条: N01-N03)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "N01",
        "required_plus": ["if (!", "if (ptr", "IS_ERR_OR_NULL("],
        "required_minus": [],
        "optional_plus": ["return -E", "return -ENOMEM", "return -EINVAL", "goto "],
        "min_hits": 0,
        "message_hint": ["null pointer", "null deref", "oops", "NULL", "null check"],
        "root_cause": "Null pointer dereference — missing NULL validation before pointer access",
        "fix_pattern": "NULL pointer check (if (!ptr)) added before dereference",
    },
    {
        "name": "N02",
        "required_plus": ["return -E", "goto "],
        "required_minus": [],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["error handling", "error path", "missing check", "return value"],
        "root_cause": "Missing error handling — function return value not checked for error",
        "fix_pattern": "error return value check and propagation added",
    },
    {
        "name": "N03",
        "required_plus": ["if (", ">= ", "> ", "ARRAY_SIZE("],
        "required_minus": [],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["out of bounds", "overflow", "index", "bounds", "OOB", "oob"],
        "root_cause": "Array/buffer index out of bounds — missing bounds validation before array access",
        "fix_pattern": "bounds check (index >= size or ARRAY_SIZE) added before access",
    },

    # ═══════════════════════════════════════════════════════════════
    # 并发/原子类 (2 条: A01-A02)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "A01",
        "required_plus": ["atomic_inc(", "atomic_dec(", "atomic_cmpxchg(", "cmpxchg("],
        "required_minus": [],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["race", "concurrent", "smp", "atomic", "data race"],
        "root_cause": "Non-atomic access in concurrent context — race condition on shared variable",
        "fix_pattern": "atomic operation (atomic_inc/atomic_dec/atomic_cmpxchg) used for concurrent access",
    },
    {
        "name": "A02",
        "required_plus": ["smp_mb(", "smp_rmb(", "smp_wmb(", "barrier("],
        "required_minus": [],
        "optional_plus": [],
        "min_hits": 0,
        "message_hint": ["race", "reorder", "memory ordering", "barrier", "smp"],
        "root_cause": "Memory ordering violation — missing memory barrier between ordered operations",
        "fix_pattern": "memory barrier (smp_mb/smp_rmb/smp_wmb) added for ordering guarantee",
    },
]


# ============================================================================
# RootCauseSummary — CommitRootCauseBuilder 的输出数据结构
# ============================================================================

@dataclass
class RootCauseSummary:
    """Commit 根因分析摘要 — CommitRootCauseBuilder.build() 的输出

    Attributes:
        bug_type: 标准化的 Bug 类型 (对应 BugType 枚举值)
        subsystem: 受影响的子系统
        root_cause: 根因描述文本 (英文, 用于 embedding)
        severity: 严重程度 1-10
        typical_fix: 典型修复方案描述
        fix_pattern: Diff 规则确定的修复模式
        lock_added: Collector 从 diff 提取的锁添加证据
        refcount_fix: Collector 从 diff 提取的引用计数修复证据
        rcu_fix: Collector 从 diff 提取的 RCU 修复证据
        fix_tags: 修复标签 (Fixes:, Cc:stable, CVE 等)
        cves: 提取的 CVE 编号列表
        evidence: 证据链 (记录命中了哪些规则/条件)
        confidence: 置信度 0.0 ~ 1.0
    """
    bug_type: str = "unknown"
    subsystem: str = "unknown"
    root_cause: str = ""
    severity: int = 5
    typical_fix: str = ""
    fix_pattern: str = ""
    lock_added: bool = False
    refcount_fix: bool = False
    rcu_fix: bool = False
    fix_tags: List[str] = field(default_factory=list)
    cves: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.0


# ============================================================================
# CommitRootCauseBuilder — 三层轻量 Commit 根因分析引擎
# ============================================================================

class CommitRootCauseBuilder:
    """轻量级 Commit 根因分析引擎 — 替代 RootCauseAnalyzer 用于离线索引

    采用三层分析策略 (全部计算 <5ms):
    Layer 1: BUG_TEMPLATE 查表 — bug_type + subsystem → root_cause (<0.01ms)
    Layer 2: DIFF_RULES 规则匹配 — 25 条规则分析 diff 修复模式 (1-3ms)
    Layer 3: 置信度评估 + 轻量兜底 — 多维度评分, 低分兜底 (<1ms)

    Usage:
        >>> builder = CommitRootCauseBuilder()
        >>> summary = builder.build(commit_info)
        >>> print(summary.root_cause, summary.confidence)
    """

    def __init__(self):
        self.templates = BUG_TEMPLATE
        self.rules = DIFF_RULES

    # ── 公共入口 ──────────────────────────────────────────────────

    def build(self, commit: Any) -> RootCauseSummary:
        """公共入口: 对 CommitInfo 执行三层根因分析

        Args:
            commit: CommitInfo 对象 (来自 src.collector.models)

        Returns:
            RootCauseSummary: 包含根因、修复模式、证据链、置信度
        """
        # Layer 1: BUG_TEMPLATE 查表
        summary = self._infer_from_features(commit)

        # Layer 2: Diff 规则匹配增强
        summary = self._apply_diff_rules(commit, summary)

        # Layer 3: 置信度评估 + 兜底
        summary = self._evaluate_and_fallback(commit, summary)

        return summary

    # ── Layer 1: 结构化特征推断 ──────────────────────────────────

    def _infer_from_features(self, commit: Any) -> RootCauseSummary:
        """Layer 1: 直接利用 Collector 已提取的特征查表

        Collector 已经确定了 commit 的 bug_type/subsystem/lock_added 等，
        这里不做推断——只做查表和语义增强。
        """
        bt = getattr(commit, "bug_type", "unknown") or "unknown"
        subsys = getattr(commit, "subsystem", "unknown") or "unknown"

        template = self.templates.get(bt, self.templates["unknown"])

        # 优先使用 subsystem 细分描述
        subsystem_hints = template.get("subsystem_hint", {})
        root_cause = subsystem_hints.get(subsys, template.get("root_cause", "Undetermined root cause"))

        # 从 Collector diff 分析提取事实证据
        lock_added = getattr(commit, "lock_added", False)
        refcount_fix = getattr(commit, "refcount_fix", False)
        rcu_fix = getattr(commit, "rcu_fix", False)
        fix_tags = list(getattr(commit, "fix_tags", []) or [])

        # 提取 CVE 编号
        cves = [t for t in fix_tags if t.upper().startswith("CVE")]

        return RootCauseSummary(
            bug_type=bt,
            subsystem=subsys,
            root_cause=root_cause,
            severity=template.get("severity", 5),
            typical_fix=template.get("typical_fix", ""),
            lock_added=lock_added,
            refcount_fix=refcount_fix,
            rcu_fix=rcu_fix,
            fix_tags=fix_tags,
            cves=cves,
            evidence=[],
            confidence=0.80,  # 初始置信度 (后续 Layer 2/3 调整)
        )

    # ── Layer 2: Diff 规则匹配 ───────────────────────────────────

    def _apply_diff_rules(self, commit: Any, summary: RootCauseSummary) -> RootCauseSummary:
        """Layer 2: 用 25 条 Diff 规则分析代码变更中的修复模式

        对 25 条规则逐一评分，选最高分命中者更新 root_cause 和 fix_pattern。
        如果无规则命中，保留 Layer 1 的结果 (不降分)。
        """
        diff = getattr(commit, "diff_content", "") or ""
        if not diff:
            return summary

        diff_plus = [l for l in diff.split("\n") if l.startswith("+") and not l.startswith("+++")]
        diff_minus = [l for l in diff.split("\n") if l.startswith("-") and not l.startswith("---")]
        message = f"{getattr(commit, 'subject', '')} {getattr(commit, 'body', '')}".lower()

        best_rule = None
        best_score = 0

        for rule in self.rules:
            score = 0

            # required_plus: 至少一个模式在 diff_plus 中出现 (OR 逻辑)
            req_plus = rule.get("required_plus", [])
            if req_plus:
                plus_text = "\n".join(diff_plus)
                hits = sum(1 for p in req_plus if p in plus_text)
                if hits < 1:
                    continue  # 必要条件不满足
                score += 3 * hits

            # required_minus: 至少一个模式在 diff_minus 中出现 (OR 逻辑)
            req_minus = rule.get("required_minus", [])
            if req_minus:
                minus_text = "\n".join(diff_minus)
                hits = sum(1 for p in req_minus if p in minus_text)
                if hits < 1:
                    continue  # 必要条件不满足
                score += 2 * hits

            # optional_plus: 加分项 (OR, 至少命中 min_hits 个)
            opt_plus = rule.get("optional_plus", [])
            if opt_plus:
                plus_text = "\n".join(diff_plus)
                hits = sum(1 for p in opt_plus if p in plus_text)
                min_h = rule.get("min_hits", 1)
                if hits >= min_h:
                    score += hits

            # message_hint: commit message 关键词 (OR, 至少命中一个)
            msg_hints = rule.get("message_hint", [])
            if msg_hints:
                if any(h in message for h in msg_hints):
                    score += 2
                else:
                    score -= 1  # diff 有证据但 message 不匹配，轻微降分

            if score > best_score:
                best_score = score
                best_rule = rule

        # 应用最佳命中规则
        if best_rule and best_score > 0:
            summary.root_cause = best_rule.get("root_cause", summary.root_cause)
            summary.fix_pattern = best_rule.get("fix_pattern", summary.fix_pattern)
            summary.confidence = min(0.95, 0.80 + best_score * 0.03)
            summary.evidence.append(f"diff_rule:{best_rule['name']}(score={best_score})")

        return summary

    # ── Layer 3: 置信度评估与兜底 ─────────────────────────────────

    def _evaluate_and_fallback(self, commit: Any, summary: RootCauseSummary) -> RootCauseSummary:
        """Layer 3: 多维度置信度评估 + 低置信度兜底策略

        加分维度:
        - bug_type 已知 (非 unknown) → +0.05
        - subsystem 已知 (非 unknown) → +0.02
        - 每个 diff 证据 (lock_added/refcount_fix/rcu_fix) → +0.03
        - 包含 CVE 编号 → +0.05
        - 包含 Fixes: 标签 → +0.03
        """
        # bug_type 质量加分
        bt = summary.bug_type
        if bt and bt != "unknown":
            summary.confidence += 0.05

        # subsystem 质量加分
        subsys = summary.subsystem
        if subsys and subsys != "unknown":
            summary.confidence += 0.02

        # diff 证据加分
        diff_evidence_count = sum([summary.lock_added, summary.refcount_fix, summary.rcu_fix])
        summary.confidence += diff_evidence_count * 0.03

        # Fix tags 信号加分
        fix_tags_lower = [t.lower() for t in summary.fix_tags]
        if any("cve" in t for t in fix_tags_lower):
            summary.confidence += 0.05
        if any("fixes:" in t for t in summary.fix_tags):
            summary.confidence += 0.03

        # 上限
        summary.confidence = min(0.98, summary.confidence)

        # 兜底: 极低置信度且 bug_type=unknown 时做轻量 message 关键词推断
        if summary.confidence < 0.60 and bt == "unknown":
            summary = self._lightweight_fallback(commit, summary)

        return summary

    def _lightweight_fallback(self, commit: Any, summary: RootCauseSummary) -> RootCauseSummary:
        """轻量兜底: 从 commit message 做关键词推断 (仅在 Collector 完全无法识别时)

        使用 10 组正则关键词，快速扫描 commit 消息。
        仅对 bug_type="unknown" 的极少数 commit 生效 (<5%).
        """
        msg = f"{getattr(commit, 'subject', '')} {getattr(commit, 'body', '')}".lower()

        fallback_patterns: List[Tuple[List[str], str, str]] = [
            (["deadlock", "lockdep", "circular locking"], "deadlock", "Potential lock ordering or circular dependency issue"),
            (["use.after.free", "use-after-free", "uaf", "kasan.*use.after.free"], "use_after_free", "Potential use-after-free detected by KASAN or code review"),
            (["double.free", "double-free"], "double_free", "Potential double free detected in memory deallocation"),
            (["null.*pointer", "null.*deref", "null ptr"], "null_pointer", "Potential null pointer dereference"),
            (["buffer.*overflow", "overflow.*buffer"], "buffer_overflow", "Potential buffer overflow"),
            (["out.of.bound", "out-of-bounds", "oob"], "out_of_bound", "Potential out-of-bounds access"),
            (["memory.*leak", "kmemleak", "memory leak"], "memory_leak", "Potential memory leak"),
            (["race.*condition", "race condition", "data race", "concurrent"], "race_condition", "Potential race condition"),
            (["softlockup", "hardlockup", "hung.task", "rcu.stall", "stall"], "hang", "Potential system hang or stall"),
            (["refcount", "kref.*put", "kref.*get", "ref.count"], "use_after_free", "Potential reference count imbalance"),
        ]

        for patterns, bt, rc in fallback_patterns:
            try:
                if any(re.search(p, msg, re.IGNORECASE) for p in patterns):
                    summary.bug_type = bt
                    summary.root_cause = rc
                    summary.confidence = 0.55
                    summary.evidence.append("fallback:keyword_match_from_message")
                    break
            except re.error:
                continue

        return summary


# ============================================================================
# Embedding 文本生成
# ============================================================================

def build_commit_embedding_text(summary: RootCauseSummary, commit: Any) -> str:
    """从 RootCauseSummary + CommitInfo 生成语义增强的 embedding 文本

    生成的文本用于 BGE-M3 编码后存入 Milvus/FAISS 向量库。
    格式与在线 Crash 路径的 retrieval_query 保持语义对称。

    Args:
        summary: CommitRootCauseBuilder.build() 的输出
        commit: CommitInfo 对象

    Returns:
        优化的 embedding 文本 (多行结构化字符串)
    """
    parts: List[str] = []

    # 主语义层
    parts.append(f"BugType: {summary.bug_type}")
    parts.append(f"Subsystem: {summary.subsystem}")
    parts.append(f"RootCause: {summary.root_cause}")

    # 修复语义层 (最关键 — 与在线 crash retrieval_query 对齐)
    if summary.fix_pattern:
        parts.append(f"FixPattern: {summary.fix_pattern}")

    # 修复行为证据 (从 Collector diff 分析直接获取)
    if summary.lock_added:
        parts.append("FixAction: lock synchronization added")
    if summary.refcount_fix:
        parts.append("FixAction: reference count correction applied")
    if summary.rcu_fix:
        parts.append("FixAction: RCU synchronization/protection fix applied")

    # 结构化元数据
    subject = getattr(commit, "subject", "")
    if subject:
        parts.append(f"CommitTitle: {subject}")

    body = getattr(commit, "body", "")
    if body:
        parts.append(f"CommitMessage: {body[:500]}")

    files = getattr(commit, "files_changed", []) or []
    if files:
        parts.append(f"ModifiedFiles: {', '.join(files[:10])}")

    # 安全/稳定性标签
    fix_tags = summary.fix_tags
    if fix_tags:
        parts.append(f"Tags: {', '.join(fix_tags[:8])}")

    if summary.cves:
        parts.append(f"CVEs: {', '.join(summary.cves[:5])}")

    # 严重度
    if summary.severity >= 8:
        parts.append(f"Severity: Critical (level {summary.severity})")

    # Diff 关键修复行 (代码级匹配信号)
    diff = getattr(commit, "diff_content", "") or ""
    if diff:
        key_lines = _extract_key_diff_lines(diff, max_lines=15)
        if key_lines:
            parts.append(f"KeyDiffLines:\n{key_lines}")

    return "\n".join(parts)


def _extract_key_diff_lines(diff_content: str, max_lines: int = 15) -> str:
    """从 diff 中提取关键修复代码行

    只保留以 + 开头且包含修复模式的代码行:
    - 锁操作: spin_lock, mutex_lock, spin_unlock...
    - 内存操作: kfree, kmalloc, kref_get, kref_put...
    - RCU 操作: kfree_rcu, synchronize_rcu, rcu_read_lock...
    - 错误处理: NULL check, error handling, goto...
    """
    fix_keywords = [
        "spin_lock", "spin_unlock", "mutex_lock", "mutex_unlock",
        "kref_get", "kref_put", "kref_init",
        "refcount_inc", "refcount_dec", "refcount_add",
        "kfree", "kmalloc", "kzalloc",
        "kfree_rcu", "synchronize_rcu", "rcu_read_lock", "rcu_read_unlock",
        "if (!", "NULL", "null",
        "return -", "goto ", "error",
        "BUG", "WARN",
        "atomic_inc", "atomic_dec", "atomic_read", "atomic_cmpxchg",
        "down_read", "down_write", "up_read", "up_write",
        "smp_mb", "smp_rmb", "smp_wmb",
        "cond_resched", "schedule_timeout",
        "put_device", "get_device",
        "IS_ERR_OR_NULL",
        "snprintf", "strscpy", "scnprintf",
    ]

    key_lines = []
    for line in diff_content.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            line_lower = line.lower()
            if any(kw.lower() in line_lower for kw in fix_keywords):
                key_lines.append(line[1:].strip()[:120])  # 去掉 + 前缀
                if len(key_lines) >= max_lines:
                    break

    return "\n".join(key_lines)


# ============================================================================
# 全局单例
# ============================================================================

_builder: Optional[CommitRootCauseBuilder] = None


def get_builder() -> CommitRootCauseBuilder:
    """获取/创建全局 CommitRootCauseBuilder 单例"""
    global _builder
    if _builder is None:
        _builder = CommitRootCauseBuilder()
    return _builder


def reset_builder():
    """重置 CommitRootCauseBuilder 单例 (测试/配置切换时使用)"""
    global _builder
    _builder = None


# ============================================================================
# 便捷函数
# ============================================================================

def build_commit_embedding_text_simple(commit: Any) -> str:
    """一步完成: CommitInfo → RootCauseSummary → embedding 文本

    这是离线索引流水线中最常用的便捷入口。

    Args:
        commit: CommitInfo 对象

    Returns:
        可直接送入 BGE-M3 编码的 embedding 文本
    """
    builder = get_builder()
    summary = builder.build(commit)
    return build_commit_embedding_text(summary, commit)


__all__ = [
    # 常量
    "BUG_TEMPLATE",
    "DIFF_RULES",
    # 数据结构
    "RootCauseSummary",
    # 核心引擎
    "CommitRootCauseBuilder",
    # 单例
    "get_builder",
    "reset_builder",
    # 文本生成
    "build_commit_embedding_text",
    "build_commit_embedding_text_simple",
    "_extract_key_diff_lines",
]
