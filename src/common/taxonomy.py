"""统一 Bug 类型分类体系 — 跨模块标准化

解决 collector/bugtype(21种)、bug_patterns(10种)、rootcause(11种)、
dmesg(~14种) 之间 bug_type 命名不一致的问题。

设计原则:
- BugType 枚举为权威来源 (Single Source of Truth)
- BUG_TYPE_ALIASES 提供旧名→标准名的映射
- normalize_bug_type() 将任意输入标准化为 BugType
"""

from enum import Enum


class BugType(str, Enum):
    """内核 Bug 类型标准枚举 — 全项目统一使用"""
    # 内存错误
    NULL_POINTER = "null_pointer"
    USE_AFTER_FREE = "use_after_free"
    DOUBLE_FREE = "double_free"
    BUFFER_OVERFLOW = "buffer_overflow"
    OUT_OF_BOUND = "out_of_bound"
    MEMORY_CORRUPTION = "memory_corruption"
    MEMORY_LEAK = "memory_leak"
    USE_BEFORE_INIT = "use_before_init"
    UNINITIALIZED = "uninitialized"

    # 并发错误
    DEADLOCK = "deadlock"
    RACE_CONDITION = "race_condition"

    # 系统挂起
    HANG = "hang"
    RCU_STALL = "rcu_stall"
    SOFT_LOCKUP = "soft_lockup"

    # 资源
    OOM = "oom"
    RESOURCE_LEAK = "resource_leak"

    # 安全
    SECURITY = "security"

    # 泛型
    CRASH = "crash"
    REGRESSION = "regression"
    PERFORMANCE = "performance"
    LOGIC_ERROR = "logic_error"
    CONFIGURATION = "configuration"
    INTEGER_OVERFLOW = "integer_overflow"
    STACK_OVERFLOW = "stack_overflow"
    UNKNOWN = "unknown"


# 别名映射: 任意历史/非标准名称 → 标准 BugType
BUG_TYPE_ALIASES: dict[str, BugType] = {
    # 简写
    "uaf": BugType.USE_AFTER_FREE,
    "oob": BugType.OUT_OF_BOUND,
    "npd": BugType.NULL_POINTER,

    # 不同命名风格
    "null_pointer_dereference": BugType.NULL_POINTER,
    "null_pointer_deref": BugType.NULL_POINTER,
    "null_ptr": BugType.NULL_POINTER,
    "use-after-free": BugType.USE_AFTER_FREE,
    "use after free": BugType.USE_AFTER_FREE,
    "double-free": BugType.DOUBLE_FREE,
    "double free": BugType.DOUBLE_FREE,
    "use_before_initialization": BugType.USE_BEFORE_INIT,
    "buffer_overflow": BugType.BUFFER_OVERFLOW,
    "buffer overrun": BugType.BUFFER_OVERFLOW,
    "out-of-bounds": BugType.OUT_OF_BOUND,
    "out of bounds": BugType.OUT_OF_BOUND,
    "memory_leak": BugType.MEMORY_LEAK,
    "memory-corruption": BugType.MEMORY_CORRUPTION,
    "memory corruption": BugType.MEMORY_CORRUPTION,
    "list_corruption": BugType.MEMORY_CORRUPTION,
    "race": BugType.RACE_CONDITION,
    "race-condition": BugType.RACE_CONDITION,
    "data race": BugType.RACE_CONDITION,
    "data_race": BugType.RACE_CONDITION,
    "concurrency": BugType.RACE_CONDITION,
    "rcu-stall": BugType.RCU_STALL,
    "rcu stall": BugType.RCU_STALL,
    "rcu_sched_stall": BugType.RCU_STALL,
    "soft-lockup": BugType.SOFT_LOCKUP,
    "softlockup": BugType.SOFT_LOCKUP,
    "hardlockup": BugType.HANG,
    "hard_lockup": BugType.HANG,
    "hungtask": BugType.HANG,
    "hung_task": BugType.HANG,
    "out-of-memory": BugType.OOM,
    "out of memory": BugType.OOM,
    "resource-leak": BugType.RESOURCE_LEAK,
    "resource leak": BugType.RESOURCE_LEAK,
    "stack-overflow": BugType.STACK_OVERFLOW,
    "stack overflow": BugType.STACK_OVERFLOW,
    "integer-overflow": BugType.INTEGER_OVERFLOW,
    "integer overflow": BugType.INTEGER_OVERFLOW,

    # 泛型 → 最可能的类型
    "kernel_panic": BugType.CRASH,
    "kernel oops": BugType.CRASH,
    "general protection": BugType.CRASH,
    "general protection fault": BugType.CRASH,
    "gpf": BugType.CRASH,
    "machine check": BugType.CRASH,
    "mce": BugType.CRASH,
    "security vulnerability": BugType.SECURITY,
    "cve": BugType.SECURITY,
    "regression": BugType.REGRESSION,
    "performance regression": BugType.PERFORMANCE,
    "logic error": BugType.LOGIC_ERROR,
    "configuration error": BugType.CONFIGURATION,
}


def normalize_bug_type(raw: str) -> BugType:
    """将任意 Bug 类型名称标准化为 BugType 枚举

    处理步骤:
    1. 直接匹配 BugType 枚举值
    2. 通过 BUG_TYPE_ALIASES 映射
    3. 模糊匹配 (去连字符/下划线/空格后比较)
    4. 返回 UNKNOWN

    Args:
        raw: 原始 Bug 类型字符串 (如 "uaf", "use-after-free", "Use After Free")

    Returns:
        标准化的 BugType 枚举值

    Example:
        >>> normalize_bug_type("uaf")
        <BugType.USE_AFTER_FREE: 'use_after_free'>
        >>> normalize_bug_type("NULL pointer dereference")
        <BugType.NULL_POINTER: 'null_pointer'>
    """
    if not raw or not raw.strip():
        return BugType.UNKNOWN

    key = raw.strip()

    # 1. 直接匹配 BugType 值
    for bt in BugType:
        if bt.value == key:
            return bt

    # 2. 通过别名映射
    key_lower = key.lower()
    if key_lower in BUG_TYPE_ALIASES:
        return BUG_TYPE_ALIASES[key_lower]

    # 3. 标准化后匹配 (去连字符/下划线/空格)
    normalized = key_lower.replace("-", "_").replace(" ", "_")
    if normalized in BUG_TYPE_ALIASES:
        return BUG_TYPE_ALIASES[normalized]

    # 4. 直接匹配枚举值 (用标准化后的key)
    for bt in BugType:
        if bt.value == normalized:
            return bt

    # 5. 模糊匹配: 包含关系
    for bt in BugType:
        if bt.value in normalized or normalized in bt.value:
            return bt

    return BugType.UNKNOWN


def get_bug_type_category(bt: BugType) -> str:
    """获取 BugType 的分类"""
    memory_types = {
        BugType.NULL_POINTER, BugType.USE_AFTER_FREE, BugType.DOUBLE_FREE,
        BugType.BUFFER_OVERFLOW, BugType.OUT_OF_BOUND, BugType.MEMORY_CORRUPTION,
        BugType.MEMORY_LEAK, BugType.USE_BEFORE_INIT, BugType.UNINITIALIZED,
        BugType.STACK_OVERFLOW, BugType.INTEGER_OVERFLOW,
    }
    concurrency_types = {BugType.DEADLOCK, BugType.RACE_CONDITION}
    hang_types = {BugType.HANG, BugType.RCU_STALL, BugType.SOFT_LOCKUP}
    resource_types = {BugType.OOM, BugType.RESOURCE_LEAK}

    if bt in memory_types:
        return "memory"
    if bt in concurrency_types:
        return "concurrency"
    if bt in hang_types:
        return "hang"
    if bt in resource_types:
        return "resource"
    if bt == BugType.SECURITY:
        return "security"
    return "other"


__all__ = [
    "BugType",
    "BUG_TYPE_ALIASES",
    "normalize_bug_type",
    "get_bug_type_category",
]
