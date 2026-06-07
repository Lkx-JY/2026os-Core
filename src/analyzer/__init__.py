"""宕机分析核心模块

负责从 dmesg 日志和 vmcore 文件中提取故障特征，并进行根因抽象分析。
整合了以下功能：
- dmesg: 日志正则解析 + LLM 深度分析 + Call Trace 特征提取
- vmcore: 基于 drgn 的深度内核对象提取 + 调用栈重建
- rootcause: 根因抽象与因果链构建（28 条专家规则 + LLM 协同推理 + 修复模式推断）
- pipeline: 分析流水线编排 (支持 rule_only / hybrid 模式)
- models: CrashFeature / RootCauseResult 数据模型
"""

from .models import CrashFeature, RootCauseResult
from .dmesg import (
    parse_dmesg,
    parse_dmesg_with_llm,
    extract_call_trace,
    extract_call_trace_region,
    extract_panic_msg,
    extract_all_panic_info,
    locate_call_trace_bounds,
    llm_deep_analysis,
    build_llm_analysis_prompt,
)
from .vmcore import (
    analyze_vmcore,
    extract_features_from_vmcore,
    fuse_features,
    load_vmcore,
    extract_kernel_version,
    extract_call_trace_from_vmcore,
    extract_kernel_objects,
)
from .rootcause import (
    RootCauseAnalyzer,
    abstract_root_cause,
    get_analyzer,
    list_all_rules,
    get_rule_by_id,
    analyze_call_trace_structure,
    infer_fix_patterns,
    build_retrieval_query,
    EXPERT_RULES,
)
from .rootcause.llm_rootcause import (
    llm_root_cause_analysis,
    hybrid_root_cause_analysis,
    build_root_cause_llm_prompt,
)
from .pipeline import run_analysis_pipeline

__all__ = [
    # 数据模型
    'CrashFeature',
    'RootCauseResult',
    # dmesg 解析 (Phase 1)
    'parse_dmesg',
    'parse_dmesg_with_llm',
    'extract_call_trace',
    'extract_call_trace_region',
    'extract_panic_msg',
    'extract_all_panic_info',
    'locate_call_trace_bounds',
    'llm_deep_analysis',
    'build_llm_analysis_prompt',
    # vmcore 解析 (Phase 1)
    'analyze_vmcore',
    'extract_features_from_vmcore',
    'fuse_features',
    'load_vmcore',
    'extract_kernel_version',
    'extract_call_trace_from_vmcore',
    'extract_kernel_objects',
    # 根因分析 (Phase 2) — 专家规则
    'RootCauseAnalyzer',
    'abstract_root_cause',
    'get_analyzer',
    'list_all_rules',
    'get_rule_by_id',
    'analyze_call_trace_structure',
    'infer_fix_patterns',
    'build_retrieval_query',
    'EXPERT_RULES',
    # 根因分析 (Phase 2) — LLM 增强
    'llm_root_cause_analysis',
    'hybrid_root_cause_analysis',
    'build_root_cause_llm_prompt',
    # 流水线
    'run_analysis_pipeline',
]
