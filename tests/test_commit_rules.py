"""CommitRootCauseBuilder 单元测试 — 覆盖 25 种 BUG_TEMPLATE + 25 条 DIFF_RULES.

测试覆盖:
- TestBugTemplate: BUG_TEMPLATE 结构完整性 + 全部 25 种类型覆盖
- TestDiffRules: DIFF_RULES 格式验证 + 规则模式匹配
- TestRootCauseSummary: 数据类默认值 + 字段赋值
- TestCommitRootCauseBuilder: build() 各场景 (已知/未知 bug_type, diff 规则命中, 兜底)
- TestEmbeddingTextGeneration: embedding 文本输出格式
- TestBuilderSingleton: 单例模式
"""

import pytest
from src.analyzer.commit_rules import (
    BUG_TEMPLATE,
    DIFF_RULES,
    RootCauseSummary,
    CommitRootCauseBuilder,
    get_builder,
    reset_builder,
    build_commit_embedding_text,
    build_commit_embedding_text_simple,
)
from src.collector.models import CommitInfo


# ============================================================================
# TestBugTemplate
# ============================================================================

class TestBugTemplate:
    """验证 BUG_TEMPLATE 覆盖全部 25 种 BugType."""

    def test_template_count(self):
        """BUG_TEMPLATE 应包含 25 种标准 Bug 类型 (对应 BugType 枚举全部值)."""
        count = len(BUG_TEMPLATE)
        assert count == 25, f"Expected 25 bug types, got {count}"

    @pytest.mark.parametrize("bug_type", list(BUG_TEMPLATE.keys()))
    def test_template_has_required_fields(self, bug_type):
        """每个模板必须有 root_cause, severity, typical_fix."""
        template = BUG_TEMPLATE[bug_type]
        assert "root_cause" in template, f"'{bug_type}' missing 'root_cause'"
        assert "severity" in template, f"'{bug_type}' missing 'severity'"
        assert "typical_fix" in template, f"'{bug_type}' missing 'typical_fix'"
        assert 1 <= template["severity"] <= 10, (
            f"'{bug_type}' severity out of range: {template['severity']}"
        )

    def test_common_bug_types_present(self):
        """最常用的 Bug 类型必须存在."""
        required = [
            "null_pointer", "use_after_free", "double_free", "buffer_overflow",
            "out_of_bound", "memory_corruption", "memory_leak", "deadlock",
            "race_condition", "hang", "crash", "security", "unknown",
        ]
        for bt in required:
            assert bt in BUG_TEMPLATE, f"Missing required bug type: {bt}"

    def test_unknown_has_fallback(self):
        """'unknown' 类型必须有兜底模板."""
        unknown = BUG_TEMPLATE.get("unknown", {})
        assert unknown.get("root_cause"), "unknown template needs root_cause"
        assert unknown.get("severity", 0) >= 1, "unknown template needs valid severity"


# ============================================================================
# TestDiffRules
# ============================================================================

class TestDiffRules:
    """验证 DIFF_RULES 的 25 条规则."""

    def test_rule_count(self):
        """必须有恰好 25 条 Diff 规则."""
        assert len(DIFF_RULES) == 25, f"Expected 25 rules, got {len(DIFF_RULES)}"

    @pytest.mark.parametrize("rule_idx,expected_prefix", [
        (0, "L"), (8, "R"), (12, "C"), (15, "M"), (20, "N"), (23, "A"),
    ])
    def test_rule_ordering(self, rule_idx, expected_prefix):
        """验证规则按类别排序: L → R → C → M → N → A."""
        assert DIFF_RULES[rule_idx]["name"].startswith(expected_prefix), (
            f"Rule at index {rule_idx} expected prefix '{expected_prefix}', "
            f"got '{DIFF_RULES[rule_idx]['name']}'"
        )

    @pytest.mark.parametrize("field", ["name", "root_cause", "fix_pattern"])
    def test_all_rules_have_required_fields(self, field):
        """每条规则必须有 name, root_cause, fix_pattern."""
        for i, rule in enumerate(DIFF_RULES):
            assert field in rule, f"Rule {i} ({rule.get('name', '?')}) missing '{field}'"

    def test_rule_names_unique(self):
        """规则 name 必须唯一."""
        names = [r["name"] for r in DIFF_RULES]
        assert len(names) == len(set(names)), (
            f"Duplicate rule names: {[n for n in names if names.count(n) > 1]}"
        )

    @pytest.mark.parametrize("rule_idx,diff_added,should_hit", [
        # L01: mutex_unlock in diff → should hit
        (0, ["+mutex_unlock(&lock);", "+return 0;"], True),
        # L01: no lock pattern → should not hit
        (0, ["+pr_info(\"hello\");"], False),
        # R01: kref_put → should hit
        (8, ["+kref_put(&obj->ref, release_handler);"], True),
        # N01: NULL check → should hit
        (20, ["+if (!ptr) return -EINVAL;"], True),
        # A01: atomic_inc → should hit
        (23, ["+atomic_inc(&counter);"], True),
    ])
    def test_rule_pattern_matching(self, rule_idx, diff_added, should_hit):
        """测试单条规则的匹配逻辑."""
        builder = CommitRootCauseBuilder()
        commit = CommitInfo(
            commit_hash="abc123" + str(rule_idx),
            subject=f"fix: test {DIFF_RULES[rule_idx]['name']}",
            body="test commit for rule matching",
            bug_type="crash",
            diff_content="\n".join(diff_added),
        )
        summary = builder.build(commit)
        rule_name = DIFF_RULES[rule_idx]["name"]
        hit = any(rule_name in e for e in summary.evidence)
        assert hit == should_hit, (
            f"Rule {rule_name}: expected hit={should_hit}, got hit={hit}, "
            f"evidence={summary.evidence}"
        )


# ============================================================================
# TestRootCauseSummary
# ============================================================================

class TestRootCauseSummary:
    """RootCauseSummary 数据类测试."""

    def test_default_values(self):
        s = RootCauseSummary()
        assert s.bug_type == "unknown"
        assert s.subsystem == "unknown"
        assert s.root_cause == ""
        assert s.severity == 5
        assert s.confidence == 0.0
        assert s.fix_tags == []
        assert s.cves == []
        assert s.evidence == []

    def test_field_assignment(self):
        s = RootCauseSummary(
            bug_type="use_after_free",
            subsystem="mm",
            root_cause="Object lifetime violation",
            confidence=0.85,
            evidence=["diff_rule:L01(score=5)"],
            cves=["CVE-2024-12345"],
        )
        assert s.bug_type == "use_after_free"
        assert s.subsystem == "mm"
        assert s.confidence == 0.85
        assert len(s.evidence) == 1
        assert "CVE-2024-12345" in s.cves


# ============================================================================
# TestCommitRootCauseBuilder
# ============================================================================

class TestCommitRootCauseBuilder:
    """CommitRootCauseBuilder.build() 核心测试."""

    def test_build_known_bug_type(self):
        """已知 bug_type 应通过模板查表产生高置信度结果."""
        builder = CommitRootCauseBuilder()
        commit = CommitInfo(
            commit_hash="abc001",
            subject="mm: fix use-after-free in slub allocator",
            body="KASAN reported UAF in kmalloc-64. Add kref_get before use.",
            subsystem="mm",
            bug_type="use_after_free",
            lock_added=False,
            refcount_fix=True,
            rcu_fix=False,
            fix_tags=["Fixes: def456", "Cc: stable@vger.kernel.org"],
            diff_content="+kref_get(&obj->ref);\n-kfree(obj);\n+kfree_rcu(obj, rcu);",
        )
        summary = builder.build(commit)
        assert summary.bug_type == "use_after_free"
        assert summary.subsystem == "mm"
        assert len(summary.root_cause) > 10  # 非空且有意义
        assert summary.confidence >= 0.80
        assert summary.refcount_fix is True

    def test_build_unknown_bug_type(self):
        """未知 bug_type 应触发轻量兜底."""
        builder = CommitRootCauseBuilder()
        commit = CommitInfo(
            commit_hash="abc002",
            subject="fix: null pointer dereference in driver probe",
            body="Fixes a crash when ptr is NULL after probe failure.",
            subsystem="unknown",
            bug_type="unknown",
            fix_tags=[],
        )
        summary = builder.build(commit)
        # 兜底应识别出 null_pointer 或保留 unknown
        assert summary.bug_type in ("null_pointer", "unknown")
        assert len(summary.root_cause) > 0
        # 兜底置信度应在 0.50-0.65 之间
        if summary.bug_type != "unknown":
            assert 0.50 <= summary.confidence <= 0.70, (
                f"Fallback confidence {summary.confidence} out of expected range"
            )

    def test_build_diff_rule_match_deadlock(self):
        """包含锁解锁 diff 的 deadlock commit 应命中 L01 规则."""
        builder = CommitRootCauseBuilder()
        commit = CommitInfo(
            commit_hash="abc003",
            subject="net: fix deadlock in tcp stack — add missing unlock",
            body="Add missing mutex_unlock on error path to prevent deadlock.",
            subsystem="net",
            bug_type="deadlock",
            diff_content=(
                "+mutex_unlock(&sk->sk_lock);\n"
                "+return -ENOMEM;\n"
            ),
        )
        summary = builder.build(commit)
        assert summary.bug_type == "deadlock"
        assert any("diff_rule" in e for e in summary.evidence), (
            f"Expected diff_rule evidence, got: {summary.evidence}"
        )
        assert summary.fix_pattern != ""
        assert summary.confidence >= 0.80

    def test_build_security_cve_extraction(self):
        """安全 patch 应正确提取 CVE 编号."""
        builder = CommitRootCauseBuilder()
        commit = CommitInfo(
            commit_hash="abc004",
            subject="security: fix CVE-2024-12345 and CVE-2024-67890",
            bug_type="security",
            fix_tags=["CVE-2024-12345", "Fixes: abc", "CVE-2024-67890"],
        )
        summary = builder.build(commit)
        assert "CVE-2024-12345" in summary.cves
        assert "CVE-2024-67890" in summary.cves
        assert len(summary.cves) == 2

    @pytest.mark.parametrize("bug_type", [
        "use_after_free", "deadlock", "null_pointer", "unknown", "crash", "hang",
    ])
    def test_confidence_in_range(self, bug_type):
        """置信度必须在 [0, 1] 范围内."""
        builder = CommitRootCauseBuilder()
        commit = CommitInfo(
            commit_hash="test_range",
            subject=f"fix: {bug_type} issue",
            bug_type=bug_type,
            subsystem="kernel",
        )
        summary = builder.build(commit)
        assert 0.0 <= summary.confidence <= 1.0, (
            f"Confidence {summary.confidence} out of [0,1] for bug_type={bug_type}"
        )

    def test_build_with_empty_diff(self):
        """无 diff 的 commit 仍应正常工作 (仅 Layer 1 查表)."""
        builder = CommitRootCauseBuilder()
        commit = CommitInfo(
            commit_hash="abc005",
            subject="mm: fix memory leak",
            bug_type="memory_leak",
            subsystem="mm",
            diff_content="",
        )
        summary = builder.build(commit)
        assert summary.bug_type == "memory_leak"
        assert summary.root_cause != ""
        assert summary.confidence >= 0.70


# ============================================================================
# TestEmbeddingTextGeneration
# ============================================================================

class TestEmbeddingTextGeneration:
    """embedding 文本生成测试."""

    def test_output_contains_required_sections(self):
        """embedding 文本必须包含关键语义段落."""
        summary = RootCauseSummary(
            bug_type="use_after_free",
            subsystem="mm",
            root_cause="Object lifetime violation — memory accessed after deallocation",
            fix_pattern="reference count increment added before use",
            lock_added=False,
            refcount_fix=True,
            rcu_fix=True,
            cves=["CVE-2024-99999"],
        )
        commit = CommitInfo(
            commit_hash="abc100",
            subject="mm: fix UAF in page allocator",
            body="Add proper kref_get before queuing work to prevent UAF.",
            files_changed=["mm/page_alloc.c", "include/linux/mm.h"],
        )
        text = build_commit_embedding_text(summary, commit)
        assert len(text) > 100, f"Embedding text too short: {len(text)} chars"
        assert "BugType:" in text
        assert "Subsystem:" in text
        assert "RootCause:" in text
        assert "FixPattern:" in text
        assert "FixAction:" in text
        assert "use_after_free" in text
        assert "CommitTitle:" in text
        assert "CVE-2024-99999" in text

    def test_output_without_diff(self):
        """无 diff 时不应报错."""
        summary = RootCauseSummary(bug_type="crash", root_cause="Kernel crash")
        commit = CommitInfo(commit_hash="abc101", subject="fix crash")
        text = build_commit_embedding_text(summary, commit)
        assert len(text) > 0

    def test_convenience_function(self):
        """便捷函数 build_commit_embedding_text_simple 应端到端工作."""
        commit = CommitInfo(
            commit_hash="abc102",
            subject="mm: fix use-after-free",
            bug_type="use_after_free",
            subsystem="mm",
            diff_content="+kref_get(&obj->ref);\n+rcu_read_lock();",
        )
        text = build_commit_embedding_text_simple(commit)
        assert len(text) > 100
        assert "use_after_free" in text


# ============================================================================
# TestBuilderSingleton
# ============================================================================

class TestBuilderSingleton:
    """单例模式测试."""

    def test_same_instance(self):
        reset_builder()
        b1 = get_builder()
        b2 = get_builder()
        assert b1 is b2, "get_builder() should return same instance"

    def test_reset_creates_new_instance(self):
        reset_builder()
        b1 = get_builder()
        reset_builder()
        b2 = get_builder()
        assert b1 is not b2, "reset_builder() should create a new instance"
