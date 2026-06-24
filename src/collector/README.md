# Collector 模块

Commit 信息收集和分析模块，提供从 Git 仓库收集 commit 信息并进行多维度分析的功能。

## 模块架构

```
collector/
├── __init__.py       # 模块入口，整合所有子模块
├── models/           # 数据模型定义 (CommitInfo, QueryResult)
├── git/              # Git 仓库操作模块
├── parser/           # Commit 消息解析模块
├── subsystem/        # 子系统识别模块
├── bugtype/          # Bug 类型识别模块
└── analysis/         # 高级特征分析模块
```

## 子模块说明

### models 模块

定义了收集器使用的核心数据结构。

**主要类：**
- `CommitInfo`: 存储 Commit 的所有分析结果
- `QueryResult`: 存储查询和根因分析结果

---

### git 模块

负责从 Git 仓库读取 commit 信息，基于 PyDriller 实现流式遍历。

**主要功能：**
- 流式遍历 commit 历史 (`traverse_commits` — O(1) 内存，生成器模式)
- 批量获取 commit 信息 (`collect_commits_batch`)
- 获取单个 commit 的详细信息 (`get_commit_info`)
- 获取 commit 历史列表 (`get_commit_history`)
- 按日期筛选 commit (`get_commits_since_date`)
- 按作者筛选 commit (`get_commits_by_author`)
- 检查路径是否为 Git 仓库 (`is_git_repo`)

**核心函数：**
```python
from src.collector.git import traverse_commits, get_commit_info, get_commit_history

# 流式遍历 — 推荐用于大规模处理 (百万级 commit 不 OOM)
for commit in traverse_commits(repo_path="/path/to/repo", limit=10000):
    process(commit)

# 获取 commit 历史
commits = get_commit_history(repo_path="/path/to/repo", limit=100)

# 获取单个 commit 信息
commit = get_commit_info(commit_hash="abc123", repo_path="/path/to/repo")
```

### parser 模块

负责解析 commit 消息和 diff 内容。

**主要功能：**
- 从 commit 消息中提取关键字（Fixes、CVE、BUG 等）
- 识别修复相关标签
- 从 diff 中提取函数名
- 判断是否为修复类 commit
- 解析 commit subject 前缀（子系统标记）

**核心函数：**
```python
from src.collector.parser import extract_keywords, extract_fix_tags, parse_commit_message, parse_subject

# 提取关键字
keywords = extract_keywords(commit)

# 提取修复标签
fix_tags = extract_fix_tags(commit)

# 完整解析 commit 消息
commit = parse_commit_message(commit)

# 解析 subject 前缀 (如 "mm: fix NULL pointer")
subsystem_from_subject = parse_subject(commit.subject)
```

### subsystem 模块

负责根据修改的文件路径识别 commit 所属的子系统。

**主要功能：**
- 根据文件路径识别子系统
- 从 commit subject 前缀识别子系统
- 获取子系统层级关系
- 从内容猜测子系统

**支持的子系统：**
`mm`, `fs`, `net`, `block`, `driver`, `usb`, `pci`, `scsi`, `nvme`, `crypto`, `security`, `kernel`, `irq`, `rcu`, `kvm`, `virt`, `power`, `acpi`, `dt`, `firmware`, `lib`, `tools`, `doc`, `arch`, `bpf`, `cgroup`, `nfs`, `smb`

**核心函数：**
```python
from src.collector.subsystem import detect_subsystem, get_subsystem_hierarchy

# 识别子系统
subsystem = detect_subsystem(commit)

# 获取子系统层级
hierarchy = get_subsystem_hierarchy(subsystem)
```

### bugtype 模块

负责根据 commit 消息和 diff 内容识别 bug 类型。

**主要功能：**
- 识别 commit 的 bug 类型
- 识别所有可能的 bug 类型
- 获取 bug 类型描述

**支持的 Bug 类型：**
`use_after_free`, `null_pointer`, `buffer_overflow`, `memory_leak`, `deadlock`, `race_condition`, `integer_overflow`, `out_of_bound`, `double_free`, `use_before_init`, `uninitialized`, `memory_corruption`, `concurrency`, `hang`, `crash`, `regression`, `security`, `performance`, `resource_leak`, `logic_error`, `configuration`

**核心函数：**
```python
from src.collector.bugtype import detect_bug_type, detect_all_bug_types, get_bug_type_description

# 识别 bug 类型
bug_type = detect_bug_type(commit)

# 识别所有可能的 bug 类型
bug_types = detect_all_bug_types(commit)

# 获取 bug 类型描述
description = get_bug_type_description(bug_type)
```

### analysis 模块

负责分析 commit 的高级特征。

**主要功能：**
- 判断是否添加了锁
- 判断是否修复了引用计数问题
- 判断是否修复了 RCU 相关问题
- 计算 commit 的重要性分数

**核心函数：**
```python
from src.collector.analysis import has_lock_added, has_refcount_fix, has_rcu_fix, calculate_score, analyze_commit

# 判断是否添加了锁
lock_added = has_lock_added(commit)

# 判断是否修复了引用计数
refcount_fix = has_refcount_fix(commit)

# 判断是否修复了 RCU 问题
rcu_fix = has_rcu_fix(commit)

# 计算重要性分数
score = calculate_score(commit)

# 完整分析 commit
commit = analyze_commit(commit)
```

## 综合使用

### 收集单个 Commit

```python
from src.collector import collect_commit

commit = collect_commit(commit_hash="abc123", repo_path="/path/to/git/repo")
if commit:
    print(f"Subsystem: {commit.subsystem}")
    print(f"Bug Type: {commit.bug_type}")
    print(f"Score: {commit.score}")
```

### 收集多个 Commits

```python
from src.collector import collect_commits

# 收集最近 100 个 commit (批量模式 — 一次遍历)
commits = collect_commits(repo_path="/path/to/git/repo", limit=100)

for commit in commits:
    print(f"{commit.commit_hash}: {commit.subject}")
```

### 流式收集 (★ 推荐 — 适用于百万级 Commit)

```python
from src.collector import collect_commits_stream

# 生成器模式 — 逐条产出，永不 OOM
for commit in collect_commits_stream(repo_path="/path/to/git/repo", limit=10000):
    print(f"{commit.commit_hash}: {commit.subject}")
    # 可在此逐条写入向量库
```

### 按日期收集

```python
from datetime import datetime
from src.collector import collect_commits_since_date

# 收集指定日期之后的 commit
commits = collect_commits_since_date(
    date=datetime(2024, 1, 1),
    repo_path="/path/to/git/repo"
)
```

### 按作者收集

```python
from src.collector import collect_commits_by_author

# 收集指定作者的 commit
commits = collect_commits_by_author(
    author="John Doe",
    repo_path="/path/to/git/repo"
)
```

## 数据类型

### CommitInfo

```python
@dataclass
class CommitInfo:
    # 基本信息
    commit_hash: str      # Commit 哈希值
    author: str           # 作者姓名
    email: str            # 作者邮箱
    date: str             # 提交日期
    subject: str          # 提交主题
    body: str             # 提交正文
    files_changed: List[str]  # 修改的文件列表
    insertions: int       # 新增代码行数
    deletions: int        # 删除代码行数
    diff_content: str     # Diff 内容
    parent_hashes: List[str]  # 父 commit 哈希列表
    
    # 分析结果
    subsystem: str        # 所属子系统
    bug_type: str         # Bug 类型
    fix_tags: List[str]   # 修复标签
    functions: List[str]  # 涉及的函数
    lock_added: bool      # 是否添加了锁
    refcount_fix: bool    # 是否修复引用计数
    rcu_fix: bool         # 是否修复 RCU 问题
    score: float          # 重要性分数 (0-10)
```

### 方法

```python
# 转换为字典
data = commit.to_dict()

# 从字典创建
commit = CommitInfo.from_dict(data)

# 生成用于 embedding 的文本
text = commit.to_embedding_text()
```

## 导出接口

所有子模块的函数都可以从 `src.collector` 直接导入：

```python
from src.collector import (
    # Git 操作
    traverse_commits,
    collect_commits_batch,
    get_commit_history,
    get_commit_info,
    get_commits_since_date,
    get_commits_by_author,
    is_git_repo,
    
    # 解析功能
    extract_keywords,
    extract_fix_tags,
    extract_functions,
    parse_commit_message,
    parse_subject,
    is_fix_commit,
    
    # 子系统识别
    detect_subsystem,
    get_subsystem_hierarchy,
    get_all_subsystems,
    
    # Bug 类型识别
    detect_bug_type,
    detect_all_bug_types,
    get_bug_type_description,
    get_all_bug_types,
    
    # 分析功能
    has_lock_added,
    has_refcount_fix,
    has_rcu_fix,
    calculate_score,
    analyze_commit,
    
    # 综合功能
    collect_commit,
    collect_commits,
    collect_commits_stream,
    collect_commits_since_date,
    collect_commits_by_author,
)
```

## 依赖

- Python 3.7+
- Git 命令行工具

## 注意事项

1. 需要系统安装 Git 命令行工具
2. 子系统识别主要针对 Linux 内核项目
3. Bug 类型识别基于关键字匹配，可能存在误判
4. 分数计算基于启发式规则，仅供参考