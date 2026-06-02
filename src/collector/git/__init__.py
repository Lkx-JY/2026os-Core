"""Git 仓库操作模块

负责从 Git 仓库读取 commit 信息，包括：
- 遍历 commit 历史
- 获取 commit 的基本信息（hash、author、date、subject、body）
- 获取修改的文件列表和 diff 内容
"""

import subprocess
import os
from typing import List, Optional
from datetime import datetime
from datatypes import CommitInfo


def run_git_command(cmd: List[str], repo_path: str = ".") -> str:
    """执行 git 命令并返回输出"""
    try:
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return e.stderr.strip()


def get_commit_history(repo_path: str = ".", limit: int = 100) -> List[str]:
    """获取 commit hash 列表"""
    cmd = ["git", "log", "--format=%H", f"-{limit}"]
    output = run_git_command(cmd, repo_path)
    return output.split("\n") if output else []


def get_commit_info(commit_hash: str, repo_path: str = ".") -> CommitInfo:
    """获取单个 commit 的详细信息"""
    # 获取基本信息
    cmd = ["git", "show", commit_hash, "--stat", "--format=format:%H%n%an%n%ae%n%ad%n%s%n%b"]
    output = run_git_command(cmd, repo_path)
    
    lines = output.split("\n")
    if len(lines) < 6:
        return CommitInfo(commit_hash=commit_hash)
    
    commit = CommitInfo(
        commit_hash=lines[0],
        author=lines[1],
        email=lines[2],
        date=lines[3],
        subject=lines[4],
        body="\n".join(lines[5:])
    )
    
    # 获取修改的文件列表
    cmd = ["git", "show", "--stat", commit_hash, "--format="]
    files_output = run_git_command(cmd, repo_path)
    commit.files_changed = [
        line.split("|")[0].strip()
        for line in files_output.split("\n")
        if line and "|" in line
    ]
    
    # 获取统计信息
    cmd = ["git", "show", "--numstat", commit_hash, "--format="]
    numstat_output = run_git_command(cmd, repo_path)
    insertions = 0
    deletions = 0
    for line in numstat_output.split("\n"):
        parts = line.split("\t")
        if len(parts) >= 2:
            try:
                insertions += int(parts[0]) if parts[0] else 0
                deletions += int(parts[1]) if parts[1] else 0
            except ValueError:
                pass
    commit.insertions = insertions
    commit.deletions = deletions
    
    # 获取 diff 内容
    cmd = ["git", "show", commit_hash, "--format="]
    commit.diff_content = run_git_command(cmd, repo_path)
    
    # 获取父 commit
    cmd = ["git", "rev-list", "--parents", "-n", "1", commit_hash]
    parents_output = run_git_command(cmd, repo_path)
    parts = parents_output.split()
    commit.parent_hashes = parts[1:] if len(parts) > 1 else []
    
    return commit


def get_commits_since_date(date: datetime, repo_path: str = ".") -> List[str]:
    """获取指定日期之后的 commit 列表"""
    date_str = date.strftime("%Y-%m-%d")
    cmd = ["git", "log", "--format=%H", f"--since={date_str}"]
    output = run_git_command(cmd, repo_path)
    return output.split("\n") if output else []


def get_commits_by_author(author: str, repo_path: str = ".") -> List[str]:
    """获取指定作者的 commit 列表"""
    cmd = ["git", "log", "--format=%H", f"--author={author}"]
    output = run_git_command(cmd, repo_path)
    return output.split("\n") if output else []


def is_git_repo(path: str) -> bool:
    """检查路径是否为 git 仓库"""
    git_dir = os.path.join(path, ".git")
    return os.path.isdir(git_dir)