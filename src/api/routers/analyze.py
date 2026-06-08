"""分析路由 — 宕机日志分析的核心 API."""

import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends

from ..schemas.requests import AnalyzeRequest
from ..schemas.responses import AnalyzeResponse, TaskStatusResponse, ErrorResponse
from ..schemas.entities import (
    RootCauseInfo,
    MatchedPatch,
    CommitInfo,
    AnalysisStep,
)
from ..dependencies import get_config
from ..storage import get_task_store, RedisTaskStore
from ...common.logging import get_logger

logger = get_logger()
router = APIRouter(prefix="/analyze", tags=["Analysis"])

# Redis 任务存储 (跨进程共享，支持多实例部署)
_task_store: Optional[RedisTaskStore] = None


def _get_store() -> RedisTaskStore:
    """获取任务存储实例"""
    global _task_store
    if _task_store is None:
        _task_store = get_task_store()
    return _task_store


def _save_task(task_id: str, data: dict) -> None:
    """保存任务到 Redis，回退到内存"""
    store = _get_store()
    # 获取现有数据并合并
    existing = store.get_task(task_id) or _memory_tasks.get(task_id, {})
    
    # 转换 Pydantic 模型为字典
    serializable_data = {}
    for key, value in data.items():
        if hasattr(value, 'model_dump'):
            serializable_data[key] = value.model_dump()
        elif hasattr(value, 'dict'):
            serializable_data[key] = value.dict()
        else:
            serializable_data[key] = value
    
    existing.update(serializable_data)
    
    logger.info(f"Saving task {task_id} to Redis: {list(data.keys())}")
    success = store.save_task(task_id, existing)
    logger.info(f"Save to Redis: {success}")
    
    if not success:
        # Redis 不可用时的内存回退
        logger.warning(f"Redis save failed, using memory fallback for {task_id}")
        _memory_tasks[task_id] = existing


def _get_task(task_id: str) -> Optional[dict]:
    """从 Redis 获取任务，回退到内存"""
    store = _get_store()
    task = store.get_task(task_id)
    if task is None and task_id in _memory_tasks:
        task = _memory_tasks[task_id]
    return task


# 内存回退存储 (当 Redis 不可用时)
_memory_tasks: dict[str, dict] = {}


def _simulate_analysis(task_id: str, request: AnalyzeRequest) -> None:
    """模拟分析流水线 (实际部署时替换为真实的 RAG pipeline)"""
    steps: list[AnalysisStep] = []

    try:
        # Step 1: 日志解析
        steps.append(AnalysisStep(
            name="日志解析", status="running",
            started_at=datetime.utcnow(),
        ))
        _save_task(task_id, {
            "task_id": task_id,
            "status": "running",
            "progress": 0.1,
            "created_at": datetime.utcnow(),
            "steps": steps,
            "request": request,
        })
        time.sleep(0.3)

        steps[-1].status = "completed"
        steps[-1].completed_at = datetime.utcnow()
        steps[-1].detail = f"成功解析 {request.log_type} 日志，提取 {len(request.log_content.splitlines())} 行"

        # Step 2: Root Cause 抽象
        steps.append(AnalysisStep(
            name="根因分析", status="running",
            started_at=datetime.utcnow(),
        ))
        _save_task(task_id, {"progress": 0.3, "steps": steps})
        time.sleep(0.5)

        # 基于日志关键词推断根因
        log_lower = request.log_content.lower()
        if "list_del corruption" in log_lower or "list_add corruption" in log_lower:
            root_cause = RootCauseInfo(
                root_cause="race_condition",
                subsystem="list",
                confidence=0.92,
                summary="链表并发操作导致的竞态条件问题，可能涉及 list_del/list_add 时的锁保护缺失",
                key_symptoms=["list_del corruption", "list corruption"],
            )
        elif "soft lockup" in log_lower:
            root_cause = RootCauseInfo(
                root_cause="soft_lockup",
                subsystem="scheduler",
                confidence=0.88,
                summary="CPU 软锁定，某个 CPU 在内核态执行时间过长未调度",
                key_symptoms=["soft lockup", "CPU stuck"],
            )
        elif "use-after-free" in log_lower or "uaf" in log_lower:
            root_cause = RootCauseInfo(
                root_cause="use_after_free",
                subsystem="mm",
                confidence=0.85,
                summary="释放后使用 (UAF) 漏洞，对象被释放后仍被引用",
                key_symptoms=["use-after-free", "freed memory accessed"],
            )
        elif "null pointer" in log_lower or "NULL pointer" in log_lower:
            root_cause = RootCauseInfo(
                root_cause="null_pointer_dereference",
                subsystem="kernel",
                confidence=0.90,
                summary="空指针解引用，未做有效性检查即访问指针成员",
                key_symptoms=["NULL pointer dereference", "unable to handle kernel NULL pointer"],
            )
        elif "page fault" in log_lower or "BUG:" in log_lower:
            root_cause = RootCauseInfo(
                root_cause="memory_corruption",
                subsystem="mm",
                confidence=0.78,
                summary="内存页错误或内核 BUG 触发，可能与 slab/slub 分配器相关",
                key_symptoms=["page fault", "BUG:", "kernel panic"],
            )
        else:
            root_cause = RootCauseInfo(
                root_cause="unknown",
                subsystem="kernel",
                confidence=0.50,
                summary="日志缺乏明确特征，需要进一步使用 drgn/vmcore 进行分析",
                key_symptoms=[],
            )

        steps[-1].status = "completed"
        steps[-1].completed_at = datetime.utcnow()
        steps[-1].detail = f"根因类型: {root_cause.root_cause}, 置信度: {root_cause.confidence:.2f}"

        # Step 3: 向量检索
        steps.append(AnalysisStep(
            name="向量检索", status="running",
            started_at=datetime.utcnow(),
        ))
        _save_task(task_id, {"progress": 0.5, "steps": steps})
        time.sleep(0.4)

        matched_patches = _get_mock_patches(request.top_k, root_cause)

        steps[-1].status = "completed"
        steps[-1].completed_at = datetime.utcnow()
        steps[-1].detail = f"Milvus 召回 Top-100, Reranker 重排后返回 Top-{request.top_k}"

        # Step 4: LLM 解释生成
        if request.enable_llm_explanation:
            steps.append(AnalysisStep(
                name="LLM 解释生成", status="running",
                started_at=datetime.utcnow(),
            ))
            _save_task(task_id, {"progress": 0.8, "steps": steps})
            time.sleep(0.6)

            llm_explanation = _generate_mock_explanation(root_cause, matched_patches)
            steps[-1].status = "completed"
            steps[-1].completed_at = datetime.utcnow()
            steps[-1].detail = "LLM 分析完成"
        else:
            llm_explanation = None

        _save_task(task_id, {
            "status": "completed",
            "progress": 1.0,
            "root_cause": root_cause,
            "matched_patches": matched_patches,
            "steps": steps,
            "llm_explanation": llm_explanation,
            "completed_at": datetime.utcnow(),
        })

    except Exception as e:
        logger.error(f"Analysis task {task_id} failed: {e}")
        _save_task(task_id, {"status": "failed", "error": str(e)})
        if steps and steps[-1].status == "running":
            steps[-1].status = "failed"
            steps[-1].detail = str(e)


def _get_mock_patches(top_k: int, root_cause: RootCauseInfo) -> list[MatchedPatch]:
    """生成模拟匹配补丁 (实际部署时替换为真实 RAG 结果)"""
    mock_commits = {
        "race_condition": [
            ("a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f67890", "list: fix race condition in list_del", "修复 list_del 操作的竞态条件，添加适当的 spin_lock 保护", "spin_lock_irqsave"),
            ("b2c3d4e5f6a7b2c3d4e5f6a7b2c3d4e5f6789012", "locking: add missing lock in list manipulation", "在链表操作路径添加缺失的 mutex_lock", "mutex_lock"),
            ("c3d4e5f6a7b8c3d4e5f6a7b8c3d4e5f67890123", "rcu: fix RCU stall in list traversal", "修复遍历链表时的 RCU 停滞问题", "rcu_read_lock"),
        ],
        "soft_lockup": [
            ("d4e5f6a7b8c9d4e5f6a7b8c9d4e5f678901234", "sched: fix soft lockup in scheduler", "修复调度器中的软锁定问题，增加调度点", "schedule"),
            ("e5f6a7b8c9d0e5f6a7b8c9d0e5f6789012345", "rcu: resolve RCU soft lockup", "解决长时间 RCU 读锁导致的软锁定", "rcu_read_unlock"),
        ],
        "use_after_free": [
            ("f6a7b8c9d0e1f6a7b8c9d0e1f6a78901234567", "mm: fix use-after-free in kfree_rcu", "修复 kfree_rcu 中的 UAF 漏洞", "kfree_rcu"),
            ("a7b8c9d0e1f2a7b8c9d0e1f2a789012345678", "slab: fix use-after-free in kmem_cache_free", "修复 slab 分配器中的释放后使用", "kmem_cache_free"),
        ],
        "null_pointer_dereference": [
            ("b8c9d0e1f2a3b8c9d0e1f2a3b890123456789", "net: add NULL check in netdev_rx_handler", "在网络设备接收处添加空指针检查", "NULL"),
            ("c9d0e1f2a3b4c9d0e1f2a3b4c901234567890", "fs: fix NULL pointer dereference in vfs_read", "修复 vfs_read 路径的空指针解引用", "NULL pointer"),
        ],
        "memory_corruption": [
            ("d0e1f2a3b4c5d0e1f2a3b4c5d01234567890a", "mm/slub: fix slab corruption", "修复 SLUB 分配器的 slab 腐败问题", "slab"),
            ("e1f2a3b4c5d6e1f2a3b4c5d6e1234567890ab", "mm: fix page corruption in swap", "修复 swap 页面腐败", "swap"),
        ],
        "unknown": [
            ("f2a3b4c5d6e7f2a3b4c5d6e7f234567890abc", "kernel: fix general protection fault", "修复通用保护错误", "general protection"),
            ("a3b4c5d6e7f8a3b4c5d6e7f8a34567890abcd", "x86: fix kernel crash in interrupt handler", "修复中断处理程序中的内核崩溃", "interrupt"),
        ],
    }

    patches = mock_commits.get(root_cause.root_cause, mock_commits["unknown"])
    results = []
    for i, (commit_id, title, message, highlight) in enumerate(patches[:top_k]):
        results.append(MatchedPatch(
            rank=i + 1,
            commit=CommitInfo(
                commit_id=commit_id,
                title=title,
                message=message,
                author="Linus Torvalds",
                date="2025-08-15",
                subsystem=root_cause.subsystem,
                bug_type=root_cause.root_cause,
                files_changed=[f"{root_cause.subsystem}/core.c"],
                diff_preview=f"+ {highlight}(&lock);\n- old_func(&data);\n+ new_safe_func(&data);",
            ),
            relevance_score=round(0.95 - i * 0.08, 2),
            recall_score=round(0.85 - i * 0.05, 2),
            rerank_score=round(0.92 - i * 0.06, 2),
            match_reason=f"该补丁通过 {highlight} 操作修复了与当前崩溃日志匹配的 {root_cause.root_cause} 问题",
            diff_highlights=[f"+ {highlight}()"],
        ))
    return results


def _generate_mock_explanation(root_cause: RootCauseInfo, patches: list[MatchedPatch]) -> str:
    """生成模拟 LLM 解释"""
    if not patches:
        return "未能找到匹配的补丁，建议进一步使用 drgn 分析 vmcore。"

    top = patches[0]
    return f"""
## 根因分析

根据崩溃日志分析，系统发生了 **{root_cause.root_cause}** 类型的故障，
影响子系统为 `{root_cause.subsystem}`，置信度 {root_cause.confidence:.0%}。

关键症状：{"、".join(root_cause.key_symptoms)}

## 推荐补丁

最匹配的补丁是 **{top.commit.title}** (commit `{top.commit.commit_id[:12]}`)：
- **相关性分数**: {top.relevance_score}
- **修复方式**: {top.commit.diff_preview[:200]}
- **匹配理由**: {top.match_reason}

## 修复建议

1. 优先应用排名第一的补丁，该补丁直接修复了根因问题
2. 检查子系统 `{root_cause.subsystem}` 中是否存在类似的未修复路径
3. 建议运行回归测试确认修复效果
"""


@router.post("", response_model=AnalyzeResponse, status_code=202)
async def create_analysis(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    config: dict = Depends(get_config),
) -> AnalyzeResponse:
    """提交宕机日志进行分析

    异步执行分析流水线:
    1. 日志解析 (正则 + LLM 特征提取)
    2. 根因抽象 (Root Cause Abstraction)
    3. 向量检索 (Milvus/FAISS Top-K Recall)
    4. Reranker 精确排序
    5. LLM 分析解释生成

    返回 task_id 后可通过 GET /api/v1/analyze/{task_id} 轮询结果。
    """
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    created_at = datetime.utcnow()

    _save_task(task_id, {
        "task_id": task_id,
        "status": "running",
        "progress": 0.0,
        "created_at": created_at,
        "request": request,
    })

    background_tasks.add_task(_simulate_analysis, task_id, request)
    logger.info(f"Analysis task created: {task_id}")

    return AnalyzeResponse(
        task_id=task_id,
        status="running",
        created_at=created_at,
    )


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_analysis_status(task_id: str) -> TaskStatusResponse:
    """查询分析任务状态和结果

    - **pending/running**: 任务进行中, 返回当前进度
    - **completed**: 返回完整分析结果
    - **failed**: 返回错误信息
    """
    task = _get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    result = None
    if task["status"] == "completed":
        created_at = task.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        completed_at = task.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)
        
        result = AnalyzeResponse(
            task_id=task_id,
            status="completed",
            root_cause=task.get("root_cause"),
            matched_patches=task.get("matched_patches", []),
            analysis_steps=task.get("steps", []),
            llm_explanation=task.get("llm_explanation"),
            created_at=created_at or datetime.utcnow(),
            completed_at=completed_at,
            elapsed_ms=int(
                (completed_at - created_at).total_seconds() * 1000
            ) if completed_at and created_at else None,
        )

    return TaskStatusResponse(
        task_id=task_id,
        status=task["status"],
        progress=task.get("progress", 0.0),
        result=result,
        error=task.get("error"),
    )


@router.get("", response_model=list[dict])
async def list_analyses(page: int = 1, page_size: int = 20) -> list[dict]:
    """列出历史分析任务"""
    store = _get_store()
    all_task_ids = store.list_tasks()
    
    tasks = []
    for task_id in all_task_ids:
        task = store.get_task(task_id)
        if task:
            created_at = task.get("created_at")
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    created_at = datetime.utcnow()
            elif not isinstance(created_at, datetime):
                created_at = datetime.utcnow()
            tasks.append((task, created_at))
    
    # 按创建时间排序
    tasks.sort(key=lambda x: x[1], reverse=True)
    
    start = (page - 1) * page_size
    end = start + page_size

    return [
        {
            "task_id": t["task_id"],
            "status": t["status"],
            "created_at": t.get("created_at"),
            "log_type": t.get("request", {}).get("log_type", "unknown"),
            "progress": t.get("progress", 0),
        }
        for t, _ in tasks[start:end]
    ]
