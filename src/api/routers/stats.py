"""统计路由 — 系统概览和仪表盘数据."""

import time

from fastapi import APIRouter, Depends

from ..schemas.responses import StatsResponse
from ..dependencies import get_config
from ...common.logging import get_logger

logger = get_logger()
router = APIRouter(prefix="/stats", tags=["Stats"])

# 服务启动时间
_START_TIME = time.time()

# 模拟统计计数器
_mock_stats = {
    "total_analyses": 0,
}


@router.get("", response_model=StatsResponse)
async def get_stats(config: dict = Depends(get_config)) -> StatsResponse:
    """获取系统概览统计

    返回:
    - 已索引 Commit 总数
    - 已完成分析总数
    - 子系统/Bug 类型分布
    - 向量库大小
    - 服务运行时间
    - 平均分析耗时
    """
    return StatsResponse(
        total_commits=1_250_000,  # 模拟值 — Linux kernel ~1.25M commits
        total_analyses=_mock_stats["total_analyses"],
        subsystems=[
            {"name": "kernel", "count": 180_000},
            {"name": "drivers", "count": 620_000},
            {"name": "net", "count": 95_000},
            {"name": "fs", "count": 110_000},
            {"name": "mm", "count": 75_000},
            {"name": "arch", "count": 120_000},
            {"name": "others", "count": 50_000},
        ],
        bug_types=[
            {"name": "race_condition", "count": 28000, "description": "竞态条件"},
            {"name": "use_after_free", "count": 15000, "description": "释放后使用"},
            {"name": "null_pointer_dereference", "count": 22000, "description": "空指针解引用"},
            {"name": "memory_corruption", "count": 12000, "description": "内存损坏"},
            {"name": "deadlock", "count": 8000, "description": "死锁"},
            {"name": "soft_lockup", "count": 5000, "description": "软锁定"},
        ],
        vector_db_size=1250000,
        uptime_seconds=time.time() - _START_TIME,
        avg_analysis_ms=1850.5,
    )


@router.post("/increment-analysis")
async def increment_analysis_count() -> dict:
    """增加分析计数 (内部使用)"""
    _mock_stats["total_analyses"] += 1
    return {"total_analyses": _mock_stats["total_analyses"]}
