"""Commit 分析模块 — 利用 PyDriller 结构化 file-level diff 做精确分析

核心优化:
- 使用 file_changes[].diff_parsed_added 精确匹配新增代码行 (不再手工解析 + 前缀)
- 利用 m.methods (PyDriller 提取的方法名) 做函数级匹配
- 利用 m.complexity 圈复杂度加权分数
"""

import re
from typing import List
from ..models import CommitInfo


# ─────────────────────────────────────────────────────────────
#  关键词典 (不变的核心领域知识)
# ─────────────────────────────────────────────────────────────

LOCK_KEYWORDS = [
    'spin_lock', 'spin_unlock', 'spin_lock_irqsave', 'spin_lock_irq',
    'mutex_lock', 'mutex_unlock', 'mutex_init',
    'rwlock', 'rwsem', 'semaphore',
    'mutex_lock_interruptible', 'mutex_lock_killable',
    'down_read', 'down_write', 'up_read', 'up_write',
    'lockdep', 'lock_acquire', 'lock_release',
]

REFCOUNT_KEYWORDS = [
    'refcount_inc', 'refcount_dec', 'refcount_add', 'refcount_set',
    'refcount_read', 'refcount_inc_not_zero',
    'kref_get', 'kref_put', 'kref_init',
    'atomic_inc', 'atomic_dec', 'atomic_add', 'atomic_set',
    'get_', 'put_',
]

REFCOUNT_FIX_PATTERNS = [
    r'refcount.*leak', r'ref.*leak',
    r'missing.*(?:get|put)', r'extra.*(?:get|put)',
    r'wrong.*refcount', r'inconsistent.*ref',
]

RCU_KEYWORDS = [
    'rcu_read_lock', 'rcu_read_unlock',
    'synchronize_rcu', 'synchronize_rcu_expedited',
    'call_rcu', 'call_rcu_sched', 'call_rcu_bh',
    'rcu_barrier', 'rcu_assign_pointer',
    'rcu_dereference', 'rcu_access_pointer',
    'rcu_swap_pointer', 'rcu_replace_pointer',
    'rcu_head', 'rcu_callback',
    'synchronize_srcu', 'srcu_read_lock', 'srcu_read_unlock',
]

RCU_FIX_PATTERNS = [
    r'rcu.*(?:bug|fix|issue|race|deadlock)',
    r'synchronize.*rcu',
]


# ─────────────────────────────────────────────────────────────
#  行级精确检测: 优先使用 diff_parsed_added (PyDriller 提供)
#  降级: 使用 diff_content 的正则匹配
# ─────────────────────────────────────────────────────────────

def _get_added_lines(commit: CommitInfo) -> List[str]:
    """收集所有新增的代码行 — 优先使用结构化数据"""
    lines = []

    # 方式1 (优): 从 file_changes 的 diff_parsed_added 直接获取
    if commit.file_changes:
        for fc in commit.file_changes:
            if fc.diff_parsed_added:
                lines.extend(fc.diff_parsed_added)
    if lines:
        return lines

    # 方式2 (降级): 从 raw diff_content 解析 + 开头的行
    if commit.diff_content:
        for line in commit.diff_content.split("\n"):
            if line.startswith('+') and not line.startswith('+++'):
                lines.append(line[1:])  # 去掉 + 前缀
    return lines


def _get_methods_from_files(commit: CommitInfo) -> List[str]:
    """从 file_changes 收集 PyDriller 提取的方法名"""
    methods = []
    if commit.file_changes:
        for fc in commit.file_changes:
            if fc.methods:
                methods.extend(fc.methods)
    return methods


# ─────────────────────────────────────────────────────────────
#  特征检测
# ─────────────────────────────────────────────────────────────

def has_lock_added(commit: CommitInfo) -> bool:
    """判断 commit 是否添加了锁相关代码

    优化: 从 diff_parsed_added 精确匹配新增行，不再依赖原始 diff 文本的 + 前缀识别。
    """
    added_lines = _get_added_lines(commit)
    if not added_lines:
        return False

    for line in added_lines:
        line_lower = line.lower()
        for kw in LOCK_KEYWORDS:
            if kw in line_lower:
                return True
    return False


def has_refcount_fix(commit: CommitInfo) -> bool:
    """判断 commit 是否修复了引用计数问题

    双层检测:
    1. 新增/删除行中出现 refcount/kref/atomic 关键字
    2. subject+body 中出现引用计数修复描述
    """
    full_text = f"{commit.subject} {commit.body}".lower()

    # 层1: 代码行关键字匹配
    added_lines = _get_added_lines(commit)
    for line in added_lines:
        line_lower = line.lower()
        for kw in REFCOUNT_KEYWORDS:
            if kw in line_lower:
                return True

    # 层2: commit message 修复描述
    for pattern in REFCOUNT_FIX_PATTERNS:
        if re.search(pattern, full_text):
            return True

    return False


def has_rcu_fix(commit: CommitInfo) -> bool:
    """判断 commit 是否修复了 RCU 相关问题"""
    added_lines = _get_added_lines(commit)
    full_text = f"{commit.subject} {commit.body}".lower()

    # 层1: 代码行 RCU API 匹配
    for line in added_lines:
        line_lower = line.lower()
        for kw in RCU_KEYWORDS:
            if kw in line_lower:
                return True

    # 层2: commit message 修复描述
    for pattern in RCU_FIX_PATTERNS:
        if re.search(pattern, full_text):
            return True

    return False


# ─────────────────────────────────────────────────────────────
#  分数计算 — 增加了复杂度加权
# ─────────────────────────────────────────────────────────────

def calculate_score(commit: CommitInfo) -> float:
    """计算 commit 的重要性分数

    优化: 利用 file_changes[].complexity 圈复杂度作为加权因子。
    高复杂度修复通常更关键 (逻辑更复杂，容易出现隐蔽漏洞)。
    """
    score = 0.0

    # 1. bug 类型基础分
    bug_type_scores = {
        'security': 10.0,
        'use_after_free': 9.0,
        'null_pointer': 8.0,
        'buffer_overflow': 9.0,
        'deadlock': 8.0,
        'race_condition': 8.0,
        'memory_leak': 7.0,
        'crash': 7.0,
        'regression': 6.0,
        'performance': 5.0,
    }
    if commit.bug_type in bug_type_scores:
        score += bug_type_scores[commit.bug_type]

    # 2. 特殊修复类型加分
    if commit.lock_added:
        score += 2.0
    if commit.refcount_fix:
        score += 3.0
    if commit.rcu_fix:
        score += 3.0

    # 3. 修改文件数量加分
    if commit.files_changed:
        score += min(len(commit.files_changed) * 0.5, 5.0)

    # 4. 代码变更量加分
    changes = commit.insertions + commit.deletions
    if changes > 0:
        score += min(changes / 100, 3.0)

    # 5. CVE 编号大幅加分
    if commit.fix_tags:
        for tag in commit.fix_tags:
            if 'CVE' in tag.upper():
                score += 10.0
                break

    # 6. 新增: 圈复杂度加权 (高复杂度修复 <- 更关键)
    if commit.file_changes:
        max_complexity = max((fc.complexity for fc in commit.file_changes), default=0)
        if max_complexity > 50:
            score += 2.0
        elif max_complexity > 20:
            score += 1.0

    # 7. 新增: merge commit 可能有特殊重要性
    if commit.is_merge:
        score += 0.5

    # 归一化
    score = min(score, 10.0)
    return round(score, 2)


def analyze_commit(commit: CommitInfo) -> CommitInfo:
    """完整分析 commit 的所有特征"""
    commit.lock_added = has_lock_added(commit)
    commit.refcount_fix = has_refcount_fix(commit)
    commit.rcu_fix = has_rcu_fix(commit)
    commit.score = calculate_score(commit)
    return commit
