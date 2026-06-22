"""API 依赖注入 — 鉴权、配置、服务实例获取."""

import os
from typing import Optional

from fastapi import Header, HTTPException, Depends

from ...common.logging import get_logger

# ★ 复用公共配置模块，避免重复实现
from ...common.config import load_yaml_config, get_config

logger = get_logger()


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
# 向量库状态检查 (analyze 和 search 路由共用)
# ============================================================================

def check_index_ready() -> bool:
    """检查向量库是否已初始化并有数据，同时验证嵌入模型是否就绪

    供 analyze 和 search 路由共用，避免代码重复。
    """
    try:
        from ...indexer.milvus import get_milvus_client
        from ...indexer.embedding import get_encoder

        # 检查嵌入模型（会触发一次性的降级警告）
        encoder = get_encoder()
        info = encoder.get_info()
        if info.get("is_fallback", False):
            logger.warning(
                f"嵌入模型 {info['model_name']} 不可用 ({info.get('init_error', 'unknown')})，"
                f"语义检索将不可靠"
            )

        # 检查向量库
        client = get_milvus_client()
        count = client.count()
        return count > 0
    except Exception as e:
        logger.warning(f"向量库状态检查失败: {e}")
        return False


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
    "load_yaml_config",
    "get_config",
    "verify_api_key",
    "PaginationParams",
    "get_analysis_service",
    "check_index_ready",
]
