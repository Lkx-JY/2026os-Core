"""报告生成模块 — Report Generation Layer

负责将诊断结果和补丁检索结果整合为可读的诊断报告。
是整个系统"从数据到洞察"的最后一公里。

整合了以下功能:
- llm: 统一的 LLM 调用接口 (DeepSeek / Qwen / OpenAI 兼容)
- prompt: Prompt 工程 (场景模板、Few-shot 示例、结构化约束)
- report: 报告生成引擎 (Markdown / JSON / HTML 多格式输出)
"""

from .llm import (
    LLMClient,
    get_llm_client,
    reset_llm_client,
)
from .prompt import (
    build_diagnosis_report_prompt,
    build_patch_explanation_prompt,
    build_causal_reasoning_prompt,
    build_root_cause_analysis_prompt,
    get_few_shot_example,
    FEW_SHOT_EXAMPLES,
    truncate_for_prompt,
    format_call_trace_for_prompt,
    build_system_prompt,
)
from .report import (
    DiagnosisReport,
    ReportGenerator,
    generate_report,
    generate_patch_comparison_table,
)

__all__ = [
    # LLM 接口
    "LLMClient",
    "get_llm_client",
    "reset_llm_client",
    # Prompt 工程
    "build_diagnosis_report_prompt",
    "build_patch_explanation_prompt",
    "build_causal_reasoning_prompt",
    "build_root_cause_analysis_prompt",
    "get_few_shot_example",
    "FEW_SHOT_EXAMPLES",
    "truncate_for_prompt",
    "format_call_trace_for_prompt",
    "build_system_prompt",
    # 报告生成
    "DiagnosisReport",
    "ReportGenerator",
    "generate_report",
    "generate_patch_comparison_table",
]
