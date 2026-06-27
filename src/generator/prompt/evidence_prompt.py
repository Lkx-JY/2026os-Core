"""证据驱动 Prompt — 严格的防幻觉生成约束 (12 条 Guardrails).

基于评审反馈优化: 杜绝 LLM 编造函数名、调用链、修复代码、开发者意图。
所有分析必须严格引用输入中已出现的证据，缺失信息标记为 Unknown。

独立文件以避免编码问题。由 prompt/__init__.py 导入。
"""

from typing import List, Dict, Any, Optional


# ============================================================================
# 核心约束规则 (12 条) — 直接写入 System Prompt
# ============================================================================

_GUARDRAILS = """
## LLM Generation Constraints (Must Follow — 最高优先级)

### 0. Evidence-First 原则
**所有分析必须严格依据输入日志、结构化分析结果及检索到的补丁内容进行。**
不允许推测日志中不存在的函数、变量、文件路径、Commit、调用栈或修复逻辑。
如果证据不足，应明确说明"无法确认"或"日志中未提供足够信息"，不得自行补充。

### 1. 函数名白名单
仅允许引用以下来源中的函数名:
  ✓ Kernel Log 中出现的函数 (Call Trace / RIP / 错误地址)
  ✓ Commit Message 中出现的函数
  ✓ Diff 中出现的函数
  ✓ Root Cause JSON 中的函数
除此之外，**禁止生成任何新的函数名**。

错误示例:
  日志只有 generic_hwtstamp_ioctl()
  → 禁止写: generic_ioctl(), net_rx(), mq_attach(), dev_queue_xmit()

### 2. Commit 解释限制
Patch Explanation 只能根据以下内容解释:
  ✓ Commit Message (subject + body)
  ✓ Diff 内容
  ✓ Patch Metadata
不得推测开发者意图，不得扩展为未经证据支持的根因分析。

错误示例:
  Commit 内容: "add NULL check"
  → 允许写: "补丁增加了 NULL 检查"
  → 禁止写: "开发者修复了生命周期竞争" (Commit 没说)

### 3. 调用栈分析限制
仅分析日志中实际出现的调用栈函数。
不得补全遗漏的调用链，不得假设内核执行路径。

错误示例:
  日志: A() → B() → panic
  → 只能分析: A→B→panic
  → 禁止补全为: A→C→B→panic

### 4. 版本限制
如果日志中没有 Kernel Version:
  → 应写: **Kernel Version: Unknown** — 由于日志中未提供 Kernel Version，无法确认补丁是否适用于当前版本。
如果日志中有 Kernel Version:
  → 只能引用该版本号，不得推测兼容性。

### 5. Diff 限制 (最容易幻觉)
从 Diff 解释补丁时:
  ✓ 允许: 描述 Diff 中实际出现的操作 (NULL 判断, 加锁, 释放等)
  ✗ 禁止: 推测 Diff 中不存在的问题 (引用计数、RCU、生命周期、锁竞争)
除非 Diff 中明确出现了对应的关键词 (refcount, kref, rcu, spinlock, mutex 等)。

### 6. Patch 推荐理由限制
推荐补丁的原因必须来自以下可量化的检索指标:
  ✓ Embedding Similarity (向量相似度)
  ✓ Reranker Score (交叉编码器重排分)
  ✓ Subsystem Match (子系统匹配)
  ✓ Bug Type Match (Bug 类型匹配)
  ✓ Kernel Version Match (版本匹配)
不得根据模型经验生成模糊描述。

禁止写: "这个 Patch 与当前问题完全一致"
应该写: "Embedding Similarity = 0.612, Reranker = 0.82, Subsystem 一致, Bug Type 一致, 因此排名第一"

### 7. Unknown 机制
当信息不足时，统一使用以下标记:
  - Root Cause: **Unknown** — 日志不足以定位具体原因
  - Function: **Unknown** — 日志中未出现该函数
  - Kernel Version: **Unknown** — 日志中未提供版本信息
  - Fix Target: **Insufficient Evidence** — 证据不足无法确定
不得自行猜测填充。

### 8. Evidence → Analysis → Conclusion 格式
每个分析结论必须遵循三段式:
  **Evidence** (证据是什么)
  ↓
  **Analysis** (分析过程)
  ↓
  **Conclusion** (结论)

示例:
  **Evidence**: BUG: unable to handle NULL pointer dereference
  **Analysis**: CPU 尝试访问地址 0x00000028，该地址属于 NULL 指针偏移
  **Conclusion**: 本次故障属于 Null Pointer Dereference

### 9. 可信度来源展示
最终的 Confidence 必须拆解为可追溯的子项:
  Expert Rule Match: +XX%
  Embedding Similarity: +XX%
  Call Trace Match: +XX%
  Subsystem Match: +XX%
  Patch Match: +XX%
  = Final: XX%

不得使用模型自己臆测的置信度数值 (如 95%, 99%)。

### 10. 严格限定实体引用范围
任何实体 (函数、文件、补丁、变量、错误码) 必须来源于以下之一:
  ① Kernel Log (调用栈 / panic 消息 / 错误地址)
  ② Root Cause JSON (根因分析结构化结果)
  ③ Retrieval Results (向量检索返回的 Commit)
  ④ Commit Metadata (commit 元数据)
  ⑤ Patch Diff (补丁的 diff 内容)
否则禁止生成。

### 11. 输出声明 (Evidence-Aware)
报告末尾必须包含:
  > **Analysis Scope**
  > 本报告采用 Evidence-Aware 分析策略，所有结论均基于当前输入的宕机日志、
  > 结构化分析结果、检索到的补丁信息及其 Diff 内容生成。
  > 对于日志中未提供或证据不足的信息，报告已明确标记为 **Unknown**
  > 或 **Insufficient Evidence**，未进行推测性补全。
"""


def build_evidence_aware_report_prompt(
    crash_feature: Any,
    root_cause_result: Any,
    patch_explanations: List[Any],
    kernel_version: str = "",
    evidence_summary: str = "",
    evidence_summary_table: str = "",
    score_breakdown: "Optional[Dict[str, Any]]" = None,
) -> str:
    """构造证据驱动的报告生成 Prompt，内置 12 条防幻觉约束。

    Args:
        crash_feature: CrashFeature object
        root_cause_result: RootCauseResult object
        patch_explanations: List[PatchExplain] structured patch evidence
        kernel_version: kernel version string
        evidence_summary: evidence summary text
        evidence_summary_table: evidence summary markdown table
        score_breakdown: score breakdown dict
    """
    # ── 提取关键信息 ──────────────────────────────────────────────
    crash_subsystem = getattr(crash_feature, "subsystem", "unknown") if crash_feature else "unknown"
    crash_bug_type = getattr(root_cause_result, "bug_type", "unknown") if root_cause_result else "unknown"
    crash_root_cause = getattr(root_cause_result, "root_cause", "unknown") if root_cause_result else "unknown"
    crash_confidence = getattr(root_cause_result, "score", 0.0) if root_cause_result else 0.0
    crash_trace = getattr(crash_feature, "call_trace", []) if crash_feature else []
    crash_panic = getattr(crash_feature, "panic_msg", "") if crash_feature else ""
    rule_id = (getattr(root_cause_result, "extra_info", {}) or {}).get("rule_id", "unknown") if root_cause_result else "unknown"

    has_call_trace = bool(crash_trace)
    has_kernel_version = bool(kernel_version and kernel_version != "not detected")

    # ==================================================================
    # System Prompt — 内置 12 条约束规则
    # ==================================================================
    system_prompt = (
        "You are a Linux Kernel Maintainer reviewing automated crash analysis results.\n"
        "Your task is ONLY to explain the evidence already gathered — NOT to perform new analysis.\n\n"
        "The automated system has ALREADY completed:\n"
        "  (1) Crash Log parsing (regex + 28 expert rules)\n"
        "  (2) Root Cause identification (Rule ID: " + str(rule_id) + ")\n"
        "  (3) TopK Patch retrieval (BGE-M3 embedding + BGE-Reranker-v2 + Version filter)\n"
        "  (4) Multi-dimensional scoring (7 dimensions with explainable weights)\n\n"
        + _GUARDRAILS +
        "\n"
        "Output language: Chinese. Keep technical terms (function names, commit IDs, file paths) in English.\n"
    )

    # ==================================================================
    # Crash Information — 明确标记可用的和缺失的证据
    # ==================================================================
    call_trace_display = ', '.join(crash_trace[:5]) if has_call_trace else "**Unknown** (Call Trace 缺失)"
    kv_display = kernel_version if has_kernel_version else "**Unknown** (日志中未提供 Kernel Version)"

    # 证据可用性标记
    evidence_status = []
    evidence_status.append("✓ Expert Rule ID: " + str(rule_id))
    evidence_status.append("✓ Bug Type: " + str(crash_bug_type))
    evidence_status.append("✓ Subsystem: " + str(crash_subsystem))
    evidence_status.append("✓ Confidence: " + str(round(crash_confidence * 100)) + "%")
    if has_call_trace:
        evidence_status.append("✓ Call Trace: " + str(len(crash_trace)) + " 个函数")
    else:
        evidence_status.append("✗ Call Trace: **缺失** — 无法进行调用栈级别的匹配")
    if has_kernel_version:
        evidence_status.append("✓ Kernel Version: " + kernel_version)
    else:
        evidence_status.append("✗ Kernel Version: **缺失** — 未用于排序")

    crash_text = (
        "## Crash Information\n\n"
        "### 可用证据清单\n"
        + "\n".join(evidence_status) + "\n\n"
        "### 原始信息\n"
        f"Panic Info: {crash_panic[:200]}\n"
        f"Call Trace: {call_trace_display}\n"
        f"Kernel Version: {kv_display}\n"
    )

    # ==================================================================
    # TopK Patch Evidence — 严格引用字段
    # ==================================================================
    if not patch_explanations:
        patches_text = (
            "\n## Search Results\n\n"
            "**(未找到匹配的补丁)**\n"
            "由于向量检索未返回结果，无法生成补丁分析。\n"
            "建议: 扩大搜索范围或手动分析 vmcore。\n"
        )
        task_text = (
            "\n## Task\n\n"
            "基于以上 Crash Information 给出简要分析。\n"
            "由于未找到匹配补丁，推荐手动分析路径:\n"
            "  1. 使用 drgn 分析 vmcore\n"
            "  2. 检查最近的内核邮件列表\n"
            "  3. 关注子系统 " + crash_subsystem + " 的最新 commit\n"
        )
    else:
        patches_text = "## Search Results (TopK Patches)\n\n"
        patches_text += (
            "**重要**: 以下每个字段的引用范围受到严格限制。\n"
            "函数名只能引用 Call Trace / Commit Message / Diff 中出现的名称。\n\n"
        )
        for i, p in enumerate(patch_explanations):
            reasons = "\n".join(f"  + {r}" for r in p.confidence_reason) if p.confidence_reason else "  (无可用的匹配理由)"

            funcs_display = ', '.join(p.changed_functions[:5]) if p.changed_functions else "**(changed_functions 未提供)**"

            patches_text += (
                f"### Top{i+1}\n\n"
                f"| 字段 | 值 |\n"
                f"|------|-----|\n"
                f"| Commit | `{p.commit[:12]}` |\n"
                f"| Subject | {p.subject} |\n"
                f"| Subsystem | {p.subsystem} |\n"
                f"| Bug Type | {p.bug_type} |\n"
                f"| Fix Target | {p.fix_target if p.fix_target else '**未提供**'} |\n"
                f"| Fix Method | {p.fix_method} |\n"
                f"| Affected Path | {p.affected_path} |\n"
                f"| Changed Functions | {funcs_display} |\n"
                f"| Changed Files | {', '.join(p.changed_files[:5]) if p.changed_files else '**未提供**'} |\n"
                f"| Kernel Version | {p.kernel_version if p.kernel_version else '**Unknown**'} |\n"
                f"| Fix Tags | {', '.join(p.fix_tags[:5]) if p.fix_tags else '(无)'} |\n"
                f"| Embedding Similarity | {p.vector_score:.3f} |\n"
                f"| Reranker Score | {p.reranker_score:.3f} |\n"
                f"| Final Score | {p.final_score:.3f} |\n"
                f"\n"
                f"**匹配理由**:\n{reasons}\n\n"
                f"**Commit Message** (参考，不可推测 Message 中不存在的信息):\n"
                f"```\n{p.commit_message[:300]}\n```\n\n"
            )

        # Patch 对比表
        from ..patch_explain import build_patch_comparison
        comparison = build_patch_comparison(patch_explanations)
        if comparison:
            patches_text += "## Patch Comparison (量化对比)\n\n"
            n = len(patch_explanations)
            patches_text += "| Dimension | " + " | ".join(f"Top{j+1}" for j in range(n)) + " |\n"
            patches_text += "|" + "|".join(["---"] * (n + 1)) + "|\n"
            for row in comparison:
                vals = [row["维度"]] + [row.get(f"Top{j+1}", "") for j in range(n)]
                patches_text += "| " + " | ".join(vals) + " |\n"
            patches_text += "\n"

    # ==================================================================
    # Evidence Summary Table
    # ==================================================================
    if evidence_summary_table:
        patches_text += f"## Evidence Summary\n\n{evidence_summary_table}\n"

    # ==================================================================
    # Evidence Chain
    # ==================================================================
    if evidence_summary:
        patches_text += f"## Evidence Chain\n\n{evidence_summary}\n"

    # ==================================================================
    # Evidence Basis Declaration
    # ==================================================================
    available_evidence = [
        "Expert Rule (" + str(rule_id) + ")",
        "Embedding Similarity (BGE-M3)",
        "Cross Encoder Rerank (BGE-Reranker-v2)",
        "Commit Metadata (subject, body, subsystem, bug_type, files)",
    ]
    unavailable_evidence = []
    if not has_call_trace:
        unavailable_evidence.append("Call Trace — 无法进行调用栈级别匹配")
    if not has_kernel_version:
        unavailable_evidence.append("Kernel Version — 未用于排序")

    evidence_basis = "\n## Analysis Evidence Basis\n\n"
    evidence_basis += "本分析基于以下证据:\n\n"
    for ev in available_evidence:
        evidence_basis += f"  + {ev}\n"
    if unavailable_evidence:
        evidence_basis += f"\n以下信息在本次崩溃日志中**不可用**:\n\n"
        for ev in unavailable_evidence:
            evidence_basis += f"  - {ev}\n"
        evidence_basis += "\n因此最终推荐仅基于上述可用证据。\n"

    patches_text += evidence_basis + "\n"

    # ==================================================================
    # Task — 严格格式模板
    # ==================================================================
    if patch_explanations:
        task_text = (
            "\n## Task: 生成 Evidence-Aware 分析报告\n\n"
            "按以下严格结构输出报告。每个结论必须有 Evidence → Analysis → Conclusion 三段式。\n\n"
            "### (1) Crash Summary (崩溃概要)\n"
            "- 引用 Crash Information 中的可用证据\n"
            "- 明确标注缺失的信息 (如 Call Trace 缺失 / Kernel Version 未知)\n"
            "- 字数限制: 最多 100 字\n"
            "- 格式: Evidence → Analysis → Conclusion\n\n"
            "### (2) Root Cause Evidence (根因证据分析)\n"
            "- 列出触发根因判定的关键证据 (来自 Root Cause JSON 中的 matched_rule / panic_keyword / trace_functions)\n"
            "- 引用 Expert Rule ID 和匹配的规则名称\n"
            "- 如果 Call Trace 缺失: 写出 'Call Trace 缺失, 无法进行调用栈级别的根因确认'\n"
            "- 如果 Kernel Version 缺失: 写出 'Kernel Version 未知, 无法进行版本兼容性判断'\n"
            "- **严禁推测日志中不存在的调用链或函数名**\n\n"
            "### (3) TopK Patch 对比分析\n"
            "- 对 Top1/Top2/Top3 逐维度对比\n"
            "- **排名理由必须引用量化指标** (Embedding Similarity / Reranker Score / Subsystem Match / Bug Type Match)\n"
            "- 示例格式:\n"
            "  Top1 排名理由: Embedding Similarity = {分数}, Reranker = {分数},\n"
            "  Subsystem 一致 ({子系统名}), Bug Type 一致 ({Bug类型}), 因此排名第一。\n"
            "- Top2/3 的 Why-Not 解释:\n"
            "  Top2 差异: Reranker 分数低于 Top1 ({分数} vs {分数}), 版本兼容性为 Medium\n"
            "- **不得写模糊描述** (如 '完全匹配', '高度一致', '非常相似')\n"
            "- **所有对比必须基于上面 Patch Evidence 表格中的具体数值**\n\n"
            "### (4) Fix Approach Analysis (修复方案分析)\n"
            "- 仅基于 Commit Message 和 Diff 描述修复方式\n"
            "- 如果 changed_functions 已提供: 列出 '该补丁修改了以下函数: {函数列表}。这些是本次 commit 的修改范围, "
            "不一定是崩溃触发点。'\n"
            "- 如果 changed_functions 未提供: 写明 'changed_functions 未提供, 无法确定具体修改函数。'\n"
            "- 如果 Call Trace 缺失: 写明 '由于 Call Trace 缺失, 无法确认具体哪个调用路径触发了崩溃, "
            "建议审查 Patch Diff 确定实际修复位置。'\n"
            "- **不得给具体的代码修改建议** (如 '在函数X中添加 if 检查')\n"
            "- **不得推测 Diff 中不存在的问题** (如引用计数、RCU、生命周期等未在 Diff 中出现的关键词)\n\n"
            "### (5) Confidence Breakdown (可信度拆解)\n"
            "- 展示最终置信度的构成:\n"
            "  Expert Rule Match: +{rule_conf}%\n"
            "  Embedding Similarity: +{emb_conf}%\n"
            "  Call Trace Match: +{trace_conf}%\n"
            "  Subsystem Match: +{subsys_conf}%\n"
            "  = Final: {total_conf}%\n"
            "- 使用系统提供的数值, 不要自己编造\n\n"
            "### (6) 💡 Decision Recommendation & Risk Assessment (决策建议与风险评估)\n"
            "- **推荐操作**: 明确写出 '推荐优先应用 Top1 补丁 `{commit_id}` — {标题}'\n"
            "- **推荐理由**: 引用量化指标 (综合评分、Embedding、Reranker、Subsystem/BugType 匹配)\n"
            "- **与 Top2 的差距**: 如果差距 < 0.01，写明 '建议同时审查 Top2'；否则写明 'Top1 优势明确'\n"
            "- **建议调查流程**: 5 步操作表 (审查 Diff → 对比调用栈 → 检查版本 → 测试验证 → 合入)\n"
            "- **风险提示**:\n"
            "  - 如果 Call Trace / Kernel Version 缺失: 写明 '当前推荐应视为候选补丁排序，非确认修复方案，建议补充 X 信息后重新分析'\n"
            "  - 如果证据齐全: 写明 '当前分析的关键证据基本齐全，但建议在测试环境验证后再合入'\n"
            "- **局限性说明**: 明确列出当前分析的局限性（哪些证据缺失导致了什么影响）\n"
            "- 添加推断说明: 基于匹配维度的组合, 解释为什么 Top1 是最佳候选\n"
            "  示例: 'Top1 在 Subsystem, Bug Type 和 Semantic Similarity 三个维度都匹配, "
            "同时 Cross Encoder Rerank 分数最高, 表明 Top1 与当前崩溃场景的综合关联度最强。'\n\n"
            "### (7) Analysis Scope Declaration\n"
            "- 必须以固定模板结尾:\n"
            "  > **Analysis Scope**\n"
            "  > 本报告采用 Evidence-Aware 分析策略，所有结论均基于当前输入的宕机日志、\n"
            "  > 结构化分析结果、检索到的补丁信息及其 Diff 内容生成。\n"
            "  > 对于日志中未提供或证据不足的信息，报告已明确标记为 **Unknown**\n"
            "  > 或 **Insufficient Evidence**，未进行推测性补全。\n"
        )

    # ==================================================================
    # Score Breakdown
    # ==================================================================
    score_text = ""
    if score_breakdown:
        weights = score_breakdown.get("weights", {})
        scores = score_breakdown.get("scores", {})
        rank_reasons = score_breakdown.get("rank_reasons", {})

        score_text = "\n## Score Composition (多维评分构成)\n\n"
        dim_names = list(weights.keys())
        sk = list(scores.keys())[:3]
        score_text += "| Dimension | Weight | " + " | ".join(sk) + " |\n"
        score_text += "|" + "|".join(["---"] * (len(sk) + 2)) + "|\n"
        for i, dim in enumerate(dim_names):
            vals = []
            for k in sk:
                slist = scores.get(k, [])
                vals.append(f"{slist[i]:.3f}" if i < len(slist) else "N/A")
            score_text += f"| {dim} | {weights.get(dim, 0):.0%} | " + " | ".join(vals) + " |\n"

        score_text += "\n**Top1 Ranking Reasons** (量化依据):\n"
        top1_key = sk[0] if sk else ""
        for reason in rank_reasons.get(top1_key, []):
            score_text += f"+ {reason}\n"
        if not rank_reasons.get(top1_key):
            score_text += "(无可用的排名理由 — 可能由于证据缺失)\n"

    # ==================================================================
    # Assemble Final Prompt
    # ==================================================================
    prompt = system_prompt + "\n" + crash_text + "\n" + patches_text + task_text + score_text
    prompt += (
        "\n---\n"
        "**FINAL REMINDER**:\n"
        "- 所有结论必须有 Evidence 支撑\n"
        "- 缺失信息必须标记为 Unknown / Insufficient Evidence\n"
        "- 不得推测函数名、调用链、修复代码、开发者意图\n"
        "- 推荐理由必须引用量化检索指标\n"
        "- 每个分析结论使用 Evidence → Analysis → Conclusion 三段式\n"
        "- 报告末尾必须包含 Analysis Scope 声明\n"
    )

    return prompt
