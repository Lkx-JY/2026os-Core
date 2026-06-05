"""Commit 信息收集器模块 — PyDriller 深度集成版

提供完整的 commit 信息收集和分析功能。支持:
- 流式收集 (traverse_commits 一次遍历、O(1)内存)
- 批量收集 (collect_commits)
- 单点查询 (collect_commit)
- PyDriller 原生过滤 (按日期/作者/文件/分支)

核心优化: collect_commits 不再做"先收集 hash → 再逐个查询"的二次遍历，
而是通过 traverse_commits 一次性完成全量数据提取。
"""

from typing import List, Optional, Callable, Generator, Iterator
from datetime import datetime

from .models import CommitInfo, QueryResult, FileChangeInfo
from .git import traverse_commits, collect_commits_batch
from .git import get_commit_info, is_git_repo
from .git import get_commit_history, get_commits_since_date, get_commits_by_author
from .parser import parse_commit_message, extract_keywords, extract_fix_tags, extract_functions, parse_subject, is_fix_commit
from .subsystem import detect_subsystem, get_subsystem_hierarchy, get_all_subsystems
from .bugtype import detect_bug_type, detect_all_bug_types, get_bug_type_description, get_all_bug_types
from .analysis import has_lock_added, has_refcount_fix, has_rcu_fix, calculate_score, analyze_commit


# ─────────────────────────────────────────────────────────────
#  单 commit 收集 (保持不变)
# ─────────────────────────────────────────────────────────────

def collect_commit(commit_hash: str, repo_path: str = ".") -> Optional[CommitInfo]:
    """收集单个 commit 的完整信息

    流程: git提取 → parser解析 → subsystem识别 → bugtype识别 → analysis分析
    """
    if not is_git_repo(repo_path):
        return None

    commit = get_commit_info(commit_hash, repo_path)
    if not commit or not commit.commit_hash:
        return None

    return _analyze_full(commit)


# ─────────────────────────────────────────────────────────────
#  批量收集 — 一次遍历 (替代旧的二次遍历)
# ─────────────────────────────────────────────────────────────

def collect_commits(
    repo_path: str = ".",
    limit: int = 100,
    *,
    since: Optional[datetime] = None,
    to: Optional[datetime] = None,
    filepath: Optional[str] = None,
    only_no_merge: bool = True,
    only_in_branch: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> List[CommitInfo]:
    """收集多个 commit 的完整信息 — 一次遍历

    优化前 (两步):
    1. get_commit_history() → [hash1, hash2, ...]  # 遍历一次
    2. for hash in hashes: get_commit_info(hash)     # 再遍历 N 次
    总计: 1 + N 次 PyDriller Repository 实例化

    优化后 (一步):
    1. traverse_commits(since, to, filepath, ...)   # 遍历一次
    → 每个 commit 直接在遍历中完成全量提取
    总计: 1 次 PyDriller Repository 实例化

    PyDriller 的迭代器原生流式处理，百万级 commit 也不会 OOM。
    """
    if not is_git_repo(repo_path):
        return []

    results = []
    for commit in traverse_commits(
        repo_path=repo_path,
        since=since,
        to=to,
        filepath=filepath,
        only_no_merge=only_no_merge,
        only_in_branch=only_in_branch,
        order='reverse',
        limit=limit,
        progress_callback=progress_callback,
    ):
        _analyze_full(commit)
        results.append(commit)

    return results


def collect_commits_stream(
    repo_path: str = ".",
    limit: Optional[int] = None,
    *,
    since: Optional[datetime] = None,
    to: Optional[datetime] = None,
    filepath: Optional[str] = None,
    only_no_merge: bool = True,
    only_in_branch: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Generator[CommitInfo, None, None]:
    """流式收集 commit — 生成器模式，一条一条产出

    适合场景:
    - 逐条入库 (写入向量库/SQLite)
    - 流式分析 (不需要等全部收集完)
    - 超大仓库 (百万级 commit，避免内存问题)

    Example:
        >>> for commit in collect_commits_stream(repo, limit=10000):
        ...     indexer.index_one(commit)
    """
    if not is_git_repo(repo_path):
        return

    yield from (
        _analyze_full(c)
        for c in traverse_commits(
            repo_path=repo_path,
            since=since, to=to,
            filepath=filepath,
            only_no_merge=only_no_merge,
            only_in_branch=only_in_branch,
            order='reverse',
            limit=limit,
            progress_callback=progress_callback,
        )
    )


# ─────────────────────────────────────────────────────────────
#  按日期/作者收集 (向下兼容)
# ─────────────────────────────────────────────────────────────

def collect_commits_since_date(
    date: datetime, repo_path: str = "."
) -> List[CommitInfo]:
    """收集指定日期之后的 commit — 直接使用 since 参数，无需二次过滤"""
    return collect_commits(repo_path=repo_path, since=date, only_no_merge=False)


def collect_commits_by_author(
    author: str, repo_path: str = "."
) -> List[CommitInfo]:
    """收集指定作者的 commit — PyDriller 层面暂无原生 author 过滤，遍历后筛选"""
    if not is_git_repo(repo_path):
        return []

    results = []
    author_lower = author.lower()
    for commit in traverse_commits(repo_path=repo_path, only_no_merge=False):
        if author_lower in commit.author.lower() or author_lower in commit.email.lower():
            _analyze_full(commit)
            results.append(commit)
    return results


# ─────────────────────────────────────────────────────────────
#  内部: 完整的分析流水线 (collector → parser → subsystem → bugtype → analysis)
# ─────────────────────────────────────────────────────────────

def _analyze_full(commit: CommitInfo) -> CommitInfo:
    """对一个 CommitInfo 执行全部分析流程"""
    commit = parse_commit_message(commit)
    commit.subsystem = detect_subsystem(commit)
    commit.bug_type = detect_bug_type(commit)
    commit = analyze_commit(commit)
    return commit


# ─────────────────────────────────────────────────────────────
#  导出
# ─────────────────────────────────────────────────────────────

__all__ = [
    # 数据类型
    'CommitInfo', 'QueryResult', 'FileChangeInfo',

    # Git 操作
    'traverse_commits', 'collect_commits_batch',
    'get_commit_info', 'is_git_repo',
    'get_commit_history', 'get_commits_since_date', 'get_commits_by_author',

    # 解析功能
    'extract_keywords', 'extract_fix_tags', 'extract_functions',
    'parse_commit_message', 'is_fix_commit', 'parse_subject',

    # 子系统识别
    'detect_subsystem', 'get_subsystem_hierarchy', 'get_all_subsystems',

    # Bug 类型识别
    'detect_bug_type', 'detect_all_bug_types',
    'get_bug_type_description', 'get_all_bug_types',

    # 分析功能
    'has_lock_added', 'has_refcount_fix', 'has_rcu_fix',
    'calculate_score', 'analyze_commit',

    # 综合功能
    'collect_commit', 'collect_commits', 'collect_commits_stream',
    'collect_commits_since_date', 'collect_commits_by_author',
]
