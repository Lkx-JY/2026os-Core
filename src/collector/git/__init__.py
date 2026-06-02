"""Git 仓库操作模块

负责从 Git 仓库读取 commit 信息，包括：
- 遍历 commit 历史
- 获取 commit 的基本信息（hash、author、date、subject、body）
- 获取修改的文件列表和 diff 内容
"""

import os
from typing import List
from datetime import datetime
from pydriller import Repository
from ..models import CommitInfo


def get_commit_history(repo_path: str = ".", limit: int = 100) -> List[str]:
    """获取 commit hash 列表"""
    hashes = []
    try:
        for commit in Repository(repo_path, order='reverse').traverse_commits():
            hashes.append(commit.hash)
            if len(hashes) >= limit:
                break
    except Exception:
        pass
    return hashes


def get_commit_info(commit_hash: str, repo_path: str = ".") -> CommitInfo:
    """获取单个 commit 的详细信息"""
    try:
        for commit in Repository(repo_path, single=commit_hash).traverse_commits():
            return CommitInfo(
                commit_hash=commit.hash,
                author=commit.author.name if commit.author.name else "",
                email=commit.author.email if commit.author.email else "",
                date=commit.author_date.strftime("%Y-%m-%d %H:%M:%S") if commit.author_date else "",
                subject=commit.msg.split('\n')[0] if commit.msg else "",
                body=commit.msg if commit.msg else "",
                files_changed=[m.filename for m in commit.modified_files if m.filename],
                insertions=commit.insertions,
                deletions=commit.deletions,
                diff_content="\n".join([m.diff for m in commit.modified_files if m.diff]),
                parent_hashes=commit.parents
            )
    except Exception:
        pass
    return CommitInfo(commit_hash=commit_hash)


def get_commits_since_date(date: datetime, repo_path: str = ".") -> List[str]:
    """获取指定日期之后的 commit 列表"""
    hashes = []
    try:
        for commit in Repository(repo_path, since=date).traverse_commits():
            hashes.append(commit.hash)
    except Exception:
        pass
    return hashes


def get_commits_by_author(author: str, repo_path: str = ".") -> List[str]:
    """获取指定作者的 commit 列表"""
    hashes = []
    author_lower = author.lower()
    try:
        for commit in Repository(repo_path).traverse_commits():
            name = (commit.author.name or "").lower()
            email = (commit.author.email or "").lower()
            if author_lower in name or author_lower in email:
                hashes.append(commit.hash)
    except Exception:
        pass
    return hashes


def is_git_repo(path: str) -> bool:
    """检查路径是否为 git 仓库"""
    return os.path.isdir(os.path.join(path, ".git"))
