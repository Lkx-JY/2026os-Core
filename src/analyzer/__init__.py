"""宕机分析核心模块

负责从 dmesg 日志和 vmcore 文件中提取故障特征，并进行根因抽象分析。
整合了以下功能：
- dmesg: 日志正则解析与特征提取
- vmcore: 基于 drgn 的深度内核对象提取
- rootcause: 根因抽象与因果链构建
- pipeline: 分析流水线编排
"""

from .models import CrashFeature, RootCauseResult
from .dmesg import parse_dmesg
from .vmcore import analyze_vmcore
from .rootcause import abstract_root_cause
from .pipeline import run_analysis_pipeline

__all__ = [
    'CrashFeature',
    'RootCauseResult',
    'parse_dmesg',
    'analyze_vmcore',
    'abstract_root_cause',
    'run_analysis_pipeline',
]
