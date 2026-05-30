# 03_commit_extractor - Git 提交提取模块

## 任务目标

从 Linux 内核 Git 仓库采集、清洗、理解和索引补丁信息，构建结构化的知识库。

## 需要完成的工作

### 1. Git 仓库管理
- [ ] 克隆 Linux 内核仓库（支持浅克隆和全量克隆）
- [ ] 更新本地仓库到最新版本
- [ ] 管理多个仓库镜像（可选）
- [ ] 仓库完整性验证

### 2. Commit 信息提取
- [ ] 提取 commit hash、author、date 等元数据
- [ ] 提取 commit message（subject + body）
- [ ] 提取修改的文件列表
- [ ] 提取代码差异（diff）
- [ ] 提取统计信息（insertions/deletions）

### 3. Diff 解析和结构化
- [ ] 解析 unified diff 格式
- [ ] 提取文件变更（新增/删除/修改）
- [ ] 提取 hunk 信息
- [ ] 提取代码变更行
- [ ] 识别关键代码模式（spin_lock、kfree 等）

### 4. 领域知识标注
- [ ] 识别子系统（根据文件路径）
- [ ] 识别 Bug 类型（根据 commit message）
- [ ] 识别修复模式（根据 diff 内容）
- [ ] 提取 Fix 标签（Fixes:、Cc: stable 等）
- [ ] 提取修改的函数名

### 5. 数据持久化
- [ ] 存储到 SQLite 数据库
- [ ] 导出为 JSON 格式
- [ ] 建立索引加速查询
- [ ] 支持增量更新

## 代码架构

```python
# repository_manager.py
class RepositoryManager:
    """仓库管理器"""
    
    KERNEL_GIT_URL = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"
    
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
    
    def clone(self, depth: int = None) -> bool:
        """克隆仓库"""
        pass
    
    def update(self) -> bool:
        """更新仓库"""
        pass
    
    def get_commit_hashes(self, limit: int = 1000, 
                         since: str = None) -> List[str]:
        """获取 commit hash 列表"""
        pass


# commit_extractor.py
class CommitExtractor:
    """Commit 提取器"""
    
    # 子系统路径模式
    SUBSYSTEM_PATTERNS = {
        'net': r'^net/',
        'mm': r'^mm/',
        'fs': r'^fs/',
        # ...
    }
    
    # Bug 类型关键词
    BUG_TYPES = {
        'race_condition': ['race condition', 'concurrency'],
        # ...
    }
    
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
    
    def extract_commit(self, commit_hash: str) -> Dict:
        """提取单个 commit"""
        pass
    
    def extract_batch(self, limit: int = 500) -> List[Dict]:
        """批量提取 commit"""
        pass
    
    def _detect_subsystem(self, files: List[str]) -> str:
        """检测子系统"""
        pass
    
    def _detect_bug_type(self, message: str) -> str:
        """检测 Bug 类型"""
        pass
    
    def _extract_fix_tags(self, message: str) -> List[str]:
        """提取 Fix 标签"""
        pass


# diff_parser.py
class DiffParser:
    """Diff 解析器"""
    
    def parse(self, diff_text: str) -> Dict:
        """解析 diff"""
        pass
    
    def extract_files(self) -> List[Dict]:
        """提取文件变更"""
        pass
    
    def extract_hunks(self) -> List[Dict]:
        """提取 hunk 信息"""
        pass
    
    def extract_code_changes(self) -> List[Dict]:
        """提取代码变更"""
        pass
    
    def detect_fix_patterns(self) -> Dict:
        """检测修复模式"""
        pass


# data_storage.py
class DataStorage:
    """数据存储"""
    
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._init_database()
    
    def _init_database(self):
        """初始化数据库"""
        pass
    
    def store_commit(self, commit: Dict) -> bool:
        """存储 commit"""
        pass
    
    def store_batch(self, commits: List[Dict]) -> int:
        """批量存储"""
        pass
    
    def query(self, sql: str, params: Tuple = ()) -> List[Dict]:
        """查询数据"""
        pass
```

## 技术栈

### 核心工具
- **PyDriller**: Git 仓库分析（强烈推荐）
- **b4**: 邮件列表补丁处理
- **verhaal**: 内核 commit 数据库构建
- **whatthepatch**: diff 解析库
- **tree-sitter**: 代码增量解析

### Python 库
- **pydriller**: Git 分析
- **whatthepatch**: diff 解析
- **tree-sitter-c**: C 语言解析
- **GitPython**: Git 操作

## 数据结构

### CommitInfo 结构
```python
@dataclass
class CommitInfo:
    """Commit 信息"""
    commit_hash: str
    author: str
    email: str
    date: str
    subject: str
    body: str
    files_changed: List[str]
    insertions: int
    deletions: int
    diff_content: str
    parent_hashes: List[str]
    
    # 领域知识增强字段
    subsystem: str = "unknown"
    bug_type: str = "unknown"
    fix_tags: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    lock_added: bool = False
    refcount_fix: bool = False
    rcu_fix: bool = False
```

### 数据库表结构
```sql
CREATE TABLE commits (
    id INTEGER PRIMARY KEY,
    commit_hash TEXT UNIQUE,
    author TEXT,
    date TEXT,
    subject TEXT,
    body TEXT,
    files_changed TEXT,
    diff_content TEXT,
    subsystem TEXT,
    bug_type TEXT,
    fix_tags TEXT,
    functions TEXT,
    lock_added BOOLEAN,
    refcount_fix BOOLEAN,
    rcu_fix BOOLEAN,
    embedding_text TEXT,
    created_at TIMESTAMP
);

CREATE INDEX idx_subsystem ON commits(subsystem);
CREATE INDEX idx_bug_type ON commits(bug_type);
CREATE INDEX idx_hash ON commits(commit_hash);
```

## 输入输出

### 输入
- Git 仓库路径
- 提取数量限制
- 时间范围（可选）

### 输出
```json
{
  "commit_hash": "abc123def456...",
  "author": "John Doe",
  "date": "2024-01-15T10:30:00Z",
  "subject": "net: fix race condition in skb handling",
  "body": "This patch fixes a race condition...",
  "files_changed": ["net/core/dev.c", "net/core/skbuff.c"],
  "diff_content": "diff --git a/net/core/dev.c...",
  "subsystem": "net",
  "bug_type": "race_condition",
  "fix_tags": ["Fixes: abc123", "stable"],
  "functions": ["skb_receive", "skb_queue_tail"],
  "lock_added": true,
  "refcount_fix": false,
  "rcu_fix": false
}
```

## 与其他模块的接口

### 提供给 04_vector_database
```python
def get_commits() -> List[Dict]:
    """返回所有 commit"""
    return commits

def get_commit_text(commit: Dict) -> str:
    """返回用于 embedding 的文本"""
    return embedding_text
```

### 提供给 05_rag_search_engine
```python
def search_by_subsystem(subsystem: str) -> List[Dict]:
    """按子系统搜索"""
    pass

def search_by_bug_type(bug_type: str) -> List[Dict]:
    """按 Bug 类型搜索"""
    pass
```

## 领域知识增强

### 修复模式检测
```python
FIX_PATTERNS = {
    'lock_added': [
        'spin_lock', 'spin_lock_irqsave', 'spin_lock_bh',
        'mutex_lock', 'mutex_lock_interruptible',
        'down_read', 'down_write'
    ],
    'refcount_fix': [
        'refcount_inc', 'refcount_dec', 'refcount_set',
        'kref_get', 'kref_put', 'atomic_inc'
    ],
    'rcu_fix': [
        'rcu_read_lock', 'rcu_read_unlock', 'synchronize_rcu',
        'call_rcu', 'rcu_assign_pointer'
    ]
}
```

### Embedding 文本构造
```python
def to_enhanced_embedding_text(commit: Dict) -> str:
    """构建语义增强的 embedding 文本"""
    return f"""Title:
{commit['subject']}

Subsystem:
{commit['subsystem']}

BugType:
{commit['bug_type']}

Files:
{', '.join(commit['files_changed'][:10])}

Functions:
{', '.join(commit['functions'][:5])}

CommitMessage:
{commit['body']}

FixTags:
{', '.join(commit['fix_tags'])}

LockAdded:
{str(commit['lock_added'])}

RCUFix:
{str(commit['rcu_fix'])}

RefcountFix:
{str(commit['refcount_fix'])}
"""
```

## 测试用例

### 测试 1: Commit 提取
```python
def test_commit_extraction():
    extractor = CommitExtractor("/path/to/linux")
    commit = extractor.extract_commit("abc123...")
    assert commit is not None
    assert commit['subject'] is not None
```

### 测试 2: Diff 解析
```python
def test_diff_parsing():
    parser = DiffParser()
    diff = """diff --git a/file.c b/file.c
+ spin_lock(&lock);"""
    result = parser.parse(diff)
    assert result['lock_added'] == True
```

### 测试 3: 领域知识标注
```python
def test_domain_annotation():
    extractor = CommitExtractor("/path/to/linux")
    commit = extractor.extract_commit("abc123...")
    assert commit['subsystem'] in ['net', 'mm', 'fs', ...]
    assert commit['bug_type'] != 'unknown'
```

## 进度追踪

- [ ] Git 仓库管理实现
- [ ] Commit 提取实现
- [ ] Diff 解析实现
- [ ] 领域知识标注实现
- [ ] 数据存储实现
- [ ] 单元测试编写
- [ ] 集成测试

## 注意事项

1. Linux 内核仓库很大（20GB+），确保磁盘空间充足
2. 首次克隆耗时较长，建议支持断点续传
3. Diff 内容可能很大，注意内存管理
4. 建议支持增量更新，避免重复处理
