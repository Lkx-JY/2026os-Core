"""锁规则知识库 — Lock Rule Knowledge Base

包含 Linux 内核锁机制的规则和最佳实践知识，用于辅助死锁分析、锁使用模式识别。

知识来源:
- Linux 内核文档 (Documentation/locking/)
- LOCKDEP 报告的常见模式
- 内核锁专家 (Peter Zijlstra, Ingo Molnar, etc.) 的设计原则
- LKML 上讨论的锁相关 Bug 模式

设计要点:
- 锁层次结构: spinlock → mutex → rwsem 的使用场景和限制
- 锁获取顺序规则: 常见子系统的锁顺序约束
- 中断上下文锁规则: spin_lock vs spin_lock_irqsave
- 锁依赖检测模式: LOCKDEP 常见报告解析
"""

from typing import List, Dict, Any, Optional


# ============================================================================
# 锁类型定义
# ============================================================================

LOCK_TYPES: Dict[str, Dict[str, Any]] = {
    "spinlock": {
        "name": "自旋锁 (Spinlock)",
        "api": ["spin_lock", "spin_unlock", "spin_lock_irq", "spin_unlock_irq",
                "spin_lock_irqsave", "spin_unlock_irqrestore",
                "spin_lock_bh", "spin_unlock_bh", "spin_trylock"],
        "sleepable": False,
        "preempt_disabled": True,
        "interrupt_safe_only_with_irqsave": True,
        "use_case": "短临界区、中断上下文、不可睡眠",
        "typical_abuse": [
            "spin_lock() 后调用可能睡眠的函数 (schedule, kmalloc(GFP_KERNEL), copy_from_user 等)",
            "中断上下文中使用 spin_lock() 而非 spin_lock_irqsave()",
            "长时间持锁 (>几微秒)",
        ],
        "lockdep_class": "&__key.xx",
    },
    "mutex": {
        "name": "互斥锁 (Mutex)",
        "api": ["mutex_lock", "mutex_unlock", "mutex_lock_interruptible",
                "mutex_lock_killable", "mutex_trylock", "mutex_is_locked"],
        "sleepable": True,
        "preempt_disabled": False,
        "interrupt_safe_only_with_irqsave": False,
        "use_case": "可能睡眠的临界区、进程上下文",
        "typical_abuse": [
            "中断上下文中使用 mutex_lock()",
            "持 mutex 时调用 schedule() 导致优先级反转",
            "未释放 mutex 就返回",
        ],
        "lockdep_class": "mutex_lock_nested",
    },
    "rwsem": {
        "name": "读写信号量 (R/W Semaphore)",
        "api": ["down_read", "up_read", "down_write", "up_write",
                "down_read_trylock", "down_write_trylock",
                "downgrade_write"],
        "sleepable": True,
        "preempt_disabled": False,
        "interrupt_safe_only_with_irqsave": False,
        "use_case": "读多写少的场景、页表锁、文件系统锁",
        "typical_abuse": [
            "读锁内调用可能修改共享数据的函数",
            "写锁饥饿 (读锁持续持有)",
            "递归 read lock (在持 read lock 时再次 read lock)",
        ],
        "lockdep_class": "down_read_nested",
    },
    "rcu": {
        "name": "RCU (Read-Copy-Update)",
        "api": ["rcu_read_lock", "rcu_read_unlock",
                "synchronize_rcu", "synchronize_rcu_expedited",
                "call_rcu", "rcu_assign_pointer", "rcu_dereference",
                "rcu_barrier", "rcu_access_pointer"],
        "sleepable": False,  # rcu_read_lock 内不可睡眠
        "preempt_disabled": False,
        "interrupt_safe_only_with_irqsave": True,
        "use_case": "读频繁写稀少、指针更新保护",
        "typical_abuse": [
            "rcu_read_lock() 内睡眠",
            "未在 rcu_read_lock() 保护下使用 rcu_dereference()",
            "synchronize_rcu() 在不可睡眠上下文中调用",
            "rcu_read_lock() 与 rcu_read_unlock() 不配对",
        ],
        "lockdep_class": "rcu_read_lock",
    },
    "rwlock": {
        "name": "读写自旋锁 (R/W Spinlock)",
        "api": ["read_lock", "read_unlock", "write_lock", "write_unlock",
                "read_lock_irqsave", "write_lock_irqsave",
                "read_lock_bh", "write_lock_bh"],
        "sleepable": False,
        "preempt_disabled": True,
        "interrupt_safe_only_with_irqsave": True,
        "use_case": "读多写少 + 不可睡眠的短临界区",
        "typical_abuse": [
            "同 spinlock 的滥用模式",
            "写锁饥饿",
        ],
        "lockdep_class": "rwlock",
    },
    "seqlock": {
        "name": "顺序锁 (Seqlock)",
        "api": ["write_seqlock", "write_sequnlock",
                "read_seqbegin", "read_seqretry",
                "write_seqlock_irqsave", "write_sequnlock_irqrestore"],
        "sleepable": False,
        "preempt_disabled": True,
        "interrupt_safe_only_with_irqsave": True,
        "use_case": "写非常稀少、读非常频繁 (如 jiffies, timekeeping)",
        "typical_abuse": [
            "读端做太多工作",
            "写端持锁太久",
        ],
        "lockdep_class": "seqlock",
    },
}


# ============================================================================
# 锁依赖规则
# ============================================================================

# 常见锁获取顺序约束 (先获取 → 后获取)
LOCK_ORDERING_RULES: List[Dict[str, Any]] = [
    {
        "id": "L001",
        "description": "先获取外层锁，再获取内层锁",
        "example": "先 mm->mmap_lock，再 vma->vm_lock",
        "subsystems": ["mm"],
    },
    {
        "id": "L002",
        "description": "先 inode->i_mutex，再 file->f_lock",
        "example": "先 mutex_lock(&inode->i_mutex)，再 spin_lock(&file->f_lock)",
        "subsystems": ["fs"],
    },
    {
        "id": "L003",
        "description": "先 socket lock，再 socket buffer lock",
        "example": "先 lock_sock(sk)，再 spin_lock(&sk->sk_lock)",
        "subsystems": ["net"],
    },
    {
        "id": "L004",
        "description": "先 rcu_read_lock，再 spin_lock",
        "example": "rcu_read_lock(); spin_lock(); spin_unlock(); rcu_read_unlock();",
        "subsystems": ["kernel", "mm", "net", "fs"],
    },
    {
        "id": "L005",
        "description": "先 mutex，再 spinlock (进程上下文)",
        "example": "先 mutex_lock，再 spin_lock (两者在同一路径中)",
        "subsystems": ["kernel"],
    },
    {
        "id": "L006",
        "description": "release 顺序: 先释放内层锁，再释放外层锁",
        "example": "spin_unlock(inner); mutex_unlock(outer);",
        "subsystems": ["kernel"],
    },
    {
        "id": "L007",
        "description": "中断上下文只能使用 spin_lock_irqsave，不能使用 mutex",
        "example": "在中断处理函数中使用 spin_lock_irqsave 而非 mutex_lock",
        "subsystems": ["kernel", "drivers"],
    },
    {
        "id": "L008",
        "description": "page fault 路径中避免获取 mmap_sem 外的其他锁",
        "example": "handle_mm_fault 内不应获取 inode mutex",
        "subsystems": ["mm", "fs"],
    },
]


# ============================================================================
# 常见死锁模式
# ============================================================================

DEADLOCK_PATTERNS: List[Dict[str, Any]] = [
    {
        "name": "ABBA Deadlock",
        "description": "两个锁以相反顺序获取导致死锁",
        "pattern": "CPU0: lock(A) → lock(B) | CPU1: lock(B) → lock(A)",
        "fix": "统一锁获取顺序",
        "lockdep_message": "possible circular locking dependency detected",
    },
    {
        "name": "Recursive Lock",
        "description": "同一 CPU 尝试获取已持有的锁",
        "pattern": "CPU0: lock(A) → lock(A) (non-recursive)",
        "fix": "使用递归版本锁或重构代码避免重复获取",
        "lockdep_message": "possible recursive locking detected",
    },
    {
        "name": "Interrupt Deadlock",
        "description": "中断上下文尝试获取已被进程上下持有的锁",
        "pattern": "Process: spin_lock(A) → INTERRUPT → spin_lock(A)",
        "fix": "进程上下文使用 spin_lock_irqsave 禁止本地中断",
        "lockdep_message": "possible irq lock inversion dependency detected",
    },
    {
        "name": "Sleep-in-Atomic",
        "description": "在持 spinlock 时尝试睡眠 (调用可能阻塞的函数)",
        "pattern": "spin_lock(A); schedule()/kmalloc(GFP_KERNEL)/copy_from_user()",
        "fix": "使用 mutex 替代 spinlock，或将睡眠操作移出临界区",
        "lockdep_message": "sleeping function called from invalid context",
    },
    {
        "name": "Lock Inversion",
        "description": "不同优先级的上下文以不同顺序获取锁",
        "pattern": "Softirq: lock(A) | Process: lock(B) → lock(A)",
        "fix": "在可能被软中断中断的路径中使用 spin_lock_bh",
        "lockdep_message": "possible irq lock inversion dependency detected",
    },
]


# ============================================================================
# 锁修复模式
# ============================================================================

LOCK_FIX_PATTERNS: Dict[str, str] = {
    "add_spinlock": "添加 spin_lock/spin_unlock 保护共享数据访问",
    "add_spinlock_irqsave": "在可能被中断访问的数据路径中使用 spin_lock_irqsave",
    "add_mutex": "在可能睡眠的临界区使用 mutex_lock/mutex_unlock",
    "add_rcu": "使用 RCU 保护读多写少的指针型共享数据",
    "fix_ordering": "修正锁获取顺序，确保所有路径使用相同顺序",
    "reduce_critical_section": "缩小临界区，将非关键操作移到锁外",
    "convert_to_atomic": "对简单共享变量使用 atomic_t 代替锁",
    "add_rcu_dereference": "添加 rcu_dereference/rcu_dereference_protected 保护 RCU 指针访问",
}


# ============================================================================
# 查询接口
# ============================================================================

def get_lock_type(lock_name: str) -> Optional[Dict[str, Any]]:
    """根据锁名称获取锁类型定义

    Args:
        lock_name: 锁类型名 (如 "spinlock")

    Returns:
        锁类型定义字典
    """
    # 直接匹配
    if lock_name in LOCK_TYPES:
        return dict(LOCK_TYPES[lock_name])

    # 通过 API 函数名匹配
    lock_lower = lock_name.lower()
    for lock_type, info in LOCK_TYPES.items():
        for api in info["api"]:
            if lock_lower in api:
                return dict(info)

    return None


def detect_lock_type_from_function(func_name: str) -> Optional[str]:
    """从函数名检测锁类型

    Args:
        func_name: 函数名 (如 "mutex_lock")

    Returns:
        锁类型 (如 "mutex") 或 None
    """
    func_lower = func_name.lower()
    for lock_type, info in LOCK_TYPES.items():
        for api in info["api"]:
            if api in func_lower:
                return lock_type
    return None


def get_lock_ordering_rules(subsystem: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取锁获取顺序规则

    Args:
        subsystem: 可选过滤 — "mm", "fs", "net", "kernel"

    Returns:
        匹配的锁顺序规则列表
    """
    if subsystem:
        return [r for r in LOCK_ORDERING_RULES if subsystem in r.get("subsystems", [])]
    return list(LOCK_ORDERING_RULES)


def match_deadlock_pattern(lockdep_msg: str) -> List[Dict[str, Any]]:
    """根据 lockdep 消息匹配死锁模式

    Args:
        lockdep_msg: lockdep 输出的报告文本

    Returns:
        匹配的死锁模式列表
    """
    matches = []
    msg_lower = lockdep_msg.lower()

    for pattern in DEADLOCK_PATTERNS:
        lockdep_key = pattern.get("lockdep_message", "").lower()
        if lockdep_key and lockdep_key in msg_lower:
            matches.append(dict(pattern))

    if not matches:
        # 通用匹配
        if "circular locking" in msg_lower:
            matches.append(DEADLOCK_PATTERNS[0])  # ABBA
        if "recursive locking" in msg_lower:
            matches.append(DEADLOCK_PATTERNS[1])
        if "irq lock inversion" in msg_lower:
            matches.append(DEADLOCK_PATTERNS[2])
        if "sleeping function called from invalid context" in msg_lower:
            matches.append(DEADLOCK_PATTERNS[3])

    return matches


def get_lock_fix_pattern(fix_type: str) -> str:
    """获取锁修复模式的描述

    Args:
        fix_type: 修复类型标识

    Returns:
        修复描述文本
    """
    return LOCK_FIX_PATTERNS.get(fix_type, "未知锁修复模式")


def analyze_lock_usage(call_trace: List[str]) -> Dict[str, Any]:
    """分析调用栈中的锁使用模式

    识别调用栈中的锁获取/释放函数，分析锁使用是否正确。

    Args:
        call_trace: 调用栈帧列表

    Returns:
        {
            "locks_acquired": [...],   # 识别到的锁获取
            "locks_released": [...],   # 识别到的锁释放
            "lock_types": [...],       # 使用的锁类型
            "potential_issues": [...], # 潜在问题
        }
    """
    locks_acquired = []
    locks_released = []
    lock_types_found = set()

    for frame in call_trace:
        frame_lower = frame.lower()

        for lock_type, info in LOCK_TYPES.items():
            for api in info["api"]:
                if api in frame_lower:
                    if "lock" in api and "unlock" not in api:
                        locks_acquired.append({"function": api, "frame": frame, "type": lock_type})
                        lock_types_found.add(lock_type)
                    elif "unlock" in api or "up_" in api:
                        locks_released.append({"function": api, "frame": frame, "type": lock_type})
                        lock_types_found.add(lock_type)

    # 检测潜在问题
    potential_issues = []

    # 检查 spinlock 后是否有 schedule/sleep
    has_spinlock = "spinlock" in lock_types_found or "rwlock" in lock_types_found
    has_sleep = any("schedule" in f.lower() or "sleep" in f.lower() for f in call_trace)

    if has_spinlock and has_sleep:
        potential_issues.append("持 spinlock 时可能调用了 sleepable 函数 (sleep-in-atomic)")

    # 检查是否有 spin_lock 而没有 spin_lock_irqsave (在中断相关路径中)
    has_spin_lock = any("spin_lock" in f.lower() and "irq" not in f.lower() for f in call_trace)
    has_irq_context = any("irq" in f.lower() or "interrupt" in f.lower() for f in call_trace)
    if has_spin_lock and has_irq_context:
        potential_issues.append("中断相关路径中使用 spin_lock 而非 spin_lock_irqsave")

    # 检查 RCU 持有期间是否有睡眠
    has_rcu_read_lock = any("rcu_read_lock" in f.lower() for f in call_trace)
    if has_rcu_read_lock and has_sleep:
        potential_issues.append("rcu_read_lock 内调用了可能睡眠的函数")

    return {
        "locks_acquired": locks_acquired[:10],
        "locks_released": locks_released[:10],
        "lock_types": list(lock_types_found),
        "potential_issues": potential_issues,
    }


def generate_lock_context_for_llm(call_trace: List[str]) -> str:
    """生成用于 LLM 的锁分析上下文

    Args:
        call_trace: 调用栈

    Returns:
        锁分析上下文字符串
    """
    analysis = analyze_lock_usage(call_trace)

    lines = ["## Lock Usage Analysis", ""]

    if analysis["lock_types"]:
        lines.append("### Lock Types Detected")
        for lt in analysis["lock_types"]:
            info = LOCK_TYPES.get(lt, {})
            lines.append(f"- **{lt}**: {info.get('name', lt)} — {info.get('use_case', '')}")
        lines.append("")

    if analysis["locks_acquired"]:
        lines.append("### Lock Acquire Operations")
        for la in analysis["locks_acquired"][:5]:
            lines.append(f"- `{la['function']}()` in `{la['frame'][:80]}`")
        lines.append("")

    if analysis["potential_issues"]:
        lines.append("### ⚠️ Potential Lock Issues")
        for issue in analysis["potential_issues"]:
            lines.append(f"- **{issue}**")
        lines.append("")

    if not analysis["lock_types"] and not analysis["potential_issues"]:
        lines.append("*(No lock operations detected in call trace)*")

    return "\n".join(lines)


__all__ = [
    # 知识库
    "LOCK_TYPES",
    "LOCK_ORDERING_RULES",
    "DEADLOCK_PATTERNS",
    "LOCK_FIX_PATTERNS",
    # 查询接口
    "get_lock_type",
    "detect_lock_type_from_function",
    "get_lock_ordering_rules",
    "match_deadlock_pattern",
    "get_lock_fix_pattern",
    "analyze_lock_usage",
    "generate_lock_context_for_llm",
]
