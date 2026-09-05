"""报告生成模块 — Report Generation Engine

负责将诊断结果和检索到的补丁整合为可读的诊断报告。
支持多种输出格式: Markdown、JSON、HTML。

核心功能:
- 结构化报告生成: 包含摘要、分析、根因、补丁推荐、预防措施
- 多格式输出: Markdown (默认) / JSON / HTML
- 补丁对比表: Top-K 补丁的对比分析
- LLM 增强: 可选使用 LLM 生成更专业的描述
- 可解释性: 每个推荐补丁附带排名理由
"""

from __future__ import annotations
import json
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime

from ..prompt import (
    build_diagnosis_report_prompt,
    build_patch_explanation_prompt,
)
from ..llm import get_llm_client


# ============================================================================
# 报告数据结构
# ============================================================================

@dataclass
class DiagnosisReport:
    """完整的诊断报告

    包含从崩溃分析到补丁推荐的全部信息。
    """
    # 元信息
    report_id: str = ""
    generated_at: str = ""
    generator_version: str = "1.0.0"

    # 崩溃信息
    crash_summary: str = ""
    kernel_version: str = ""
    panic_type: str = ""
    affected_subsystem: str = ""

    # 诊断结果
    root_cause: str = ""
    bug_type: str = ""
    causal_chain: List[str] = field(default_factory=list)
    confidence: float = 0.0
    severity: str = "UNKNOWN"

    # 补丁推荐
    recommended_patches: List[Dict[str, Any]] = field(default_factory=list)
    alternative_patches: List[Dict[str, Any]] = field(default_factory=list)

    # LLM 增强
    llm_executive_summary: str = ""
    llm_detailed_analysis: str = ""
    llm_fix_explanation: str = ""

    # 元数据
    analysis_mode: str = "rule_only"
    total_time_ms: float = 0.0
    extra_info: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Markdown 输出 ──────────────────────────────────────────

    def to_markdown(self, include_llm_sections: bool = True) -> str:
        """生成 Markdown 格式的诊断报告

        Args:
            include_llm_sections: 是否包含 LLM 增强部分

        Returns:
            完整的 Markdown 报告
        """
        lines = []
        lines.append(f"# Linux Kernel Crash Diagnosis Report")
        lines.append(f"")
        lines.append(f"**Report ID**: {self.report_id}")
        lines.append(f"**Generated**: {self.generated_at}")
        lines.append(f"**Analysis Mode**: {self.analysis_mode}")
        lines.append(f"**Total Time**: {self.total_time_ms:.0f}ms")
        lines.append(f"")

        # ── 1. 执行摘要 ──────────────────────────────────────
        lines.append(f"## 1. Executive Summary")
        lines.append(f"")
        if self.llm_executive_summary and include_llm_sections:
            lines.append(self.llm_executive_summary)
        else:
            lines.append(self._generate_summary_text())
        lines.append(f"")

        # ── 2. 崩溃概况 ──────────────────────────────────────
        lines.append(f"## 2. Crash Overview")
        lines.append(f"")
        lines.append(f"| Field | Value |")
        lines.append(f"|-------|-------|")
        lines.append(f"| Kernel Version | {self.kernel_version or 'unknown'} |")
        lines.append(f"| Panic Type | {self.panic_type or 'unknown'} |")
        lines.append(f"| Affected Subsystem | {self.affected_subsystem or 'unknown'} |")
        lines.append(f"| Bug Type | {self.bug_type or 'unknown'} |")
        lines.append(f"| Severity | **{self.severity}** |")
        lines.append(f"| Confidence | {self.confidence:.1%} |")
        lines.append(f"")
        lines.append(f"### Crash Summary")
        lines.append(f"```")
        lines.append(self.crash_summary[:2000])
        lines.append(f"```")
        lines.append(f"")

        # ── 3. 根因诊断 ──────────────────────────────────────
        lines.append(f"## 3. Root Cause Diagnosis")
        lines.append(f"")
        lines.append(f"### Root Cause")
        lines.append(f"")
        lines.append(f"> **{self.root_cause}**")
        lines.append(f"")

        if self.causal_chain:
            lines.append(f"### Causal Chain")
            lines.append(f"")
            for i, step in enumerate(self.causal_chain, 1):
                lines.append(f"{i}. {step}")
            lines.append(f"")

        if self.llm_detailed_analysis and include_llm_sections:
            lines.append(f"### Detailed Analysis (LLM Enhanced)")
            lines.append(f"")
            lines.append(self.llm_detailed_analysis)
            lines.append(f"")

        # ── 4. 补丁推荐 ──────────────────────────────────────
        lines.append(f"## 4. Patch Recommendations")
        lines.append(f"")
        if self.recommended_patches:
            lines.append(self._format_patch_table(self.recommended_patches[:10]))
        else:
            lines.append("*(No matching patches found)*")
        lines.append(f"")

        if self.llm_fix_explanation and include_llm_sections:
            lines.append(f"### Fix Analysis")
            lines.append(f"")
            lines.append(self.llm_fix_explanation)
            lines.append(f"")

        # ── 5. 预防措施 ──────────────────────────────────────
        lines.append(f"## 5. Prevention Measures")
        lines.append(f"")
        lines.extend(self._generate_prevention_measures())
        lines.append(f"")

        # ── 页脚 ─────────────────────────────────────────────
        lines.append(f"---")
        lines.append(f"*Report generated by Linux 内核宕机自动诊断与补丁匹配系统 — Automated Kernel Crash Analysis System*")

        return "\n".join(lines)

    # ── JSON 输出 ────────────────────────────────────────────

    def to_json(self, indent: int = 2) -> str:
        """生成 JSON 格式的诊断报告

        Returns:
            格式化的 JSON 字符串
        """
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "generator_version": self.generator_version,
            "crash_summary": self.crash_summary,
            "kernel_version": self.kernel_version,
            "panic_type": self.panic_type,
            "affected_subsystem": self.affected_subsystem,
            "root_cause": self.root_cause,
            "bug_type": self.bug_type,
            "causal_chain": self.causal_chain,
            "confidence": self.confidence,
            "severity": self.severity,
            "recommended_patches": self.recommended_patches[:10],
            "alternative_patches": self.alternative_patches[:5],
            "llm_executive_summary": self.llm_executive_summary,
            "llm_detailed_analysis": self.llm_detailed_analysis,
            "llm_fix_explanation": self.llm_fix_explanation,
            "analysis_mode": self.analysis_mode,
            "total_time_ms": self.total_time_ms,
            "extra_info": self.extra_info,
        }

    # ── 内部方法 ──────────────────────────────────────────────

    def _generate_summary_text(self) -> str:
        """生成简明的摘要文本"""
        severity_emoji = {
            "CRITICAL": "🔴",
            "HIGH": "🟠",
            "MEDIUM": "🟡",
            "LOW": "🟢",
            "UNCERTAIN": "⚪",
        }
        emoji = severity_emoji.get(self.severity, "⚪")

        lines = [
            f"{emoji} **{self.severity} Severity** — Confidence: {self.confidence:.0%}",
            f"",
            f"A kernel crash was detected in the **{self.affected_subsystem or 'unknown'}** subsystem. "
            f"Analysis identified the root cause as **{self.root_cause}**.",
        ]

        if self.recommended_patches:
            top = self.recommended_patches[0]
            lines.append(f"")
            lines.append(
                f"The top recommended patch is `{top.get('commit_hash', 'N/A')[:12]}` "
                f"(score: {top.get('final_score', 0):.3f}): "
                f"*{top.get('subject', 'N/A')[:100]}*"
            )

        return "\n".join(lines)

    def _format_patch_table(self, patches: List[Dict[str, Any]]) -> str:
        """格式化补丁对比表"""
        lines = [
            f"| # | Commit | Subsystem | Bug Type | Score | Subject |",
            f"|---|--------|-----------|----------|-------|---------|",
        ]
        for item in patches:
            rank = item.get("rank", "?")
            commit = item.get("commit_hash", "N/A")[:10]
            subsystem = item.get("subsystem", "unknown")
            bug_type = item.get("bug_type", "unknown")
            score = item.get("final_score", item.get("score", 0))
            subject = item.get("subject", "N/A")[:80]

            lines.append(
                f"| {rank} | `{commit}` | {subsystem} | {bug_type} | {score:.3f} | {subject} |"
            )

        return "\n".join(lines)

    def _generate_prevention_measures(self) -> List[str]:
        """生成预防措施建议"""
        measures = []

        # 基于 bug 类型的预防建议
        bug_type_prevention = {
            "use_after_free": [
                "- Enable **KASAN** (Kernel Address Sanitizer) to detect UAF at runtime",
                "- Use **SLUB_DEBUG** for slab allocation debugging",
                "- Consider using `__free_after_rcu` pattern for RCU-protected frees",
                "- Run **syzkaller** fuzzing tests targeting this code path",
            ],
            "deadlock": [
                "- Enable **LOCKDEP** (CONFIG_PROVE_LOCKING) to detect lock ordering violations",
                "- Enable **LOCK_STAT** to monitor lock contention",
                "- Review lock ordering documentation for this subsystem",
                "- Use `spin_lock_irqsave` in interrupt context instead of `spin_lock`",
            ],
            "null_pointer": [
                "- Add defensive NULL checks before dereferencing pointers",
                "- Enable **KASAN** for null pointer detection",
                "- Review error handling paths in the affected functions",
                "- Use `ERR_PTR` / `IS_ERR` patterns for error propagation",
            ],
            "race_condition": [
                "- Enable **KCSAN** (Kernel Concurrency Sanitizer) for data race detection",
                "- Review locking strategy in the affected code path",
                "- Use RCU or spinlocks for shared data protection",
                "- Consider using atomic operations for simple shared variables",
            ],
            "buffer_overflow": [
                "- Enable **CONFIG_FORTIFY_SOURCE** for compile-time buffer overflow detection",
                "- Use `strscpy()` instead of `strcpy()`, `scnprintf()` instead of `sprintf()`",
                "- Add bounds checking before array/string operations",
                "- Enable **UBSAN** (Undefined Behavior Sanitizer)",
            ],
            "memory_leak": [
                "- Enable **KMEMLEAK** for kernel memory leak detection",
                "- Review all error paths for missing `kfree()` / `put_*()` calls",
                "- Use `__must_check` annotation for allocation functions",
                "- Implement proper cleanup in module exit / error unwind paths",
            ],
        }

        measures.append("### Recommended Kernel Config Options")
        measures.append("")
        measures.append("```")
        measures.append("CONFIG_KASAN=y           # Kernel Address Sanitizer")
        measures.append("CONFIG_LOCKDEP=y         # Lock Dependency Engine")
        measures.append("CONFIG_PROVE_LOCKING=y   # Lock Ordering Verification")
        measures.append("CONFIG_KCSAN=y           # Kernel Concurrency Sanitizer")
        measures.append("CONFIG_DEBUG_KMEMLEAK=y  # Memory Leak Detector")
        measures.append("CONFIG_FORTIFY_SOURCE=y  # Buffer Overflow Protection")
        measures.append("CONFIG_UBSAN=y           # Undefined Behavior Sanitizer")
        measures.append("CONFIG_SLUB_DEBUG=y      # Slab Debugging")
        measures.append("CONFIG_DEBUG_LIST=y      # Linked List Debugging")
        measures.append("```")
        measures.append("")

        if self.bug_type in bug_type_prevention:
            measures.append(f"### Specific Measures for {self.bug_type.replace('_', ' ').title()}")
            measures.append("")
            measures.extend(bug_type_prevention[self.bug_type])
            measures.append("")

        measures.append("### Testing Recommendations")
        measures.append("")
        measures.append(f"- Run **syzkaller** with focus on the `{self.affected_subsystem or 'kernel'}` subsystem")
        measures.append("- Add regression tests for the identified code path")
        measures.append("- Run **LTP** (Linux Test Project) kernel syscall tests")
        measures.append("- Consider stress testing under memory pressure / CPU load")

        return measures


# ============================================================================
# 报告生成器
# ============================================================================

class ReportGenerator:
    """诊断报告生成器

    将 RootCauseResult + RetrievalResult 整合为可读的诊断报告。

    Example:
        >>> gen = ReportGenerator()
        >>> report = gen.generate(
        ...     root_cause_result=analysis_result,
        ...     retrieval_result=retrieval_result,
        ...     dmesg_content=dmesg_log,
        ... )
        >>> print(report.to_markdown())
    """

    def __init__(self, use_llm: bool = False, model_name: str = "deepseek-chat"):
        """
        Args:
            use_llm: 是否使用 LLM 增强报告质量
            model_name: LLM 模型名称
        """
        self.use_llm = use_llm
        self.model_name = model_name
        self._report_counter = 0

    def generate(
        self,
        root_cause_result,
        retrieval_result=None,
        dmesg_content: str = "",
        vmcore_path: str = "",
    ) -> DiagnosisReport:
        """生成诊断报告

        Args:
            root_cause_result: RootCauseResult 对象 (来自 analyzer)
            retrieval_result: RetrievalResult 对象 (来自 retriever, 可选)
            dmesg_content: 原始 dmesg 日志
            vmcore_path: vmcore 路径

        Returns:
            DiagnosisReport 对象
        """
        self._report_counter += 1
        report_id = f"LKR-{datetime.now().strftime('%Y%m%d')}-{self._report_counter:04d}"

        # 提取信息
        feature = getattr(root_cause_result, "crash_feature", None)
        panic_msg = getattr(feature, "panic_msg", "") if feature else ""
        kernel_version = getattr(feature, "kernel_version", "") if feature else ""
        subsystem = getattr(feature, "subsystem", "unknown") if feature else "unknown"

        report = DiagnosisReport(
            report_id=report_id,
            crash_summary=dmesg_content[:2000] if dmesg_content else panic_msg,
            kernel_version=kernel_version,
            panic_type=self._classify_panic(panic_msg),
            affected_subsystem=subsystem,
            root_cause=getattr(root_cause_result, "root_cause", ""),
            bug_type=getattr(root_cause_result, "bug_type", "unknown"),
            causal_chain=list(getattr(root_cause_result, "causal_chain", [])),
            confidence=getattr(root_cause_result, "score", 0.0),
            severity=getattr(root_cause_result, "get_severity_label", lambda: "UNKNOWN")(),
            analysis_mode="hybrid" if self.use_llm else "rule_only",
        )

        # 提取补丁推荐
        if retrieval_result:
            report.recommended_patches = []
            report.alternative_patches = []
            ranked_items = getattr(retrieval_result, "ranked_items", [])
            for item in ranked_items[:10]:
                report.recommended_patches.append({
                    "rank": getattr(item, "rank", 0),
                    "commit_hash": getattr(item, "commit_hash", ""),
                    "subject": getattr(item, "subject", ""),
                    "subsystem": getattr(item, "subsystem", "unknown"),
                    "bug_type": getattr(item, "bug_type", "unknown"),
                    "vector_score": getattr(item, "vector_score", 0.0),
                    "reranker_score": getattr(item, "reranker_score", 0.0),
                    "llm_judge_score": getattr(item, "llm_judge_score", 0.0),
                    "final_score": getattr(item, "final_score", 0.0),
                    "rank_reason": getattr(item, "rank_reason", ""),
                })

        # LLM 增强
        if self.use_llm and retrieval_result:
            self._enhance_with_llm(report, root_cause_result, retrieval_result)

        return report

    def _classify_panic(self, panic_msg: str) -> str:
        """从 panic 消息中分类 panic 类型"""
        msg = panic_msg.lower()
        if "kernel panic" in msg:
            if "out of memory" in msg or "oom" in msg:
                return "Kernel Panic (OOM)"
            if "vfs" in msg or "filesystem" in msg:
                return "Kernel Panic (VFS)"
            return "Kernel Panic"
        if "kernel oops" in msg or "oops:" in msg:
            return "Kernel Oops"
        if "kernel bug" in msg or "bug:" in msg:
            return "Kernel BUG"
        if "kasan" in msg:
            return "KASAN Report"
        if "lockdep" in msg:
            return "Lockdep Report"
        if "rcu stall" in msg:
            return "RCU Stall"
        if "hung task" in msg or "hung_task" in msg:
            return "Hung Task"
        if "hard lockup" in msg or "hardlockup" in msg:
            return "Hard Lockup"
        if "soft lockup" in msg or "softlockup" in msg:
            return "Soft Lockup"
        if "mce" in msg:
            return "Machine Check Exception"
        if "gpf" in msg:
            return "General Protection Fault"
        return "Unknown"

    def _enhance_with_llm(
        self,
        report: DiagnosisReport,
        root_cause_result,
        retrieval_result,
    ):
        """使用 LLM 增强报告"""
        try:
            llm = get_llm_client(model=self.model_name)

            # 生成执行摘要
            summary_prompt = self._build_summary_prompt(report)
            report.llm_executive_summary = llm.chat(
                summary_prompt,
                system_prompt="You are a technical report writer. Write concisely.",
                max_tokens=500,
            )

            # 生成详细分析
            if report.recommended_patches:
                analysis_prompt = self._build_analysis_prompt(report, root_cause_result)
                report.llm_detailed_analysis = llm.chat(
                    analysis_prompt,
                    system_prompt="You are a Linux kernel expert.",
                    max_tokens=1000,
                )

                # 生成修复解释
                top_patch = report.recommended_patches[0]
                fix_prompt = build_patch_explanation_prompt(
                    crash_analysis=report.crash_summary,
                    patch_subject=top_patch.get("subject", ""),
                    patch_diff=top_patch.get("metadata", {}).get("diff_content", ""),
                    root_cause=report.root_cause,
                )
                report.llm_fix_explanation = llm.chat(
                    fix_prompt,
                    system_prompt="You are a Linux kernel expert.",
                    max_tokens=800,
                )

        except Exception as e:
            report.extra_info["llm_enhancement_error"] = str(e)

    def _build_summary_prompt(self, report: DiagnosisReport) -> str:
        """构造摘要 prompt"""
        return f"""Write a 2-3 sentence executive summary of this kernel crash diagnosis:

- Severity: {report.severity}
- Subsystem: {report.affected_subsystem}
- Root Cause: {report.root_cause}
- Bug Type: {report.bug_type}
- Confidence: {report.confidence:.0%}
- Top Patch: {report.recommended_patches[0].get('subject', 'N/A') if report.recommended_patches else 'None found'}

Be concise and actionable."""

    def _build_analysis_prompt(self, report: DiagnosisReport, root_cause_result) -> str:
        """构造分析 prompt"""
        patches_info = ""
        for p in report.recommended_patches[:3]:
            patches_info += f"- [{p.get('rank')}] {p.get('subject', '')} (score: {p.get('final_score', 0):.3f})\n"

        return f"""Analyze why the top patch recommendations are relevant to this crash:

Root Cause: {report.root_cause}
Bug Type: {report.bug_type}
Causal Chain: {' -> '.join(report.causal_chain) if report.causal_chain else 'N/A'}

Top Matches:
{patches_info}

Explain the causal connection between the crash and the recommended fixes."""


# ============================================================================
# 便捷函数
# ============================================================================

def generate_report(
    root_cause_result,
    retrieval_result=None,
    dmesg_content: str = "",
    use_llm: bool = False,
    output_format: str = "markdown",
) -> Union[str, Dict[str, Any]]:
    """便捷函数: 一站式报告生成

    Args:
        root_cause_result: RootCauseResult 对象
        retrieval_result: RetrievalResult 对象 (可选)
        dmesg_content: dmesg 日志
        use_llm: 是否使用 LLM 增强
        output_format: "markdown" / "json" / "dict"

    Returns:
        Markdown 字符串 / JSON 字符串 / 字典
    """
    generator = ReportGenerator(use_llm=use_llm)
    report = generator.generate(
        root_cause_result=root_cause_result,
        retrieval_result=retrieval_result,
        dmesg_content=dmesg_content,
    )

    if output_format == "json":
        return report.to_json()
    elif output_format == "dict":
        return report.to_dict()
    else:
        return report.to_markdown()


def generate_patch_comparison_table(
    patches: List[Dict[str, Any]],
    include_reason: bool = True,
) -> str:
    """生成补丁对比的 Markdown 表格

    Args:
        patches: 补丁列表
        include_reason: 是否包含推荐理由

    Returns:
        Markdown 表格
    """
    if not patches:
        return "*(No patches to compare)*"

    header = "| # | Commit | Subsys | BugType | Score | Subject"
    sep = "|---|--------|--------|---------|-------|--------"
    if include_reason:
        header += " | Reason |"
        sep += "---|"

    lines = [header, sep]

    for item in patches[:20]:
        rank = item.get("rank", "?")
        commit = item.get("commit_hash", "N/A")[:10]
        subsys = item.get("subsystem", "-")[:8]
        bug = item.get("bug_type", "-")[:8]
        score = item.get("final_score", item.get("score", 0))
        subject = item.get("subject", "N/A")[:60]

        row = f"| {rank} | `{commit}` | {subsys} | {bug} | {score:.3f} | {subject}"
        if include_reason:
            reason = item.get("rank_reason", "-")[:50]
            row += f" | {reason} |"

        lines.append(row)

    return "\n".join(lines)


__all__ = [
    # 数据结构
    "DiagnosisReport",
    # 生成器
    "ReportGenerator",
    # 便捷函数
    "generate_report",
    "generate_patch_comparison_table",
]
