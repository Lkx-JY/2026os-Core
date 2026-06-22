"""LLM 增强根因抽象模块 — LLM-Enhanced Root Cause Abstraction

在现有 28 条专家规则基础上，引入 LLM 进行更深层的根因推理。
LLM 和专家规则协同工作，互补优势:

专家规则的优势:
- 精确匹配已知模式，速度快
- 确定性输出，可回溯

LLM 的优势:
- 处理未知/复杂模式
- 理解上下文语义
- 生成人类可读的因果解释
- 跨子系统推理

协同策略:
- 规则匹配成功 (score >= 0.6): 以规则为主，LLM 补充因果推理
- 规则匹配失败 (score < 0.6): LLM 作为主分析引擎
- LLM 不可用: 纯规则作为降级方案
"""

import json
import re
from typing import Dict, Any, Optional, List, Tuple

from ..models import CrashFeature, RootCauseResult
from . import (
    RootCauseAnalyzer,
    abstract_root_cause,
    analyze_call_trace_structure,
    infer_fix_patterns,
    build_retrieval_query,
)


# LLM 根因分析系统提示
ROOT_CAUSE_LLM_SYSTEM_PROMPT = """You are a senior Linux kernel debugging expert with deep knowledge of:
- Memory management (mm): slab/slub allocators, page cache, folio, kasan, oom
- File systems (fs): VFS, ext4/xfs/btrfs, dentry/inode, writeback
- Networking (net): TCP/UDP stack, socket buffers, NAPI, netfilter
- Locking: spinlocks, mutexes, RCU, read-write locks, lockdep
- Scheduling: CFS, RT, workqueues, timers, preemption
- Interrupts: IRQ handling, softirqs, NMI watchdog

Given crash information, perform deep root cause analysis:
1. Trace the causal chain from symptom to root cause
2. Identify the exact kernel mechanism that failed
3. Determine what type of fix is needed
4. Construct an optimized retrieval query for finding matching patches

Output ONLY valid JSON with this exact structure:
{
    "root_cause": "<concise root cause diagnosis, e.g. 'RCU grace period stall due to missing rcu_read_unlock in error path'>",
    "bug_type": "<standardized bug type>",
    "causal_chain": ["<step 1: symptom>", "<step 2: immediate cause>", "<step 3: root cause>"],
    "score": <0.0-1.0 confidence>,
    "reason": "<detailed explanation for kernel engineers>",
    "severity": "<critical|high|medium|low>",
    "retrieval_query": "<optimized search query text for finding matching patches>",
    "suggested_keywords": ["<relevant search terms>"],
    "fix_patterns": {
        "needs_lock_fix": <true/false>,
        "needs_refcount_fix": <true/false>,
        "needs_rcu_fix": <true/false>,
        "needs_null_check": <true/false>,
        "needs_bound_check": <true/false>
    }
}

Guidelines:
- retrieval_query: Construct a natural language query that captures the ESSENCE of the bug, suitable for BGE-M3 embedding search. Include: root cause, bug type, affected subsystem, key functions, and fix pattern hints.
- causal_chain: At least 3 steps showing progressive reasoning from crash to root cause
- Be specific: instead of "memory corruption", say "list_del corruption caused by missing spin_lock in multi-CPU path"
- When uncertain, acknowledge it in the reason and lower the score"""


def build_root_cause_llm_prompt(feature: CrashFeature) -> str:
    """构造发送给 LLM 的根因分析提示

    结合 CrashFeature 中的所有可用信息构造完整的分析上下文。

    Args:
        feature: 从 dmesg/vmcore 提取的特征

    Returns:
        LLM prompt 文本
    """
    parts = []

    # 1. Panic/Oops 消息
    if feature.panic_msg:
        parts.append(f"## Crash/Panic Message:\n```\n{feature.panic_msg}\n```")

    # 2. 调用栈
    if feature.call_trace:
        trace_text = "\n".join(feature.call_trace[-30:])
        parts.append(f"## Call Trace (last 30 frames):\n```\n{trace_text}\n```")

    # 3. 子系统
    if feature.subsystem and feature.subsystem != "unknown":
        parts.append(f"## Affected Subsystem: {feature.subsystem}")

    # 4. Bug 类型 (初步推断)
    if feature.bug_type and feature.bug_type != "unknown":
        parts.append(f"## Preliminary Bug Type: {feature.bug_type}")

    # 5. 内核版本
    if feature.kernel_version:
        parts.append(f"## Kernel Version: {feature.kernel_version}")

    # 6. 已加载模块
    if feature.modules:
        parts.append(f"## Loaded Modules: {', '.join(feature.modules[:20])}")

    # 7. LLM 初步分析结果 (来自 dmesg 深度分析)
    llm_analysis = feature.extra_info.get("llm_analysis", {})
    if llm_analysis:
        llm_text = json.dumps(llm_analysis, ensure_ascii=False, indent=2)
        parts.append(f"## Preliminary LLM Analysis:\n```json\n{llm_text}\n```")

    # 8. 内核对象信息 (来自 vmcore)
    kernel_objects = feature.extra_info.get("kernel_objects", {})
    if kernel_objects:
        obj_text = json.dumps(kernel_objects, ensure_ascii=False, indent=2)
        parts.append(f"## Kernel Object State (from vmcore):\n```json\n{obj_text}\n```")

    prompt = "\n\n".join(parts)
    prompt += "\n\nPerform deep root cause analysis and output the JSON result."

    return prompt


def _call_llm_for_root_cause(
    system_prompt: str,
    user_prompt: str,
    model_name: str = "deepseek-chat",
    temperature: float = 0.1,
    max_tokens: int = 2048,
) -> str:
    """调用 LLM API 进行根因分析 — 委托给统一的 LLMClient"""
    try:
        from ...generator.llm import get_llm_client
        return get_llm_client().chat(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model_name,
        )
    except Exception as e:
        raise RuntimeError(f"LLM API call failed: {e}")


def _parse_root_cause_llm_response(
    response: str,
    feature: CrashFeature,
) -> Dict[str, Any]:
    """解析 LLM 返回的根因分析 JSON"""
    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            try:
                result = json.loads(json_match.group())
            except json.JSONDecodeError:
                return {"error": "Failed to parse LLM response", "raw": response[:500]}
        else:
            return {"error": "No JSON found in LLM response", "raw": response[:500]}

    return {
        "root_cause": str(result.get("root_cause", ""))[:500],
        "bug_type": str(result.get("bug_type", feature.bug_type))[:100],
        "causal_chain": list(result.get("causal_chain", []))[:10],
        "score": float(min(max(result.get("score", 0.5), 0.0), 1.0)),
        "reason": str(result.get("reason", ""))[:1000],
        "severity": str(result.get("severity", "medium"))[:20],
        "retrieval_query": str(result.get("retrieval_query", ""))[:2000],
        "suggested_keywords": list(result.get("suggested_keywords", []))[:10],
        "fix_patterns": dict(result.get("fix_patterns", {})),
    }


def llm_root_cause_analysis(
    feature: CrashFeature,
    model_name: str = "deepseek-chat",
) -> Dict[str, Any]:
    """使用 LLM 进行根因分析

    这是 LLM 根因分析的核心函数。
    接收 CrashFeature，返回包含根因诊断、因果链、检索查询的结构化结果。

    Args:
        feature: 从 dmesg/vmcore 提取的特征
        model_name: LLM 模型名称

    Returns:
        {
            "root_cause": str,
            "bug_type": str,
            "causal_chain": List[str],
            "score": float,
            "reason": str,
            "severity": str,
            "retrieval_query": str,
            "suggested_keywords": List[str],
            "fix_patterns": Dict[str, bool],
        }

    Example:
        >>> from src.analyzer.dmesg import parse_dmesg_with_llm
        >>> from src.analyzer.rootcause.llm_rootcause import llm_root_cause_analysis
        >>> feature = parse_dmesg_with_llm(dmesg_log)
        >>> result = llm_root_cause_analysis(feature)
        >>> print(result["root_cause"])
        >>> print(result["retrieval_query"])
    """
    # 构造提示
    prompt = build_root_cause_llm_prompt(feature)

    # 调用 LLM
    try:
        raw_response = _call_llm_for_root_cause(
            system_prompt=ROOT_CAUSE_LLM_SYSTEM_PROMPT,
            user_prompt=prompt,
            model_name=model_name,
        )
        result = _parse_root_cause_llm_response(raw_response, feature)
        return result
    except Exception as e:
        return {
            "root_cause": "",
            "bug_type": feature.bug_type,
            "causal_chain": [],
            "score": 0.0,
            "reason": f"LLM analysis failed: {e}",
            "severity": "medium",
            "retrieval_query": "",
            "suggested_keywords": [],
            "fix_patterns": {},
            "llm_error": str(e),
        }


# ============================================================================
# 协同分析器 — 专家规则 + LLM
# ============================================================================

def hybrid_root_cause_analysis(
    feature: CrashFeature,
    use_llm: bool = True,
    model_name: str = "deepseek-chat",
    rule_score_threshold: float = 0.6,
) -> RootCauseResult:
    """协同根因分析 — 专家规则 + LLM 混合推理

    协同策略:
    1. 先运行专家规则分析 (28 条规则)
    2. 如果规则匹配成功且置信度高 (score >= threshold)，以规则为主
       - LLM 补充因果推理链和更详细的解释
    3. 如果规则匹配失败或置信度低，LLM 作为主分析引擎
    4. LLM 不可用时，规则作为降级方案

    Args:
        feature: 从 dmesg/vmcore 提取的特征
        use_llm: 是否启用 LLM 分析
        model_name: LLM 模型名称
        rule_score_threshold: 规则匹配的置信度阈值

    Returns:
        RootCauseResult — 融合了规则和 LLM 的分析结果

    Example:
        >>> result = hybrid_root_cause_analysis(feature)
        >>> print(result.root_cause)         # 根因诊断
        >>> print(result.retrieval_query)    # 优化后的检索查询
        >>> print(result.extra_info["analysis_source"])  # "rule" / "llm" / "hybrid"
    """
    # Step 1: 运行专家规则分析
    rule_result = abstract_root_cause(feature)

    if not use_llm:
        rule_result.extra_info["analysis_source"] = "rule_only"
        return rule_result

    # Step 2: LLM 分析
    llm_result = llm_root_cause_analysis(feature, model_name=model_name)

    if llm_result.get("llm_error"):
        # LLM 失败，降级到纯规则
        rule_result.extra_info["analysis_source"] = "rule_only (llm failed)"
        rule_result.extra_info["llm_error"] = llm_result["llm_error"]
        return rule_result

    # Step 3: 融合规则和 LLM 结果
    rule_score = rule_result.score

    if rule_score >= rule_score_threshold:
        # 规则置信度高 — 以规则为主，LLM 补充
        analysis_source = "hybrid_rule_primary"
        # 保留规则的 root_cause 和 bug_type（更精确）
        # 但用 LLM 的 causal_chain 和 reason 补充可读性
        if llm_result.get("causal_chain"):
            # 追加 LLM 的因果推理（不替换规则推理链）
            for step in llm_result["causal_chain"]:
                if step not in rule_result.causal_chain:
                    rule_result.causal_chain.append(f"[LLM] {step}")

        if llm_result.get("reason") and len(llm_result["reason"]) > len(rule_result.reason):
            rule_result.extra_info["llm_reason"] = llm_result["reason"]

        # 用 LLM 的 fix_patterns 补充规则推断
        rule_fix = rule_result.extra_info.get("fix_hints", {})
        llm_fix = llm_result.get("fix_patterns", {})
        for key in ["needs_lock_fix", "needs_refcount_fix", "needs_rcu_fix",
                     "needs_null_check", "needs_bound_check"]:
            if llm_fix.get(key) and not rule_fix.get(key):
                rule_fix[key] = True
        rule_result.extra_info["fix_hints"] = rule_fix

        # LLM 的 retrieval_query 作为备用
        if llm_result.get("retrieval_query"):
            rule_result.extra_info["llm_retrieval_query"] = llm_result["retrieval_query"]

    else:
        # 规则置信度低 — LLM 作为主引擎
        analysis_source = "hybrid_llm_primary"

        # 用 LLM 结果覆盖
        if llm_result.get("root_cause"):
            rule_result.root_cause = llm_result["root_cause"]
        if llm_result.get("bug_type", "unknown") != "unknown":
            rule_result.bug_type = llm_result["bug_type"]
        if llm_result.get("score", 0) > rule_result.score:
            rule_result.score = llm_result["score"]
        if llm_result.get("reason"):
            rule_result.reason = llm_result["reason"]
        if llm_result.get("causal_chain"):
            rule_result.causal_chain = llm_result["causal_chain"]

        # LLM 的 fix_patterns
        llm_fix = llm_result.get("fix_patterns", {})
        if llm_fix:
            rule_result.extra_info["fix_hints"] = llm_fix

        # LLM 的 retrieval_query
        if llm_result.get("retrieval_query"):
            rule_result.retrieval_query = llm_result["retrieval_query"]

        # 用 LLM 的 suggested_keywords
        if llm_result.get("suggested_keywords"):
            rule_result.suggested_keywords = llm_result["suggested_keywords"]

    # 如果 LLM 的 retrieval_query 更好，优先使用
    llm_retrieval = llm_result.get("retrieval_query", "")
    if llm_retrieval and (not rule_result.retrieval_query or analysis_source == "hybrid_llm_primary"):
        rule_result.retrieval_query = llm_retrieval

    # 元信息
    rule_result.extra_info["analysis_source"] = analysis_source
    rule_result.extra_info["llm_analysis"] = {
        "root_cause": llm_result.get("root_cause"),
        "score": llm_result.get("score"),
        "severity": llm_result.get("severity"),
        "fix_patterns": llm_result.get("fix_patterns"),
    }

    return rule_result


__all__ = [
    # LLM 根因分析
    "ROOT_CAUSE_LLM_SYSTEM_PROMPT",
    "build_root_cause_llm_prompt",
    "llm_root_cause_analysis",
    # 协同分析
    "hybrid_root_cause_analysis",
]
