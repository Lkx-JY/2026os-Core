"""证据驱动 Prompt — 防幻觉 + 专业化 (基于评审反馈优化).

独立文件以避免编码问题。由 prompt/__init__.py 导入。
"""

from typing import List, Dict, Any, Optional


def build_evidence_aware_report_prompt(
    crash_feature: Any,
    root_cause_result: Any,
    patch_explanations: List[Any],
    kernel_version: str = "",
    evidence_summary: str = "",
    evidence_summary_table: str = "",
    score_breakdown: "Optional[Dict[str, Any]]" = None,
) -> str:
    """构造证据驱动的报告生成 Prompt.

    Priority 1: 禁止 LLM 编造函数名/调用链/结构体/修复代码
    Priority 2: 推荐理由全部引用已有分析结果, 缺失信息明确标注
    Priority 4: 增加「本分析基于以下证据」声明
    Priority 5: Evidence Summary 表格

    Args:
        crash_feature: CrashFeature object
        root_cause_result: RootCauseResult object
        patch_explanations: List[PatchExplain] structured patch evidence
        kernel_version: kernel version string
        evidence_summary: evidence summary text (Part 4)
        evidence_summary_table: evidence summary markdown table (Priority 5)
        score_breakdown: score breakdown dict
    """
    crash_subsystem = getattr(crash_feature, "subsystem", "unknown") if crash_feature else "unknown"
    crash_bug_type = getattr(root_cause_result, "bug_type", "unknown") if root_cause_result else "unknown"
    crash_root_cause = getattr(root_cause_result, "root_cause", "unknown") if root_cause_result else "unknown"
    crash_confidence = getattr(root_cause_result, "score", 0.0) if root_cause_result else 0.0
    crash_trace = getattr(crash_feature, "call_trace", []) if crash_feature else []
    crash_panic = getattr(crash_feature, "panic_msg", "") if crash_feature else ""
    rule_id = (getattr(root_cause_result, "extra_info", {}) or {}).get("rule_id", "unknown") if root_cause_result else "unknown"

    # Check what evidence is available vs missing
    has_call_trace = bool(crash_trace)
    has_kernel_version = bool(kernel_version and kernel_version != "not detected")

    # ==================================================================
    # Priority 1+2+4: Anti-hallucination System Prompt
    # ==================================================================
    system_prompt = (
        "You are a Linux Kernel Maintainer reviewing automated crash analysis results.\n\n"
        "The system has ALREADY completed:\n"
        "  (1) Crash Log parsing via regex + 28 expert rules\n"
        "  (2) Root Cause identification (Rule ID: " + str(rule_id) + ")\n"
        "  (3) TopK Patch retrieval (BGE-M3 embedding + BGE-Reranker-v2 + Version filter)\n\n"
        "Your task is NOT to re-analyze the Root Cause.\n"
        "Your task is to EXPLAIN why these Patches match, based ONLY on the evidence provided below.\n\n"
        "=== CRITICAL: Anti-Hallucination Rules (MUST follow) ===\n\n"
        "ALLOWED to reference (ONLY these fields):\n"
        "  - Commit Title (subject)\n"
        "  - Commit Message (body)\n"
        "  - changed_functions (if present in the evidence)\n"
        "  - changed_files (if present in the evidence)\n"
        "  - Root Cause label\n"
        "  - Bug Type\n"
        "  - Subsystem\n"
        "  - Expert Rule ID\n"
        "  - Embedding score\n"
        "  - Rerank score\n\n"
        "FORBIDDEN (DO NOT do any of these):\n"
        "  - DO NOT guess function names not listed in changed_functions\n"
        "  - DO NOT guess call chains\n"
        "  - DO NOT guess struct members (e.g. 'address 0x28 belongs to Qdisc struct')\n"
        "  - DO NOT guess fix code (e.g. 'add if (!ptr) check in register_qdisc')\n"
        "  - DO NOT explain NULL Pointer / Deadlock / UAF concepts or principles\n"
        "  - DO NOT re-guess Bug Type or Root Cause\n"
        "  - DO NOT invent any information not present in the evidence fields\n\n"
        "IF information is NOT available in the provided evidence:\n"
        "  - Say: '[specific field] is not available, cannot determine [specific conclusion]'\n"
        "  - Example: 'changed_functions is not provided for this Patch, "
        "therefore the exact fix target function cannot be determined'\n"
        "  - Example: 'Call Trace is missing from crash log, "
        "therefore struct member inference is not possible'\n\n"
        "Recommendation reasons MUST cite existing analysis results.\n"
        "DO NOT introduce information that does not exist in the evidence.\n\n"
        "When Version is unknown, state: 'Kernel Version information is missing, "
        "not used in ranking.'\n"
        "When Call Trace is missing, state: 'Call Trace is missing, "
        "not used in ranking.'\n\n"
        "Output language: Chinese. Keep technical terms in English.\n"
    )

    # ==================================================================
    # Crash Summary
    # ==================================================================
    call_trace_display = ', '.join(crash_trace[:5]) if has_call_trace else "(Call Trace missing)"
    kv_display = kernel_version if has_kernel_version else "Unknown (not used in ranking)"

    crash_text = (
        "## Crash Information\n\n"
        f"Bug Type: {crash_bug_type}\n"
        f"Root Cause: {crash_root_cause}\n"
        f"Expert Rule: {rule_id}\n"
        f"Subsystem: {crash_subsystem}\n"
        f"Confidence: {crash_confidence:.0%}\n"
        f"Kernel Version: {kv_display}\n"
        f"Call Trace: {call_trace_display}\n"
        f"Panic Info: {crash_panic[:200]}\n"
    )

    # ==================================================================
    # TopK Evidence
    # ==================================================================
    if not patch_explanations:
        patches_text = (
            "\n## Search Results\n\n"
            "(No matching patches found)\n"
        )
        task_text = (
            "\n## Task\n\n"
            "Explain analysis result based on crash info above. "
            "Mark as 'no matching patch found, suggest manual analysis'.\n"
        )
    else:
        patches_text = "## Search Results (TopK Patches)\n\n"
        for i, p in enumerate(patch_explanations):
            reasons = "\n".join(f"  + {r}" for r in p.confidence_reason) if p.confidence_reason else "  (none available)"

            # Priority 1: If no changed_functions, explicitly label it
            funcs_display = ', '.join(p.changed_functions[:5]) if p.changed_functions else "(changed_functions not provided)"

            patches_text += (
                f"### Top{i+1} -- Score: {p.final_score:.1f}\n\n"
                f"Commit: {p.commit[:12]}\n"
                f"Subject: {p.subject}\n"
                f"Subsystem: {p.subsystem} | Bug Type: {p.bug_type}\n"
                f"Fix Target: {p.fix_target if p.fix_target else '(not provided)'}\n"
                f"Fix Method: {p.fix_method}\n"
                f"Affected Path: {p.affected_path}\n"
                f"Changed Functions: {funcs_display}\n"
                f"Changed Files: {', '.join(p.changed_files[:5]) if p.changed_files else '(not provided)'}\n"
                f"Kernel Version: {p.kernel_version if p.kernel_version else 'Unknown'}\n"
                f"Fix Tags: {', '.join(p.fix_tags[:5]) if p.fix_tags else '(none)'}\n"
                f"Embedding Similarity: {p.vector_score:.3f} | Rerank Score: {p.reranker_score:.3f} | Final: {p.final_score:.2f}\n"
                f"\nMatch Reasons:\n{reasons}\n\n"
                f"Commit Message:\n{p.commit_message[:300]}\n\n"
            )

        # Patch Comparison Table
        from ..patch_explain import build_patch_comparison
        comparison = build_patch_comparison(patch_explanations)
        if comparison:
            patches_text += "## Patch Comparison\n\n"
            n = len(patch_explanations)
            patches_text += "| Dimension | " + " | ".join(f"Top{j+1}" for j in range(n)) + " |\n"
            patches_text += "|" + "|".join(["---"] * (n + 1)) + "|\n"
            for row in comparison:
                vals = [row["维度"]] + [row.get(f"Top{j+1}", "") for j in range(n)]
                patches_text += "| " + " | ".join(vals) + " |\n"

            patches_text += "\n"
            for i, p in enumerate(patch_explanations):
                same = [r for r in (p.confidence_reason or [])]
                diff = []
                if p.subsystem != crash_subsystem:
                    diff.append(f"subsystem differs ({p.subsystem} vs {crash_subsystem})")
                if p.bug_type != crash_bug_type:
                    diff.append(f"bug_type differs ({p.bug_type} vs {crash_bug_type})")
                s = "; ".join(same) if same else "(no match data)"
                d = "; ".join(diff) if diff else "(no difference data)"
                patches_text += f"Top{i+1} matches: {s} | differs: {d}\n"

        patches_text += "\n"

    # ==================================================================
    # Priority 5: Evidence Summary Table
    # ==================================================================
    if evidence_summary_table:
        patches_text += f"## Evidence Summary\n\n{evidence_summary_table}\n"

    # ==================================================================
    # Priority 4: Evidence Citations
    # ==================================================================
    if evidence_summary:
        patches_text += f"## Evidence Chain\n\n{evidence_summary}\n"

    # ==================================================================
    # Priority 4: Evidence basis declaration
    # ==================================================================
    available_evidence = ["Expert Rule ({})".format(rule_id), "Embedding Similarity", "Cross Encoder Rerank", "Commit Metadata"]
    unavailable_evidence = []
    if not has_call_trace:
        unavailable_evidence.append("Call Trace")
    if not has_kernel_version:
        unavailable_evidence.append("Kernel Version")

    evidence_basis = (
        "\n## Analysis Evidence Basis\n\n"
        "This analysis is based on the following evidence:\n\n"
    )
    for ev in available_evidence:
        evidence_basis += f"  + {ev}\n"
    if unavailable_evidence:
        evidence_basis += f"\nThe following information is NOT available in the current crash log:\n\n"
        for ev in unavailable_evidence:
            evidence_basis += f"  - {ev}\n"
        evidence_basis += f"\nTherefore, the final recommendation is primarily based on the available evidence listed above.\n"

    patches_text += evidence_basis + "\n"

    # ==================================================================
    # Priority 1+2+6: Fixed Output Template with anti-hallucination rules
    # ==================================================================
    if patch_explanations:
        task_text = (
            "\n## Task\n\n"
            "Output report in the following STRICT structure:\n\n"
            "### (1) Crash Summary\n"
            "- Summarize key info from crash log\n"
            "- Bug Type / Subsystem / Fault Function\n"
            "- Max 100 words\n\n"
            "### (2) Search Result Analysis\n"
            "- Which dimensions did Top1 match? Why highest score?\n"
            "- How does Top2 differ from Top1?\n"
            "- Why is Top3 ranked lower?\n"
            "- **MUST reference specific fields from TopK evidence above**\n"
            "- **If a field is not provided, explicitly state it**\n\n"
            "### (3) Patch Comparison\n"
            "- Compare Top1/Top2/Top3 per dimension\n"
            "- Explain why Top1 ranks first\n\n"
            "### (4) Final Recommendation\n"
            "- Which Patch to recommend?\n"
            "- Reasons MUST cite match dimensions from evidence\n"
            "- If Top1 is credible, explain evidence; if not, explain gaps\n"
            "- **Add a brief inference**: Based on the match dimensions, explain WHY "
            "this combination of evidence makes Top1 the best candidate.\n"
            "  Example: 'Top1 matches on subsystem, Bug Type, and semantic similarity "
            "all three dimensions. Combined with the highest Cross Encoder rerank score, "
            "this indicates Top1 has the strongest overall relevance to the current crash scenario.'\n"
            "- **Recommendation reasons must reference existing analysis results**\n"
            "- **Do NOT introduce information not present in the evidence**\n\n"
            "### (5) Fix Suggestions\n"
            "- Refer to the fix approach adopted by the recommended Top1 Patch\n"
            "- Based on the Patch description, the fix method is: [fix_method from evidence]\n"
            "- If changed_functions ARE provided: list them as 'Patch modified functions', NOT as 'fix target'.\n"
            "  These are functions that were modified in this commit, "
            "but they are NOT necessarily the crash trigger point.\n"
            "  Example: 'This Patch modified: register_qdisc, unregister_qdisc, qdisc_get_default. "
            "These functions are the scope of this commit. "
            "Since the Crash log lacks Call Trace, "
            "it is not possible to determine which specific call path triggered the crash. "
            "Suggest reviewing the Patch Diff for the actual fix location.'\n"
            "- If changed_functions are NOT provided, state:\n"
            "  'changed_functions is not provided for this Patch.'\n"
            "- If Call Trace is missing, state: 'Due to Call Trace missing from crash log, "
            "cannot confirm which specific function triggered the crash.'\n"
            "- Do NOT give generic advice like 'add if check in function_X'\n"
            "- Do NOT suggest specific code modifications\n"
        )

    # ==================================================================
    # Score Breakdown (Priority 6 — kept, with raw score display)
    # ==================================================================
    score_text = ""
    if score_breakdown:
        weights = score_breakdown.get("weights", {})
        scores = score_breakdown.get("scores", {})
        rank_reasons = score_breakdown.get("rank_reasons", {})

        score_text = "\n## Score Composition\n\n"
        dim_names = list(weights.keys())
        sk = list(scores.keys())[:3]
        score_text += "| Dimension | Weight | " + " | ".join(sk) + " |\n"
        score_text += "|" + "|".join(["---"] * (len(sk) + 2)) + "|\n"
        for i, dim in enumerate(dim_names):
            vals = []
            for k in sk:
                slist = scores.get(k, [])
                # Priority 3: Show raw scores, not percentages
                vals.append(f"{slist[i]:.2f}" if i < len(slist) else "0.00")
            score_text += f"| {dim} | {weights[dim]:.0%} | " + " | ".join(vals) + " |\n"

        score_text += "\n**Top1 Ranking Reasons**:\n"
        top1_key = sk[0] if sk else ""
        for reason in rank_reasons.get(top1_key, []):
            score_text += f"+ {reason}\n"

    # ==================================================================
    # Assemble
    # ==================================================================
    prompt = system_prompt + "\n" + crash_text + "\n" + patches_text + task_text + score_text
    prompt += (
        "\n---\n"
        "FINAL WARNING: Output report directly. Do NOT explain concepts. "
        "Do NOT guess functions/structs/call-chains not in the evidence. "
        "If evidence is missing for a claim, explicitly state the limitation. "
        "Base ALL analysis on the Patch evidence data provided above.\n"
    )

    return prompt
