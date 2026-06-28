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
                 bug_type: Optional[str] = None,
                 retrieval_mode: str = "fast") -> list[dict]:
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

    result = quick_search(query, top_k=top_k, mode=retrieval_mode)
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

    ★ 数据源自动检测: data_full → data → 空结果
    """
    if not _is_index_ready():
        logger.warning(f"向量库无数据, 搜索返回空结果: query='{request.query}'")
        return SearchResponse(
            query=request.query,
            total=0,
            page=request.page,
            page_size=request.page_size,
            results=[],
            analysis_mode="none",
            facets={"subsystems": {}, "bug_types": {}},
        )

    logger.info(f"使用真实向量检索: query='{request.query}'")
    # ★ 真实向量检索 (基于 page_size 计算召回量，最小 100)
    effective_top_k = max(request.page_size * 5, 100)
    all_results = _search_real(
        query=request.query,
        top_k=effective_top_k,
        subsystem=request.subsystem,
        bug_type=request.bug_type,
        retrieval_mode=request.retrieval_mode,
    )
    facets = _get_facets_real(all_results)

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

    # ★ 获取当前数据源名称
    from ..dependencies import resolve_data_source
    ds = resolve_data_source()
    dataset_name = ds[1] if ds else "none"

    return SearchResponse(
        query=request.query,
        total=total,
        page=request.page,
        page_size=request.page_size,
        results=commit_infos,
        analysis_mode=dataset_name,
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

    # 向量库无数据时返回 404
    raise HTTPException(status_code=404, detail=f"Commit {commit_id} 不存在 (向量库无数据)")


@router.get("/subsystems/list", response_model=list[str])
async def list_subsystems() -> list[str]:
    """列出所有内核子系统"""
    if _is_index_ready():
        from ...knowledge.subsystem_graph import get_all_subsystems
        subs = get_all_subsystems()
        if subs:
            return sorted(subs)
    return []


@router.get("/bug-types/list", response_model=list[str])
async def list_bug_types() -> list[str]:
    """列出所有 Bug 类型"""
    if _is_index_ready():
        from ...knowledge.bug_patterns import get_all_bug_types
        types = get_all_bug_types()
        if types:
            return sorted(types)
    return []
