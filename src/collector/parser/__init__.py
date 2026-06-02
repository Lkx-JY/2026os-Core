"""Commit 消息解析模块

负责解析 commit 的各种信息：
- 从 subject 和 body 中提取关键字
- 识别 fix 相关标签（Fixes、CVE、BUG 等）
- 提取涉及的函数名
"""

import re
from typing import List, Tuple
from ..models import CommitInfo


def extract_keywords(commit: CommitInfo) -> List[str]:
    """从 commit 消息中提取关键字"""
    keywords = []
    
    full_text = f"{commit.subject} {commit.body}"
    
    # 提取 Fixes 标签中的 issue 编号
    fixes_pattern = r'Fixes:\s*(\d+)'
    matches = re.findall(fixes_pattern, full_text, re.IGNORECASE)
    keywords.extend([f"Fixes:{m}" for m in matches])
    
    # 提取 CVE 编号
    cve_pattern = r'CVE-\d{4}-\d{4,}'
    matches = re.findall(cve_pattern, full_text)
    keywords.extend(matches)
    
    # 提取 BUG 编号
    bug_pattern = r'BUG:\s*(\d+)'
    matches = re.findall(bug_pattern, full_text, re.IGNORECASE)
    keywords.extend([f"BUG:{m}" for m in matches])
    
    # 提取 commit hash 引用
    hash_pattern = r'([0-9a-f]{7,40})'
    matches = re.findall(hash_pattern, full_text)
    keywords.extend(matches)
    
    return keywords


def extract_fix_tags(commit: CommitInfo) -> List[str]:
    """提取修复相关标签"""
    fix_tags = []
    
    full_text = f"{commit.subject} {commit.body}"
    
    # 常见的 fix 标签
    tag_patterns = [
        r'\bFixes\b',
        r'\bfix\b',
        r'\bBUG\b',
        r'\bbug\b',
        r'\bCVE\b',
        r'\bsecurity\b',
        r'\bpatch\b',
        r'\brevert\b',
        r'\bregression\b',
        r'\bcrash\b',
        r'\bpanic\b',
        r'\bdeadlock\b',
        r'\bleak\b',
        r'\boops\b',
    ]
    
    for pattern in tag_patterns:
        if re.search(pattern, full_text, re.IGNORECASE):
            fix_tags.append(pattern.strip(r'\b'))
    
    return fix_tags


def extract_functions(diff_content: str) -> List[str]:
    """从 diff 中提取函数名"""
    functions = []
    
    # 匹配函数定义
    func_patterns = [
        # C 函数定义
        r'^[a-zA-Z_][a-zA-Z0-9_]*\s+\*?[a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*\)',
        # 函数声明/定义
        r'^[a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*\)\s*\{',
        # 函数指针赋值
        r'\s*=\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\(',
    ]
    
    for line in diff_content.split("\n"):
        for pattern in func_patterns:
            match = re.match(pattern, line)
            if match:
                # 提取函数名
                func_name = re.search(r'[a-zA-Z_][a-zA-Z0-9_]*', match.group())
                if func_name and func_name.group() not in functions:
                    functions.append(func_name.group())
    
    return functions[:20]  # 限制最多 20 个函数


def parse_commit_message(commit: CommitInfo) -> CommitInfo:
    """解析 commit 消息，提取关键字和标签"""
    commit.fix_tags = extract_fix_tags(commit)
    
    if commit.diff_content:
        commit.functions = extract_functions(commit.diff_content)
    
    return commit


def parse_subject(subject: str) -> Tuple[str, str]:
    """解析 subject，分离前缀和主题"""
    # 常见的前缀格式：subsystem: subject
    if ':' in subject:
        parts = subject.split(':', 1)
        prefix = parts[0].strip()
        message = parts[1].strip()
        return prefix, message
    return "", subject


def is_fix_commit(commit: CommitInfo) -> bool:
    """判断是否为修复类 commit"""
    full_text = f"{commit.subject} {commit.body}"
    fix_keywords = ['fix', 'fixes', 'fixed', 'bug', 'cve', 'patch', 'revert']
    return any(keyword in full_text.lower() for keyword in fix_keywords)