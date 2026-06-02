"""Commit 分析模块

负责分析 commit 的高级特征：
- lock_added: 是否添加了锁
- refcount_fix: 是否修复了引用计数问题
- rcu_fix: 是否修复了 RCU 相关问题
- score: 计算 commit 的重要性分数
"""

import re
from ..models import CommitInfo


# 锁相关的关键字
LOCK_KEYWORDS = [
    'spin_lock', 'spin_unlock', 'spin_lock_irqsave', 'spin_lock_irq',
    'mutex_lock', 'mutex_unlock', 'mutex_init',
    'rwlock', 'rwsem', 'semaphore',
    'mutex_lock_interruptible', 'mutex_lock_killable',
    'down_read', 'down_write', 'up_read', 'up_write',
    'lockdep', 'lock_acquire', 'lock_release',
]


# 引用计数相关的关键字
REFCOUNT_KEYWORDS = [
    'refcount_inc', 'refcount_dec', 'refcount_add', 'refcount_set',
    'refcount_read', 'refcount_inc_not_zero',
    'kref_get', 'kref_put', 'kref_init',
    'atomic_inc', 'atomic_dec', 'atomic_add', 'atomic_set',
    'get_', 'put_',
    'refcnt', 'refcount', 'ref',
]


# RCU 相关的关键字
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


def has_lock_added(commit: CommitInfo) -> bool:
    """判断 commit 是否添加了锁相关代码"""
    if not commit.diff_content:
        return False
    
    content = commit.diff_content.lower()
    
    # 检查是否有新增的锁调用
    lines = commit.diff_content.split("\n")
    for line in lines:
        # 只检查新增行（以 + 开头）
        if line.startswith('+'):
            line_lower = line.lower()
            for keyword in LOCK_KEYWORDS:
                if keyword in line_lower:
                    return True
    
    return False


def has_refcount_fix(commit: CommitInfo) -> bool:
    """判断 commit 是否修复了引用计数问题"""
    full_text = f"{commit.subject} {commit.body} {commit.diff_content}".lower()
    
    # 检查关键字
    for keyword in REFCOUNT_KEYWORDS:
        if keyword in full_text:
            return True
    
    # 检查是否有引用计数相关的修复描述
    refcount_fix_patterns = [
        r'refcount.*leak',
        r'ref.*leak',
        r'missing.*get',
        r'missing.*put',
        r'extra.*get',
        r'extra.*put',
        r'wrong.*refcount',
        r'inconsistent.*ref',
    ]
    
    for pattern in refcount_fix_patterns:
        if re.search(pattern, full_text):
            return True
    
    return False


def has_rcu_fix(commit: CommitInfo) -> bool:
    """判断 commit 是否修复了 RCU 相关问题"""
    full_text = f"{commit.subject} {commit.body} {commit.diff_content}".lower()
    
    # 检查 RCU 关键字
    for keyword in RCU_KEYWORDS:
        if keyword in full_text:
            return True
    
    # 检查 RCU 相关的修复描述
    rcu_fix_patterns = [
        r'rcu.*bug',
        r'rcu.*fix',
        r'rcu.*issue',
        r'rcu.*race',
        r'rcu.*deadlock',
        r'synchronize.*rcu',
    ]
    
    for pattern in rcu_fix_patterns:
        if re.search(pattern, full_text):
            return True
    
    return False


def calculate_score(commit: CommitInfo) -> float:
    """计算 commit 的重要性分数"""
    score = 0.0
    
    # 根据 bug 类型加权
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
    
    # 根据特殊修复类型加分
    if commit.lock_added:
        score += 2.0
    if commit.refcount_fix:
        score += 3.0
    if commit.rcu_fix:
        score += 3.0
    
    # 根据修改文件数量加分
    if commit.files_changed:
        score += min(len(commit.files_changed) * 0.5, 5.0)
    
    # 根据代码变更量加分
    changes = commit.insertions + commit.deletions
    if changes > 0:
        score += min(changes / 100, 3.0)
    
    # 如果有 CVE 编号，大幅加分
    if commit.fix_tags:
        for tag in commit.fix_tags:
            if 'CVE' in tag:
                score += 10.0
                break
    
    # 归一化到 0-10 范围
    score = min(score, 10.0)
    
    return round(score, 2)


def analyze_commit(commit: CommitInfo) -> CommitInfo:
    """完整分析 commit 的所有特征"""
    commit.lock_added = has_lock_added(commit)
    commit.refcount_fix = has_refcount_fix(commit)
    commit.rcu_fix = has_rcu_fix(commit)
    commit.score = calculate_score(commit)
    
    return commit