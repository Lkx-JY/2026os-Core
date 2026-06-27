"""分析路由 — 宕机日志分析的核心 API."""

import asyncio
import time
import uuid
import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends  # type: ignore

from ..schemas.requests import AnalyzeRequest
from ..schemas.responses import AnalyzeResponse, TaskStatusResponse, ErrorResponse
from ..schemas.entities import (
    RootCauseInfo,
    MatchedPatch,
    CommitInfo,
    AnalysisStep,
    ScoreBreakdown,
    RootCauseEvidence,
    VersionAnalysis,
    WhyNotExplanation,
)
from ..dependencies import get_config, check_index_ready, verify_api_key
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


# 内存回退存储 (当 Redis 不可用时) — 必须在 _save_task 之前定义
_memory_tasks: dict[str, dict] = {}
_memory_lock = threading.Lock()


def _serialize_value(value):
    """递归转换值为 JSON 可序列化格式 — 处理嵌套 Pydantic/datetime"""
    if hasattr(value, 'model_dump'):
        return _serialize_value(value.model_dump())
    elif hasattr(value, 'dict'):
        return _serialize_value(value.dict())
    elif isinstance(value, list):
        return [_serialize_value(item) for item in value]
    elif isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    elif isinstance(value, datetime):
        return value.isoformat()
    else:
        return value


def _save_task(task_id: str, data: dict) -> None:
    """保存任务到 Redis，回退到内存"""
    store = _get_store()
    # 获取现有数据并合并
    existing = store.get_task(task_id) or _memory_tasks.get(task_id, {})
    
    # 递归转换 Pydantic 模型和 datetime 为 JSON 可序列化格式
    serializable_data = _serialize_value(data)
    
    existing.update(serializable_data)
    
    logger.info(f"Saving task {task_id} to Redis: {list(data.keys())}")
    success = store.save_task(task_id, existing)
    logger.info(f"Save to Redis: {success}")

    if not success:
        # Redis 不可用时的内存回退
        logger.warning(f"Redis save failed, using memory fallback for {task_id}")
        with _memory_lock:
            # 限制内存存储上限，防止内存泄漏
            if len(_memory_tasks) >= 10000:
                # 清理最早创建的条目（基于 created_at）
                try:
                    oldest = min(
                        _memory_tasks.keys(),
                        key=lambda k: _memory_tasks[k].get("created_at", datetime.now(timezone.utc)),
                    )
                    del _memory_tasks[oldest]
                except (ValueError, KeyError):
                    pass
            _memory_tasks[task_id] = existing


def _get_task(task_id: str) -> Optional[dict]:
    """从 Redis 获取任务，回退到内存"""
    store = _get_store()
    task = store.get_task(task_id)
    if task is None:
        with _memory_lock:
            task = _memory_tasks.get(task_id)
    return task


# ── 模式开关: 优先使用真实 RAG Pipeline, 向量库为空时回退 Mock ──
_USE_REAL_PIPELINE = None  # None = 自动检测, True = 强制真实, False = 强制 Mock
_LAST_READY_CHECK_TIME = 0.0  # 上次检查时间戳


# ★ 复用 shared dependency 中的 index ready 检查
_check_index_ready = check_index_ready


def _should_use_real_pipeline() -> bool:
    """决定使用真实流水线还是 mock

    ★ 关键设计:
    - True 永久缓存 (向量库不会在运行时消失)
    - False 每 30 秒重试一次 (启动时 FAISS 索引可能还在加载中)
    """
    global _USE_REAL_PIPELINE, _LAST_READY_CHECK_TIME
    now = time.time()

    # True 永久有效
    if _USE_REAL_PIPELINE:
        return True

    # False 时每 30 秒重试一次
    if _USE_REAL_PIPELINE is not None and _LAST_READY_CHECK_TIME > 0:
        if now - _LAST_READY_CHECK_TIME < 30:
            return False

    _LAST_READY_CHECK_TIME = now
    ready = _check_index_ready()
    if ready:
        _USE_REAL_PIPELINE = True
        logger.info("✓ 向量库就绪，切换到真实 RAG Pipeline")
    else:
        _USE_REAL_PIPELINE = False
        logger.warning("向量库为空, 回退到 Mock 模式。请先运行: python scripts/index_all_commits.py")
    return ready


async def _simulate_analysis(task_id: str, request: AnalyzeRequest) -> None:
    """Mock 分析流水线 (向量库未初始化时的降级方案)"""
    steps: list[AnalysisStep] = []

    try:
        # Step 1: 日志解析
        steps.append(AnalysisStep(
            name="日志解析", status="running",
            started_at=datetime.now(timezone.utc),
        ))
        _save_task(task_id, {
            "task_id": task_id,
            "status": "running",
            "progress": 0.1,
            "created_at": datetime.now(timezone.utc),
            "steps": steps,
            "request": request,
        })
        await asyncio.sleep(0.3)

        steps[-1].status = "completed"
        steps[-1].completed_at = datetime.now(timezone.utc)
        steps[-1].detail = f"成功解析 {request.log_type} 日志，提取 {len(request.log_content.splitlines())} 行"

        # Step 2: Root Cause 抽象
        steps.append(AnalysisStep(
            name="根因分析", status="running",
            started_at=datetime.now(timezone.utc),
        ))
        _save_task(task_id, {"progress": 0.3, "steps": steps})
        await asyncio.sleep(0.5)

        # 基于日志关键词推断根因
        log_lower = request.log_content.lower()
        if "list_del corruption" in log_lower or "list_add corruption" in log_lower:
            root_cause = RootCauseInfo(
                root_cause="race_condition",
                subsystem="list",
                confidence=0.92,
                summary="链表并发操作导致的竞态条件问题，可能涉及 list_del/list_add 时的锁保护缺失",
                key_symptoms=["list_del corruption", "list corruption"],
                evidence=RootCauseEvidence(
                    panic_keyword="List Corruption", fault_address="ffff8800a1b2c3d4",
                    subsystem="list", confidence=0.92,
                    matched_rule_id="R007", matched_rule_name="Memory Corruption (List)",
                    trace_functions=["__list_del_entry_valid+0x89/0xa0", "__slab_free+0xab/0x2c0"],
                    causal_chain=["Expert Rule: R007", "Affected Subsystem: list"],
                ),
            )
        elif "soft lockup" in log_lower:
            root_cause = RootCauseInfo(
                root_cause="soft_lockup",
                subsystem="scheduler",
                confidence=0.88,
                summary="CPU 软锁定，某个 CPU 在内核态执行时间过长未调度",
                key_symptoms=["soft lockup", "CPU stuck"],
                evidence=RootCauseEvidence(
                    panic_keyword="Soft Lockup", subsystem="scheduler", confidence=0.88,
                    matched_rule_id="R011", matched_rule_name="Soft Lockup",
                    trace_functions=["watchdog_timer_fn+0x1a5/0x1d0", "__hrtimer_run_queues+0x10a/0x180"],
                    causal_chain=["Expert Rule: R011", "Affected Subsystem: scheduler"],
                ),
            )
        elif "use-after-free" in log_lower or "uaf" in log_lower:
            root_cause = RootCauseInfo(
                root_cause="use_after_free",
                subsystem="mm",
                confidence=0.85,
                summary="释放后使用 (UAF) 漏洞，对象被释放后仍被引用",
                key_symptoms=["use-after-free", "freed memory accessed"],
                evidence=RootCauseEvidence(
                    panic_keyword="Use-After-Free (KASAN)", fault_address="ffff880123456789",
                    subsystem="mm", confidence=0.85,
                    matched_rule_id="R003", matched_rule_name="Use After Free (KASAN)",
                    trace_functions=["kmem_cache_alloc+0x5f/0x170", "kasan_report+0x8e/0xb0"],
                    causal_chain=["Expert Rule: R003", "Knowledge Base: UAF pattern matched"],
                ),
            )
        elif "null pointer" in log_lower or "NULL pointer" in log_lower:
            root_cause = RootCauseInfo(
                root_cause="null_pointer_dereference",
                subsystem="kernel",
                confidence=0.90,
                summary="空指针解引用，未做有效性检查即访问指针成员",
                key_symptoms=["NULL pointer dereference", "unable to handle kernel NULL pointer"],
                evidence=RootCauseEvidence(
                    panic_keyword="NULL pointer dereference", fault_address="0000000000000028",
                    subsystem="kernel", confidence=0.90,
                    matched_rule_id="R002", matched_rule_name="Null Pointer Dereference",
                    trace_functions=["my_function+0x123/0x456", "my_other_function+0xab/0xcd"],
                    causal_chain=["Expert Rule: R002 (Null Pointer)", "Severity: HIGH"],
                ),
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
        steps[-1].completed_at = datetime.now(timezone.utc)
        steps[-1].detail = f"根因类型: {root_cause.root_cause}, 置信度: {root_cause.confidence:.2f}"

        # Step 3: 向量检索
        steps.append(AnalysisStep(
            name="向量检索", status="running",
            started_at=datetime.now(timezone.utc),
        ))
        _save_task(task_id, {"progress": 0.5, "steps": steps})
        await asyncio.sleep(0.4)

        matched_patches = _get_mock_patches(request.top_k, root_cause)

        steps[-1].status = "completed"
        steps[-1].completed_at = datetime.now(timezone.utc)
        steps[-1].detail = f"Milvus 召回 Top-100, Reranker 重排后返回 Top-{request.top_k}"

        # Step 4: LLM 解释生成
        if request.enable_llm_explanation:
            steps.append(AnalysisStep(
                name="LLM 解释生成", status="running",
                started_at=datetime.now(timezone.utc),
            ))
            _save_task(task_id, {"progress": 0.8, "steps": steps})
            await asyncio.sleep(0.6)

            llm_explanation = _generate_mock_explanation(root_cause, matched_patches)
            steps[-1].status = "completed"
            steps[-1].completed_at = datetime.now(timezone.utc)
            steps[-1].detail = "LLM 分析完成"
        else:
            llm_explanation = None

        _save_task(task_id, {
            "status": "completed",
            "progress": 1.0,
            "analysis_mode": "mock",
            "root_cause": root_cause,
            "matched_patches": matched_patches,
            "steps": steps,
            "llm_explanation": llm_explanation,
            "completed_at": datetime.now(timezone.utc),
        })

    except Exception as e:
        logger.error(f"Analysis task {task_id} failed: {e}", exc_info=True)
        _save_task(task_id, {"status": "failed", "error": str(e)})
        if steps and steps[-1].status == "running":
            steps[-1].status = "failed"
            steps[-1].detail = str(e)


def _run_real_analysis(task_id: str, request: AnalyzeRequest) -> None:
    """★ 真实分析流水线 — 对接完整的 RAG Pipeline

    全链路:
    Step 1 → Feature Extraction (dmesg regex + 规则引擎)
    Step 2 → Root Cause Abstraction (28 条专家规则 + 4 层分层推断)
    Step 3 → Embedding Encoding (BGE-M3 → 1024d vector)
    Step 4 → Vector Retrieval (Milvus/FAISS Top-K recall)
    Step 5 → Multi-stage Ranking (Filter → BGE Rerank)
    """
    steps: list[AnalysisStep] = []

    # ★ 设置请求级 LLM 配置 — 后续所有 get_llm_client() 调用自动使用此配置
    from ...generator.llm import set_request_llm_config
    set_request_llm_config(
        api_key=request.user_api_key,
        base_url=request.user_api_base,
        model=request.user_api_model,
    )

    try:
        # ── Step 1: 日志解析 ──────────────────────────────────────
        steps.append(AnalysisStep(
            name="日志解析", status="running",
            started_at=datetime.now(timezone.utc),
        ))
        _save_task(task_id, {
            "task_id": task_id,
            "status": "running",
            "progress": 0.05,
            "created_at": datetime.now(timezone.utc),
            "steps": steps,
            "request": request,
        })

        from ...analyzer.dmesg import parse_dmesg
        feature = parse_dmesg(request.log_content)
        steps[-1].status = "completed"
        steps[-1].completed_at = datetime.now(timezone.utc)
        steps[-1].detail = (
            f"成功解析 {request.log_type} 日志, "
            f"子系统={feature.subsystem}, "
            f"初步 Bug 类型={feature.bug_type}"
        )

        # ── Step 2: Root Cause 抽象 ──────────────────────────────
        steps.append(AnalysisStep(
            name="根因分析", status="running",
            started_at=datetime.now(timezone.utc),
        ))
        _save_task(task_id, {"progress": 0.15, "steps": steps})

        from ...analyzer.rootcause import get_analyzer, extract_root_cause_evidence
        analyzer = get_analyzer()
        root_cause_result = analyzer.analyze(feature)

        # ★ 提取根因证据 (可解释性增强)
        evidence_dict = extract_root_cause_evidence(feature, root_cause_result)
        root_cause_evidence = RootCauseEvidence(**evidence_dict) if evidence_dict else None

        root_cause_info = RootCauseInfo(
            root_cause=root_cause_result.root_cause,
            subsystem=getattr(feature, "subsystem", "unknown"),
            confidence=round(root_cause_result.score, 2),
            summary=root_cause_result.reason,
            key_symptoms=root_cause_result.causal_chain or [],
            evidence=root_cause_evidence,  # ★ 挂载证据
        )

        steps[-1].status = "completed"
        steps[-1].completed_at = datetime.now(timezone.utc)
        steps[-1].detail = (
            f"根因: {root_cause_result.root_cause}, "
            f"置信度: {root_cause_result.score:.2f}, "
            f"规则数: 28"
        )
        _save_task(task_id, {
            "progress": 0.30,
            "steps": steps,
            "root_cause": root_cause_info,
        })

        # ── Step 3: 向量检索 + 重排 ──────────────────────────────
        steps.append(AnalysisStep(
            name="向量检索与重排", status="running",
            started_at=datetime.now(timezone.utc),
        ))
        _save_task(task_id, {"progress": 0.40, "steps": steps})

        from ...services import run_online_diagnosis

        diagnosis = run_online_diagnosis(
            dmesg_content=request.log_content,
            use_llm=request.enable_llm_explanation,
            retrieval_mode="standard",
            top_k=100,
        )

        matched_patches = []
        if diagnosis.retrieval_result:
            # ★ 导入可解释性增强模块
            from ...retriever.rerank import (
                compute_score_breakdown,
                generate_why_not_explanations,
            )
            from ...retriever.filter import compute_version_analysis

            # ★ 先构造 matched_patches (不含增强字段)
            temp_patches = []
            for item in diagnosis.retrieval_result.top(request.top_k):
                meta = item.metadata or {}
                diff_preview = _build_diff_preview(meta)

                temp_patches.append({
                    "item": item,
                    "patch": MatchedPatch(
                        rank=item.rank,
                        commit=CommitInfo(
                            commit_id=item.commit_hash,
                            title=item.subject,
                            message=item.metadata.get("body", "")[:500] if item.metadata else "",
                            author=item.metadata.get("author", "") if item.metadata else "",
                            date=item.metadata.get("date", "") if item.metadata else "",
                            subsystem=item.subsystem,
                            bug_type=item.bug_type,
                            files_changed=item.metadata.get("files_changed", []) if item.metadata else [],
                            diff_preview=diff_preview,
                        ),
                        relevance_score=round(item.final_score, 3),
                        recall_score=round(item.vector_score, 3),
                        rerank_score=round(item.reranker_score, 3),
                        match_reason=item.rank_reason,
                    ),
                })

            # ★ 为每个补丁计算 ScoreBreakdown
            crash_kv = getattr(feature, "kernel_version", "") or ""
            crash_subsystem = getattr(feature, "subsystem", "unknown")
            crash_call_trace = getattr(feature, "call_trace", []) or []
            crash_bug_type = root_cause_result.bug_type
            rule_id = root_cause_result.extra_info.get("rule_id", "")

            for tp in temp_patches:
                item = tp["item"]
                meta = item.metadata or {}

                # ScoreBreakdown
                breakdown_dict = compute_score_breakdown(
                    item,
                    crash_subsystem=crash_subsystem,
                    crash_call_trace=crash_call_trace,
                    crash_kernel_version=crash_kv,
                    crash_bug_type=crash_bug_type,
                    rule_id=rule_id,
                )
                tp["patch"].score_breakdown = ScoreBreakdown(**breakdown_dict)

                # VersionAnalysis
                version_dict = compute_version_analysis(
                    crash_kernel_version=crash_kv,
                    patch_commit_info=meta,
                    patch_date=meta.get("date", ""),
                )
                if version_dict.get("crash_kernel_version") or version_dict.get("patch_kernel_version"):
                    tp["patch"].version_analysis = VersionAnalysis(**version_dict)

            # ★ 生成 "为什么不是其他补丁" 解释
            ranked_items_for_explain = [tp["item"] for tp in temp_patches]
            why_not_list = generate_why_not_explanations(ranked_items_for_explain)

            for i, tp in enumerate(temp_patches):
                if i > 0 and i < len(why_not_list) and why_not_list[i]:
                    tp["patch"].why_not_explanation = WhyNotExplanation(**why_not_list[i])

            matched_patches = [tp["patch"] for tp in temp_patches]

        steps[-1].status = "completed"
        steps[-1].completed_at = datetime.now(timezone.utc)
        if diagnosis.retrieval_result:
            steps[-1].detail = (
                f"召回 {diagnosis.retrieval_result.recall_count} 条, "
                f"过滤后 {diagnosis.retrieval_result.after_filter_count} 条, "
                f"最终 Top-{len(matched_patches)}, "
                f"耗时 {diagnosis.total_time_ms:.0f}ms"
            )
        else:
            steps[-1].detail = (
                f"检索未返回结果, "
                f"最终 Top-{len(matched_patches)}, "
                f"耗时 {diagnosis.total_time_ms:.0f}ms"
            )
        _save_task(task_id, {
            "progress": 0.80,
            "steps": steps,
            "matched_patches": matched_patches,
        })

        # ── Step 4: LLM 解释生成 ──────────────────────────────────
        if request.enable_llm_explanation:
            steps.append(AnalysisStep(
                name="LLM 解释生成", status="running",
                started_at=datetime.now(timezone.utc),
            ))
            _save_task(task_id, {"progress": 0.90, "steps": steps})

            try:
                from ...generator.llm import get_llm_client
                from ...generator.prompt import build_evidence_aware_report_prompt
                from ...generator.patch_explain import (
                    extract_patch_explanations,
                    build_evidence_summary,
                    build_evidence_summary_table,
                    build_score_breakdown,
                )

                # Step 4a: Patch Explain — 提取结构化证据 (Part 5)
                explanations = extract_patch_explanations(
                    ranked_items=diagnosis.retrieval_result.ranked_items[:5]
                    if diagnosis.retrieval_result else [],
                    crash_feature=feature,
                    root_cause_result=root_cause_result,
                )

                # Step 4b: 构建证据摘要 + 证据表格 + 分数拆解
                evidence_summary = build_evidence_summary(explanations, feature)
                evidence_table = build_evidence_summary_table(
                    crash_feature=feature,
                    root_cause_result=root_cause_result,
                    top_patch=explanations[0] if explanations else None,
                    kernel_version=getattr(feature, "kernel_version", ""),
                )
                score_info = build_score_breakdown(explanations, feature, root_cause_result)

                # Step 4c: 构造证据驱动 Prompt
                prompt = build_evidence_aware_report_prompt(
                    crash_feature=feature,
                    root_cause_result=root_cause_result,
                    patch_explanations=explanations,
                    kernel_version=getattr(feature, "kernel_version", ""),
                    evidence_summary=evidence_summary,
                    evidence_summary_table=evidence_table,
                    score_breakdown=score_info,
                )

                # Step 4d: LLM 生成报告
                llm = get_llm_client()
                llm_explanation = llm.chat(prompt)
            except Exception as llm_err:
                logger.warning(f"LLM 调用失败, 使用规则引擎生成解释: {llm_err}")
                llm_explanation = _generate_real_explanation(root_cause_info, matched_patches)

            steps[-1].status = "completed"
            steps[-1].completed_at = datetime.now(timezone.utc)
            steps[-1].detail = "LLM 分析完成"
        else:
            llm_explanation = None

        _save_task(task_id, {
            "status": "completed",
            "progress": 1.0,
            "analysis_mode": "real",
            "root_cause": root_cause_info,
            "matched_patches": matched_patches,
            "steps": steps,
            "llm_explanation": llm_explanation,
            "completed_at": datetime.now(timezone.utc),
        })

    except Exception as e:
        logger.error(f"Real analysis task {task_id} failed: {e}", exc_info=True)
        _save_task(task_id, {"status": "failed", "error": str(e)})
        if steps and steps[-1].status == "running":
            steps[-1].status = "failed"
            steps[-1].detail = str(e)


def _build_diff_preview(meta: dict) -> str:
    """从元数据构建 diff 预览。

    由于 raw diff 未存入 metadata (过大), 从已有字段合成可读摘要:
    - 修改文件列表 + 增删行数
    - 涉及的函数
    - 修复标签
    - commit body 前 300 字
    """
    parts = []

    # 1. 文件变更摘要
    file_changes = meta.get("file_changes", [])
    if file_changes:
        for fc in file_changes[:3]:
            fname = fc.get("filename", "?")
            added = fc.get("added_lines", 0)
            deleted = fc.get("deleted_lines", 0)
            parts.append(f"  {fname} (+{added}/-{deleted})")
        if len(file_changes) > 3:
            parts.append(f"  ... and {len(file_changes)-3} more files")
    elif meta.get("files_changed"):
        for f in (meta["files_changed"] or [])[:3]:
            parts.append(f"  {f}")
    if parts:
        parts.insert(0, "Modified files:")

    # 2. 修改函数
    functions = meta.get("functions", [])
    if functions:
        func_str = ", ".join(functions[:8])
        if len(functions) > 8:
            func_str += f" ... (+{len(functions)-8} more)"
        parts.append(f"Functions: {func_str}")

    # 3. 修复标签
    fix_tags = meta.get("fix_tags", [])
    if fix_tags:
        parts.append(f"Tags: {', '.join(fix_tags[:5])}")

    # 4. 修复特征
    features = []
    if meta.get("lock_added"):
        features.append("lock_added")
    if meta.get("refcount_fix"):
        features.append("refcount_fix")
    if meta.get("rcu_fix"):
        features.append("rcu_fix")
    if features:
        parts.append(f"Fix features: {', '.join(features)}")

    # 5. 内核版本 + 插入/删除
    kv = meta.get("kernel_version", "")
    ins = meta.get("insertions", 0)
    dele = meta.get("deletions", 0)
    if kv or ins or dele:
        info_parts = []
        if kv:
            info_parts.append(f"v{kv}")
        if ins or dele:
            info_parts.append(f"+{ins}/-{dele}")
        parts.append(" | ".join(info_parts))

    # 6. commit body 摘要 (关键信息)
    body = (meta.get("body", "") or "")[:300]
    if body:
        parts.append(f"\nCommit message:\n{body}")

    return "\n".join(parts) if parts else "(diff not available - raw diff not stored in index)"


def _generate_real_explanation(root_cause: RootCauseInfo, patches: list[MatchedPatch]) -> str:
    """基于规则引擎生成分析解释 (LLM 不可用时的降级)"""
    if not patches:
        return "未能找到匹配的补丁，建议进一步使用 drgn 分析 vmcore。"

    top = patches[0]
    patch_list = "\n".join(
        f"{p.rank}. **{p.commit.title}** (相关性: {p.relevance_score:.3f})"
        for p in patches[:5]
    )
    return f"""## 根因分析

根据宕机日志分析，系统发生了 **{root_cause.root_cause}** 类型的故障，
影响子系统为 `{root_cause.subsystem}`，置信度 {root_cause.confidence:.0%}。

关键症状：{"、".join(root_cause.key_symptoms) if root_cause.key_symptoms else "待确认"}

## 推荐补丁 (Top-{len(patches)})

{patch_list}

## 修复建议

1. 优先应用排名第一的补丁 `{top.commit.commit_id[:12]}`，该补丁直接修复了根因问题
2. 检查子系统 `{root_cause.subsystem}` 中是否存在类似的未修复路径
3. 建议运行回归测试确认修复效果
"""


def _get_mock_patches(top_k: int, root_cause: RootCauseInfo) -> list[MatchedPatch]:
    """生成模拟匹配补丁 (包含可解释性增强字段)"""
    mock_commits = {
        "race_condition": [
            ("a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f67890", "list: fix race condition in list_del",
             "修复 list_del 操作的竞态条件，添加适当的 spin_lock 保护", "spin_lock_irqsave",
             "kernel", "race_condition", ["kernel/locking.c", "include/linux/list.h"]),
            ("b2c3d4e5f6a7b2c3d4e5f6a7b2c3d4e5f6789012", "locking: add missing lock in list manipulation",
             "在链表操作路径添加缺失的 mutex_lock", "mutex_lock",
             "kernel", "race_condition", ["kernel/locking.c"]),
            ("c3d4e5f6a7b8c3d4e5f6a7b8c3d4e5f67890123", "rcu: fix RCU stall in list traversal",
             "修复遍历链表时的 RCU 停滞问题", "rcu_read_lock",
             "rcu", "hang", ["kernel/rcu/tree.c"]),
        ],
        "soft_lockup": [
            ("d4e5f6a7b8c9d4e5f6a7b8c9d4e5f678901234", "sched: fix soft lockup in scheduler",
             "修复调度器中的软锁定问题，增加调度点", "schedule",
             "kernel", "hang", ["kernel/sched/core.c"]),
            ("e5f6a7b8c9d0e5f6a7b8c9d0e5f6789012345", "rcu: resolve RCU soft lockup",
             "解决长时间 RCU 读锁导致的软锁定", "rcu_read_unlock",
             "rcu", "hang", ["kernel/rcu/update.c"]),
        ],
        "use_after_free": [
            ("f6a7b8c9d0e1f6a7b8c9d0e1f6a78901234567", "mm: fix use-after-free in kfree_rcu",
             "修复 kfree_rcu 中的 UAF 漏洞", "kfree_rcu",
             "mm", "use_after_free", ["mm/slab_common.c", "kernel/rcu/tree.c"]),
            ("a7b8c9d0e1f2a7b8c9d0e1f2a789012345678", "slab: fix use-after-free in kmem_cache_free",
             "修复 slab 分配器中的释放后使用", "kmem_cache_free",
             "mm", "use_after_free", ["mm/slub.c"]),
        ],
        "null_pointer_dereference": [
            ("b8c9d0e1f2a3b8c9d0e1f2a3b890123456789", "net: add NULL check in netdev_rx_handler",
             "在网络设备接收处理函数中添加空指针检查，防止因未初始化的 net_device 导致的崩溃", "NULL",
             "net", "null_pointer", ["net/core/dev.c", "drivers/net/ethernet/intel/e1000.c"]),
            ("c9d0e1f2a3b4c9d0e1f2a3b4c901234567890", "fs: fix NULL pointer dereference in vfs_read",
             "修复 vfs_read 路径中 file->f_op 未检查导致的空指针解引用", "NULL pointer",
             "fs", "null_pointer", ["fs/read_write.c"]),
        ],
        "memory_corruption": [
            ("d0e1f2a3b4c5d0e1f2a3b4c5d01234567890a", "mm/slub: fix slab corruption in double free",
             "修复 SLUB 分配器因并发双重释放导致的 slab 腐败问题", "slab",
             "mm", "memory_corruption", ["mm/slub.c"]),
            ("e1f2a3b4c5d6e1f2a3b4c5d6e1234567890ab", "mm: fix page corruption in swap",
             "修复 swap 换出路径的页面腐败", "swap",
             "mm", "memory_corruption", ["mm/swapfile.c"]),
        ],
        "unknown": [
            ("f2a3b4c5d6e7f2a3b4c5d6e7f234567890abc", "kernel: fix general protection fault",
             "修复通用保护错误", "general protection",
             "kernel", "crash", ["kernel/irq/handle.c"]),
            ("a3b4c5d6e7f8a3b4c5d6e7f8a34567890abcd", "x86: fix kernel crash in interrupt handler",
             "修复中断处理程序中的内核崩溃", "interrupt",
             "arch", "crash", ["arch/x86/kernel/irq.c"]),
        ],
    }

    patches = mock_commits.get(root_cause.root_cause, mock_commits["unknown"])
    results = []
    for i, (commit_id, title, message, highlight, subsystem, bug_type, files) in enumerate(patches[:top_k]):
        # ScoreBreakdown — 模拟多维分数
        sb = ScoreBreakdown(
            embedding_score=round(0.88 - i * 0.06, 4),
            reranker_score=round(0.92 - i * 0.06, 4),
            expert_rule_score=round(0.95 - i * 0.10, 4),
            callstack_match_score=round(0.90 - i * 0.20, 4),
            subsystem_match_score=round(1.0 - i * 0.15, 4),
            version_match_score=round(0.85 - i * 0.05, 4),
            llm_judge_score=round(0.88 - i * 0.08, 4),
            final_score=round(0.95 - i * 0.08, 4),
        )

        # VersionAnalysis — 模拟版本对比
        va = VersionAnalysis(
            crash_kernel_version="6.6.0",
            patch_kernel_version="6.4.0" if i < 1 else "6.1.0",
            version_distance="2 Minor Release" if i < 1 else "5 Minor Release",
            distance_value=2 if i < 1 else 5,
            compatibility="High" if i < 1 else "Medium",
            compatibility_reason="补丁版本略新于崩溃内核，大概率可直接 backport"
            if i < 1 else "版本差距较大，需确认补丁依赖的 API 在目标内核中仍存在",
            patch_release_date="2024-03-15",
            crash_release_date="2024-05-20",
        )

        # WhyNotExplanation — 为非 Top-1 生成对比解释
        wn = None
        if i > 0:
            wn = WhyNotExplanation(
                compared_to_rank=1,
                same_aspects=[f"同属于 {bug_type} 修复", f"同一子系统 {subsystem}"],
                different_aspects=[
                    f"补丁修改文件集中在 {files[0].split('/')[0]} 子目录，与崩溃调用栈关联度较低",
                    f"补丁对应的内核版本较旧，存在兼容性差异",
                    f"Reranker 语义重排分数低于 Top-1 ({sb.reranker_score} vs {0.92})",
                ],
                ranking_reason=f"综合 {3} 个差异因素，排名第 {i + 1}",
            )

        results.append(MatchedPatch(
            rank=i + 1,
            commit=CommitInfo(
                commit_id=commit_id,
                title=title,
                message=message,
                author="Linus Torvalds",
                date="2025-08-15",
                subsystem=subsystem,
                bug_type=bug_type,
                files_changed=files,
                diff_preview=f"+ {highlight}(&lock);\n- old_func(&data);\n+ new_safe_func(&data);",
            ),
            relevance_score=round(0.95 - i * 0.08, 2),
            recall_score=round(0.85 - i * 0.05, 2),
            rerank_score=round(0.92 - i * 0.06, 2),
            match_reason=f"该补丁通过 {highlight} 操作修复了与当前崩溃日志匹配的 {root_cause.root_cause} 问题",
            diff_highlights=[f"+ {highlight}()"],
            score_breakdown=sb,
            version_analysis=va,
            why_not_explanation=wn,
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
    api_key: str = Depends(verify_api_key),
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
    created_at = datetime.now(timezone.utc)

    _save_task(task_id, {
        "task_id": task_id,
        "status": "running",
        "progress": 0.0,
        "created_at": created_at,
        "request": request,
    })

    # ★ 自动选择: 向量库有数据 → 真实 Pipeline, 否则 → Mock 降级
    if _should_use_real_pipeline():
        logger.info(f"使用真实 RAG Pipeline 处理任务 {task_id}")
        background_tasks.add_task(_run_real_analysis, task_id, request)
    else:
        logger.info(f"使用 Mock Pipeline 处理任务 {task_id} (向量库为空)")
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
            analysis_mode=task.get("analysis_mode", "real"),
            root_cause=task.get("root_cause"),
            matched_patches=task.get("matched_patches", []),
            analysis_steps=task.get("steps", []),
            llm_explanation=task.get("llm_explanation"),
            created_at=created_at or datetime.now(timezone.utc),
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
    """列出历史分析任务

    注意: 当前实现为简化版本，大量任务时建议使用 Redis 的有序集合分页。
    """
    MAX_LOAD = 500  # 最多加载 500 条任务，防止内存溢出
    store = _get_store()
    all_task_ids = store.list_tasks()

    # 内存回退时也有 list_tasks 操作，统一兼容
    if not all_task_ids:
        all_task_ids = list(_memory_tasks.keys())

    tasks = []
    # 从最新开始迭代，达到 MAX_LOAD 时停止
    for task_id in reversed(all_task_ids):
        if len(tasks) >= MAX_LOAD:
            break
        task = store.get_task(task_id) or _memory_tasks.get(task_id)
        if task:
            created_at = task.get("created_at")
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    created_at = datetime.now(timezone.utc)
            elif not isinstance(created_at, datetime):
                created_at = datetime.now(timezone.utc)
            tasks.append((task, created_at))

    # 按创建时间排序（已经在迭代中大致有序，再做精确排序）
    tasks.sort(key=lambda x: x[1], reverse=True)

    start = (page - 1) * page_size
    end = start + page_size

    return [
        {
            "task_id": t["task_id"],
            "status": t["status"],
            "created_at": t.get("created_at"),
            "log_type": t.get("request", {}).get("log_type", "unknown"),
            "log_preview": (t.get("request", {}).get("log_content", "") or "")[:100],
            "progress": t.get("progress", 0),
        }
        for t, _ in tasks[start:end]
    ]
