"""知识库模块 — Domain Knowledge Layer

包含 Linux 内核领域的结构化知识，为根因分析、补丁检索和报告生成提供领域上下文。

整合了以下知识:
- bug_patterns: Bug 模式知识库 (UAF / deadlock / null pointer / race condition / buffer overflow 等)
- lock_rules: 锁规则知识库 (spinlock / mutex / rcu / rwsem 使用规则和死锁模式)
- subsystem_graph: 子系统关系图 (父子关系、耦合关系、调用关系)
"""

from .bug_patterns import (
    BUG_PATTERNS,
    get_bug_pattern,
    get_fix_patterns,
    get_search_keywords,
    get_detection_tools,
    list_bug_patterns,
    search_bug_by_symptom,
    generate_bug_context_for_llm,
)
from .lock_rules import (
    LOCK_TYPES,
    LOCK_ORDERING_RULES,
    DEADLOCK_PATTERNS,
    LOCK_FIX_PATTERNS,
    get_lock_type,
    detect_lock_type_from_function,
    get_lock_ordering_rules,
    match_deadlock_pattern,
    get_lock_fix_pattern,
    analyze_lock_usage,
    generate_lock_context_for_llm,
)
from .subsystem_graph import (
    SUBSYSTEMS,
    SUBSYSTEM_HIERARCHY,
    COUPLED_SUBSYSTEMS,
    CALL_RELATIONS,
    get_subsystem_info,
    get_children,
    get_parent,
    get_ancestors,
    get_related_subsystems,
    detect_subsystem_by_path,
    detect_subsystem_by_function,
    get_all_subsystems as list_all_subsystems,
    list_subsystems_by_bug_type,
    generate_subsystem_context_for_llm,
)

__all__ = [
    # Bug 模式
    "BUG_PATTERNS",
    "get_bug_pattern",
    "get_fix_patterns",
    "get_search_keywords",
    "get_detection_tools",
    "list_bug_patterns",
    "search_bug_by_symptom",
    "generate_bug_context_for_llm",
    # 锁规则
    "LOCK_TYPES",
    "LOCK_ORDERING_RULES",
    "DEADLOCK_PATTERNS",
    "LOCK_FIX_PATTERNS",
    "get_lock_type",
    "detect_lock_type_from_function",
    "get_lock_ordering_rules",
    "match_deadlock_pattern",
    "get_lock_fix_pattern",
    "analyze_lock_usage",
    "generate_lock_context_for_llm",
    # 子系统关系
    "SUBSYSTEMS",
    "SUBSYSTEM_HIERARCHY",
    "COUPLED_SUBSYSTEMS",
    "CALL_RELATIONS",
    "get_subsystem_info",
    "get_children",
    "get_parent",
    "get_ancestors",
    "get_related_subsystems",
    "detect_subsystem_by_path",
    "detect_subsystem_by_function",
    "list_all_subsystems",
    "list_subsystems_by_bug_type",
    "generate_subsystem_context_for_llm",
]
