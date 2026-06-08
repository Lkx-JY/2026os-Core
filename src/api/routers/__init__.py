"""API 路由汇总."""

from fastapi import APIRouter

from .analyze import router as analyze_router
from .search import router as search_router
from .stats import router as stats_router

# 创建主路由, 挂载所有子路由
api_router = APIRouter(prefix="/api/v1")

api_router.include_router(analyze_router)
api_router.include_router(search_router)
api_router.include_router(stats_router)

__all__ = ["api_router"]
