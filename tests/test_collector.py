"""Collector module unit tests — Git traversal, parsing, subsystem detection."""

import pytest
from src.collector.models import CommitInfo


class TestCommitInfoModel:
    """Test the core CommitInfo data model."""

    def test_commit_info_creation(self):
        c = CommitInfo(
            commit_hash="abc123def456",
            subject="mm: fix use-after-free in slub",
            subsystem="mm",
            bug_type="use_after_free",
        )
        assert c.commit_hash == "abc123def456"
        assert c.subject == "mm: fix use-after-free in slub"

    def test_commit_info_defaults(self):
        c = CommitInfo(commit_hash="abc123", subject="test")
        assert c.subsystem == "unknown"
        assert c.bug_type is None
        assert c.files_changed == []
        assert c.fix_tags == []


class TestSubsystemDetection:
    """Test file path → subsystem mapping."""

    @pytest.mark.parametrize("file_path,expected", [
        ("mm/slub.c", "mm"),
        ("mm/page_alloc.c", "mm"),
        ("include/linux/mm.h", "mm"),
        ("fs/ext4/inode.c", "fs"),
        ("net/core/dev.c", "net"),
        ("net/ipv4/tcp.c", "net"),
        ("block/blk-core.c", "block"),
        ("kernel/sched/core.c", "kernel"),
        ("kernel/rcu/tree.c", "kernel"),
        ("drivers/net/ethernet/intel/e1000/e1000_main.c", "drivers"),
        ("drivers/nvme/host/core.c", "drivers"),
        ("arch/x86/kernel/setup.c", "arch"),
        ("security/selinux/hooks.c", "security"),
    ])
    def test_subsystem_by_path(self, file_path, expected):
        from src.knowledge.subsystem_graph import detect_subsystem_by_path
        result = detect_subsystem_by_path(file_path)
        assert result == expected, f"'{file_path}' → expected '{expected}', got '{result}'"

    @pytest.mark.parametrize("file_path", [
        "include/linux/list.h",
        "scripts/Makefile",
        "Documentation/admin-guide/kernel-parameters.txt",
        "unknown/dir/file.c",
    ])
    def test_unknown_path(self, file_path):
        from src.knowledge.subsystem_graph import detect_subsystem_by_path
        result = detect_subsystem_by_path(file_path)
        assert result is None, f"'{file_path}' should be None, got '{result}'"


class TestBugTypeClassification:
    """Test commit message → bug_type mapping."""

    @pytest.mark.parametrize("title,expected", [
        ("mm: fix use-after-free in slub allocator", "use_after_free"),
        ("net: fix NULL pointer dereference in napi_poll", "null_pointer"),
        ("locking: fix deadlock in mutex_unlock path", "deadlock"),
        ("mm: fix slab out-of-bounds write", "out_of_bound"),
        ("sched: fix soft lockup in CFS load balancer", "hang"),
        ("mm: fix memory leak in vmalloc", "memory_leak"),
        ("fs: fix list corruption in dentry cache", "memory_corruption"),
    ])
    def test_bug_type_from_title(self, title, expected):
        from src.collector.bugtype import classify_bug_type
        result = classify_bug_type(title)
        assert result == expected, f"'{title}' → expected '{expected}', got '{result}'"


class TestDiffParsing:
    """Test commit diff analysis."""

    def test_added_lines_extraction(self):
        from src.collector.analysis import _get_added_lines
        diff = """
--- a/mm/slub.c
+++ b/mm/slub.c
@@ -1000,6 +1000,8 @@
        struct page *page;
        void *object;

+       spin_lock_irqsave(&s->list_lock, flags);
        object = slab_alloc(s);
+       spin_unlock_irqrestore(&s->list_lock, flags);

        return object;
"""
        added = _get_added_lines(diff)
        assert len(added) >= 2
        assert any("spin_lock_irqsave" in line for line in added)

    def test_empty_diff(self):
        from src.collector.analysis import _get_added_lines
        assert _get_added_lines("") == []
        assert _get_added_lines("no additions here") == []
