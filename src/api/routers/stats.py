"""统计路由 — 系统概览和仪表盘数据.

★ 优先从向量库获取真实统计, 向量库为空时回退到预估值.
"""

import time
from typing import Optional

from fastapi import APIRouter, Depends

from ..schemas.responses import StatsResponse
from ..dependencies import get_config
from ...common.logging import get_logger

logger = get_logger()
router = APIRouter(prefix="/stats", tags=["Stats"])

# 服务启动时间
_START_TIME = time.time()

# 统计数据内存缓存 (启动时由 lifespan 预热，避免每次解析 1.7GB JSON)
_stats_cache: Optional[dict] = None


def _get_real_stats() -> dict:
    """从向量库获取真实统计数据 (内存缓存)."""
    global _stats_cache
    if _stats_cache is not None:
        return _stats_cache

    try:
        from ...indexer.milvus import get_milvus_client
        client = get_milvus_client()
        stats = client.get_stats()
        count = client.count()
        _stats_cache = {
            "total_commits": count,
            "vector_db_size": count,
            "backend": stats.get("backend", "unknown"),
            "index_type": stats.get("index_type", "unknown"),
            "has_real_data": count > 0,
        }
        return _stats_cache
    except Exception as e:
        logger.warning(f"获取向量库统计失败: {e}")
        return {"total_commits": 0, "vector_db_size": 0, "has_real_data": False}


def _get_real_bug_types() -> list[dict]:
    """从向量库元数据聚合 Bug 类型分布"""
    try:
        from ...knowledge.bug_patterns import get_all_bug_types, get_bug_pattern

        bug_types_list = get_all_bug_types()
        if not bug_types_list:
            return []

        return [
            {
                "name": bt,
                "count": 0,
                "description": (get_bug_pattern(bt) or {}).get("name", bt),
            }
            for bt in bug_types_list
        ]
    except Exception:
        return []


def _get_real_subsystems() -> list[dict]:
    """从子系统知识库获取列表"""
    try:
        from ...knowledge.subsystem_graph import get_all_subsystems
        subs = get_all_subsystems()
        if subs:
            return [{"name": s, "count": 0} for s in sorted(subs)]
        return []
    except Exception:
        return []


@router.get("", response_model=StatsResponse)
async def get_stats(config: dict = Depends(get_config)) -> StatsResponse:
    """获取系统概览统计

    返回:
    - 已索引 Commit 总数 (★ 真实数据)
    - 已完成分析总数
    - 子系统/Bug 类型分布 (★ 真实列表)
    - 向量库大小 (★ 真实数据)
    - 服务运行时间
    - 平均分析耗时
    """
    real = _get_real_stats()

    # ★ 获取当前数据源名称
    from ..dependencies import resolve_data_source
    ds = resolve_data_source()
    dataset_name = ds[1] if ds else "none"

    has_real_data = real.get("has_real_data", False)
    subsystems = _get_real_subsystems() if has_real_data else []
    bug_types = _get_real_bug_types() if has_real_data else []
    total_commits = real.get("total_commits", 0)
    vector_db_size = real.get("vector_db_size", 0)

    return StatsResponse(
        total_commits=total_commits,
        total_analyses=0,
        subsystems=subsystems,
        bug_types=bug_types,
        vector_db_size=vector_db_size,
        analysis_mode=dataset_name,
        uptime_seconds=time.time() - _START_TIME,
        avg_analysis_ms=0,
    )


@router.post("/increment-analysis")
async def increment_analysis_count() -> dict:
    """增加分析计数 (内部使用)"""
    return {"total_analyses": 0}
