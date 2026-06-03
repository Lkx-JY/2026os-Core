"""宕机分析数据模型"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class CrashFeature:
    """从 dmesg/vmcore 中提取的特征"""
    call_trace: List[str] = field(default_factory=list)
    subsystem: str = "unknown"
    bug_type: str = "unknown"
    kernel_version: str = ""
    modules: List[str] = field(default_factory=list)
    panic_msg: str = ""
    extra_info: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "call_trace": self.call_trace,
            "subsystem": self.subsystem,
            "bug_type": self.bug_type,
            "kernel_version": self.kernel_version,
            "modules": self.modules,
            "panic_msg": self.panic_msg,
            "extra_info": self.extra_info
        }


@dataclass
class RootCauseResult:
    """根因抽象结果"""
    crash_feature: CrashFeature
    root_cause: str = ""
    causal_chain: List[str] = field(default_factory=list)
    score: float = 0.0
    reason: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "crash_feature": self.crash_feature.to_dict(),
            "root_cause": self.root_cause,
            "causal_chain": self.causal_chain,
            "score": self.score,
            "reason": self.reason
        }
