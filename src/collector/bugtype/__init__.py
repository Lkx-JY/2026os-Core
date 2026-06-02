"""Bug 类型识别模块

负责根据 commit 消息和 diff 内容识别 bug 类型。
"""

import re
from typing import List, Dict
from ..models import CommitInfo


# Bug 类型定义
BUG_TYPES = [
    'use_after_free',
    'null_pointer',
    'buffer_overflow',
    'memory_leak',
    'deadlock',
    'race_condition',
    'integer_overflow',
    'out_of_bound',
    'double_free',
    'use_before_init',
    'uninitialized',
    'memory_corruption',
    'concurrency',
    'hang',
    'crash',
    'regression',
    'security',
    'performance',
    'resource_leak',
    'logic_error',
    'configuration',
]


# Bug 类型关键字映射
BUG_TYPE_KEYWORDS: Dict[str, List[str]] = {
    'use_after_free': [
        'use after free', 'use-after-free', 'use_after_free',
        'freed pointer', 'dangling pointer', 'use after freed'
    ],
    'null_pointer': [
        'null pointer', 'null ptr', 'dereference null',
        'null dereference', 'null ptr deref', 'npe'
    ],
    'buffer_overflow': [
        'buffer overflow', 'buffer overrun', 'stack overflow',
        'heap overflow', 'out of bounds write', 'overwrite'
    ],
    'memory_leak': [
        'memory leak', 'leak', 'unfreed', 'not freed',
        'missing free', 'resource leak'
    ],
    'deadlock': [
        'deadlock', 'lock order', 'circular wait',
        'mutex deadlock', 'spinlock deadlock'
    ],
    'race_condition': [
        'race condition', 'data race', 'concurrent access',
        'race', 'thread safety', 'atomicity'
    ],
    'integer_overflow': [
        'integer overflow', 'int overflow', 'overflow',
        'signed overflow', 'unsigned overflow'
    ],
    'out_of_bound': [
        'out of bound', 'out-of-bounds', 'index out of range',
        'array index', 'buffer overread', 'read beyond'
    ],
    'double_free': [
        'double free', 'double-free', 'free twice',
        'double dealloc', 'multiple free'
    ],
    'use_before_init': [
        'use before init', 'use-before-init', 'uninitialized',
        'undefined value', 'garbage value'
    ],
    'uninitialized': [
        'uninitialized', 'not initialized', 'init missed',
        'zero init', 'missing initialization'
    ],
    'memory_corruption': [
        'memory corruption', 'corrupt memory', 'memory damage',
        'corrupted data', 'memory overwrite'
    ],
    'concurrency': [
        'concurrency', 'thread', 'parallel', 'mutex',
        'spinlock', 'atomic', 'synchronization'
    ],
    'hang': [
        'hang', 'hung', 'stall', 'freeze', 'unresponsive'
    ],
    'crash': [
        'crash', 'panic', 'oops', 'segfault',
        'segmentation fault', 'abort'
    ],
    'regression': [
        'regression', 'broke', 'introduced', 'revert'
    ],
    'security': [
        'security', 'cve', 'exploit', 'vulnerability',
        'privilege', 'escalation', 'attack'
    ],
    'performance': [
        'performance', 'slow', 'latency', 'throughput',
        'optimization', 'speed up', 'bottleneck'
    ],
    'resource_leak': [
        'resource leak', 'fd leak', 'file descriptor leak',
        'socket leak', 'handle leak'
    ],
    'logic_error': [
        'logic error', 'wrong logic', 'incorrect',
        'bug', 'mistake', 'error'
    ],
    'configuration': [
        'config', 'configuration', 'setting', 'option'
    ],
}


def detect_bug_type(commit: CommitInfo) -> str:
    """识别 commit 的 bug 类型"""
    full_text = f"{commit.subject} {commit.body}".lower()
    
    # 根据关键字匹配 bug 类型
    for bug_type, keywords in BUG_TYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in full_text:
                return bug_type
    
    return "unknown"


def detect_all_bug_types(commit: CommitInfo) -> List[str]:
    """识别所有可能的 bug 类型"""
    bug_types = []
    full_text = f"{commit.subject} {commit.body}".lower()
    
    for bug_type, keywords in BUG_TYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in full_text:
                bug_types.append(bug_type)
                break
    
    return bug_types if bug_types else ["unknown"]


def get_bug_type_description(bug_type: str) -> str:
    """获取 bug 类型的描述"""
    descriptions = {
        'use_after_free': '使用已释放的内存',
        'null_pointer': '空指针解引用',
        'buffer_overflow': '缓冲区溢出',
        'memory_leak': '内存泄漏',
        'deadlock': '死锁',
        'race_condition': '竞态条件',
        'integer_overflow': '整数溢出',
        'out_of_bound': '越界访问',
        'double_free': '重复释放',
        'use_before_init': '初始化前使用',
        'uninitialized': '未初始化变量',
        'memory_corruption': '内存损坏',
        'concurrency': '并发问题',
        'hang': '系统挂起',
        'crash': '崩溃',
        'regression': '回归问题',
        'security': '安全漏洞',
        'performance': '性能问题',
        'resource_leak': '资源泄漏',
        'logic_error': '逻辑错误',
        'configuration': '配置问题',
        'unknown': '未知类型',
    }
    return descriptions.get(bug_type, '未知类型')


def get_all_bug_types() -> List[str]:
    """获取所有已知 bug 类型"""
    return BUG_TYPES.copy()