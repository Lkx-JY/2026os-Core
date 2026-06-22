"""Root cause analyzer unit tests — 28 rules + knowledge integration."""

import pytest
from src.analyzer.models import CrashFeature
from src.analyzer.rootcause import (
    abstract_root_cause,
    analyze_call_trace_structure,
    infer_fix_patterns,
    get_analyzer,
)


# ═══════════════════════════════════════════════════════════
# Parameterized: dmesg fixture → expected bug_type
# ═══════════════════════════════════════════════════════════

FIXTURE_EXPECTATIONS = [
    ("dmesg_hardlockup.txt", "hang"),
    ("dmesg_softlockup.txt", "hang"),
    ("dmesg_uaf.txt", "use_after_free"),
    ("dmesg_list_corruption.txt", "memory_corruption"),
    ("dmesg_null_pointer.txt", "null_pointer"),
    ("dmesg_deadlock.txt", "deadlock"),
    ("dmesg_oom.txt", "memory_leak"),
    ("dmesg_rcu_stall.txt", "hang"),
    ("dmesg_double_free.txt", "double_free"),
    ("dmesg_page_fault.txt", "memory_corruption"),
]


class TestRootCauseAnalyzer:
    """Test the 4-layer root cause analysis pipeline."""

    @pytest.mark.parametrize("fixture_file,expected_bug_type", FIXTURE_EXPECTATIONS)
    def test_bug_type_detection(self, sample_dmesg, fixture_file, expected_bug_type):
        """Verify bug_type is correctly identified from crash logs."""
        content = sample_dmesg(fixture_file)
        feature = CrashFeature(
            panic_msg=content,
            call_trace=content.splitlines(),
            subsystem="unknown",
            bug_type="unknown",
        )
        result = abstract_root_cause(feature)
        assert result.bug_type == expected_bug_type, (
            f"Expected bug_type='{expected_bug_type}', "
            f"got '{result.bug_type}' for {fixture_file}"
        )

    @pytest.mark.parametrize("fixture_file,_", FIXTURE_EXPECTATIONS)
    def test_confidence_above_minimum(self, sample_dmesg, fixture_file, _):
        """Verify every fixture yields score >= 0.10 (above 'unknown' baseline)."""
        content = sample_dmesg(fixture_file)
        feature = CrashFeature(
            panic_msg=content,
            call_trace=content.splitlines(),
            subsystem="unknown",
            bug_type="unknown",
        )
        result = abstract_root_cause(feature)
        assert result.score >= 0.10, (
            f"Score too low ({result.score:.2f}) for {fixture_file}"
        )

    def test_root_cause_not_empty(self, sample_dmesg):
        """Root cause string should never be empty."""
        content = sample_dmesg("dmesg_uaf.txt")
        feature = CrashFeature(
            panic_msg=content,
            call_trace=content.splitlines(),
            subsystem="unknown",
            bug_type="unknown",
        )
        result = abstract_root_cause(feature)
        assert result.root_cause, "Root cause string is empty"
        assert len(result.root_cause) > 3

    def test_causal_chain_populated(self, sample_dmesg):
        """Causal chain should contain diagnostic entries."""
        content = sample_dmesg("dmesg_null_pointer.txt")
        feature = CrashFeature(
            panic_msg=content,
            call_trace=content.splitlines(),
            subsystem="unknown",
            bug_type="unknown",
        )
        result = abstract_root_cause(feature)
        assert len(result.causal_chain) > 0, "Causal chain is empty"

    def test_retrieval_query_generated(self, sample_dmesg):
        """Retrieval query must be a non-empty string for downstream search."""
        content = sample_dmesg("dmesg_deadlock.txt")
        feature = CrashFeature(
            panic_msg=content,
            call_trace=content.splitlines(),
            subsystem="unknown",
            bug_type="unknown",
        )
        result = abstract_root_cause(feature)
        assert result.retrieval_query, "Retrieval query is empty"
        assert "RootCause:" in result.retrieval_query

    def test_knowledge_enhancement_applied(self, sample_dmesg):
        """P0-1: Knowledge base must enhance the analysis result."""
        content = sample_dmesg("dmesg_uaf.txt")
        feature = CrashFeature(
            panic_msg=content,
            call_trace=content.splitlines(),
            subsystem="mm",
            bug_type="use_after_free",
        )
        result = abstract_root_cause(feature)
        has_knowledge = (
            "knowledge_bug_match" in result.extra_info
            or "lock_analysis" in result.extra_info
            or "subsystem_info" in result.extra_info
        )
        assert has_knowledge, (
            "Knowledge enhancement not applied. "
            f"extra_info keys: {list(result.extra_info.keys())}"
        )


class TestCallTraceAnalysis:
    """Test Layer 2: call trace structure analysis."""

    def test_lock_functions_detected(self):
        trace = [
            "spin_lock_irqsave+0x3b/0x50",
            "mutex_lock+0x9a/0x840",
            "try_to_wake_up+0x2a1/0x5e0",
        ]
        result = analyze_call_trace_structure(trace)
        assert len(result["lock_functions"]) >= 2
        assert result["inferred_issue"] in ("deadlock_or_lock_contention", "possible_lock_issue")

    def test_memory_functions_detected(self):
        trace = [
            "kmalloc+0x4c/0x100",
            "kfree+0x8e/0x1f0",
            "kasan_report+0xc8/0x100",
        ]
        result = analyze_call_trace_structure(trace)
        assert len(result["memory_functions"]) >= 2
        assert result["inferred_issue"] == "memory_related"

    def test_rcu_functions_detected(self):
        trace = [
            "rcu_read_lock+0x0/0x40",
            "synchronize_rcu+0x5a/0x130",
            "rcu_dereference+0x1f/0x30",
        ]
        result = analyze_call_trace_structure(trace)
        assert len(result["rcu_functions"]) >= 2
        assert result["inferred_issue"] == "rcu_related"

    def test_empty_trace(self):
        result = analyze_call_trace_structure([])
        assert result["inferred_issue"] == "unknown"
        assert result["lock_functions"] == []


class TestFixPatternInference:
    """Test fix pattern mapping from bug_type → needed fixes."""

    def test_uaf_needs_refcount_and_rcu(self):
        result = infer_fix_patterns("use_after_free", {"lock_functions": []})
        assert result["needs_refcount_fix"] is True
        assert result["needs_rcu_fix"] is True

    def test_deadlock_needs_lock_fix(self):
        result = infer_fix_patterns("deadlock", {"lock_functions": []})
        assert result["needs_lock_fix"] is True

    def test_null_pointer_needs_null_check(self):
        result = infer_fix_patterns("null_pointer", {"lock_functions": []})
        assert result["needs_null_check"] is True

    def test_suggested_keywords_non_empty(self):
        result = infer_fix_patterns("use_after_free", {"lock_functions": []})
        assert len(result["suggested_search_keywords"]) > 0


class TestExpertRules:
    """Test the 28 expert rules."""

    def test_all_rules_have_required_fields(self):
        from src.analyzer.rootcause import EXPERT_RULES
        required = ["id", "name", "bug_type", "description"]
        for rule in EXPERT_RULES:
            for field in required:
                assert field in rule, f"Rule {rule.get('id', '?')} missing '{field}'"

    def test_rule_ids_unique(self):
        from src.analyzer.rootcause import EXPERT_RULES
        ids = [r["id"] for r in EXPERT_RULES]
        assert len(ids) == len(set(ids)), f"Duplicate rule IDs"


class TestAnalyzerSingleton:
    """Test the module-level singleton."""

    def test_same_instance_returned(self):
        a1 = get_analyzer()
        a2 = get_analyzer()
        assert a1 is a2
