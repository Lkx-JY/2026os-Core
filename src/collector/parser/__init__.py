"""Commit 消息解析模块 — 利用 PyDriller 提取的结构化方法名

核心优化:
- extract_functions: 优先使用 file_changes[].methods (PyDriller 的 method-level diff 分析)，
  降级时才用正则匹配 raw diff 文本
- extract_keywords: 增加 Linux 内核特有的标签 (Cc:/Reported-by/Closes/)
"""

import re
from typing import List, Tuple
from ..models import CommitInfo


# ─────────────────────────────────────────────────────────────
#  关键字提取 — 增强了 Linux 内核特有的标签
# ─────────────────────────────────────────────────────────────

def extract_keywords(commit: CommitInfo) -> List[str]:
    """从 commit 消息中提取关键字

    覆盖:
    - Fixes: / Closes: / Resolves: issue 引用
    - CVE-XXXX-XXXX 编号
    - Reported-by / Suggested-by / Tested-by 等内核标签
    - Cc: stable 稳定版标记
    """
    keywords = []
    full_text = f"{commit.subject}\n{commit.body}"

    # Fixes / Closes / Resolves
    for prefix in ['Fixes', 'Closes', 'Resolves']:
        pattern = rf'{prefix}:\s*([0-9a-f]+)'
        for m in re.findall(pattern, full_text, re.IGNORECASE):
            keywords.append(f"{prefix}:{m}")

    # CVE 编号
    for m in re.findall(r'CVE-\d{4}-\d{4,}', full_text):
        keywords.append(m)

    # Cc: stable 稳定版标记
    if re.search(r'Cc:\s*stable', full_text, re.IGNORECASE):
        keywords.append("Cc:stable")

    # Reported-by / Suggested-by / Tested-by / Reviewed-by
    for tag in ['Reported-by', 'Suggested-by', 'Tested-by', 'Reviewed-by', 'Acked-by']:
        pattern = rf'{tag}:\s*([^\n<]+)'
        for m in re.findall(pattern, full_text, re.IGNORECASE):
            name = m.strip()
            if name and len(name) > 2:
                keywords.append(f"{tag}:{name}")

    return keywords


# ─────────────────────────────────────────────────────────────
#  修复标签提取
# ─────────────────────────────────────────────────────────────

def extract_fix_tags(commit: CommitInfo) -> List[str]:
    """提取修复相关标签 — 增强 Linux 内核上下文"""
    fix_tags = []
    full_text = f"{commit.subject} {commit.body}"

    tag_patterns = [
        # 基本修复标识
        (r'\bFixes\b', 'Fixes'),
        (r'\bfix\b', 'fix'),
        (r'\bBUG\b', 'BUG'),
        (r'\bbug\b', 'bug'),
        (r'\bCVE\b', 'CVE'),
        # 安全/崩溃
        (r'\bsecurity\b', 'security'),
        (r'\bcrash\b', 'crash'),
        (r'\bpanic\b', 'panic'),
        (r'\boops\b', 'oops'),
        (r'\bdeadlock\b', 'deadlock'),
        # 其他修复模式
        (r'\bpatch\b', 'patch'),
        (r'\brevert\b', 'revert'),
        (r'\bregression\b', 'regression'),
        (r'\bleak\b', 'leak'),
        (r'\bcorruption\b', 'corruption'),
        (r'\brace\b', 'race'),
        (r'\boverflow\b', 'overflow'),
        (r'\bnull\b', 'null'),
        # 内核特有
        (r'\bstable\b', 'stable'),
        (r'\bbackport\b', 'backport'),
        (r'\bupstream\b', 'upstream'),
    ]

    for pattern, label in tag_patterns:
        if re.search(pattern, full_text, re.IGNORECASE):
            if label not in fix_tags:
                fix_tags.append(label)

    return fix_tags


# ─────────────────────────────────────────────────────────────
#  函数名提取 — 优先使用 PyDriller 提取的方法名
# ─────────────────────────────────────────────────────────────

def extract_functions(commit: CommitInfo) -> List[str]:
    """提取 commit 涉及的函数名

    优化: 优先使用 PyDriller 从 diff 中自动提取的 method names
    (file_changes[].methods)，这是基于代码解析的精确提取。
    降级时使用正则匹配。
    """
    functions = []

    # 方式1 (优): PyDriller 已提取的方法名
    if commit.file_changes:
        for fc in commit.file_changes:
            if fc.methods:
                for m in fc.methods:
                    if m and m not in functions:
                        functions.append(m)
    if functions:
        return functions[:20]

    # 方式2 (降级): 正则匹配 raw diff
    if commit.diff_content:
        func_patterns = [
            r'^[a-zA-Z_][a-zA-Z0-9_]*\s+\*?[a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*\)',
            r'^[a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*\)\s*\{',
            r'\s*=\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\(',
        ]
        for line in commit.diff_content.split("\n"):
            for pattern in func_patterns:
                match = re.match(pattern, line)
                if match:
                    func_name = re.search(r'[a-zA-Z_][a-zA-Z0-9_]*', match.group())
                    if func_name and func_name.group() not in functions:
                        functions.append(func_name.group())
        return functions[:20]

    return functions


# ─────────────────────────────────────────────────────────────
#  Commit 消息解析 & 辅助函数
# ─────────────────────────────────────────────────────────────

def parse_commit_message(commit: CommitInfo) -> CommitInfo:
    """解析 commit 消息，填充 fix_tags 和 functions"""
    commit.fix_tags = extract_fix_tags(commit)
    commit.functions = extract_functions(commit)
    return commit


def parse_subject(subject: str) -> Tuple[str, str]:
    """解析 subject，分离前缀和主题

    Linux 内核常见的格式: "mm: fix page fault"
    也可能是: "mm/damon: fix ..." (多级前缀)
    """
    if ':' in subject:
        parts = subject.split(':', 1)
        prefix = parts[0].strip()
        message = parts[1].strip()
        return prefix, message
    return "", subject


def is_fix_commit(commit: CommitInfo) -> bool:
    """判断是否为修复类 commit"""
    full_text = f"{commit.subject} {commit.body}".lower()
    fix_keywords = ['fix', 'fixes', 'fixed', 'bug', 'cve', 'patch', 'revert', 'backport']
    return any(keyword in full_text for keyword in fix_keywords)
