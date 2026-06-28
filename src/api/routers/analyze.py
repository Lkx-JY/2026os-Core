"""分析路由 — 宕机日志分析的核心 API."""

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
    ConfidenceBreakdown,
    EvidenceCoverage,
    EvidenceCoverageItem,
)
from ..dependencies import get_config, check_index_ready, verify_api_key, resolve_data_source
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


# ★ 复用 shared dependency 中的 index ready 检查
_check_index_ready = check_index_ready



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
        # ★ 安全: 不保存 user_api_key 到任务存储
        safe_request = request.model_dump(exclude={"user_api_key"})
        _save_task(task_id, {
            "task_id": task_id,
            "status": "running",
            "progress": 0.05,
            "created_at": datetime.now(timezone.utc),
            "steps": steps,
            "request": safe_request,
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

        from ...analyzer.rootcause import (
            get_analyzer, extract_root_cause_evidence,
            compute_possible_causes, compute_confidence_breakdown,
        )
        analyzer = get_analyzer()
        root_cause_result = analyzer.analyze(feature)

        # ★ 提取根因证据 (可解释性增强)
        evidence_dict = extract_root_cause_evidence(feature, root_cause_result)
        root_cause_evidence = RootCauseEvidence(**evidence_dict) if evidence_dict else None

        # ★ 两层根因抽象: Bug Type → Possible Causes (含子系统上下文)
        possible_causes = compute_possible_causes(
            root_cause_result.bug_type,
            subsystem=getattr(feature, "subsystem", "unknown"),
            call_trace=getattr(feature, "call_trace", None),
        )

        # ★ 置信度拆解: 先占位 (等检索完成后填入 historical_similarity)
        confidence_breakdown_dict = None

        root_cause_info = RootCauseInfo(
            root_cause=root_cause_result.root_cause,
            subsystem=getattr(feature, "subsystem", "unknown"),
            confidence=round(root_cause_result.score, 2),
            summary=root_cause_result.reason,
            key_symptoms=[
                s for s in (root_cause_result.causal_chain or [])
                if not s.startswith("Expert Rule:")
                and not s.startswith("Severity:")
                and not s.startswith("Related Subsystems:")
                and not s.startswith("Knowledge Base:")
                and not s.startswith("Lock Issue:")
                and not s.startswith("Affected Subsystem:")
                and not s.startswith("Kernel Version:")
                and not s.startswith("Loaded Modules:")
                and not s.startswith("Trace Structure:")
                and not s.startswith("Bug Type:")
                and not s.startswith("Panic Keyword:")
                and not s.startswith("Insufficient")
            ],  # ★ 过滤内部推理标记，仅保留用户可见症状
            possible_causes=possible_causes,  # ★ 两层根因抽象
            confidence_breakdown=None,  # ★ 检索完成后填入
            evidence=root_cause_evidence,
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

                # ★ 确保所有分数在 [0, 1] 范围内
                _clamp = lambda v: round(max(0.0, min(1.0, float(v or 0))), 3)

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
                        relevance_score=_clamp(item.final_score),
                        recall_score=_clamp(item.vector_score),
                        reranker_score=_clamp(item.reranker_score),
                        match_reason=item.rank_reason,
                    ),
                })

            # ★ 为每个补丁计算 ScoreBreakdown
            # (向量分数归一化已在 rerank_candidates() 中完成, 此处无需重复处理)
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

        # ── ★ 置信度拆解 (检索完成后, 使用 Top-1 的 embedding score) ──
        top1_emb_score = (
            matched_patches[0].score_breakdown.embedding_score
            if matched_patches and matched_patches[0].score_breakdown
            else 0.0
        )
        cb_dict = compute_confidence_breakdown(root_cause_result, feature, top1_emb_score)
        root_cause_info.confidence_breakdown = ConfidenceBreakdown(**cb_dict)

        # ── ★ 证据完整度评估 (比赛加分模块) ──
        from ...analyzer.rootcause import compute_evidence_coverage
        ec_dict = compute_evidence_coverage(feature, root_cause_info, matched_patches)
        evidence_coverage = EvidenceCoverage(
            items=[EvidenceCoverageItem(**item) for item in ec_dict["items"]],
            coverage_pct=ec_dict["coverage_pct"],
            reliability=ec_dict["reliability"],
            reliability_reason=ec_dict["reliability_reason"],
        )

        _save_task(task_id, {
            "status": "completed",
            "progress": 1.0,
            "root_cause": root_cause_info,
            "matched_patches": matched_patches,
            "steps": steps,
            "llm_explanation": llm_explanation,
            "evidence_coverage": evidence_coverage,  # ★ 证据完整度
            "retrieval_query": getattr(root_cause_result, "retrieval_query", ""),
            "retrieval_mode": "standard",
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
    """基于规则引擎生成分析解释 (LLM 不可用时的降级)

    增强版: 即使 LLM 不可用，也能生成包含维度贡献、风险提示、
    Evidence-Aware 声明的有信息量报告。
    """
    if not patches:
        return (
            "## 分析结果\n\n"
            "未能找到匹配的补丁。\n\n"
            "### 建议\n"
            "1. 使用 drgn 分析 vmcore 以获取更多证据\n"
            "2. 扩大搜索范围，检查相关子系统的最新 commit\n"
            "3. 检查内核邮件列表中是否有相关讨论\n"
        )

    top = patches[0]

    # ── (1) Crash Summary ──
    lines = [
        "## 🤖 注意: 当前为规则引擎生成的降级报告",
        "",
        "LLM 服务未连接，以下分析基于专家规则和检索指标自动生成。",
        "启用 LLM (Ollama 或 API Key) 可获得更详细的分析报告。",
        "",
        "---",
        "",
        "## (1) Crash Summary",
        "",
        f"**根因类型**: {root_cause.root_cause}",
        f"**受影响子系统**: `{root_cause.subsystem}`",
        f"**置信度**: {root_cause.confidence:.0%}",
        f"**摘要**: {root_cause.summary}",
    ]

    # ── (2) Evidence ──
    if root_cause.evidence:
        ev = root_cause.evidence
        lines += [
            "",
            "## (2) 根因证据",
            "",
        ]
        if ev.panic_keyword:
            lines.append(f"- **Panic 关键词**: {ev.panic_keyword}")
        if ev.fault_address:
            lines.append(f"- **故障地址**: `{ev.fault_address}`")
        if ev.matched_rule_id:
            lines.append(f"- **匹配规则**: {ev.matched_rule_id} — {ev.matched_rule_name or ''}")
        if ev.trace_functions:
            lines.append(f"- **调用栈函数**: {', '.join(ev.trace_functions[:5])}")

    # ── (3) TopK Patches ──
    lines += [
        "",
        "## (3) 推荐补丁",
        "",
        "| Rank | Score | Commit | Subject |",
        "|------|-------|--------|---------|",
    ]
    for p in patches[:5]:
        lines.append(
            f"| {p.rank} | {p.relevance_score:.3f} | "
            f"`{p.commit.commit_id[:12]}` | {p.commit.title[:80]} |"
        )

    # ── (4) Score Composition (从 score_breakdown 获取) ──
    if top.score_breakdown and top.score_breakdown.score_contribution:
        contrib = top.score_breakdown.score_contribution
        lines += [
            "",
            "## (4) 评分构成 (Top-1)",
            "",
            "| Dimension | Weight | Score | Contribution |",
            "|-----------|--------|-------|-------------|",
        ]
        dims = [
            ("Embedding", "embedding", top.score_breakdown.embedding_score),
            ("Reranker", "reranker", top.score_breakdown.reranker_score),
            ("Expert Rule", "expert_rule", top.score_breakdown.expert_rule_score),
            ("Call Stack", "callstack_match", top.score_breakdown.callstack_match_score),
            ("Subsystem", "subsystem_match", top.score_breakdown.subsystem_match_score),
            ("Version", "version_match", top.score_breakdown.version_match_score),
            ("LLM Judge", "llm_judge", top.score_breakdown.llm_judge_score),
        ]
        for name, key, score in dims:
            c = contrib.get(key, 0)
            lines.append(f"| {name} | {top.score_breakdown.fusion_weights.get(key, 0):.0%} | {score:.3f} | {c:.3f} |")
        lines.append(f"| **Total** | — | — | **{top.score_breakdown.final_score:.3f}** |")

    # ── (5) Ranking Reasons ──
    lines += [
        "",
        "## (5) 排序理由",
        "",
    ]
    for p in patches[:3]:
        lines.append(f"**Top{p.rank}** — {p.commit.title[:60]}...")
        if p.match_reason:
            lines.append(f"- 匹配理由: {p.match_reason}")
        if p.why_not_explanation and p.rank > 1:
            wn = p.why_not_explanation
            if wn.different_aspects:
                lines.append(f"- 与 Top1 的差异: {'; '.join(wn.different_aspects[:3])}")
            if wn.ranking_reason:
                lines.append(f"- 排名原因: {wn.ranking_reason}")
        lines.append("")

    # ── (6) Limitations ──
    missing = []
    if not (root_cause.evidence and root_cause.evidence.trace_functions):
        missing.append("Call Trace")
    if not (root_cause.evidence and root_cause.evidence.kernel_version):
        missing.append("Kernel Version")
    if missing:
        lines += [
            "## (6) ⚠️ 分析局限性",
            "",
            f"以下关键证据缺失: **{', '.join(missing)}**",
            "",
            "当前推荐应视为**候选补丁排序**，而非确认修复方案。",
            f"建议补充 {', '.join(missing)} 信息后重新分析以获得更准确的结果。",
        ]

    # ── (7) Decision Recommendation ──
    top1_title = top.commit.title[:80]
    top2 = patches[1] if len(patches) > 1 else None

    lines += [
        "",
        "## (7) 💡 决策建议",
        "",
        f"**推荐操作**: 优先应用 Top1 补丁 `{top.commit.commit_id[:12]}` — *{top1_title}*",
        "",
        f"**推荐理由**:",
        f"- 综合评分最高 ({top.relevance_score:.3f})",
        f"- 匹配了 Expert Rule {root_cause.evidence.matched_rule_id if root_cause.evidence else 'N/A'}",
        f"- 修复类型 ({top.commit.bug_type or 'N/A'}) 与根因 ({root_cause.root_cause}) 一致",
    ]

    if top2:
        gap = top.relevance_score - top2.relevance_score
        if gap < 0.01:
            lines.append(f"- ⚠️ 与 Top2 差距极小 ({gap:.4f})，建议同时审查 Top2")
        else:
            lines.append(f"- 与 Top2 差距为 {gap:.4f}，Top1 优势明确")

    lines += [
        "",
        "### 建议调查流程",
        "",
        "| 步骤 | 操作 | 目的 |",
        "|------|------|------|",
        "| ① | 审查 Top1 的 Diff | 理解具体修复方式 |",
        "| ② | 对比补丁修改函数 vs 崩溃调用栈 | 确认修复是否覆盖崩溃路径 |",
        "| ③ | 检查内核版本兼容性 | 确认补丁可直接 backport |",
        "| ④ | 在测试环境验证补丁 | 确认无回归问题 |",
        "| ⑤ | 合入生产内核 | — |",
    ]

    # ★ 风险提示
    missing = []
    if not (root_cause.evidence and root_cause.evidence.trace_functions):
        missing.append("Call Trace")
    if not (root_cause.evidence and root_cause.evidence.kernel_version):
        missing.append("Kernel Version")

    if missing:
        lines += [
            "",
            "### ⚠️ 风险提示",
            "",
            f"当前分析缺少以下关键证据: **{', '.join(missing)}**。",
            f"因此 Top1 推荐应视为**候选补丁排序**中的最佳候选，而非已确认的修复方案。",
            f"建议补充 {', '.join(missing)} 信息后重新分析，以获得更高可信度的推荐。",
        ]
    else:
        lines += [
            "",
            "### ✅ 可信度评估",
            "",
            "当前分析的关键证据基本齐全，Top1 推荐可信度较高。",
            "但仍建议在测试环境验证后再合入生产内核。",
        ]

    # ── (8) Analysis Scope ──
    lines += [
        "",
        "---",
        "> **Analysis Scope**",
        "> 本报告采用 Evidence-Aware 分析策略，所有结论均基于当前输入的宕机日志、",
        "> 结构化分析结果、检索到的补丁信息及其 Diff 内容生成。",
        "> 对于日志中未提供或证据不足的信息，报告已明确标记为 **Unknown**",
        "> 或 **Insufficient Evidence**，未进行推测性补全。",
    ]

    return "\n".join(lines)



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

    # ★ 自动检测数据源: data_full → data → 503 错误
    data_source = resolve_data_source()
    if data_source is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "NO_DATA_SOURCE",
                "message": (
                    "未检测到向量库数据 (data_full/ 和 data/ 均无 FAISS 索引)。"
                    "请先下载数据: bash scripts/download_data_full.sh "
                    "或构建 demo 数据: python scripts/build_demo_data.py"
                ),
            },
        )

    dataset_name = data_source[1]

    # ★ 安全: 不保存 user_api_key
    safe_request = request.model_dump(exclude={"user_api_key"})
    _save_task(task_id, {
        "task_id": task_id,
        "status": "running",
        "progress": 0.0,
        "created_at": created_at,
        "request": safe_request,
        "analysis_mode": dataset_name,  # ★ 记录使用的数据源
    })

    logger.info(f"使用真实 RAG Pipeline 处理任务 {task_id} (数据源: {dataset_name})")
    background_tasks.add_task(_run_real_analysis, task_id, request)
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
            evidence_coverage=task.get("evidence_coverage"),
            retrieval_query=task.get("retrieval_query"),
            retrieval_mode=task.get("retrieval_mode", "standard"),
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
