"""Commit 信息收集器模块

提供完整的 commit 信息收集和分析功能，整合了以下子模块：
- git: Git 仓库操作
- parser: Commit 消息解析
- subsystem: 子系统识别
- bugtype: Bug 类型识别
- analysis: 高级特征分析
"""

from typing import List, Optional
from .models import CommitInfo, QueryResult

from .git import (
    get_commit_history,
    get_commit_info,
    get_commits_since_date,
    get_commits_by_author,
    is_git_repo,
)

from .parser import (
    extract_keywords,
    extract_fix_tags,
    extract_functions,
    parse_commit_message,
    is_fix_commit,
)

from .subsystem import (
    detect_subsystem,
    get_subsystem_hierarchy,
    get_all_subsystems,
)

from .bugtype import (
    detect_bug_type,
    detect_all_bug_types,
    get_bug_type_description,
    get_all_bug_types,
)

from .analysis import (
    has_lock_added,
    has_refcount_fix,
    has_rcu_fix,
    calculate_score,
    analyze_commit,
)


def collect_commit(commit_hash: str, repo_path: str = ".") -> Optional[CommitInfo]:
    """收集单个 commit 的完整信息"""
    if not is_git_repo(repo_path):
        return None
    
    # 获取基本信息
    commit = get_commit_info(commit_hash, repo_path)
    if not commit.commit_hash:
        return None
    
    # 解析 commit 消息
    commit = parse_commit_message(commit)
    
    # 识别子系统
    commit.subsystem = detect_subsystem(commit)
    
    # 识别 bug 类型
    commit.bug_type = detect_bug_type(commit)
    
    # 分析高级特征
    commit = analyze_commit(commit)
    
    return commit


def collect_commits(repo_path: str = ".", limit: int = 100) -> List[CommitInfo]:
    """收集多个 commit 的完整信息"""
    commits = []
    
    if not is_git_repo(repo_path):
        return commits
    
    commit_hashes = get_commit_history(repo_path, limit)
    
    for commit_hash in commit_hashes:
        if commit_hash:
            commit = collect_commit(commit_hash, repo_path)
            if commit:
                commits.append(commit)
    
    return commits


def collect_commits_since_date(date, repo_path: str = ".") -> List[CommitInfo]:
    """收集指定日期之后的 commit"""
    commits = []
    
    if not is_git_repo(repo_path):
        return commits
    
    commit_hashes = get_commits_since_date(date, repo_path)
    
    for commit_hash in commit_hashes:
        if commit_hash:
            commit = collect_commit(commit_hash, repo_path)
            if commit:
                commits.append(commit)
    
    return commits


def collect_commits_by_author(author: str, repo_path: str = ".") -> List[CommitInfo]:
    """收集指定作者的 commit"""
    commits = []
    
    if not is_git_repo(repo_path):
        return commits
    
    commit_hashes = get_commits_by_author(author, repo_path)
    
    for commit_hash in commit_hashes:
        if commit_hash:
            commit = collect_commit(commit_hash, repo_path)
            if commit:
                commits.append(commit)
    
    return commits


__all__ = [
    # 数据类型
    'CommitInfo',
    
    # Git 操作
    'get_commit_history',
    'get_commit_info',
    'get_commits_since_date',
    'get_commits_by_author',
    'is_git_repo',
    
    # 解析功能
    'extract_keywords',
    'extract_fix_tags',
    'extract_functions',
    'parse_commit_message',
    'is_fix_commit',
    
    # 子系统识别
    'detect_subsystem',
    'get_subsystem_hierarchy',
    'get_all_subsystems',
    
    # Bug 类型识别
    'detect_bug_type',
    'detect_all_bug_types',
    'get_bug_type_description',
    'get_all_bug_types',
    
    # 分析功能
    'has_lock_added',
    'has_refcount_fix',
    'has_rcu_fix',
    'calculate_score',
    'analyze_commit',
    
    # 综合功能
    'collect_commit',
    'collect_commits',
    'collect_commits_since_date',
    'collect_commits_by_author',
]