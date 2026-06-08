"""Collector 模块测试"""
import pytest
from src.collector import collect_commits_stream

def test_collector_import():
    """测试 collector 模块导入"""
    from src.collector import CommitInfo, FileChangeInfo
    assert CommitInfo is not None
    assert FileChangeInfo is not None

def test_git_module():
    """测试 git 模块"""
    from src.collector.git import traverse_commits
    assert traverse_commits is not None
