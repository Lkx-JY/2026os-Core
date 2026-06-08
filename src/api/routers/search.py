"""搜索路由 — 补丁知识库的搜索和浏览."""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query

from ..schemas.requests import SearchRequest
from ..schemas.responses import SearchResponse, CommitDetailResponse
from ..schemas.entities import CommitInfo
from ..dependencies import get_config
from ...common.logging import get_logger

logger = get_logger()
router = APIRouter(prefix="/search", tags=["Search"])


# 模拟 Commit 数据 (实际部署时从 Milvus/数据库中查询)
_MOCK_COMMITS: list[dict] = [
    {
        "commit_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f67890",
        "title": "list: fix race condition in list_del",
        "message": "Add missing spin_lock protection in list_del operation to prevent concurrent modification corruption.",
        "author": "Peter Zijlstra",
        "date": "2025-09-15",
        "subsystem": "kernel",
        "bug_type": "race_condition",
        "files_changed": ["kernel/sched/list.c", "include/linux/list.h"],
        "diff_preview": "+ spin_lock_irqsave(&list->lock, flags);\n  __list_del_entry(entry);\n+ spin_unlock_irqrestore(&list->lock, flags);",
        "fix_tags": ["Fixes: abc123", "Cc: stable@vger.kernel.org"],
    },
    {
        "commit_id": "b2c3d4e5f6a7b2c3d4e5f6a7b2c3d4e5f6789012",
        "title": "mm: fix use-after-free in kmem_cache_free",
        "message": "Resolve UAF vulnerability by adding proper RCU grace period before freeing slab objects.",
        "author": "Andrew Morton",
        "date": "2025-09-10",
        "subsystem": "mm",
        "bug_type": "use_after_free",
        "files_changed": ["mm/slub.c", "mm/slab.c"],
        "diff_preview": "+ synchronize_rcu();\n  kmem_cache_free(cache, obj);\n+ /* Ensure no concurrent readers */",
        "fix_tags": ["Fixes: def456", "Cc: stable@vger.kernel.org"],
    },
    {
        "commit_id": "c3d4e5f6a7b8c3d4e5f6a7b8c3d4e5f67890123",
        "title": "net: fix NULL pointer dereference in napi_poll",
        "message": "Add null check before accessing napi->dev to prevent crash when device is detached.",
        "author": "David S. Miller",
        "date": "2025-09-05",
        "subsystem": "net",
        "bug_type": "null_pointer_dereference",
        "files_changed": ["net/core/dev.c"],
        "diff_preview": "+ if (!napi->dev)\n+     return budget;\n  work = napi->dev->rx_handler(budget);",
        "fix_tags": ["Cc: stable@vger.kernel.org"],
    },
    {
        "commit_id": "d4e5f6a7b8c9d4e5f6a7b8c9d4e5f678901234",
        "title": "sched: fix soft lockup in CFS scheduler",
        "message": "Add cond_resched() call in the load balancing loop to prevent CPU soft lockup.",
        "author": "Ingo Molnar",
        "date": "2025-09-01",
        "subsystem": "kernel",
        "bug_type": "soft_lockup",
        "files_changed": ["kernel/sched/fair.c"],
        "diff_preview": "+ cond_resched();\n  update_rq_clock(rq);",
        "fix_tags": ["Fixes: ghi789"],
    },
    {
        "commit_id": "e5f6a7b8c9d0e5f6a7b8c9d0e5f6789012345",
        "title": "fs: fix deadlock in writeback",
        "message": "Fix circular locking dependency between i_mutex and journal lock in ext4 writeback path.",
        "author": "Theodore Ts'o",
        "date": "2025-08-28",
        "subsystem": "fs",
        "bug_type": "deadlock",
        "files_changed": ["fs/ext4/inode.c", "fs/ext4/ext4_jbd2.c"],
        "diff_preview": "- mutex_lock(&inode->i_mutex);\n+ if (!mutex_trylock(&inode->i_mutex)) {\n+     /* reorder locking */\n+     mutex_lock(&journal->j_lock);\n+     mutex_lock(&inode->i_mutex);\n+ }",
        "fix_tags": ["Fixes: jkl012"],
    },
    {
        "commit_id": "f6a7b8c9d0e1f6a7b8c9d0e1f6a78901234567",
        "title": "locking: add memory barrier in rcu_dereference",
        "message": "Add smp_read_barrier_depends() to prevent CPU speculative execution from bypassing RCU read protection.",
        "author": "Paul E. McKenney",
        "date": "2025-08-20",
        "subsystem": "kernel",
        "bug_type": "race_condition",
        "files_changed": ["include/linux/rcupdate.h"],
        "diff_preview": "+ smp_read_barrier_depends();\n  p = rcu_dereference(ptr);",
        "fix_tags": ["Cc: stable@vger.kernel.org"],
    },
    {
        "commit_id": "a7b8c9d0e1f2a7b8c9d0e1f2a789012345678",
        "title": "drivers: fix slab out-of-bounds in nvme driver",
        "message": "Fix off-by-one buffer overflow in NVMe command submission path.",
        "author": "Jens Axboe",
        "date": "2025-08-15",
        "subsystem": "drivers",
        "bug_type": "memory_corruption",
        "files_changed": ["drivers/nvme/host/core.c"],
        "diff_preview": "- memcpy(dst, src, cmd->len);\n+ memcpy(dst, src, min(cmd->len, MAX_CMD_SIZE));",
        "fix_tags": ["Fixes: mno345"],
    },
]

# 按 commit_id 建立索引
_COMMIT_MAP: dict[str, dict] = {c["commit_id"]: c for c in _MOCK_COMMITS}


@router.post("", response_model=SearchResponse)
async def search_commits(
    request: SearchRequest,
    config: dict = Depends(get_config),
) -> SearchResponse:
    """搜索补丁知识库

    支持:
    - 关键词/语义搜索
    - 按子系统过滤
    - 按 Bug 类型过滤
    - 按内核版本过滤
    - 分页
    """
    query_lower = request.query.lower()
    results = []

    for commit in _MOCK_COMMITS:
        # 文本匹配
        text_match = (
            query_lower in commit["title"].lower()
            or query_lower in commit["message"].lower()
            or any(query_lower in f.lower() for f in commit["files_changed"])
            or any(query_lower in t.lower() for t in commit.get("fix_tags", []))
        )

        if not text_match:
            continue

        # 过滤器
        if request.subsystem and commit["subsystem"] != request.subsystem:
            continue
        if request.bug_type and commit.get("bug_type") != request.bug_type:
            continue

        results.append(CommitInfo(**commit))

    # 分面统计
    subsystems = {}
    bug_types = {}
    for c in results:
        subsystems[c.subsystem] = subsystems.get(c.subsystem, 0) + 1
        if c.bug_type:
            bug_types[c.bug_type] = bug_types.get(c.bug_type, 0) + 1

    total = len(results)

    # 分页
    start = (request.page - 1) * request.page_size
    end = start + request.page_size
    page_results = results[start:end]

    return SearchResponse(
        query=request.query,
        total=total,
        page=request.page,
        page_size=request.page_size,
        results=page_results,
        facets={
            "subsystems": subsystems,
            "bug_types": bug_types,
        },
    )


@router.get("/{commit_id}", response_model=CommitDetailResponse)
async def get_commit_detail(commit_id: str) -> CommitDetailResponse:
    """获取单个 Commit 的详细信息"""
    commit = _COMMIT_MAP.get(commit_id)
    if not commit:
        raise HTTPException(status_code=404, detail=f"Commit {commit_id} 不存在")

    # 找相关 commit (通过 Fixes 标签)
    related = []
    for fix_tag in commit.get("fix_tags", []):
        for c in _MOCK_COMMITS:
            if c["commit_id"] in fix_tag or fix_tag in c["commit_id"]:
                related.append(CommitInfo(**c))

    return CommitDetailResponse(
        commit=CommitInfo(**commit),
        related_commits=related[:5],
    )


@router.get("/subsystems/list", response_model=list[str])
async def list_subsystems() -> list[str]:
    """列出所有内核子系统"""
    subsystems = sorted(set(c["subsystem"] for c in _MOCK_COMMITS))
    return subsystems


@router.get("/bug-types/list", response_model=list[str])
async def list_bug_types() -> list[str]:
    """列出所有 Bug 类型"""
    bug_types = sorted(set(
        c["bug_type"] for c in _MOCK_COMMITS if c.get("bug_type")
    ))
    return bug_types
