"""Commit 信息收集器模块

提供完整的 commit 信息收集和分析功能，整合了以下子模块：
- git: Git 仓库操作
- parser: Commit 消息解析
- subsystem: 子系统识别
- bugtype: Bug 类型识别
- analysis: 高级特征分析
- ★ Root Cause 分析: 对 Commit 也执行与在线侧对称的根因抽象分析
"""

from typing import List, Optional, Dict, Any
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


def analyze_commit_root_cause(commit: CommitInfo) -> "RootCauseResult":
    """对 Commit 执行与在线侧对称的根因抽象分析

    通过 RootCauseAnalyzer (28条规则 + 4层分层分析) 生成 RootCauseResult，
    用于构造与在线宕机查询端结构对称的 embedding 文本。

    这是连接"离线 Commit 语义理解"与"在线宕机检索"的关键桥梁，
    确保离线侧补丁文档和在线侧宕机查询共享相同的语义分析维度。

    Args:
        commit: 已完成基本标注的 CommitInfo (subsystem/bug_type/lock_added 等已填充)

    Returns:
        RootCauseResult 对象，包含:
        - root_cause: 根因诊断结论
        - retrieval_query: ★ 与在线侧结构对称的 embedding 查询文本
        - causal_chain: 因果推理链
        - score: 置信度评分
        - suggested_keywords: 建议搜索关键词

    Example:
        >>> from src.collector import collect_commit, analyze_commit_root_cause
        >>> commit = collect_commit("abc123", "/path/to/linux")
        >>> result = analyze_commit_root_cause(commit)
        >>> print(result.root_cause)       # "Memory Corruption (List)"
        >>> print(result.retrieval_query)  # 6层语义融合的查询文本
    """
    from ..indexer.pipeline import _commit_to_crash_feature, _enhance_fix_hints_with_diff
    from ..analyzer.rootcause import get_analyzer, build_retrieval_query, analyze_call_trace_structure

    # Step 1: CommitInfo → CrashFeature
    feature = _commit_to_crash_feature(commit)

    # Step 2: RootCauseAnalyzer 分析 (28规则+4层分层推断)
    analyzer = get_analyzer()
    result = analyzer.analyze(feature)

    # Step 3: 用 commit diff 分析结果增强 fix_hints
    analyzer_fix_hints = result.extra_info.get("fix_hints", {})
    enhanced_fix_hints = _enhance_fix_hints_with_diff(commit, analyzer_fix_hints)

    # Step 4: 重新构造 retrieval_query (使增强后的 fix_hints 生效)
    trace_analysis = result.extra_info.get("trace_analysis", {})
    result.retrieval_query = build_retrieval_query(
        feature=feature,
        root_cause=result.root_cause,
        bug_type=result.bug_type,
        causal_chain=result.causal_chain,
        fix_hints=enhanced_fix_hints,
        trace_analysis=trace_analysis,
    )
    result.extra_info["fix_hints"] = enhanced_fix_hints

    return result


def collect_commit(
    commit_hash: str,
    repo_path: str = ".",
    use_root_cause: bool = False,
) -> Optional[CommitInfo]:
    """收集单个 commit 的完整信息

    Args:
        commit_hash: 提交哈希值
        repo_path: Git 仓库路径
        use_root_cause: 是否在采集阶段执行 Root Cause 对称分析 (默认 False,
            因为 root cause 分析也可在后续索引阶段由 indexer pipeline 统一执行)

    Returns:
        CommitInfo 对象，如果 use_root_cause=True 则在 extra_info 中包含:
        - root_cause_result: RootCauseResult 的 to_dict() 输出
        - root_cause: 根因诊断结论
        - root_cause_score: 置信度评分
        - root_cause_query: retrieval_query 文本
    """
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

    # ★ 可选: Root Cause 对称分析
    if use_root_cause:
        try:
            rc_result = analyze_commit_root_cause(commit)
            commit.extra_info = getattr(commit, "extra_info", {}) or {}
            commit.extra_info.update({
                "root_cause_result": rc_result.to_dict(),
                "root_cause": rc_result.root_cause,
                "root_cause_score": rc_result.score,
                "root_cause_query": rc_result.retrieval_query,
            })
        except Exception:
            # 根因分析不应阻塞基础采集流程
            pass

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
    'QueryResult',

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

    # ★ Root Cause 对称分析 (新增)
    'analyze_commit_root_cause',

    # 综合功能
    'collect_commit',
    'collect_commits',
    'collect_commits_since_date',
    'collect_commits_by_author',
]