"""日志模块 — Logging Configuration

基于 loguru 的统一日志管理系统。

设计要点:
- 结构化日志: 支持 JSON 格式输出用于日志收集
- 多级别输出: DEBUG (文件) + INFO (控制台)
- 自动轮转: 按大小/时间轮转，防止磁盘写满
- 上下文追踪: 自动记录模块名、函数名、行号
- 性能监控: 关键路径的执行时间记录
"""

from __future__ import annotations
import sys
import time
import os
from typing import Optional, Callable, Any, Dict
from contextlib import contextmanager


# ============================================================================
# 日志级别
# ============================================================================

class LogLevel:
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ============================================================================
# 日志配置
# ============================================================================

_default_config = {
    "log_dir": "logs",
    "app_name": "CoreLinuxCommit",
    "console_level": "INFO",
    "file_level": "DEBUG",
    "rotation": "10 MB",
    "retention": "7 days",
    "json_format": False,
    "colorize": True,
}


def setup_logging(
    log_dir: str = "logs",
    app_name: str = "CoreLinuxCommit",
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    rotation: str = "10 MB",
    retention: str = "7 days",
    json_format: bool = False,
    colorize: bool = True,
) -> Any:
    """配置全局日志系统

    Args:
        log_dir: 日志文件目录
        app_name: 应用名称 (用于日志文件前缀)
        console_level: 控制台输出级别
        file_level: 文件输出级别
        rotation: 日志轮转策略 (如 "10 MB", "1 day")
        retention: 日志保留时间 (如 "7 days")
        json_format: 是否使用 JSON 格式
        colorize: 控制台是否彩色输出

    Returns:
        loguru logger 实例

    Example:
        >>> from src.common.logging import setup_logging
        >>> logger = setup_logging(log_dir="logs", console_level="DEBUG")
        >>> logger.info("System initialized")
    """
    try:
        from loguru import logger as loguru_logger
        import logging as std_logging

        # 移除默认 handler
        loguru_logger.remove()

        # ── 控制台输出 ──────────────────────────────────────
        loguru_logger.add(
            sys.stderr,
            level=console_level,
            colorize=colorize,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            ) if not json_format else "",
            serialize=json_format,
        )

        # ── 文件输出 (DEBUG) ─────────────────────────────────
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"{app_name}_{{time:YYYY-MM-DD}}.log")

        loguru_logger.add(
            log_path,
            level=file_level,
            rotation=rotation,
            retention=retention,
            compression="gz",
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
                "{level: <8} | "
                "{name}:{function}:{line} - "
                "{message}"
            ),
            serialize=json_format,
            enqueue=True,  # 多进程安全
        )

        # ── 错误日志单独文件 ────────────────────────────────
        error_log_path = os.path.join(log_dir, f"{app_name}_error_{{time:YYYY-MM-DD}}.log")
        loguru_logger.add(
            error_log_path,
            level="ERROR",
            rotation=rotation,
            retention=retention * 2 if isinstance(retention, str) else retention,
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
                "{level: <8} | "
                "{name}:{function}:{line} | "
                "{message}\n"
                "{exception}"
            ),
            enqueue=True,
        )

        # ── 拦截标准 logging ────────────────────────────────
        class InterceptHandler(std_logging.Handler):
            def emit(self, record):
                try:
                    level = loguru_logger.level(record.levelname).name
                except ValueError:
                    level = record.levelno
                frame = std_logging.currentframe()
                depth = 2
                while frame and frame.f_code.co_filename == std_logging.__file__:
                    frame = frame.f_back
                    depth += 1
                loguru_logger.opt(depth=depth, exception=record.exc_info).log(
                    level, record.getMessage()
                )

        std_logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

        return loguru_logger

    except ImportError:
        # loguru 不可用时的降级方案
        return _setup_fallback_logging(console_level)


def _setup_fallback_logging(level: str = "INFO") -> Any:
    """降级日志方案 — 使用标准 logging"""
    import logging as std_logging

    level_map = {
        "TRACE": std_logging.DEBUG,
        "DEBUG": std_logging.DEBUG,
        "INFO": std_logging.INFO,
        "SUCCESS": std_logging.INFO,
        "WARNING": std_logging.WARNING,
        "ERROR": std_logging.ERROR,
        "CRITICAL": std_logging.CRITICAL,
    }

    std_level = level_map.get(level.upper(), std_logging.INFO)

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    std_logging.basicConfig(
        level=std_level,
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )

    return std_logging.getLogger("CoreLinuxCommit")


# ============================================================================
# 全局 Logger 实例
# ============================================================================

_logger = None


def get_logger() -> Any:
    """获取全局 logger 实例

    首次调用时自动初始化默认配置。

    Returns:
        logger 实例

    Example:
        >>> from src.common.logging import get_logger
        >>> logger = get_logger()
        >>> logger.info("Processing commit {}", commit_hash)
    """
    global _logger
    if _logger is None:
        _logger = setup_logging()
    return _logger


def reset_logger():
    """重置 logger (用于测试)"""
    global _logger
    _logger = None


# ============================================================================
# 性能计时
# ============================================================================

@contextmanager
def log_time(operation: str, logger: Optional[Any] = None, level: str = "DEBUG"):
    """上下文管理器：记录代码块执行时间

    Args:
        operation: 操作描述
        logger: logger 实例 (None 时使用全局)
        level: 日志级别

    Example:
        >>> from src.common.logging import log_time
        >>> with log_time("vector_search"):
        ...     results = client.search(query_vec)
        # 自动输出: "vector_search completed in 12.34ms"
    """
    log = logger or get_logger()
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log_func = getattr(log, level.lower(), log.debug)
        log_func(f"{operation} completed in {elapsed_ms:.2f}ms")


def timed(logger: Optional[Any] = None, level: str = "DEBUG"):
    """装饰器：记录函数执行时间

    Args:
        logger: logger 实例
        level: 日志级别

    Example:
        >>> from src.common.logging import timed
        >>> @timed(level="INFO")
        ... def heavy_computation():
        ...     pass
    """
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            log = logger or get_logger()
            t0 = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                log_func = getattr(log, level.lower(), log.debug)
                log_func(f"{func.__name__}() completed in {elapsed_ms:.2f}ms")
        return wrapper
    return decorator


# ============================================================================
# 结构化日志
# ============================================================================

def log_event(
    event: str,
    data: Optional[Dict[str, Any]] = None,
    level: str = "INFO",
    logger: Optional[Any] = None,
):
    """记录结构化事件

    适用于需要后续分析的日志事件。

    Args:
        event: 事件名称
        data: 事件数据
        level: 日志级别
        logger: logger 实例

    Example:
        >>> log_event("diagnosis_completed", {
        ...     "bug_type": "use_after_free",
        ...     "confidence": 0.85,
        ...     "duration_ms": 1234,
        ... })
    """
    log = logger or get_logger()
    payload = data or {}

    import json
    log_func = getattr(log, level.lower(), log.info)
    log_func(f"EVENT:{event} | {json.dumps(payload, ensure_ascii=False, default=str)}")


def log_error_with_context(
    error: Exception,
    context: Optional[Dict[str, Any]] = None,
    logger: Optional[Any] = None,
):
    """记录带完整上下文的错误

    Args:
        error: 异常对象
        context: 额外上下文
        logger: logger 实例
    """
    log = logger or get_logger()
    ctx = context or {}

    to_dict = getattr(error, "to_dict", None)
    if callable(to_dict):
        err_data = to_dict()
        if isinstance(err_data, dict):
            ctx.update(err_data)

    # 兼容 loguru 和标准 logging
    if hasattr(log, "opt"):
        # loguru: 使用 opt(exception=True) 记录完整堆栈
        log.opt(exception=True).error(
            f"Error: {error} | Context: {ctx}"
        )
    else:
        # 标准 logging: 使用 exc_info=True
        import logging as std_logging
        if isinstance(log, std_logging.Logger):
            log.error(f"Error: {error} | Context: {ctx}", exc_info=True)
        else:
            log.error(f"Error: {error} | Context: {ctx}")


__all__ = [
    # 配置
    "setup_logging",
    "get_logger",
    "reset_logger",
    "LogLevel",
    # 性能
    "log_time",
    "timed",
    # 结构化
    "log_event",
    "log_error_with_context",
]
