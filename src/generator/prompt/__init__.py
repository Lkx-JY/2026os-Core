"""Prompt 工程模块 — Prompt Engineering Layer

负责为不同场景构造高质量的大模型提示词。
支持报告生成、补丁解释、根因分析等场景的 prompt 模板。

设计要点:
- 场景化模板: 为不同任务提供专用模板
- Few-shot 示例: 包含内核领域的高质量示例
- 结构化约束: 确保 LLM 输出符合预期的 JSON 格式
- 领域知识注入: 将专家规则、子系统关系等知识融入 prompt
"""

from typing import List, Dict, Any, Optional


# ============================================================================
# Prompt 模板: 诊断报告生成
# ============================================================================

def build_diagnosis_report_prompt(
    crash_summary: str,
    root_cause: str,
    bug_type: str,
    causal_chain: List[str],
    confidence: float,
    top_patches: List[Dict[str, Any]],
    caller_context: str = "",
) -> str:
    """构造诊断报告生成的 prompt

    Args:
        crash_summary: 宕机摘要
        root_cause: 根因诊断
        bug_type: Bug 类型
        causal_chain: 因果推导链
        confidence: 置信度
        top_patches: 推荐补丁列表
        caller_context: 调用上下文 (可选)

    Returns:
        结构化的 prompt 文本
    """
    patches_text = ""
    for i, patch in enumerate(top_patches[:10], 1):
        patches_text += (
            f"  [{i}] {patch.get('commit_hash', 'N/A')[:12]} "
            f"subsystem={patch.get('subsystem', 'unknown')} "
            f"score={patch.get('final_score', 0):.3f}\n"
            f"      {patch.get('subject', 'N/A')[:120]}\n"
        )

    if not patches_text:
        patches_text = "  (No matching patches found)\n"

    causal_text = " -> ".join(causal_chain) if causal_chain else root_cause

    return f"""You are a senior Linux kernel crash analyst. Write a professional diagnosis report based on the following analysis.

## Crash Summary
{crash_summary[:2000]}

## Diagnostic Results
- **Root Cause**: {root_cause}
- **Bug Type**: {bug_type}
- **Confidence**: {confidence:.1%}
- **Causal Chain**: {causal_text}
{caller_context}

## Recommended Patches (Top Candidates)
{patches_text}

## Report Requirements
Write a comprehensive report with the following sections:

### 1. Executive Summary
A 2-3 sentence overview of the crash and recommended action.

### 2. Crash Analysis
- What happened at the moment of crash
- Key evidence from the call trace / panic message
- Affected kernel subsystem and code path

### 3. Root Cause Diagnosis
- Detailed root cause explanation
- Causal chain from symptom to root cause
- Why this particular bug type manifests this way

### 4. Fix Recommendation
- Top recommended patches with rationale
- Alternative fixes if applicable
- Verification steps after applying patches

### 5. Prevention Measures
- Code review guidelines for similar issues
- Testing recommendations (LTP, syzkaller, lockdep, KASAN, etc.)
- Kernel config hardening suggestions (if applicable)

## Style Guidelines
- Write in Chinese (primary language for this report)
- Technical terms in English are acceptable
- Be specific about kernel functions, structures, and mechanisms
- Include concrete code-level explanations when possible
- Use tables for patch comparison

Output the report directly, no preamble."""


def build_patch_explanation_prompt(
    crash_analysis: str,
    patch_subject: str,
    patch_diff: str,
    root_cause: str,
) -> str:
    """构造补丁解释的 prompt

    用于解释为什么某个补丁能够修复当前问题。

    Args:
        crash_analysis: 崩溃分析
        patch_subject: 补丁标题
        patch_diff: 补丁 diff 内容
        root_cause: 根因诊断

    Returns:
        prompt 文本
    """
    return f"""You are a Linux kernel expert. Explain how the following patch fixes the crash issue.

## Crash Analysis
{crash_analysis[:1500]}

## Root Cause
{root_cause}

## Candidate Patch
**Subject**: {patch_subject}

**Diff**:
```
{patch_diff[:3000]}
```

## Instructions
Explain:
1. What the patch changes at the code level
2. How these changes address the root cause
3. Any potential side effects or risks of applying this patch
4. Whether this is a complete fix or partial workaround

Output a concise, technically precise explanation in Chinese with English technical terms."""


def build_causal_reasoning_prompt(
    crash_feature_text: str,
    candidate_patches: List[Dict[str, Any]],
    analysis_context: str = "",
) -> str:
    """构造因果推理的 prompt

    用于 LLM Judge 判断补丁与崩溃的因果关系。

    Args:
        crash_feature_text: 崩溃特征文本
        candidate_patches: 候选补丁列表
        analysis_context: 分析上下文

    Returns:
        prompt 文本
    """
    patches_text = ""
    for i, patch in enumerate(candidate_patches):
        patches_text += (
            f"[{i}] subsystem={patch.get('subsystem', 'unknown')} "
            f"bug_type={patch.get('bug_type', 'unknown')}\n"
            f"    {patch.get('subject', '')[:150]}\n"
        )

    return f"""You are a Linux kernel debugging expert. Analyze the causal relationship between a crash and candidate patches.

## Crash Information
{crash_feature_text[:2000]}
{analysis_context}

## Candidate Patches
{patches_text}

## Task
For each candidate patch, judge whether it truly fixes the root cause of the crash.
Consider:
1. Same subsystem and code path?
2. Same bug type and failure mode?
3. Does the fix pattern match the crash mechanism?
4. Are the affected functions/structures related?

Output a JSON array:
[{{"index": 0, "score": 0.85, "relevant": true, "reason": "..."}}, ...]

Score: 0.9-1.0 = exact fix, 0.7-0.8 = strong match, 0.5-0.6 = partial, <0.5 = unrelated"""


# ============================================================================
# Prompt 模板: 根因分析增强
# ============================================================================

def build_root_cause_analysis_prompt(
    dmesg_content: str,
    call_trace: List[str],
    panic_msg: str,
    kernel_version: str = "",
    loaded_modules: Optional[List[str]] = None,
) -> str:
    """构造根因分析的 LLM prompt

    用于 hybrid_root_cause_analysis 中调用 LLM。

    Args:
        dmesg_content: dmesg 日志内容
        call_trace: 调用栈
        panic_msg: Panic 消息
        kernel_version: 内核版本
        loaded_modules: 已加载模块

    Returns:
        prompt 文本
    """
    trace_text = "\n".join(call_trace[:20]) if call_trace else "(none)"
    modules_text = ", ".join(loaded_modules[:15]) if loaded_modules else "(none)"

    return f"""You are a Linux kernel crash analyst. Analyze the following kernel crash and determine the root cause.

## Kernel Information
- Version: {kernel_version or "unknown"}
- Loaded Modules: {modules_text}

## Panic / Oops Message
{panic_msg[:1000]}

## Call Trace
```
{trace_text}
```

## Full dmesg
```
{dmesg_content[:3000]}
```

## Analysis Instructions
Perform a systematic analysis:

### Step 1: Identify the crash type
- What kind of crash? (panic, Oops, BUG, lockdep, KASAN, etc.)
- What is the immediate failing condition?

### Step 2: Analyze the call trace
- Which functions are in the call path?
- Identify lock operations, memory operations, RCU operations
- Look for known dangerous patterns (lock in IRQ, double free, UAF, etc.)

### Step 3: Determine root cause
- What is the underlying bug type? (deadlock, UAF, null pointer, race condition, etc.)
- Which subsystem is affected? (mm, fs, net, kernel, drivers, etc.)
- What is the causal chain from root cause to crash?

### Step 4: Suggest fix strategy
- What kind of fix is needed? (add lock, fix refcount, add RCU sync, null check, etc.)
- What search keywords would find similar fixes?

## Output Format (JSON only)
```json
{{
  "root_cause": "Concise root cause description (1-2 sentences)",
  "bug_type": "one of: use_after_free, null_pointer, deadlock, race_condition, buffer_overflow, memory_leak, memory_corruption, double_free, out_of_bound, hang, crash, security, other",
  "causal_chain": ["step 1", "step 2", "step 3"],
  "affected_subsystem": "mm/fs/net/kernel/drivers/arch/etc.",
  "key_functions": ["func1", "func2"],
  "fix_pattern": "add_lock / fix_refcount / add_rcu_sync / add_null_check / fix_bound_check / other",
  "suggested_keywords": ["kw1", "kw2", "kw3"],
  "score": 0.85,
  "severity": "CRITICAL/HIGH/MEDIUM/LOW",
  "reason": "Detailed explanation in Chinese"
}}
```"""


# ============================================================================
# Few-shot 示例
# ============================================================================

FEW_SHOT_EXAMPLES = {
    "use_after_free": """
## Example: Use-After-Free Analysis

**Crash**: KASAN: use-after-free in kfree_skb
**Call Trace**:
  kfree_skb+0x45/0x230
  tcp_rcv_established+0x5d2/0x8a0
  tcp_v4_do_rcv+0x1b3/0x3e0

**Analysis**:
- Root Cause: Race condition between TCP receive path and socket close leading to UAF on sk_buff
- Bug Type: use_after_free
- Causal Chain: socket close frees sk_buff -> TCP receive still holds reference -> UAF
- Fix Pattern: add_refcount — add skb_get() before queuing in receive path
- Search Keywords: kfree_skb, use after free, tcp_rcv_established, socket close race
""",

    "deadlock": """
## Example: Spinlock Deadlock Analysis

**Crash**: NMI watchdog: BUG: soft lockup - CPU#3 stuck for 23s!
**Call Trace**:
  queued_spin_lock_slowpath+0x16b/0x360
  _raw_spin_lock_irqsave+0x46/0x60
  shrink_inactive_list+0x335/0x8d0
  ...

**Analysis**:
- Root Cause: ABBA deadlock between shrink_inactive_list (holding lru_lock, waiting for i_pages) and page fault handler (holding i_pages, waiting for lru_lock)
- Bug Type: deadlock
- Causal Chain: memory reclaim acquires lru_lock -> tries to lock i_pages -> page fault holds i_pages -> tries to lock lru_lock -> ABBA deadlock
- Fix Pattern: fix_lock_ordering — reverse the lock acquisition order in reclaim path
- Search Keywords: shrink_inactive_list, lru_lock, deadlock, ABBA, page fault
""",
}


def get_few_shot_example(bug_type: str) -> str:
    """获取指定 bug 类型的 few-shot 示例

    Args:
        bug_type: Bug 类型

    Returns:
        few-shot 示例文本
    """
    if bug_type in FEW_SHOT_EXAMPLES:
        return FEW_SHOT_EXAMPLES[bug_type]

    # 模糊匹配
    for key, example in FEW_SHOT_EXAMPLES.items():
        if key in bug_type or bug_type in key:
            return example

    return ""


# ============================================================================
# Prompt 模板: RAG 解释生成
# ============================================================================

def build_rag_explanation_prompt(
    dmesg_content: str,
    root_cause: Any,
    patches: List[Any],
) -> str:
    """构造 RAG 解释的 prompt

    用于 LLM 基于检索结果生成完整的分析解释。

    Args:
        dmesg_content: dmesg 日志内容
        root_cause: RootCauseInfo 对象
        patches: MatchedPatch 列表

    Returns:
        prompt 文本
    """
    patches_text = ""
    for i, patch in enumerate(patches[:5], 1):
        commit = getattr(patch, 'commit', None)
        patches_text += f"""  [{i}] {getattr(commit, 'subject', 'N/A')}
      Commit: {getattr(commit, 'commit_hash', 'N/A')[:12]}
      Subsystem: {getattr(commit, 'subsystem', 'unknown')}
      Score: {getattr(patch, 'relevance_score', 0):.3f}
      Reason: {getattr(patch, 'match_reason', '')}
"""

    if not patches_text:
        patches_text = "  (No matching patches found)\n"

    return f"""You are a senior Linux kernel crash analyst. Provide a comprehensive explanation based on the following analysis.

## Crash Log (dmesg)
{dmesg_content[:2000]}

## Root Cause Analysis
- **Root Cause**: {getattr(root_cause, 'root_cause', 'unknown')}
- **Subsystem**: {getattr(root_cause, 'subsystem', 'unknown')}
- **Confidence**: {getattr(root_cause, 'confidence', 0):.1%}
- **Summary**: {getattr(root_cause, 'summary', '')}
- **Key Symptoms**: {', '.join(getattr(root_cause, 'key_symptoms', []))}

## Recommended Patches
{patches_text}

## Task
Write a comprehensive analysis explanation in Chinese that includes:

1. **Crash Overview** - A brief summary of what happened
2. **Root Cause Explanation** - Detailed explanation of the root cause
3. **Patch Recommendations** - Explain why each recommended patch is relevant
4. **Fix Strategy** - What needs to be done to fix this issue
5. **Prevention Suggestions** - How to prevent similar issues

Write in a clear, technical yet accessible style. Use English technical terms where appropriate."""


# ============================================================================
# Prompt 工具函数
# ============================================================================

def truncate_for_prompt(text: str, max_chars: int = 3000) -> str:
    """截断文本以适应 prompt 长度限制

    保留开头和结尾，中间用 ... 表示截断。

    Args:
        text: 原文
        max_chars: 最大字符数

    Returns:
        截断后的文本
    """
    if len(text) <= max_chars:
        return text
    head = text[:max_chars * 2 // 3]
    tail = text[-max_chars // 3:]
    return f"{head}\n...(truncated)...\n{tail}"


def format_call_trace_for_prompt(call_trace: List[str], max_frames: int = 15) -> str:
    """格式化调用栈用于 prompt

    Args:
        call_trace: 调用栈帧列表
        max_frames: 最大保留帧数

    Returns:
        格式化的调用栈文本
    """
    if not call_trace:
        return "(no call trace)"

    frames = call_trace[:max_frames]
    return "\n".join(f"  {f}" for f in frames)


def build_system_prompt(role: str = "kernel_expert") -> str:
    """构造系统提示词

    Args:
        role: 角色 — "kernel_expert" / "report_writer" / "code_reviewer"

    Returns:
        系统提示词
    """
    prompts = {
        "kernel_expert": (
            "You are a senior Linux kernel developer with 20 years of experience. "
            "You specialize in debugging kernel crashes, analyzing memory corruption, "
            "deadlocks, race conditions, and all forms of kernel bugs. "
            "You are familiar with the Linux kernel's memory management (mm), "
            "file systems (fs), networking (net), block layer, locking primitives, "
            "RCU, and all major subsystems. "
            "Your analysis is precise, evidence-based, and helpful for kernel developers."
        ),
        "report_writer": (
            "You are a technical writer specializing in Linux kernel crash reports. "
            "You can explain complex kernel issues clearly to both experienced kernel "
            "developers and system administrators. "
            "Your reports are structured, well-organized, and include actionable recommendations."
        ),
        "code_reviewer": (
            "You are a Linux kernel code reviewer. You can identify bugs, race conditions, "
            "locking issues, memory leaks, and security vulnerabilities by reading kernel patches. "
            "You provide constructive feedback with specific code references."
        ),
    }
    return prompts.get(role, prompts["kernel_expert"])


__all__ = [
    # 报告生成
    "build_diagnosis_report_prompt",
    "build_patch_explanation_prompt",
    # RAG 解释
    "build_rag_explanation_prompt",
    # 因果推理
    "build_causal_reasoning_prompt",
    # 根因分析
    "build_root_cause_analysis_prompt",
    # 示例
    "FEW_SHOT_EXAMPLES",
    "get_few_shot_example",
    # 工具
    "truncate_for_prompt",
    "format_call_trace_for_prompt",
    "build_system_prompt",
]
