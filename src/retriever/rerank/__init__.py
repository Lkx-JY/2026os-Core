"""精排模块 — BGE-Reranker-v2 + LLM Judge

负责对向量召回阶段返回的 Top-K 候选进行精准重排序。
是四阶段检索架构的第二、三阶段，消除"表面关键词相似"与"深层因果关联"的差异。

核心功能:
- BGE-Reranker-v2 深度语义重排: 将查询-补丁对送入交叉编码器，捕获细粒度语义关联
- LLM Judge 因果评分: 利用大模型从因果关联、修复意图、子系统匹配角度进行最终评分
- 多维度评分融合: 向量相似度 + Reranker 分数 + LLM 因果分数 → 综合排名
- 可解释性输出: 为每条结果生成可读的排名理由

设计原理:
- Cross-encoder vs Bi-encoder: Reranker 使用交叉注意力机制，能捕获查询与文档间的交互语义
- LLM Judge: 大模型从领域知识角度判断补丁是否真正解决根因，而非表面关键词匹配
"""

from __future__ import annotations
import numpy as np
from typing import List, Dict, Any, Optional, Tuple, Callable
from dataclasses import dataclass, field

from ..recall import SearchResult


# ============================================================================
# 排序结果数据结构
# ============================================================================

@dataclass
class RankedItem:
    """排序后的单个候选结果"""
    rank: int                          # 最终排名 (1-based)
    commit_hash: str = ""              # commit 哈希
    subject: str = ""                  # commit 标题
    subsystem: str = ""                # 子系统
    bug_type: str = ""                 # Bug 类型

    # 多维度评分
    vector_score: float = 0.0          # 向量相似度 (来自 Recall 阶段)
    reranker_score: float = 0.0        # BGE-Reranker 交叉编码分数
    llm_judge_score: float = 0.0       # LLM 因果判断分数
    final_score: float = 0.0           # 综合加权分数

    # 可解释性
    rank_reason: str = ""              # 排名理由
    causal_relevance: str = ""         # LLM 因果关联分析
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RankedResult:
    """完整排序结果"""
    query_text: str = ""
    items: List[RankedItem] = field(default_factory=list)
    total_candidates: int = 0
    rerank_time_ms: float = 0.0

    def top(self, k: int = 5) -> List[RankedItem]:
        """返回 Top-K 结果"""
        return self.items[:k]

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """转换为字典列表"""
        return [
            {
                "rank": item.rank,
                "commit_hash": item.commit_hash,
                "subject": item.subject,
                "subsystem": item.subsystem,
                "bug_type": item.bug_type,
                "vector_score": round(item.vector_score, 4),
                "reranker_score": round(item.reranker_score, 4),
                "llm_judge_score": round(item.llm_judge_score, 4),
                "final_score": round(item.final_score, 4),
                "rank_reason": item.rank_reason,
                "causal_relevance": item.causal_relevance,
            }
            for item in self.items
        ]


# ============================================================================
# BGE-Reranker-v2 封装
# ============================================================================

class BGEReranker:
    """基于 BGE-Reranker-v2-m3 的深度语义重排器

    使用交叉编码器 (Cross-Encoder) 模型对 query-document 对进行联合编码，
    输出细粒度的语义相关性分数。

    与 Bi-encoder (BGE-M3) 的区别:
    - Bi-encoder: 分别编码 query 和 document，速度快但丢失交互信息
    - Cross-encoder: 联合编码 (query, document)，精度高但速度较慢
    - Rerank 阶段: 仅对 Top-K 候选 (通常 50-200) 做交叉编码，兼顾精度和速度

    Example:
        >>> reranker = BGEReranker()
        >>> scores = reranker.compute_scores(
        ...     query="fix deadlock in spin_lock",
        ...     documents=["commit msg 1", "commit msg 2"],
        ... )
        >>> print(scores)  # [0.85, 0.32]
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        device: Optional[str] = None,
    ):
        """
        Args:
            model_name: HuggingFace 模型名称
            device: 设备 ("cpu", "cuda")，None 时自动检测
        """
        import os as _os
        # 优先使用环境变量指定的本地模型路径
        self.model_name = _os.environ.get("RERANKER_MODEL", model_name)
        self.device = device or self._auto_device()
        self.model = None
        self.tokenizer = None
        self._initialized = False
        # 缓存本地模型路径（ModelScope 镜像）
        self._local_model_path: Optional[str] = None

    def _resolve_local_path(self) -> Optional[str]:
        """尝试查找本地缓存的模型路径（ModelScope / 本地目录）"""
        import os as _os
        # 1. 如果 model_name 本身是本地路径且存在
        if _os.path.isdir(self.model_name):
            return self.model_name
        # 2. 检查 ModelScope 缓存
        modelscope_root = _os.path.expanduser("~/.cache/modelscope/hub")
        candidate = _os.path.join(modelscope_root, self.model_name)
        if _os.path.isdir(candidate):
            return candidate
        # 3. 检查 HF 缓存
        hf_root = _os.path.expanduser("~/.cache/huggingface/hub")
        hf_dirname = "models--" + self.model_name.replace("/", "--")
        hf_candidate = _os.path.join(hf_root, hf_dirname, "snapshots")
        if _os.path.isdir(hf_candidate):
            # 取第一个可用的 snapshot
            for snap in sorted(_os.listdir(hf_candidate)):
                snap_path = _os.path.join(hf_candidate, snap)
                if _os.path.isfile(_os.path.join(snap_path, "config.json")):
                    return snap_path
        return None

    @staticmethod
    def _auto_device() -> str:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    def _lazy_init(self):
        """延迟初始化模型"""
        if self._initialized:
            return
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            # 优先使用本地模型路径，避免访问 HuggingFace
            local_path = self._resolve_local_path()
            load_kwargs = {}
            if local_path:
                load_kwargs = {"local_files_only": True}
                model_path = local_path
            else:
                model_path = self.model_name

            self.tokenizer = AutoTokenizer.from_pretrained(model_path, **load_kwargs)
            self.model = AutoModelForSequenceClassification.from_pretrained(
                model_path, **load_kwargs
            )
            self.model.eval()
            # 如果 cuda 可用，移动模型到 GPU
            if self.device == "cuda":
                try:
                    self.model = self.model.cuda()
                except Exception:
                    pass
        except ImportError:
            pass
        except Exception as e:
            print(f"Warning: BGE-Reranker init failed: {e}")
        self._initialized = True

    def compute_scores(
        self,
        query: str,
        documents: List[str],
        batch_size: int = 32,
    ) -> List[float]:
        """计算 query 与每个 document 的相关性分数

        Args:
            query: 查询文本
            documents: 候选文档列表
            batch_size: 批量大小

        Returns:
            相关性分数列表 (0.0 ~ 1.0, 越高越相关)
        """
        self._lazy_init()

        if not documents:
            return []

        if self.model is None:
            # 降级: 基于文本重叠的简单打分
            return self._fallback_scores(query, documents)

        # 构造 query-document 对
        pairs = [[query, doc] for doc in documents]

        all_scores = []
        try:
            import torch
            with torch.no_grad():
                for i in range(0, len(pairs), batch_size):
                    batch_pairs = pairs[i:i + batch_size]
                    inputs = self.tokenizer(
                        batch_pairs,
                        padding=True,
                        truncation=True,
                        max_length=512,
                        return_tensors="pt",
                    )

                    if self.device == "cuda":
                        try:
                            inputs = {k: v.cuda() for k, v in inputs.items()}
                        except Exception:
                            pass

                    outputs = self.model(**inputs)
                    # BGE-Reranker 输出 logits，sigmoid 后得到分数
                    batch_scores = (
                        torch.sigmoid(outputs.logits.view(-1))
                        .cpu()
                        .numpy()
                        .tolist()
                    )
                    all_scores.extend(batch_scores)

        except Exception as e:
            print(f"Warning: BGE-Reranker compute failed: {e}")
            return self._fallback_scores(query, documents)

        return all_scores

    def _fallback_scores(self, query: str, documents: List[str]) -> List[float]:
        """降级打分 — 基于关键词重叠的简单启发式"""
        query_words = set(query.lower().split())
        scores = []
        for doc in documents:
            doc_words = set(doc.lower().split())
            if not query_words:
                scores.append(0.5)
            else:
                overlap = len(query_words & doc_words) / len(query_words)
                scores.append(min(overlap, 1.0))
        return scores


# 全局单例
_reranker: Optional[BGEReranker] = None


def get_reranker() -> BGEReranker:
    """获取 Reranker 单例"""
    global _reranker
    if _reranker is None:
        _reranker = BGEReranker()
    return _reranker


# ============================================================================
# LLM Judge — 因果关联评分
# ============================================================================

def llm_judge_scores(
    query_text: str,
    candidates: List[Dict[str, Any]],
    model_name: str = "deepseek-chat",
    max_candidates: int = 50,
) -> List[Tuple[float, str]]:
    """使用 LLM 从因果关联角度对候选补丁进行评分

    LLM Judge 的设计理念:
    向量检索和 Reranker 都是基于语义相似度的 — 它们擅长找到"描述相似"的补丁，
    但不一定能判断补丁是否真的"解决"了当前问题。
    LLM Judge 利用大模型的推理能力，从以下维度判断因果关联:
    1. 补丁是否修复了相同的根因?
    2. 补丁是否在同一子系统/函数?
    3. 补丁的修复模式是否与故障特征匹配?

    Args:
        query_text: 查询文本 (RootCauseResult.retrieval_query)
        candidates: 候选列表 (来自 Recall 阶段)
        model_name: LLM 模型名称
        max_candidates: 最多评分的候选数 (控制 LLM 调用成本)

    Returns:
        List of (score, reason) 元组，与 candidates 顺序一致
    """
    if not candidates:
        return []

    # 只对前 max_candidates 个进行 LLM 评分
    candidates_to_judge = candidates[:max_candidates]

    judge_prompt = _build_judge_prompt(query_text, candidates_to_judge)

    try:
        response = _call_llm(judge_prompt, model_name)
        scores = _parse_judge_response(response, len(candidates_to_judge))
    except Exception as e:
        print(f"Warning: LLM Judge failed: {e}, using fallback scoring")
        scores = [(0.5, "LLM Judge unavailable") for _ in candidates_to_judge]

    # 补齐未评分的候选
    if len(scores) < len(candidates):
        scores += [(0.5, "Not judged") for _ in range(len(candidates) - len(scores))]

    return scores


def _build_judge_prompt(query_text: str, candidates: List[Dict[str, Any]]) -> str:
    """构造 LLM Judge 提示词"""
    # 截取查询文本的关键部分
    query_snippet = query_text[:800]

    candidates_text = ""
    for i, cand in enumerate(candidates):
        subject = cand.get("subject", "")[:120]
        subsystem = cand.get("subsystem", "unknown")
        bug_type = cand.get("bug_type", "unknown")
        fix_tags = cand.get("fix_tags", "")
        candidates_text += (
            f"[{i}] subsystem={subsystem} bug_type={bug_type} "
            f"fix_tags={fix_tags}\n    title: {subject}\n"
        )

    return f"""You are a Linux kernel debugging expert. Given a crash analysis and a list of candidate patches,
judge each patch's causal relevance — whether it truly fixes the root cause, not just shares keywords.

## Crash Analysis:
{query_snippet}

## Candidate Patches:
{candidates_text}

## Instructions:
For each candidate [0] to [{len(candidates) - 1}], rate its causal relevance on a 0.0-1.0 scale:
- 0.9-1.0: Directly fixes the exact root cause
- 0.7-0.8: Fixes same bug type in same subsystem
- 0.5-0.6: Fixes similar issue but different subsystem
- 0.3-0.4: Superficially related
- 0.0-0.2: Unrelated

Output ONLY a JSON array of objects:
[{{"index": 0, "score": 0.85, "reason": "Direct fix for same list corruption in mm/slab"}}, ...]

Output:"""


def _call_llm(prompt: str, model_name: str) -> str:
    """调用 LLM API — 委托给统一的 LLMClient"""
    try:
        from ...generator.llm import get_llm_client
        return get_llm_client().chat(
            prompt=prompt,
            temperature=0.1,
            max_tokens=2048,
            model=model_name,
        )
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}")


def _parse_judge_response(
    response: str, expected_count: int
) -> List[Tuple[float, str]]:
    """解析 LLM Judge 返回的 JSON"""
    import json
    import re

    # 尝试提取 JSON 数组
    try:
        json_match = re.search(r"\[.*\]", response, re.DOTALL)
        if json_match:
            items = json.loads(json_match.group())
            scores = []
            for _ in range(expected_count):
                scores.append((0.5, "Not found in response"))
            for item in items:
                idx = int(item.get("index", -1))
                score = float(item.get("score", 0.5))
                reason = str(item.get("reason", ""))[:200]
                if 0 <= idx < expected_count:
                    scores[idx] = (score, reason)
            return scores
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Warning: Failed to parse LLM Judge response: {e}")

    return [(0.5, "Parse failed") for _ in range(expected_count)]


# ============================================================================
# 多维度评分融合
# ============================================================================

def _load_fusion_weights() -> Tuple[float, float, float]:
    """从 config.yaml 加载融合权重，回退到默认值 (0.2, 0.4, 0.4)"""
    try:
        from ...common.config import load_yaml_config
        config = load_yaml_config()
        retrieval = config.get("retrieval", {}).get("fusion_weights", {})
        return (
            float(retrieval.get("recall", 0.2)),
            float(retrieval.get("reranker", 0.4)),
            float(retrieval.get("judge", 0.4)),
        )
    except Exception:
        return (0.2, 0.4, 0.4)


def fuse_scores(
    vector_scores: List[float],
    reranker_scores: List[float],
    llm_scores: List[float],
    weights: Optional[Tuple[float, float, float]] = None,
) -> List[float]:
    """融合多维度评分为综合分数

    默认权重从 config.yaml retrieval.fusion_weights 读取，设计理念:
    - 向量相似度 (0.2): 作为基础信号，但不完全依赖 — 语义相似 ≠ 因果匹配
    - Reranker 分数 (0.4): 交叉编码器捕获了 query-doc 交互语义，权重较高
    - LLM Judge (0.4): 大模型的因果推理最接近人类专家判断，权重最高

    Args:
        vector_scores: 向量相似度列表
        reranker_scores: Reranker 交叉编码分数列表
        llm_scores: LLM 因果评分列表
        weights: (vector_weight, reranker_weight, llm_weight)，None时从配置读取

    Returns:
        综合分数列表
    """
    if weights is None:
        weights = _load_fusion_weights()
    w_vec, w_rerank, w_llm = weights

    fused = []
    max_len = max(len(vector_scores), len(reranker_scores), len(llm_scores))

    for i in range(max_len):
        v = vector_scores[i] if i < len(vector_scores) else 0.5
        r = reranker_scores[i] if i < len(reranker_scores) else 0.5
        l = llm_scores[i] if i < len(llm_scores) else 0.5

        fused.append(w_vec * v + w_rerank * r + w_llm * l)

    return fused


# ============================================================================
# 完整重排流程
# ============================================================================

def rerank_candidates(
    query_text: str,
    candidates: List[Dict[str, Any]],
    vector_scores: Optional[List[float]] = None,
    use_llm_judge: bool = True,
    weights: Optional[Tuple[float, float, float]] = None,
) -> RankedResult:
    """完整的候选重排流程

    流程:
    1. BGE-Reranker-v2 交叉编码打分
    2. [可选] LLM Judge 因果评分
    3. 多维度评分融合 → 综合排名
    4. 构造可解释的 RankedResult

    Args:
        query_text: 查询文本
        candidates: 候选列表 (dict list, 来自 SearchResult.to_dict_list())
        vector_scores: 向量相似度列表 (None 时从 candidates 中提取)
        use_llm_judge: 是否启用 LLM Judge (启用会更准确但增加延迟和 API 成本)
        weights: (vector, reranker, llm) 融合权重

    Returns:
        RankedResult 对象

    Example:
        >>> from src.retriever.recall import recall_candidates
        >>> from src.retriever.rerank import rerank_candidates
        >>> hits = recall_candidates(query_text, top_k=100)
        >>> ranked = rerank_candidates(query_text, hits.to_dict_list())
        >>> for item in ranked.top(5):
        ...     print(f"#{item.rank}: {item.subject} (score={item.final_score:.3f})")
    """
    import time
    t0 = time.time()

    if not candidates:
        return RankedResult(
            query_text=query_text,
            total_candidates=0,
            rerank_time_ms=(time.time() - t0) * 1000,
        )

    n = len(candidates)

    # Step 1: 提取文档文本和向量分数
    documents = []
    if vector_scores is None:
        vector_scores = []
        for cand in candidates:
            vector_scores.append(cand.get("score", 0.5))

    for cand in candidates:
        subject = cand.get("subject", "")[:200]
        subsystem = cand.get("subsystem", "unknown")
        bug_type = cand.get("bug_type", "unknown")
        fix_tags = cand.get("fix_tags", "")
        # 构造用于 Reranker 的文档文本
        doc_text = f"[{subsystem}] [{bug_type}] {subject}"
        if fix_tags:
            doc_text += f" Fixes: {fix_tags}"
        documents.append(doc_text)

    # Step 2: BGE-Reranker 打分
    reranker = get_reranker()
    reranker_scores = reranker.compute_scores(query_text, documents)

    # Step 3: LLM Judge 打分 (可选)
    if use_llm_judge:
        llm_results = llm_judge_scores(query_text, candidates)
        llm_scores = [s for s, _ in llm_results]
    else:
        llm_scores = [0.5] * n

    # Step 4: 多维度融合
    final_scores = fuse_scores(vector_scores, reranker_scores, llm_scores)

    # Step 5: 排序
    indexed = list(enumerate(final_scores))
    indexed.sort(key=lambda x: -x[1])

    # Step 6: 构造结果
    ranked_items = []
    for rank, (orig_idx, fused_score) in enumerate(indexed, 1):
        cand = candidates[orig_idx]
        item = RankedItem(
            rank=rank,
            commit_hash=cand.get("commit_hash", ""),
            subject=cand.get("subject", ""),
            subsystem=cand.get("subsystem", "unknown"),
            bug_type=cand.get("bug_type", "unknown"),
            vector_score=vector_scores[orig_idx] if orig_idx < len(vector_scores) else 0.0,
            reranker_score=reranker_scores[orig_idx] if orig_idx < len(reranker_scores) else 0.0,
            llm_judge_score=llm_scores[orig_idx] if orig_idx < len(llm_scores) else 0.0,
            final_score=fused_score,
            rank_reason=_generate_rank_reason(
                cand, fused_score,
                reranker_scores[orig_idx] if orig_idx < len(reranker_scores) else 0.5,
            ),
            metadata=cand,
        )
        ranked_items.append(item)

    elapsed_ms = (time.time() - t0) * 1000

    return RankedResult(
        query_text=query_text,
        items=ranked_items,
        total_candidates=n,
        rerank_time_ms=elapsed_ms,
    )


def _generate_rank_reason(
    cand: Dict[str, Any],
    final_score: float,
    reranker_score: float,
) -> str:
    """为排名生成人类可读的理由"""
    parts = []

    if final_score >= 0.85:
        parts.append("高度匹配")
    elif final_score >= 0.70:
        parts.append("显著相关")
    elif final_score >= 0.50:
        parts.append("中度相关")
    else:
        parts.append("低度相关")

    subsystem = cand.get("subsystem", "unknown")
    bug_type = cand.get("bug_type", "unknown")
    parts.append(f"子系统={subsystem}")
    parts.append(f"Bug类型={bug_type}")

    if reranker_score >= 0.80:
        parts.append("语义高度相似")

    return "; ".join(parts)


# ============================================================================
# ★ 可解释性增强 — 多维评分明细 & 比较解释
# ============================================================================

# 多维融合权重 (可配置)
EXPLAINABLE_FUSION_WEIGHTS = {
    "embedding": 0.15,
    "reranker": 0.25,
    "expert_rule": 0.15,
    "callstack_match": 0.10,
    "subsystem_match": 0.10,
    "version_match": 0.10,
    "llm_judge": 0.15,
}

# 子系统层级和关联关系 (从 filter 模块共享)
_SUBSYSTEM_HIERARCHY: Dict[str, List[str]] = {
    "kernel": ["rcu", "cgroup", "bpf", "irq"],
    "drivers": ["usb", "pci", "nvme", "scsi"],
    "fs": ["nfs"],
    "arch": ["kvm"],
}

_RELATED_SUBSYSTEMS: Dict[str, List[str]] = {
    "mm": ["fs", "block", "kernel"],
    "net": ["drivers", "kernel", "bpf"],
    "fs": ["mm", "block", "kernel", "nfs"],
    "block": ["mm", "fs", "drivers", "scsi", "nvme"],
    "deadlock": ["kernel", "mm", "fs", "net", "block"],
}


def compute_score_breakdown(
    item: RankedItem,
    crash_subsystem: str = "",
    crash_call_trace: Optional[List[str]] = None,
    crash_kernel_version: str = "",
    crash_bug_type: str = "",
    rule_id: str = "",
) -> Dict[str, Any]:
    """计算多维评分明细

    将综合分数 final_score 分解为 7 个独立评分维度，
    面向前端 ScoreBreakdown 面板。

    Args:
        item: 排序后的候选补丁
        crash_subsystem: 崩溃所属子系统
        crash_call_trace: 崩溃调用栈函数列表
        crash_kernel_version: 崩溃内核版本
        crash_bug_type: 崩溃的 Bug 类型
        rule_id: 匹配的专家规则 ID

    Returns:
        Dict 可直接序列化为 ScoreBreakdown pydantic 模型
    """

    # ── 1. 专家规则匹配度 ────────────────────
    expert_rule_score = _compute_expert_rule_score(
        item.bug_type, crash_bug_type, rule_id
    )

    # ── 2. 调用栈匹配度 ──────────────────────
    callstack_match_score = _compute_callstack_match_score(
        item.metadata, crash_call_trace or [], crash_subsystem
    )

    # ── 3. 子系统匹配度 ──────────────────────
    subsystem_match_score = _compute_subsystem_match_score(
        item.subsystem, crash_subsystem
    )

    # ── 4. 版本匹配度 (从 metadata 中获取) ──
    version_match_score = item.metadata.get("_version_weight", 1.0)

    # ── 5. 综合分数 ──────────────────────────
    W = EXPLAINABLE_FUSION_WEIGHTS
    final = (
        item.vector_score * W["embedding"]
        + item.reranker_score * W["reranker"]
        + expert_rule_score * W["expert_rule"]
        + callstack_match_score * W["callstack_match"]
        + subsystem_match_score * W["subsystem_match"]
        + version_match_score * W["version_match"]
        + item.llm_judge_score * W["llm_judge"]
    )

    return {
        "embedding_score": round(item.vector_score, 4),
        "reranker_score": round(item.reranker_score, 4),
        "expert_rule_score": round(expert_rule_score, 4),
        "callstack_match_score": round(callstack_match_score, 4),
        "subsystem_match_score": round(subsystem_match_score, 4),
        "version_match_score": round(version_match_score, 4),
        "llm_judge_score": round(item.llm_judge_score, 4),
        "final_score": round(final, 4),
        "fusion_weights": dict(EXPLAINABLE_FUSION_WEIGHTS),
    }


def _compute_expert_rule_score(
    patch_bug_type: str,
    crash_bug_type: str,
    rule_id: str,
) -> float:
    """计算专家规则匹配度分数"""
    if not crash_bug_type or crash_bug_type == "unknown":
        return 0.5  # 无法判断，给中性分

    if patch_bug_type == crash_bug_type:
        return 0.95  # 完全匹配
    elif patch_bug_type and crash_bug_type:
        # 宽松匹配：bug_type 之间存在别名关系
        from ....common.taxonomy import BUG_TYPE_ALIASES, normalize_bug_type
        try:
            crash_normalized = normalize_bug_type(crash_bug_type)
            patch_normalized = normalize_bug_type(patch_bug_type)
            if crash_normalized == patch_normalized:
                return 0.85
        except Exception:
            pass

    # 有规则匹配但类型不完全一致
    if rule_id:
        return 0.70

    return 0.30  # 不匹配


def _compute_callstack_match_score(
    metadata: Dict[str, Any],
    crash_call_trace: List[str],
    crash_subsystem: str,
) -> float:
    """计算调用栈匹配度分数"""
    if not crash_call_trace:
        return 0.30  # 无调用栈信息，给低分

    trace_text = " ".join(crash_call_trace).lower() if crash_call_trace else ""

    # 1. 检查补丁修改的文件是否出现在调用栈中
    files_changed = metadata.get("files_changed", [])
    if files_changed:
        if any(f.lower() in trace_text for f in files_changed):
            return 0.90  # 文件精确出现在调用栈中

    # 2. 检查补丁修改的函数是否出现在调用栈中
    changed_funcs = metadata.get("changed_functions", [])
    if changed_funcs:
        if any(f.lower() in trace_text for f in changed_funcs):
            return 1.00  # 精确函数匹配 — 最高分

    # 3. 检查子系统是否一致
    patch_subsystem = metadata.get("subsystem", "")
    if patch_subsystem and crash_subsystem:
        if patch_subsystem == crash_subsystem:
            return 0.50  # 同子系统，可能间接匹配

    return 0.10  # 无匹配信号


def _compute_subsystem_match_score(
    patch_subsystem: str,
    crash_subsystem: str,
) -> float:
    """计算子系统匹配度分数"""
    if not patch_subsystem or not crash_subsystem:
        return 0.30

    if patch_subsystem == crash_subsystem:
        return 1.00

    # 父子关系
    if patch_subsystem in _SUBSYSTEM_HIERARCHY.get(crash_subsystem, []):
        return 0.80
    if crash_subsystem in _SUBSYSTEM_HIERARCHY.get(patch_subsystem, []):
        return 0.75

    # 关联关系
    if patch_subsystem in _RELATED_SUBSYSTEMS.get(crash_subsystem, []):
        return 0.60
    if crash_subsystem in _RELATED_SUBSYSTEMS.get(patch_subsystem, []):
        return 0.55

    return 0.20


def generate_why_not_explanations(
    ranked_items: List[RankedItem],
) -> List[Dict[str, Any]]:
    """为排名 ≥2 的补丁生成 '为什么不是 Top-1' 比较解释

    对每个非首位补丁，与 Top-1 进行多维度对比，
    找出相同点和差异点，生成人类可读的排序理由。

    Args:
        ranked_items: 已排序的补丁列表

    Returns:
        List of WhyNotExplanation dicts，与 ranked_items 等长，
        其中 index 0 (Top-1) 为 None
    """
    explanations = []

    if len(ranked_items) < 2:
        # 只有一个结果，无需对比
        for _ in ranked_items:
            explanations.append(None)
        return explanations

    top1 = ranked_items[0]

    for i, item in enumerate(ranked_items):
        if i == 0:
            # Top-1 不需要解释
            explanations.append(None)
            continue

        same = []
        different = []

        # ── 1. 比较 Bug 类型 ────────────────────
        if item.bug_type == top1.bug_type and item.bug_type != "unknown":
            same.append(f"同属于 {item.bug_type} 修复")
        elif item.bug_type != top1.bug_type:
            different.append(
                f"Bug 类型不同 ({item.bug_type} vs {top1.bug_type})，Top-1 更匹配当前根因"
            )

        # ── 2. 比较子系统 ──────────────────────
        if item.subsystem == top1.subsystem and item.subsystem != "unknown":
            same.append(f"同一子系统 {item.subsystem}")
        elif item.subsystem != top1.subsystem:
            different.append(
                f"属于 {item.subsystem} 子系统，与崩溃子系统关联度低于 {top1.subsystem}"
            )

        # ── 3. 比较分数差距 ────────────────────
        score_gap = top1.final_score - item.final_score
        if score_gap > 0.15:
            different.append(
                f"综合评分差距较大 (差 {score_gap:.0%})，各维度均弱于 Top-1"
            )
        elif score_gap > 0.05:
            different.append(
                f"综合评分存在差距 (差 {score_gap:.0%})"
            )

        # ── 4. 比较 Reranker 分数 ──────────────
        if item.reranker_score < top1.reranker_score - 0.10:
            different.append(
                "Reranker 语义重排分数显著低于 Top-1，语义层面关联度不足"
            )

        # ── 5. 版本维度 ────────────────────────
        item_vw = item.metadata.get("_version_weight", 1.0)
        top1_vw = top1.metadata.get("_version_weight", 1.0)
        if item_vw < 1.0 and top1_vw >= 1.0:
            different.append(
                f"版本匹配权重降低 ({item_vw:.0%})，补丁版本与崩溃内核存在兼容性差异"
            )

        # ── 6. 生成总结 ────────────────────────
        if different:
            ranking_reason = f"综合 {len(different)} 个差异因素，排名第 {item.rank}"
        else:
            ranking_reason = f"与 Top-1 特征相近，但因综合分数略低排名第 {item.rank}"

        explanations.append({
            "compared_to_rank": 1,
            "same_aspects": same,
            "different_aspects": different,
            "ranking_reason": ranking_reason,
        })

    return explanations


def _enrich_rank_reason_extended(
    item: RankedItem,
    score_breakdown: Dict[str, Any],
    why_not: Optional[Dict[str, Any]] = None,
) -> str:
    """生成增强版排名理由 — 融合多维评分信息"""
    parts = []

    # 综合分数判定
    final = score_breakdown.get("final_score", item.final_score)
    if final >= 0.85:
        parts.append("高度匹配")
    elif final >= 0.70:
        parts.append("显著相关")
    elif final >= 0.50:
        parts.append("中度相关")
    else:
        parts.append("低度相关")

    # 子系统匹配
    ss_score = score_breakdown.get("subsystem_match_score", 0)
    if ss_score >= 0.80:
        parts.append("子系统精确匹配")
    elif ss_score >= 0.50:
        parts.append("子系统部分匹配")

    # 调用栈匹配
    cs_score = score_breakdown.get("callstack_match_score", 0)
    if cs_score >= 0.80:
        parts.append("调用栈直接命中")
    elif cs_score >= 0.40:
        parts.append("调用栈间接关联")

    # 版本匹配
    v_score = score_breakdown.get("version_match_score", 1.0)
    if v_score >= 1.0:
        parts.append("版本兼容")
    elif v_score < 0.80:
        parts.append("版本兼容性偏低")

    # 专家规则
    er_score = score_breakdown.get("expert_rule_score", 0)
    if er_score >= 0.85:
        parts.append("专家规则高度匹配")

    return " | ".join(parts)


__all__ = [
    # 数据结构
    "RankedItem",
    "RankedResult",
    # Reranker
    "BGEReranker",
    "get_reranker",
    # LLM Judge
    "llm_judge_scores",
    # 融合
    "fuse_scores",
    # 完整流程
    "rerank_candidates",
    # ★ 可解释性增强
    "compute_score_breakdown",
    "generate_why_not_explanations",
    "EXPLAINABLE_FUSION_WEIGHTS",
]
