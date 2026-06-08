"""自定义异常模块 — Custom Exception Classes

定义整个项目使用的异常类层次结构，便于统一错误处理和日志记录。

设计要点:
- 层次化的异常类: 基础异常 → 模块异常 → 具体异常
- 上下文信息: 异常携带诊断所需的上下文数据
- 序列化: 支持 safe to_dict() 用于 API 响应
"""

from typing import Dict, Any, Optional


# ============================================================================
# 基类
# ============================================================================

class CoreLinuxCommitError(Exception):
    """所有项目异常的基类

    Attributes:
        message: 人类可读的错误描述
        code: 错误码 (如 "E001")
        context: 额外的上下文信息
    """

    def __init__(
        self,
        message: str,
        code: str = "E000",
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.context = context or {}

    def to_dict(self) -> Dict[str, Any]:
        """安全的序列化 — 不泄露内部路径"""
        return {
            "error": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
        }

    def __str__(self):
        return f"[{self.code}] {self.message}"


# ============================================================================
# 配置异常
# ============================================================================

class ConfigurationError(CoreLinuxCommitError):
    """配置相关的异常"""

    def __init__(self, message: str, key: str = "", context: Optional[Dict[str, Any]] = None):
        ctx = context or {}
        if key:
            ctx["config_key"] = key
        super().__init__(message, code="E001", context=ctx)


class MissingConfigError(ConfigurationError):
    """缺少必要配置项"""

    def __init__(self, key: str):
        super().__init__(
            message=f"Required configuration key '{key}' is missing",
            key=key,
        )


class InvalidConfigError(ConfigurationError):
    """配置值无效"""

    def __init__(self, key: str, value: Any, expected: str = ""):
        msg = f"Invalid value for '{key}': {value}"
        if expected:
            msg += f" (expected: {expected})"
        super().__init__(message=msg, key=key, context={"value": str(value)})


# ============================================================================
# 数据异常
# ============================================================================

class DataError(CoreLinuxCommitError):
    """数据处理相关异常"""

    def __init__(
        self,
        message: str,
        code: str = "E010",
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, code=code, context=context)


class ParsingError(DataError):
    """数据解析失败"""

    def __init__(self, message: str, data_type: str = "", raw_data: str = ""):
        super().__init__(
            message=message,
            code="E011",
            context={
                "data_type": data_type,
                "raw_data_preview": raw_data[:200],
            },
        )


class InvalidDataFormat(DataError):
    """数据格式无效"""

    def __init__(self, message: str, expected_format: str = ""):
        super().__init__(
            message=message,
            code="E012",
            context={"expected_format": expected_format},
        )


# ============================================================================
# 分析异常
# ============================================================================

class AnalysisError(CoreLinuxCommitError):
    """分析过程中的异常"""

    def __init__(self, message: str, analysis_stage: str = "", context: Optional[Dict[str, Any]] = None):
        ctx = context or {}
        if analysis_stage:
            ctx["stage"] = analysis_stage
        super().__init__(message, code="E020", context=ctx)


class DmesgParsingError(AnalysisError):
    """dmesg 日志解析失败"""

    def __init__(self, message: str, dmesg_preview: str = ""):
        super().__init__(
            message=message,
            analysis_stage="dmesg_parsing",
            context={"dmesg_preview": dmesg_preview[:200]},
        )


class VmcoreAnalysisError(AnalysisError):
    """vmcore 解析失败"""

    def __init__(self, message: str, vmcore_path: str = ""):
        super().__init__(
            message=message,
            analysis_stage="vmcore_analysis",
            context={"vmcore_path": vmcore_path},
        )


class RootCauseAnalysisError(AnalysisError):
    """根因分析失败"""

    def __init__(self, message: str, reason: str = ""):
        super().__init__(
            message=message,
            analysis_stage="root_cause_analysis",
            context={"reason": reason},
        )


# ============================================================================
# 索引/检索异常
# ============================================================================

class IndexingError(CoreLinuxCommitError):
    """索引操作异常"""

    def __init__(self, message: str, operation: str = "", context: Optional[Dict[str, Any]] = None):
        ctx = context or {}
        if operation:
            ctx["operation"] = operation
        super().__init__(message, code="E030", context=ctx)


class EmbeddingError(IndexingError):
    """向量编码失败"""

    def __init__(self, message: str, model_name: str = ""):
        super().__init__(
            message=message,
            operation="embedding",
            context={"model": model_name},
        )


class VectorDBError(IndexingError):
    """向量数据库操作失败"""

    def __init__(self, message: str, backend: str = "", operation: str = ""):
        super().__init__(
            message=message,
            operation=f"{backend}_{operation}" if backend else operation,
            context={"backend": backend},
        )


class RetrievalError(CoreLinuxCommitError):
    """检索过程异常"""

    def __init__(self, message: str, stage: str = "", context: Optional[Dict[str, Any]] = None):
        ctx = context or {}
        if stage:
            ctx["stage"] = stage
        super().__init__(message, code="E040", context=ctx)


# ============================================================================
# LLM 相关异常
# ============================================================================

class LLMError(CoreLinuxCommitError):
    """LLM 调用异常"""

    def __init__(self, message: str, model: str = "", context: Optional[Dict[str, Any]] = None):
        ctx = context or {}
        if model:
            ctx["model"] = model
        super().__init__(message, code="E050", context=ctx)


class LLMUnavailableError(LLMError):
    """LLM 服务不可用"""

    def __init__(self, model: str = "", reason: str = ""):
        super().__init__(
            message=f"LLM service unavailable{f' ({model})' if model else ''}",
            model=model,
            context={"reason": reason},
        )


class LLMResponseError(LLMError):
    """LLM 响应解析失败"""

    def __init__(self, message: str, raw_response: str = ""):
        super().__init__(
            message=message,
            context={"raw_response_preview": raw_response[:300]},
        )


# ============================================================================
# 外部依赖异常
# ============================================================================

class DependencyError(CoreLinuxCommitError):
    """外部依赖异常"""

    def __init__(self, message: str, dependency: str = "", context: Optional[Dict[str, Any]] = None):
        ctx = context or {}
        if dependency:
            ctx["dependency"] = dependency
        super().__init__(message, code="E060", context=ctx)


class GitRepoError(DependencyError):
    """Git 仓库操作失败"""

    def __init__(self, message: str, repo_path: str = ""):
        super().__init__(
            message=message,
            dependency="git",
            context={"repo_path": repo_path},
        )


class DrgnError(DependencyError):
    """drgn 工具异常"""

    def __init__(self, message: str, vmcore_path: str = ""):
        super().__init__(
            message=message,
            dependency="drgn",
            context={"vmcore_path": vmcore_path},
        )


class ModelNotAvailableError(DependencyError):
    """ML 模型不可用"""

    def __init__(self, model_name: str, reason: str = ""):
        super().__init__(
            message=f"Model '{model_name}' is not available: {reason}",
            dependency=model_name,
            context={"reason": reason},
        )


__all__ = [
    # 基类
    "CoreLinuxCommitError",
    # 配置
    "ConfigurationError",
    "MissingConfigError",
    "InvalidConfigError",
    # 数据
    "DataError",
    "ParsingError",
    "InvalidDataFormat",
    # 分析
    "AnalysisError",
    "DmesgParsingError",
    "VmcoreAnalysisError",
    "RootCauseAnalysisError",
    # 索引/检索
    "IndexingError",
    "EmbeddingError",
    "VectorDBError",
    "RetrievalError",
    # LLM
    "LLMError",
    "LLMUnavailableError",
    "LLMResponseError",
    # 依赖
    "DependencyError",
    "GitRepoError",
    "DrgnError",
    "ModelNotAvailableError",
]
