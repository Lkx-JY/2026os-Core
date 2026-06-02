"""数据类型定义"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime


@dataclass
class CommitInfo:
    """Commit 信息"""
    commit_hash: str
    author: str = ""
    email: str = ""
    date: str = ""
    subject: str = ""
    body: str = ""
    files_changed: List[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    diff_content: str = ""
    parent_hashes: List[str] = field(default_factory=list)
    
    subsystem: str = "unknown"
    bug_type: str = "unknown"
    fix_tags: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    lock_added: bool = False
    refcount_fix: bool = False
    rcu_fix: bool = False
    
    score: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "commit_hash": self.commit_hash,
            "author": self.author,
            "date": self.date,
            "subject": self.subject,
            "body": self.body,
            "files_changed": self.files_changed,
            "subsystem": self.subsystem,
            "bug_type": self.bug_type,
            "fix_tags": self.fix_tags,
            "functions": self.functions,
            "lock_added": self.lock_added,
            "refcount_fix": self.refcount_fix,
            "rcu_fix": self.rcu_fix,
            "score": self.score
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "CommitInfo":
        return cls(**data)
    
    def to_embedding_text(self) -> str:
        """构建用于 embedding 的文本"""
        return f"""Title: {self.subject}
Subsystem: {self.subsystem}
BugType: {self.bug_type}
Files: {', '.join(self.files_changed[:10])}
CommitMessage: {self.body[:2000]}
FixTags: {', '.join(self.fix_tags)}
LockAdded: {self.lock_added}
RCUFix: {self.rcu_fix}
RefcountFix: {self.refcount_fix}"""


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
            "query_time_ms": self.query_time_ms
        }
