"""Git 仓库操作模块 — 充分利用 PyDriller 的一次遍历 + 原生过滤

核心优化: 利用 PyDriller 的迭代器模式，一次遍历即完成全量数据提取，
不再需要"先收集 hash → 再逐个查询"的二次遍历。

PyDriller Repository 原生支持的过滤器 (直接在构造函数中传入):
- single: 单个 commit hash
- since / to: 日期范围过滤
- from_commit / to_commit: commit 范围
- filepath: 只处理修改了指定文件的 commit
- only_modifications_with_file_types: 只处理指定扩展名的文件
- only_no_merge: 排除 merge commit
- only_in_branch: 只处理某分支上的 commit
- order: 'reverse' 或 'date-order' 等
"""

import os
from typing import List, Optional, Callable, Generator, Any, Dict
from datetime import datetime
from pydriller import Repository, ModifiedFile
from ..models import CommitInfo, FileChangeInfo


# ─────────────────────────────────────────────────────────────
#  内部工具: PyDriller 对象 → 我们的数据模型
# ─────────────────────────────────────────────────────────────

def _extract_file_changes(modified_files: List[ModifiedFile]) -> List[FileChangeInfo]:
    """从 PyDriller ModifiedFile 列表提取结构化的 FileChangeInfo

    PyDriller 提供了远超 raw diff 的精确字段:
    - m.added_lines / m.deleted_lines: 该文件精确的新增/删除行数
    - m.nloc: 非注释非空代码行数
    - m.complexity: 圈复杂度
    - m.methods: 修改涉及的方法名列表
    - m.diff_parsed: {added: [...], deleted: [...]}  逐行解析
    - m.change_type: ADD / DELETE / MODIFY / RENAME
    """
    results = []
    for m in modified_files:
        diff_parsed_added = []
        diff_parsed_deleted = []
        if hasattr(m, 'diff_parsed') and m.diff_parsed:
            # PyDriller 返回的是 List[Tuple[int, str]]，提取内容部分
            added_tuples = m.diff_parsed.get('added', []) or []
            deleted_tuples = m.diff_parsed.get('deleted', []) or []
            diff_parsed_added = [line[1] for line in added_tuples]
            diff_parsed_deleted = [line[1] for line in deleted_tuples]

        results.append(FileChangeInfo(
            filename=m.filename or "",
            old_path=m.old_path or "",
            new_path=m.new_path or "",
            change_type=str(m.change_type.name) if hasattr(m.change_type, 'name') else "MODIFY",
            added_lines=m.added_lines or 0,
            deleted_lines=m.deleted_lines or 0,
            nloc=m.nloc or 0,
            complexity=m.complexity or 0,
            methods=[met.name for met in m.methods] if (hasattr(m, 'methods') and m.methods) else [],
            diff=m.diff or "",
            diff_parsed_added=diff_parsed_added,
            diff_parsed_deleted=diff_parsed_deleted,
        ))
    return results


def _commit_to_info(commit) -> CommitInfo:
    """PyDriller commit 对象 → CommitInfo (一次映射，零额外调用)"""
    file_changes = _extract_file_changes(commit.modified_files)

    return CommitInfo(
        # 基本信息
        commit_hash=commit.hash,
        author=commit.author.name or "",
        email=commit.author.email or "",
        date=commit.author_date.strftime("%Y-%m-%d %H:%M:%S") if commit.author_date else "",
        committer_date=commit.committer_date.strftime("%Y-%m-%d %H:%M:%S") if commit.committer_date else "",
        subject=commit.msg.split('\n')[0] if commit.msg else "",
        body=commit.msg or "",
        files_changed=[fc.filename for fc in file_changes if fc.filename],
        insertions=commit.insertions or 0,
        deletions=commit.deletions or 0,
        diff_content="\n".join([fc.diff for fc in file_changes if fc.diff]),
        parent_hashes=commit.parents or [],

        # PyDriller 原生结构信息
        # NOTE: commit.in_main_branch / commit.branches 底层调用 git branch --contains，
        # 在 Linux kernel 这种超大仓库极其缓慢 (每个 commit 几秒到几十秒) 且结果未被下游使用，
        # 直接跳过以避免性能瓶颈。
        is_merge=commit.merge,
        in_main_branch=False,
        branches=[],
        tags=commit.tags if hasattr(commit, 'tags') else [],

        # 文件级结构化变更
        file_changes=file_changes,
    )


# ─────────────────────────────────────────────────────────────
#  核心API: 流式遍历 (一次遍历，O(1) 内存)
# ─────────────────────────────────────────────────────────────

def traverse_commits(
    repo_path: str = ".",
    *,
    since: Optional[datetime] = None,
    to: Optional[datetime] = None,
    filepath: Optional[str] = None,
    only_no_merge: bool = True,
    only_in_branch: Optional[str] = None,
    order: str = 'reverse',
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Generator[CommitInfo, None, None]:
    """流式遍历 commit — PyDriller 迭代器原生流式，百万级仓库不会 OOM

    所有过滤参数直接传递给 PyDriller 的 Repository 构造函数，
    在迭代器内部完成过滤，无需应用层二次筛选。

    Args:
        repo_path: Git 仓库路径
        since: 起始日期 (只包含此日期之后的 commit)
        to: 结束日期 (只包含此日期之前的 commit)
        filepath: 只返回修改了此文件的 commit
        only_no_merge: 排除 merge commit (默认 True)
        only_in_branch: 只在指定分支上搜索
        order: 遍历顺序 ('reverse' = 从新到旧)
        limit: 最多返回 N 个 commit (None = 不限制)
        progress_callback: 进度回调 (current_index, total_estimated)

    Yields:
        CommitInfo 对象 (每个 commit 包含完整的 file_changes)
    """
    repo_kwargs: Dict[str, Any] = {
        "path_to_repo": repo_path,
        "order": order,
    }
    # PyDriller 原生过滤参数 — 只在非 None 时传入
    if since:
        repo_kwargs["since"] = since
    if to:
        repo_kwargs["to"] = to
    if filepath:
        repo_kwargs["filepath"] = filepath
    if only_no_merge:
        repo_kwargs["only_no_merge"] = True
    if only_in_branch:
        repo_kwargs["only_in_branch"] = only_in_branch

    count = 0
    # 估算总数 (用于进度显示)
    estimated = _estimate_commit_count(repo_path, since, to, filepath, only_no_merge)

    try:
        # 使用 Repository 初始化，避免 Pylance 误判 Dict 类型
        repo = Repository(**repo_kwargs)
        for commit in repo.traverse_commits():
            yield _commit_to_info(commit)
            count += 1
            if limit and count >= limit:
                break
            if progress_callback:
                progress_callback(count, estimated)
    except Exception:
        return


def _estimate_commit_count(
    repo_path: str,
    since: Optional[datetime],
    to: Optional[datetime],
    filepath: Optional[str],
    only_no_merge: bool,
) -> int:
    """估算 commit 总数 (不精确但足够用于进度条)"""
    try:
        cmd = ["git", "-C", repo_path, "rev-list", "--count", "HEAD"]
        if since:
            cmd.append(f"--since={since.isoformat()}")
        if to:
            cmd.append(f"--until={to.isoformat()}")
        if only_no_merge:
            cmd.append("--no-merges")
        if filepath:
            cmd.append("--")
            cmd.append(filepath)
        import subprocess
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return int(result.stdout.strip() or 0)
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────
#  便捷API: 批量收集
# ─────────────────────────────────────────────────────────────

def collect_commits_batch(
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
    """批量收集 commit — 内部调用 traverse_commits，一次遍历搞定

    替代旧版的两步操作: get_commit_history() + 逐个 get_commit_info()
    """
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
        results.append(commit)
    return results


def get_commit_info(commit_hash: str, repo_path: str = ".") -> Optional[CommitInfo]:
    """获取单个 commit 的详细信息 — 使用 PyDriller single 参数

    这是 collect_commit() 的单点查询入口。对于批量场景请使用 traverse_commits()。
    """
    try:
        for commit in Repository(repo_path, single=commit_hash).traverse_commits():
            return _commit_to_info(commit)
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────
#  向下兼容的简化接口 (保持旧API签名不变)
# ─────────────────────────────────────────────────────────────

def get_commit_history(repo_path: str = ".", limit: int = 100) -> List[str]:
    """获取 commit hash 列表 (保留旧接口用于兼容)"""
    return [
        c.commit_hash
        for c in traverse_commits(repo_path=repo_path, limit=limit, only_no_merge=False)
    ]


def get_commits_since_date(date: datetime, repo_path: str = ".") -> List[str]:
    """获取指定日期之后的 commit hash 列表 (保留旧接口)"""
    return [
        c.commit_hash
        for c in traverse_commits(repo_path=repo_path, since=date, only_no_merge=False)
    ]


def get_commits_by_author(author: str, repo_path: str = ".") -> List[str]:
    """获取指定作者的 commit hash 列表 (保留旧接口)"""
    author_lower = author.lower()
    return [
        c.commit_hash
        for c in traverse_commits(repo_path=repo_path, only_no_merge=False)
        if author_lower in c.author.lower() or author_lower in c.email.lower()
    ]


def is_git_repo(path: str) -> bool:
    """检查路径是否为 git 仓库"""
    return os.path.isdir(os.path.join(path, ".git"))
