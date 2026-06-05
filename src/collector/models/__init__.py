"""数据类型定义 — 充分利用 PyDriller 的结构化输出"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime


@dataclass
class FileChangeInfo:
    """单个文件的变更信息 — 利用 PyDriller modified_file 的结构化字段

    PyDriller 提供了远超 raw diff 文本的精确数据:
    - added_lines / deleted_lines: 该文件精确的增删行数 (而非全局统计)
    - nloc: 非注释非空代码行数
    - complexity: 圈复杂度
    - token_count: token 数量
    - methods: 修改涉及的方法列表
    """
    filename: str = ""
    old_path: str = ""
    new_path: str = ""
    change_type: str = "MODIFY"       # ADD, DELETE, MODIFY, RENAME
    added_lines: int = 0
    deleted_lines: int = 0
    nloc: int = 0                      # 非注释代码行数
    complexity: int = 0
    methods: List[str] = field(default_factory=list)
    diff: str = ""                     # 该文件的 unified diff 文本
    diff_parsed_added: List[str] = field(default_factory=list)   # 新增的代码行
    diff_parsed_deleted: List[str] = field(default_factory=list) # 删除的代码行

    def to_dict(self) -> Dict:
        return {
            "filename": self.filename,
            "old_path": self.old_path,
            "new_path": self.new_path,
            "change_type": self.change_type,
            "added_lines": self.added_lines,
            "deleted_lines": self.deleted_lines,
            "nloc": self.nloc,
            "complexity": self.complexity,
            "methods": self.methods,
        }


@dataclass
class CommitInfo:
    """Commit 信息 — PyDriller 一次遍历全量提取

    PyDriller 的 commit 对象在单次遍历中原生提供以下所有字段，
    无需二次调用 subprocess 或多次 Repository 实例化。
    """

    # ── 基本信息 (PyDriller commit 对象直接提供) ──
    commit_hash: str
    author: str = ""
    email: str = ""
    date: str = ""                     # commit.author_date
    committer_date: str = ""           # commit.committer_date
    subject: str = ""
    body: str = ""
    files_changed: List[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    diff_content: str = ""
    parent_hashes: List[str] = field(default_factory=list)

    # ── 新增: PyDriller 原生提供的结构信息 ──
    is_merge: bool = False             # commit.merge
    in_main_branch: bool = False       # commit.in_main_branch
    branches: List[str] = field(default_factory=list)  # commit.branches
    tags: List[str] = field(default_factory=list)      # git tags

    # ── 新增: 文件级结构化变更 ──
    file_changes: List[FileChangeInfo] = field(default_factory=list)

    # ── 分析结果 (由 parser/subsystem/bugtype/analysis 填充) ──
    subsystem: str = "unknown"
    bug_type: str = "unknown"
    fix_tags: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    lock_added: bool = False
    refcount_fix: bool = False
    rcu_fix: bool = False

    score: float = 0.0

    # ── 序列化 ──

    def to_dict(self) -> Dict:
        return {
            "commit_hash": self.commit_hash,
            "author": self.author,
            "date": self.date,
            "committer_date": self.committer_date,
            "subject": self.subject,
            "body": self.body,
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "is_merge": self.is_merge,
            "in_main_branch": self.in_main_branch,
            "branches": self.branches,
            "tags": self.tags,
            "subsystem": self.subsystem,
            "bug_type": self.bug_type,
            "fix_tags": self.fix_tags,
            "functions": self.functions,
            "lock_added": self.lock_added,
            "refcount_fix": self.refcount_fix,
            "rcu_fix": self.rcu_fix,
            "score": self.score,
            "file_changes": [fc.to_dict() for fc in self.file_changes],
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "CommitInfo":
        file_changes_data = data.pop("file_changes", [])
        instance = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        instance.file_changes = [FileChangeInfo(**fc) for fc in file_changes_data]
        return instance

    def to_embedding_text(self) -> str:
        """构建用于 embedding 的语义增强文本"""
        parts = [
            f"Title: {self.subject}",
            f"Subsystem: {self.subsystem}",
            f"BugType: {self.bug_type}",
            f"Files: {', '.join(self.files_changed[:10])}",
            f"CommitMessage: {self.body[:2000]}",
            f"FixTags: {', '.join(self.fix_tags)}",
            f"LockAdded: {self.lock_added}",
            f"RCUFix: {self.rcu_fix}",
            f"RefcountFix: {self.refcount_fix}",
        ]
        if self.tags:
            parts.append(f"Tags: {', '.join(self.tags)}")
        return "\n".join(parts)


@dataclass
class QueryResult:
    """查询结果"""
    query: str
    root_cause: str
    bug_type: str
    keywords: List[str]
    candidates: List[CommitInfo]
    recommended: Optional[CommitInfo] = None
    reason: str = ""
    query_time_ms: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "query": self.query,
            "root_cause": self.root_cause,
            "bug_type": self.bug_type,
            "keywords": self.keywords,
            "candidates": [c.to_dict() for c in self.candidates],
            "recommended": self.recommended.to_dict() if self.recommended else None,
            "reason": self.reason,
            "query_time_ms": self.query_time_ms,
        }
