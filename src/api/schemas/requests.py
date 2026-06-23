"""API 请求数据模型."""

from pydantic import BaseModel, Field
from typing import Optional


class AnalyzeRequest(BaseModel):
    """崩溃日志分析请求"""
    log_content: str = Field(
        ...,
        min_length=1,
        max_length=100_000,
        description="宕机日志内容 (dmesg / vmcore-dmesg 输出)",
    )
    log_type: str = Field(
        default="dmesg",
        pattern=r"^(dmesg|vmcore|calltrace|raw)$",
        description="日志类型",
    )
    kernel_version: Optional[str] = Field(
        default=None, description="内核版本号, 用于过滤不兼容补丁"
    )
    top_k: int = Field(default=5, ge=1, le=20, description="返回 Top-K 个匹配补丁")
    enable_llm_explanation: bool = Field(
        default=True, description="是否启用 LLM 生成分析解释"
    )
    user_api_key: Optional[str] = Field(
        default=None,
        description="用户自己的 LLM API Key（DeepSeek/OpenAI/Qwen）。不填则使用免费本地模型",
    )
    user_api_base: Optional[str] = Field(
        default=None,
        description="自定义 API Base URL（可选，默认 https://api.deepseek.com/v1）",
    )
    user_api_model: Optional[str] = Field(
        default=None,
        description="自定义模型名称（可选，默认 deepseek-chat）",
    )


class SearchRequest(BaseModel):
    """补丁知识库搜索请求"""
    query: str = Field(..., min_length=1, max_length=10_000, description="搜索关键词/描述")
    subsystem: Optional[str] = Field(default=None, description="按子系统过滤")
    bug_type: Optional[str] = Field(default=None, description="按 Bug 类型过滤")
    kernel_version: Optional[str] = Field(default=None, description="按内核版本过滤")
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页条数")


class BatchAnalyzeRequest(BaseModel):
    """批量分析请求"""
    logs: list[AnalyzeRequest] = Field(..., min_length=1, max_length=10)
    priority: str = Field(default="normal", pattern=r"^(low|normal|high)$")
