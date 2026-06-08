"""API 依赖注入 — 鉴权、配置、服务实例获取."""

import os
from typing import Optional
from functools import lru_cache

from fastapi import Header, HTTPException, Depends
import yaml

from ...common.logging import get_logger

logger = get_logger()


# ============================================================================
# 配置加载
# ============================================================================

@lru_cache()
def load_config() -> dict:
    """加载 config.yaml 配置（带缓存）"""
    config_paths = [
        os.environ.get("CONFIG_PATH", ""),
        "configs/config.yaml",
        os.path.join(os.path.dirname(__file__), "../../../configs/config.yaml"),
    ]
    for path in config_paths:
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                logger.info(f"Config loaded from {path}")
                return config or {}
    logger.warning("No config file found, using defaults")
    return {}


def get_config() -> dict:
    """获取配置字典（FastAPI 依赖注入）"""
    return load_config()


# ============================================================================
# API Key 鉴权 (可选 — 用于生产环境)
# ============================================================================

API_KEY_ENV = os.environ.get("API_KEY", "")


def verify_api_key(x_api_key: Optional[str] = Header(None)) -> Optional[str]:
    """验证 API Key — 若未配置 API_KEY 则跳过鉴权

    使用方式:
        @router.get("/protected")
        async def protected_route(api_key: str = Depends(verify_api_key)):
            ...
    """
    if not API_KEY_ENV:
        # 未配置 API_KEY，允许所有请求
        return None
    if x_api_key == API_KEY_ENV:
        return x_api_key
    raise HTTPException(
        status_code=401,
        detail={"code": "UNAUTHORIZED", "message": "无效的 API Key"},
    )


# ============================================================================
# 分页参数
# ============================================================================

class PaginationParams:
    """分页参数依赖

    使用方式:
        @router.get("/items")
        async def list_items(pagination: PaginationParams = Depends()):
            ...
    """

    def __init__(
        self,
        page: int = 1,
        page_size: int = 20,
    ):
        self.page = max(1, page)
        self.page_size = min(max(1, page_size), 100)
        self.offset = (self.page - 1) * self.page_size


# ============================================================================
# 服务实例 (懒加载)
# ============================================================================

_services_cache: dict = {}


def get_analysis_service():
    """获取分析服务实例 (单例)"""
    if "analysis" not in _services_cache:
        from ...services import run_online_diagnosis
        _services_cache["analysis"] = run_online_diagnosis
    return _services_cache["analysis"]


__all__ = [
    "load_config",
    "get_config",
    "verify_api_key",
    "PaginationParams",
    "get_analysis_service",
]
