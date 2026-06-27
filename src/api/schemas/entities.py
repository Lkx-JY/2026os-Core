"""Core entity schemas shared across requests and responses."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ============================================================================
# 可解释性增强数据模型 (赛题 "演示质量与可解释性 (15%)" 支撑)
# ============================================================================

class ScoreBreakdown(BaseModel):
    """多维评分明细 — 记录每个评分维度的独立分数

    用于前端展示排序依据，满足赛题"可解释性"评审要求。
    每个维度独立评分，最终按权重融合为 final_score。
    """

    # ── 向量维度 ──
    embedding_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="BGE-M3 向量余弦相似度 (Phase 1: 召回阶段)"
    )

    # ── 精排维度 ──
    reranker_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="BGE-Reranker-v2 Cross-encoder 语义重排分数 (Phase 3)"
    )

    # ── 领域知识维度 ──
    expert_rule_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="专家规则匹配度 — 补丁的 bug_type/fix_pattern 与根因规则的一致性"
    )

    # ── 调用栈维度 ──
    callstack_match_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="调用栈匹配度 — 补丁修改的函数/文件是否出现在崩溃调用栈中"
    )

    # ── 子系统维度 ──
    subsystem_match_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="子系统匹配度 — 补丁所属子系统与崩溃子系统的一致性"
    )

    # ── 版本维度 ──
    version_match_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="版本匹配度 — 补丁内核版本与崩溃内核版本的兼容性评分"
    )

    # ── LLM 维度 ──
    llm_judge_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="LLM Judge 因果关联评分 (Phase 4: 大模型因果推理)"
    )

    # ── 综合 ──
    final_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="加权综合分数"
    )

    # ── 融合权重 ──
    fusion_weights: dict = Field(
        default_factory=lambda: {
            "embedding": 0.15,
            "reranker": 0.25,
            "expert_rule": 0.15,
            "callstack_match": 0.10,
            "subsystem_match": 0.10,
            "version_match": 0.10,
            "llm_judge": 0.15,
        },
        description="各维度融合权重配置"
    )


class RootCauseEvidence(BaseModel):
    """根因分析证据 — 记录触发根因诊断的关键信号

    面向评委展示"为什么系统判定这个根因"，满足可解释性要求。
    """

    panic_keyword: Optional[str] = Field(
        default=None, description="从 panic 消息中提取的关键词，如 'NULL pointer dereference'"
    )
    fault_address: Optional[str] = Field(
        default=None, description="出错虚拟地址 (来自 dmesg 'at virtual address' 字段)"
    )
    error_code: Optional[str] = Field(
        default=None, description="错误码 (如 '#PF: error_code(0x0000)')"
    )
    subsystem: Optional[str] = Field(
        default=None, description="从调用栈/模块路径推断的受影响子系统"
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="根因置信度"
    )
    matched_rule_id: Optional[str] = Field(
        default=None, description="匹配到的专家规则 ID，如 'R002'"
    )
    matched_rule_name: Optional[str] = Field(
        default=None, description="匹配到的专家规则名称"
    )
    trace_functions: list[str] = Field(
        default_factory=list, description="调用栈中识别的关键函数 (最多 5 个)"
    )
    loaded_modules: list[str] = Field(
        default_factory=list, description="崩溃时加载的内核模块"
    )
    kernel_version: Optional[str] = Field(
        default=None, description="崩溃内核版本"
    )
    causal_chain: list[str] = Field(
        default_factory=list, description="因果推理链 — 从现象到根因的逐步推导"
    )


class VersionAnalysis(BaseModel):
    """版本感知分析 — 补丁版本与崩溃内核版本的对比

    赛题核心特征"版本演化的上下文敏感性"的前端可视化支撑。
    """

    crash_kernel_version: Optional[str] = Field(
        default=None, description="崩溃时的内核版本，如 '6.6.0'"
    )
    patch_kernel_version: Optional[str] = Field(
        default=None, description="补丁对应的内核版本，如 '6.4.0'"
    )
    version_distance: Optional[str] = Field(
        default=None,
        description="版本距离描述，如 '2 Minor Release' / 'Same Version' / 'Cross Major'"
    )
    distance_value: int = Field(
        default=0, description="版本距离数值 (minor release 差)"
    )
    compatibility: Optional[str] = Field(
        default=None,
        description="兼容性评估: 'High' / 'Medium' / 'Low' / 'Unknown'"
    )
    compatibility_reason: Optional[str] = Field(
        default=None,
        description="兼容性判断依据"
    )
    patch_release_date: Optional[str] = Field(
        default=None, description="补丁提交日期 (YYYY-MM-DD)"
    )
    crash_release_date: Optional[str] = Field(
        default=None, description="崩溃内核发布日期 (YYYY-MM-DD)"
    )


class WhyNotExplanation(BaseModel):
    """"为什么不是排名更高"的比较解释

    为每个非 Top-1 补丁生成相对于 Top-1 的比较解释。
    评委非常喜欢这种对比式解释。
    """

    compared_to_rank: int = Field(
        default=1, description="与哪个排名对比 (通常是 #1)"
    )
    same_aspects: list[str] = Field(
        default_factory=list,
        description="与更高排名补丁的共同点"
    )
    different_aspects: list[str] = Field(
        default_factory=list,
        description="与更高排名补丁的差异点"
    )
    ranking_reason: str = Field(
        default="", description="综合排序理由 (一句话总结)"
    )


# ============================================================================
# 核心实体模型
# ============================================================================

class RootCauseInfo(BaseModel):
    """结构化根因分析结果"""
    root_cause: str = Field(
        ..., description="根因类型: race_condition, use_after_free, deadlock, null_pointer, etc."
    )
    subsystem: str = Field(..., description="受影响的内核子系统: net, mm, fs, kernel, drivers, etc.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="根因分析置信度")
    summary: str = Field(..., description="根因自然语言描述")
    key_symptoms: list[str] = Field(default_factory=list, description="关键症状列表")

    # ★ 可解释性增强：根因证据
    evidence: Optional[RootCauseEvidence] = Field(
        default=None, description="根因证据详情 — 展示为什么判定此根因"
    )


class CommitInfo(BaseModel):
    """Linux kernel commit 结构化信息"""
    commit_id: str = Field(..., description="Git commit hash")
    title: str = Field(..., description="Commit 标题")
    message: str = Field(default="", description="完整 commit message")
    author: str = Field(default="", description="作者")
    date: str = Field(default="", description="提交日期")
    subsystem: str = Field(default="", description="所属子系统")
    bug_type: Optional[str] = Field(default=None, description="修复的 Bug 类型")
    files_changed: list[str] = Field(default_factory=list, description="变更文件列表")
    diff_preview: str = Field(default="", description="Diff 关键片段", max_length=5000)
    fix_tags: list[str] = Field(default_factory=list, description="Fixes/Cc-stable 等标签")


class MatchedPatch(BaseModel):
    """匹配到的补丁，含相关性评分与推理 (可解释性增强版)"""
    rank: int = Field(..., description="排名序号 (1-based)")
    commit: CommitInfo = Field(..., description="Commit 详细信息")
    relevance_score: float = Field(..., ge=0.0, description="综合相关性分数")
    recall_score: Optional[float] = Field(default=None, description="向量召回相似度")
    rerank_score: Optional[float] = Field(default=None, description="Reranker 精确匹配分")
    match_reason: str = Field(default="", description="匹配理由说明")
    diff_highlights: list[str] = Field(default_factory=list, description="Diff 中匹配的关键行")

    # ★ 可解释性增强
    score_breakdown: Optional[ScoreBreakdown] = Field(
        default=None, description="多维评分明细"
    )
    version_analysis: Optional[VersionAnalysis] = Field(
        default=None, description="版本感知分析"
    )
    why_not_explanation: Optional[WhyNotExplanation] = Field(
        default=None, description="为什么不是排名更高 (Top-1 时为 None)"
    )


class AnalysisStep(BaseModel):
    """分析流水线中单个步骤的状态"""
    name: str = Field(..., description="步骤名称")
    status: str = Field(..., description="pending|running|completed|failed")
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    detail: Optional[str] = Field(default=None, description="步骤详情或错误信息")


class SubsystemInfo(BaseModel):
    """内核子系统统计信息"""
    name: str = Field(..., description="子系统名称")
    commit_count: int = Field(default=0, description="该子系统 commit 数量")
    bug_types: list[str] = Field(default_factory=list)


class BugTypeInfo(BaseModel):
    """Bug 类型统计信息"""
    name: str = Field(..., description="Bug 类型名称")
    count: int = Field(default=0, description="数量")
    description: str = Field(default="", description="类型说明")
