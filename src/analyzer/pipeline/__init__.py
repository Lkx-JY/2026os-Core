"""分析流水线模块

负责协调 dmesg/vmcore 解析和根因抽象的完整流程。
"""

from typing import Optional, Union
from ..models import CrashFeature, RootCauseResult
from ..dmesg import parse_dmesg
from ..vmcore import analyze_vmcore
from ..rootcause import abstract_root_cause


def run_analysis_pipeline(
    dmesg_content: Optional[str] = None,
    vmcore_path: Optional[str] = None,
    vmlinux_path: Optional[str] = None
) -> RootCauseResult:
    """运行完整分析流水线"""
    
    feature = CrashFeature()
    
    # 1. 特征提取阶段
    if vmcore_path:
        # 优先使用 vmcore 进行深度解析
        feature = analyze_vmcore(vmcore_path, vmlinux_path or "")
        
        # 如果同时提供了 dmesg，可以补充信息
        if dmesg_content:
            dmesg_feature = parse_dmesg(dmesg_content)
            # 合并特征 (以 vmcore 为主，dmesg 补充 call trace 等)
            if not feature.call_trace:
                feature.call_trace = dmesg_feature.call_trace
            if not feature.panic_msg:
                feature.panic_msg = dmesg_feature.panic_msg
                
    elif dmesg_content:
        # 仅使用 dmesg 进行解析
        feature = parse_dmesg(dmesg_content)
    
    # 2. 根因抽象阶段
    result = abstract_root_cause(feature)
    
    return result
