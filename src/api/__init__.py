"""FastAPI 应用入口 — API 层初始化与生命周期管理."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .routers import api_router
from .middleware import (
    setup_cors,
    setup_exception_handlers,
    TimingMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
)
from .dependencies import load_config
from ..common.logging import setup_logging, get_logger

logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理 — 启动时初始化，关闭时清理"""
    # ── 启动 ────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Core.LinuxCommit API Server Starting...")
    logger.info("Loading configuration...")
    config = load_config()
    logger.info(f"Embedding model: {config.get('model', {}).get('embedding', 'N/A')}")
    logger.info(f"Vector DB: {config.get('database', {}).get('type', 'N/A')}")

    # 初始化日志系统
    setup_logging(
        log_dir="logs",
        app_name="CoreLinuxCommit",
        console_level="INFO",
        file_level="DEBUG",
    )

    logger.info("API server ready to accept requests")
    logger.info("=" * 60)

    yield  # 应用运行中...

    # ── 关闭 ────────────────────────────────────────
    logger.info("Core.LinuxCommit API Server shutting down...")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用

    包含:
    - CORS 跨域配置
    - 请求计时
    - 速率限制
    - 请求日志
    - 全局异常处理
    - 健康检查
    """
    app = FastAPI(
        title="Core.LinuxCommit — Kernel Crash Patch Matching",
        description="""
## 操作系统宕机 Upstream Patch 智能匹配系统

基于 RAG (Retrieval-Augmented Generation) + Linux Kernel Debugging + LLM 的
自动化内核补丁匹配系统。

### 核心功能
- **宕机日志分析**: 提交 dmesg/vmcore 日志，自动识别根因
- **补丁智能检索**: 从百万级 Linux kernel commit 中精准匹配修复补丁
- **LLM 分析解释**: 生成可读的自然语言分析报告
""",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # ── 中间件注册 (顺序重要) ───────────────────────
    setup_cors(app)
    app.add_middleware(TimingMiddleware)
    app.add_middleware(RateLimitMiddleware, max_requests=60, window_seconds=60)
    app.add_middleware(RequestLoggingMiddleware)

    # ── 异常处理 ─────────────────────────────────────
    setup_exception_handlers(app)

    # ── 路由 ────────────────────────────────────────
    app.include_router(api_router)

    # ── 健康检查 ─────────────────────────────────────
    @app.get("/health", tags=["Health"])
    async def health_check():
        """健康检查端点"""
        import time
        import psutil
        return {
            "status": "healthy",
            "service": "Core.LinuxCommit API",
            "version": "1.0.0",
            "uptime_seconds": time.time() - __import__("time").time(),
            "memory_mb": psutil.Process().memory_info().rss / (1024 * 1024),
        }

    @app.get("/", tags=["Root"])
    async def root():
        """根路径 — API 导航"""
        return {
            "service": "Core.LinuxCommit — Kernel Crash Patch Matching",
            "version": "1.0.0",
            "docs": "/api/docs",
            "endpoints": {
                "analyze": "/api/v1/analyze",
                "search": "/api/v1/search",
                "stats": "/api/v1/stats",
                "health": "/health",
            },
        }

    return app


# ── 全局应用实例 ────────────────────────────────────
app = create_app()


__all__ = ["app", "create_app"]
