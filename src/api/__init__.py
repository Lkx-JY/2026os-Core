"""FastAPI 应用入口 — API 层初始化与生命周期管理."""

import time
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
from .dependencies import load_yaml_config as load_config
from ..common.logging import setup_logging, get_logger

logger = get_logger()

# 服务启动时间戳（用于健康检查的 uptime 计算）
_START_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理 — 启动时初始化，关闭时清理"""
    # ── 启动 ────────────────────────────────────────
    # ★ 日志系统必须先初始化，否则后续 logger.info() 不会写入日志文件
    setup_logging(
        log_dir="logs",
        app_name="CoreLinuxCommit",
        console_level="INFO",
        file_level="DEBUG",
    )

    logger.info("=" * 60)
    logger.info("Core.LinuxCommit API Server Starting...")
    logger.info("Loading configuration...")
    config = load_config()
    logger.info(f"Embedding model: {config.get('model', {}).get('embedding', 'N/A')}")
    logger.info(f"Vector DB: {config.get('database', {}).get('type', 'N/A')}")

    # ★ 免费模型可用性检查 ──────────────────────────
    _check_free_model_on_startup()

    # ★ AUTH_API_KEY 检查 (生产环境建议配置) ─────────
    import os as _os
    if not _os.environ.get("AUTH_API_KEY", "").strip():
        logger.warning("⚠️  未配置 AUTH_API_KEY — API 端点无鉴权保护")
        logger.warning("   生产环境建议设置: export AUTH_API_KEY=your-secret-key")

    logger.info("API server ready to accept requests")
    logger.info("=" * 60)

    yield  # 应用运行中...

    # ── 关闭 ────────────────────────────────────────
    logger.info("Core.LinuxCommit API Server shutting down...")


def _check_free_model_on_startup():
    """启动时检查免费模型可用性

    检查顺序:
    1. Ollama 本地服务是否可用（推荐）
    2. 环境变量 OPENAI_API_KEY 是否配置了部署者 Key（向后兼容）
    3. 两者都无 → 降级到规则引擎（仍可正常服务）
    """
    import os

    # 检查 Ollama
    try:
        from ..generator.llm import check_ollama_health
        if check_ollama_health():
            logger.info("✓ Ollama 本地模型可用（免费，用户无需提供 API Key）")
            return
    except Exception:
        pass

    logger.warning("⚠️  Ollama 本地模型不可用")

    # 检查部署者是否配置了 OPENAI_API_KEY（仅用于向后兼容）
    deployer_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if deployer_key:
        logger.info("✓ 检测到 OPENAI_API_KEY（向后兼容，部署者付费模式）")
        logger.warning("   注意: 此模式下所有 LLM 调用将由部署者付费")
        return

    logger.warning("   → 将使用规则引擎作为 LLM 降级方案")
    logger.info("💡 安装 Ollama 以获得免费的高质量 LLM 分析:")
    logger.info("   curl -fsSL https://ollama.com/install.sh | sh")
    logger.info("   ollama pull qwen2.5:7b")


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
        import psutil
        return {
            "status": "healthy",
            "service": "Core.LinuxCommit API",
            "version": "1.0.0",
            "uptime_seconds": round(time.time() - _START_TIME, 2),
            "memory_mb": round(psutil.Process().memory_info().rss / (1024 * 1024), 2),
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
