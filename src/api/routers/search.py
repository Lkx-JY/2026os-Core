"""搜索路由 — 补丁知识库的搜索和浏览."""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query

from ..schemas.requests import SearchRequest
from ..schemas.responses import SearchResponse, CommitDetailResponse
from ..schemas.entities import CommitInfo
from ..dependencies import get_config, check_index_ready
from ...common.logging import get_logger

logger = get_logger()
router = APIRouter(prefix="/search", tags=["Search"])

# ★ 复用 shared dependency 中的 index ready 检查
_is_index_ready = check_index_ready


def _search_real(query: str, top_k: int = 50,
                 subsystem: Optional[str] = None,
                 bug_type: Optional[str] = None) -> list[dict]:
    """使用真实向量检索"""
    from ...retriever.pipeline import quick_search
    from ...indexer.milvus import get_milvus_client

    # 构建过滤表达式
    filter_expr = None
    conditions = []
    if subsystem:
        conditions.append(f'subsystem=="{subsystem}"')
    if bug_type:
        conditions.append(f'bug_type=="{bug_type}"')
    if conditions:
        filter_expr = " && ".join(conditions)

    if filter_expr:
        client = get_milvus_client()
        from ...indexer.embedding import encode_text

        query_vec = encode_text([query])[0]
        result = client.search(query_vec, top_k=top_k, filter_expr=filter_expr)
        candidates = result.to_dict_list()
        return candidates

    result = quick_search(query, top_k=top_k, mode="fast")
    items = []
    for item in result.ranked_items:
        meta = item.metadata or {}
        items.append({
            "commit_id": item.commit_hash,
            "title": item.subject,
            "message": meta.get("body", ""),
            "author": meta.get("author", ""),
            "date": meta.get("date", ""),
            "subsystem": item.subsystem,
            "bug_type": item.bug_type,
            "files_changed": meta.get("files_changed", []),
            "fix_tags": meta.get("fix_tags", []),
            "relevance_score": item.final_score,
            "vector_score": item.vector_score,
            "reranker_score": item.reranker_score,
        })
    return items


def _get_facets_real(results: list[dict]) -> dict:
    """从真实检索结果聚合约面统计"""
    subsystems = {}
    bug_types = {}
    for r in results:
        sub = r.get("subsystem", "unknown")
        bt = r.get("bug_type", "unknown")
        subsystems[sub] = subsystems.get(sub, 0) + 1
        bug_types[bt] = bug_types.get(bt, 0) + 1
    return {"subsystems": subsystems, "bug_types": bug_types}


# ── Mock 数据 (向量库为空时的降级) ─────────────────────────────────

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

# Mock 数据索引
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

    ★ 自动检测: 向量库有数据时使用真实语义检索, 否则回退 Mock
    """
    using_real = _is_index_ready()
    if using_real:
        logger.info(f"使用真实向量检索: query='{request.query}'")
        # ★ 真实向量检索 (使用用户指定的 top_k，默认 200)
        effective_top_k = max(request.top_k, 100) if request.top_k else 200
        all_results = _search_real(
            query=request.query,
            top_k=effective_top_k,
            subsystem=request.subsystem,
            bug_type=request.bug_type,
        )
        facets = _get_facets_real(all_results)
    else:
        logger.info(f"使用 Mock 检索: query='{request.query}'")
        # Mock 降级
        query_lower = request.query.lower()
        all_results = []
        for commit in _MOCK_COMMITS:
            text_match = (
                query_lower in commit["title"].lower()
                or query_lower in commit["message"].lower()
                or any(query_lower in f.lower() for f in commit["files_changed"])
                or any(query_lower in t.lower() for t in commit.get("fix_tags", []))
            )
            if not text_match:
                continue
            if request.subsystem and commit["subsystem"] != request.subsystem:
                continue
            if request.bug_type and commit.get("bug_type") != request.bug_type:
                continue
            all_results.append(commit)

        subsystems = {}
        bug_types = {}
        for c in all_results:
            subsystems[c["subsystem"]] = subsystems.get(c["subsystem"], 0) + 1
            if c.get("bug_type"):
                bug_types[c["bug_type"]] = bug_types.get(c["bug_type"], 0) + 1
        facets = {"subsystems": subsystems, "bug_types": bug_types}

    total = len(all_results)

    # 分页
    start = (request.page - 1) * request.page_size
    end = start + request.page_size
    page_results = all_results[start:end]

    # 转换为 CommitInfo
    commit_infos = []
    for r in page_results:
        commit_infos.append(CommitInfo(
            commit_id=r.get("commit_id", ""),
            title=r.get("title", ""),
            message=r.get("message", ""),
            author=r.get("author", ""),
            date=r.get("date", ""),
            subsystem=r.get("subsystem", "unknown"),
            bug_type=r.get("bug_type", "unknown"),
            files_changed=r.get("files_changed", []),
            diff_preview=r.get("diff_preview", ""),
            fix_tags=r.get("fix_tags", []),
        ))

    return SearchResponse(
        query=request.query,
        total=total,
        page=request.page,
        page_size=request.page_size,
        results=commit_infos,
        analysis_mode="real" if using_real else "mock",
        facets=facets,
    )


@router.get("/{commit_id}", response_model=CommitDetailResponse)
async def get_commit_detail(commit_id: str) -> CommitDetailResponse:
    """获取单个 Commit 的详细信息"""
    # 优先从向量库查找 — 通过标量过滤精确匹配 commit_hash
    if _is_index_ready():
        from ...indexer.milvus import get_milvus_client
        client = get_milvus_client()
        try:
            # 使用标量过滤做精确 ID 匹配，而非向量近似搜索
            result = client.get_by_id(commit_id)
            if result:
                return CommitDetailResponse(
                    commit=CommitInfo(
                        commit_id=result.get("commit_hash", commit_id),
                        title=result.get("subject", ""),
                        message=result.get("body", ""),
                        author=result.get("author", ""),
                        date=result.get("date", ""),
                        subsystem=result.get("subsystem", "unknown"),
                        bug_type=result.get("bug_type", "unknown"),
                        files_changed=result.get("files_changed", []),
                    ),
                    related_commits=[],
                )
        except AttributeError:
            # get_by_id 不可用时回退到标量过滤搜索
            filter_expr = f'commit_hash == "{commit_id}"'
            results = client.search_with_filter(filter_expr=filter_expr, top_k=1)
            items = results.to_dict_list() if hasattr(results, 'to_dict_list') else results
            if items:
                item = items[0] if isinstance(items, list) else items
                return CommitDetailResponse(
                    commit=CommitInfo(
                        commit_id=item.get("commit_hash", commit_id),
                        title=item.get("subject", ""),
                        message=item.get("body", ""),
                        author=item.get("author", ""),
                        date=item.get("date", ""),
                        subsystem=item.get("subsystem", "unknown"),
                        bug_type=item.get("bug_type", "unknown"),
                        files_changed=item.get("files_changed", []),
                    ),
                    related_commits=[],
                )
        raise HTTPException(status_code=404, detail=f"Commit {commit_id} 不存在于向量库中")

    # Mock 降级
    commit = _COMMIT_MAP.get(commit_id)
    if not commit:
        raise HTTPException(status_code=404, detail=f"Commit {commit_id} 不存在")

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
    if _is_index_ready():
        from ...knowledge.subsystem_graph import get_all_subsystems
        subs = get_all_subsystems()
        if subs:
            return sorted(subs)
    subsystems = sorted(set(c["subsystem"] for c in _MOCK_COMMITS))
    return subsystems


@router.get("/bug-types/list", response_model=list[str])
async def list_bug_types() -> list[str]:
    """列出所有 Bug 类型"""
    if _is_index_ready():
        from ...knowledge.bug_patterns import get_all_bug_types
        types = get_all_bug_types()
        if types:
            return sorted(types)
    bug_types = sorted(set(
        c["bug_type"] for c in _MOCK_COMMITS if c.get("bug_type")
    ))
    return bug_types
