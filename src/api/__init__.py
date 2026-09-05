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
        app_name="Linux 内核宕机自动诊断与补丁匹配系统",
        console_level="INFO",
        file_level="DEBUG",
    )

    logger.info("=" * 60)
    logger.info("Linux 内核宕机自动诊断与补丁匹配系统 API Server Starting...")
    logger.info("Loading configuration...")
    config = load_config()
    logger.info(f"Embedding model: {config.get('model', {}).get('embedding', 'N/A')}")
    logger.info(f"Vector DB: {config.get('database', {}).get('type', 'N/A')}")

    # ★ 免费模型可用性检查 ──────────────────────────
    _check_free_model_on_startup()

    # ★ 预热模型和向量库 (避免首次请求等待) ──────────
    _warmup_models()

    # ★ AUTH_API_KEY 检查 (生产环境建议配置) ─────────
    import os as _os
    if not _os.environ.get("AUTH_API_KEY", "").strip():
        logger.warning("⚠️  未配置 AUTH_API_KEY — API 端点无鉴权保护")
        logger.warning("   生产环境建议设置: export AUTH_API_KEY=your-secret-key")

    logger.info("API server ready to accept requests")
    logger.info("=" * 60)

    yield  # 应用运行中...

    # ── 关闭 ────────────────────────────────────────
    logger.info("Linux 内核宕机自动诊断与补丁匹配系统 API Server shutting down...")


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


def _warmup_models():
    """启动时预热所有模型和向量库.

    在 lifespan 中调用，确保首次请求不需要等待冷启动。
    预热内容:
    - BGE-M3 Embedding 模型 (约 3-6s)
    - BGE-Reranker-v2 模型 (约 5-8s)
    - FAISS 向量库 + 元数据 (约 1-2s，内存索引加载)
    """
    import time as _time
    import os as _os

    t0 = _time.time()
    logger.info("预热模型和向量库...")

    # 1. 预热 Embedding 模型 (单例，首次调用触发加载)
    try:
        from ..indexer.embedding import get_encoder
        encoder = get_encoder()
        _ = encoder.get_info()  # 触发 _lazy_init()
        logger.info(f"  ✓ Embedding 模型就绪 ({_time.time()-t0:.1f}s)")
    except Exception as e:
        logger.warning(f"  ⚠ Embedding 预热失败: {e}")

    # 2. 预热 FAISS 向量库 (单例，首次调用加载索引)
    # ★ 自动检测数据源: data_full → data
    try:
        from ..api.dependencies import resolve_data_source
        ds = resolve_data_source()
        if ds:
            logger.info(f"  ✓ 数据源: {ds[1]} (path={ds[0]})")
        else:
            logger.warning("  ⚠ 未检测到向量库数据源 (data_full/ 和 data/ 均无 FAISS 索引)")

        from ..indexer.milvus import get_milvus_client
        client = get_milvus_client()
        count = client.count()
        logger.info(f"  ✓ 向量库就绪: {count:,} 条 ({_time.time()-t0:.1f}s)")
    except Exception as e:
        logger.warning(f"  ⚠ 向量库预热失败: {e}")

    # 3. 预热 Reranker 模型 (单例，首次调用触发加载)
    try:
        from ..retriever.rerank import get_reranker
        reranker = get_reranker()
        _ = reranker.compute_scores(
            query="warmup test",
            documents=["warmup document"],
        )
        logger.info(f"  ✓ Reranker 模型就绪 ({_time.time()-t0:.1f}s)")
    except Exception as e:
        logger.warning(f"  ⚠ Reranker 预热失败: {e} (非致命)")

    logger.info(f"预热完成，总耗时 {_time.time()-t0:.1f}s")


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
        title="Linux 内核宕机自动诊断与补丁匹配系统 — Kernel Crash Patch Matching",
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
            "service": "Linux 内核宕机自动诊断与补丁匹配系统 API",
            "version": "1.0.0",
            "uptime_seconds": round(time.time() - _START_TIME, 2),
            "memory_mb": round(psutil.Process().memory_info().rss / (1024 * 1024), 2),
        }

    @app.get("/", tags=["Root"])
    async def root():
        """根路径 — API 导航"""
        return {
            "service": "Linux 内核宕机自动诊断与补丁匹配系统 — Kernel Crash Patch Matching",
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
