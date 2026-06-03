"""根因抽象模型模块

负责将提取的宕机特征抽象为结构化的根因描述。
"""

from typing import List, Dict, Any
from ..models import CrashFeature, RootCauseResult


class RootCauseAnalyzer:
    """根因分析器，融合专家经验与语义理解"""
    
    def __init__(self):
        # 预定义的专家规则库
        self.expert_rules = [
            {
                "id": "R001",
                "name": "Spinlock Deadlock",
                "bug_type": "deadlock",
                "keywords": ["spin_lock", "queued_spin_lock_slowpath", "native_queued_spin_lock_slowpath"],
                "description": "检测到自旋锁死锁，通常发生在中断上下文或持有锁时再次申请相同锁。"
            },
            {
                "id": "R002",
                "name": "Null Pointer Dereference",
                "bug_type": "null_pointer",
                "keywords": ["unable to handle kernel NULL pointer dereference"],
                "description": "内核尝试解引用空指针，通常是因为未检查指针有效性。"
            },
            {
                "id": "R003",
                "name": "Use After Free",
                "bug_type": "use_after_free",
                "keywords": ["KASAN: use-after-free", "slub_debug"],
                "description": "检测到内存释放后使用，可能是引用计数处理不当。"
            }
        ]

    def analyze(self, feature: CrashFeature) -> RootCauseResult:
        """执行根因分析"""
        result = RootCauseResult(crash_feature=feature)
        
        # 1. 基于专家规则的匹配
        for rule in self.expert_rules:
            # 检查 panic_msg
            if any(kw.lower() in feature.panic_msg.lower() for kw in rule["keywords"]):
                result.root_cause = rule["name"]
                result.causal_chain.append(f"Rule Match: {rule['id']}")
                result.reason = rule["description"]
                result.score = 0.8
                break
            
            # 检查 call_trace
            trace_text = "\n".join(feature.call_trace).lower()
            if any(kw.lower() in trace_text for kw in rule["keywords"]):
                result.root_cause = rule["name"]
                result.causal_chain.append(f"Trace Match: {rule['id']}")
                result.reason = rule["description"]
                result.score = 0.7
                break
        
        # 2. 如果没有匹配到规则，尝试通用抽象
        if not result.root_cause:
            if feature.bug_type != "unknown":
                result.root_cause = f"Generic {feature.bug_type.replace('_', ' ').title()}"
                result.reason = f"Detected bug type: {feature.bug_type} in subsystem: {feature.subsystem}"
                result.score = 0.5
            else:
                result.root_cause = "Unknown Root Cause"
                result.reason = "Could not determine root cause from available features."
                result.score = 0.1
                
        # 3. 构建因果链 (示例)
        if feature.subsystem != "unknown":
            result.causal_chain.append(f"Affected Subsystem: {feature.subsystem}")
        
        return result


def abstract_root_cause(feature: CrashFeature) -> RootCauseResult:
    """根因抽象主入口"""
    analyzer = RootCauseAnalyzer()
    return analyzer.analyze(feature)
