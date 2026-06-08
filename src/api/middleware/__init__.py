"""API 中间件 — CORS, Rate Limiting, Error Handling, Request Logging."""

import time
import asyncio
from collections import defaultdict
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ...common.logging import get_logger
from ..schemas.responses import ErrorResponse

logger = get_logger()


# ============================================================================
# CORS 配置
# ============================================================================

def setup_cors(app: FastAPI) -> None:
    """配置跨域资源共享 — 允许前端开发和生产环境访问"""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",   # Vite dev server
            "http://localhost:3000",   # 备选开发端口
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ],
        allow_origin_regex=r"https?://.*\.local(:\d+)?",  # 本地网络
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-Request-ID",
            "X-Client-Version",
        ],
        expose_headers=[
            "X-Request-ID",
            "X-Response-Time",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ],
        max_age=3600,  # 预检请求缓存 1 小时
    )


# ============================================================================
# 请求计时中间件
# ============================================================================

class TimingMiddleware(BaseHTTPMiddleware):
    """为每个请求添加 X-Response-Time 响应头，并记录慢请求"""

    SLOW_REQUEST_MS: float = 1000.0  # 超过此阈值记录警告

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        t_start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - t_start) * 1000

        response.headers["X-Response-Time"] = f"{elapsed_ms:.2f}ms"

        if elapsed_ms > self.SLOW_REQUEST_MS:
            logger.warning(
                f"Slow request: {request.method} {request.url.path} "
                f"took {elapsed_ms:.0f}ms"
            )

        return response


# ============================================================================
# 速率限制中间件 (基于滑动窗口的令牌桶)
# ============================================================================

class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于客户端 IP 的速率限制

    默认: 每分钟 60 次请求，突发允许 10 次。
    对 /api/v1/analyze 端点更严格: 每分钟 30 次。
    """

    def __init__(self, app, *, max_requests: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"

        # 对 analyze 端点限制更严格
        if request.url.path.startswith("/api/v1/analyze"):
            limit = self.max_requests // 2  # 30/min
        else:
            limit = self.max_requests

        async with self._lock:
            now = time.time()
            # 清理过期记录
            window_start = now - self.window_seconds
            self._clients[client_ip] = [
                ts for ts in self._clients[client_ip] if ts > window_start
            ]

            if len(self._clients[client_ip]) >= limit:
                logger.warning(f"Rate limit exceeded for {client_ip}")
                return JSONResponse(
                    status_code=429,
                    content=ErrorResponse(
                        code="RATE_LIMIT",
                        message="请求过于频繁，请稍后再试",
                        detail=f"每分钟最多 {limit} 次请求",
                    ).model_dump(mode="json"),
                )

            self._clients[client_ip].append(now)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(
            limit - len(self._clients[client_ip])
        )
        return response


# ============================================================================
# 全局异常处理
# ============================================================================

def setup_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器"""

    from ...common.exceptions import CoreLinuxCommitError

    @app.exception_handler(CoreLinuxCommitError)
    async def business_exception_handler(request: Request, exc: CoreLinuxCommitError):
        """业务异常 → 结构化错误响应"""
        logger.error(f"Business error: [{exc.code}] {exc.message}")
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                code=exc.code,
                message=exc.message,
                detail=str(exc.context) if exc.context else None,
            ).model_dump(mode="json"),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """参数校验异常"""
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                code="VALIDATION_ERROR",
                message="请求参数校验失败",
                detail=str(exc),
            ).model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """未捕获异常 — 兜底处理"""
        logger.opt(exception=True).error(f"Unhandled error: {exc}")
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                code="INTERNAL_ERROR",
                message="服务器内部错误",
                detail="请查看服务端日志获取详细信息",
            ).model_dump(mode="json"),
        )


# ============================================================================
# 请求日志中间件
# ============================================================================

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """记录每个请求的基本信息"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        logger.debug(f"→ {request.method} {request.url.path} from {request.client.host if request.client else '?'}")
        response = await call_next(request)
        logger.debug(f"← {request.method} {request.url.path} → {response.status_code}")
        return response


__all__ = [
    "setup_cors",
    "setup_exception_handlers",
    "TimingMiddleware",
    "RateLimitMiddleware",
    "RequestLoggingMiddleware",
]
