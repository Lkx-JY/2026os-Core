"""Core entity schemas shared across requests and responses."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class RootCauseInfo(BaseModel):
    """结构化根因分析结果"""
    root_cause: str = Field(
        ..., description="根因类型: race_condition, use_after_free, deadlock, null_pointer, etc."
    )
    subsystem: str = Field(..., description="受影响的内核子系统: net, mm, fs, kernel, drivers, etc.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="根因分析置信度")
    summary: str = Field(..., description="根因自然语言描述")
    key_symptoms: list[str] = Field(default_factory=list, description="关键症状列表")


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
    """匹配到的补丁，含相关性评分与推理"""
    rank: int = Field(..., description="排名序号 (1-based)")
    commit: CommitInfo = Field(..., description="Commit 详细信息")
    relevance_score: float = Field(..., ge=0.0, description="综合相关性分数")
    recall_score: Optional[float] = Field(default=None, description="向量召回相似度")
    rerank_score: Optional[float] = Field(default=None, description="Reranker 精确匹配分")
    match_reason: str = Field(default="", description="匹配理由说明")
    diff_highlights: list[str] = Field(default_factory=list, description="Diff 中匹配的关键行")


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
