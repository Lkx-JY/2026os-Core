"""宕机分析数据模型"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class CrashFeature:
    """从 dmesg/vmcore 中提取的标准化故障特征

    Attributes:
        call_trace: 调用栈帧列表，每行为一个栈帧
        subsystem: 受影响的子系统 (mm, fs, net, kernel, drivers, arch 等)
        bug_type: 初步推断的 Bug 类型
        kernel_version: 内核版本号
        modules: 已加载的内核模块列表
        panic_msg: Panic / Oops / BUG 消息原文
        extra_info: 扩展信息 (vmcore 元数据、drgn 版本等)
    """
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
            "extra_info": self.extra_info,
        }


@dataclass
class RootCauseResult:
    """根因抽象结果 — 连接日志理解与补丁检索的关键数据结构

    Attributes:
        crash_feature: 原始崩溃特征
        root_cause: 根因诊断结论
        bug_type: 识别出的 Bug 类型 (与 collector bugtype 的 21 种分类对齐)
        causal_chain: 因果推理链 — 从现象到根因的逐步推导
        score: 置信度评分 (0.0 ~ 1.0)
        reason: 诊断理由 — 面向运维人员的可读解释
        retrieval_query: 优化后的向量检索查询文本 — 直接供 BGE-M3 编码
        suggested_keywords: 建议的搜索关键词 — 用于补全检索或规则过滤
        extra_info: 扩展信息 (调用的规则 ID、严重程度、修复提示、调用栈分析等)
    """
    crash_feature: CrashFeature
    root_cause: str = ""
    bug_type: str = ""
    causal_chain: List[str] = field(default_factory=list)
    score: float = 0.0
    reason: str = ""
    retrieval_query: str = ""
    suggested_keywords: List[str] = field(default_factory=list)
    extra_info: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "crash_feature": self.crash_feature.to_dict(),
            "root_cause": self.root_cause,
            "bug_type": self.bug_type,
            "causal_chain": self.causal_chain,
            "score": self.score,
            "reason": self.reason,
            "retrieval_query": self.retrieval_query,
            "suggested_keywords": self.suggested_keywords,
            "extra_info": self.extra_info,
        }

    def get_severity_label(self) -> str:
        """根据评分为根因结论生成严重程度标签"""
        if self.score >= 0.85:
            return "CRITICAL"
        elif self.score >= 0.70:
            return "HIGH"
        elif self.score >= 0.50:
            return "MEDIUM"
        elif self.score >= 0.30:
            return "LOW"
        else:
            return "UNCERTAIN"
