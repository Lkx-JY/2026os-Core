"""dmesg 日志解析模块

负责从 dmesg 日志中提取 Call Trace 和初步故障特征。
"""

import re
from typing import List, Optional
from ..models import CrashFeature


def extract_call_trace(dmesg_content: str) -> List[str]:
    """使用正则定位并提取 Call Trace"""
    call_trace = []
    # 匹配 Call Trace: 或类似的起始标记
    start_patterns = [
        r"Call Trace:",
        r"\[\s*<\w+>\]",  # 某些格式的 call trace 行
    ]
    
    lines = dmesg_content.split('\n')
    in_trace = False
    
    for line in lines:
        if any(re.search(p, line) for p in start_patterns):
            in_trace = True
            call_trace.append(line.strip())
            continue
            
        if in_trace:
            # 匹配典型的 call trace 行格式，例如:  [<ffffffff81001234>] func+0x12/0x34
            if re.search(r"\[\s*<\w+>\]", line) or line.strip().startswith('?'):
                call_trace.append(line.strip())
            else:
                # 如果不再匹配且已经有内容，则认为结束
                if call_trace:
                    break
                    
    return call_trace


def extract_panic_msg(dmesg_content: str) -> str:
    """提取 Panic 消息或 Oops 消息"""
    patterns = [
        r"Kernel panic - not syncing: (.*)",
        r"BUG: (.*)",
        r"Oops: (.*)",
    ]
    for p in patterns:
        match = re.search(p, dmesg_content)
        if match:
            return match.group(0)
    return ""


def parse_dmesg(dmesg_content: str) -> CrashFeature:
    """解析 dmesg 内容并提取特征"""
    feature = CrashFeature()
    feature.call_trace = extract_call_trace(dmesg_content)
    feature.panic_msg = extract_panic_msg(dmesg_content)
    
    # 初步识别子系统和 bug 类型（可以通过简单的关键词匹配，后续由 LLM 深度分析）
    if "net/" in dmesg_content or "socket" in dmesg_content:
        feature.subsystem = "net"
    elif "mm/" in dmesg_content or "slab" in dmesg_content:
        feature.subsystem = "mm"
        
    if "null pointer" in dmesg_content.lower():
        feature.bug_type = "null_pointer"
    elif "use-after-free" in dmesg_content.lower():
        feature.bug_type = "use_after_free"
        
    return feature
