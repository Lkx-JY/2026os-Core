"""API 响应数据模型."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from .entities import RootCauseInfo, MatchedPatch, CommitInfo, AnalysisStep


class AnalyzeResponse(BaseModel):
    """单次崩溃日志分析响应"""
    task_id: str = Field(..., description="分析任务唯一标识")
    status: str = Field(..., description="completed|running|failed")
    root_cause: Optional[RootCauseInfo] = Field(default=None, description="根因分析结果")
    matched_patches: list[MatchedPatch] = Field(
        default_factory=list, description="匹配到的补丁列表"
    )
    analysis_steps: list[AnalysisStep] = Field(
        default_factory=list, description="分析流水线各步骤状态"
    )
    llm_explanation: Optional[str] = Field(
        default=None, description="LLM 生成的自然语言解释"
    )
    raw_log_summary: Optional[str] = Field(
        default=None, description="原始日志摘要"
    )
    analysis_mode: str = Field(
        default="real",
        description="real | mock — 标识本次分析使用的是真实RAG Pipeline还是模拟数据"
    )
    created_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    elapsed_ms: Optional[int] = Field(default=None, description="总耗时 (毫秒)")


class SearchResponse(BaseModel):
    """补丁搜索响应"""
    query: str
    total: int = Field(..., description="总命中数")
    page: int
    page_size: int
    results: list[CommitInfo] = Field(default_factory=list)
    analysis_mode: str = Field(
        default="real",
        description="real | mock — 标识搜索数据来源"
    )
    facets: Optional[dict] = Field(
        default=None, description="分面统计 (subsystem/bug_type 分布)"
    )


class CommitDetailResponse(BaseModel):
    """单个 Commit 详情"""
    commit: CommitInfo
    related_commits: list[CommitInfo] = Field(
        default_factory=list, description="相关 Commit (Fixes/Cc-stable 链)"
    )


class StatsResponse(BaseModel):
    """系统概览统计"""
    total_commits: int = Field(default=0, description="已索引 Commit 总数")
    total_analyses: int = Field(default=0, description="已完成分析总数")
    subsystems: list[dict] = Field(default_factory=list, description="子系统统计")
    bug_types: list[dict] = Field(default_factory=list, description="Bug 类型统计")
    vector_db_size: int = Field(default=0, description="向量库大小")
    analysis_mode: str = Field(
        default="real",
        description="real | mock — 标识统计数据来源"
    )
    uptime_seconds: float = Field(default=0, description="服务运行秒数")
    avg_analysis_ms: float = Field(default=0, description="平均分析耗时 (ms)")


class TaskStatusResponse(BaseModel):
    """异步任务状态"""
    task_id: str
    status: str = Field(..., description="pending|running|completed|failed")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="进度 0-1")
    result: Optional[AnalyzeResponse] = Field(default=None)
    error: Optional[str] = Field(default=None)


class ErrorResponse(BaseModel):
    """统一错误响应"""
    code: str = Field(..., description="错误码")
    message: str = Field(..., description="错误描述")
    detail: Optional[str] = Field(default=None, description="详细错误信息")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
