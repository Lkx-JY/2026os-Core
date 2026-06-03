"""宕机分析核心模块

负责从 dmesg 日志和 vmcore 文件中提取故障特征，并进行根因抽象分析。
整合了以下功能：
- dmesg: 日志正则解析与 Call Trace 特征提取
- vmcore: 基于 drgn 的深度内核对象提取
- rootcause: 根因抽象与因果链构建（20+ 专家规则 + 调用栈结构分析 + 修复模式推断）
- pipeline: 分析流水线编排
- models: CrashFeature / RootCauseResult 数据模型
"""

from .models import CrashFeature, RootCauseResult
from .dmesg import parse_dmesg
from .vmcore import analyze_vmcore
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
from .pipeline import run_analysis_pipeline

__all__ = [
    # 数据模型
    'CrashFeature',
    'RootCauseResult',
    # dmesg 解析
    'parse_dmesg',
    # vmcore 解析
    'analyze_vmcore',
    # 根因分析
    'RootCauseAnalyzer',
    'abstract_root_cause',
    'get_analyzer',
    'list_all_rules',
    'get_rule_by_id',
    'analyze_call_trace_structure',
    'infer_fix_patterns',
    'build_retrieval_query',
    'EXPERT_RULES',
    # 流水线
    'run_analysis_pipeline',
]
