"""规则过滤模块 — Rule-Based Filter Engine

负责在向量检索前后进行基于规则的硬过滤和软加权。
是四阶段检索架构的第一道和补充过滤器。

核心功能:
- 子系统过滤: 根据故障特征过滤相关子系统的 commit
- 内核版本过滤: 过滤版本不匹配的 commit (新版本的补丁不能用于旧内核)
- Bug 类型过滤: 根据识别的 bug_type 进行精确过滤
- 日期/时效过滤: 过滤过旧或过新的 commit
- 安全补丁优先: CVE 相关补丁加权

设计理念:
- 规则过滤在检索的任何阶段都可以插入
- 支持链式过滤 (filter pipeline)
- 确定性规则 (不依赖模型)，速度快、可解释
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional, Set, Callable
from dataclasses import dataclass, field
import re


# ============================================================================
# 内核子系统映射
# ============================================================================

# 子系统及其文件路径前缀
SUBSYSTEM_PATH_MAP = {
    "mm": ["mm/", "include/linux/mm", "include/linux/slab", "include/linux/page"],
    "fs": ["fs/", "include/linux/fs", "include/linux/file"],
    "net": ["net/", "include/net/", "include/linux/net", "include/linux/skbuff"],
    "block": ["block/", "include/linux/blk", "include/linux/bio"],
    "kernel": ["kernel/", "include/linux/sched", "include/linux/kernel"],
    "drivers": ["drivers/"],
    "arch": ["arch/"],
    "bpf": ["kernel/bpf/", "include/linux/bpf", "include/uapi/linux/bpf"],
    "security": ["security/", "include/linux/security", "include/linux/lsm"],
    "kvm": ["arch/x86/kvm/", "arch/arm64/kvm/", "virt/kvm/"],
    "rcu": ["kernel/rcu/", "include/linux/rcu"],
    "cgroup": ["kernel/cgroup/", "include/linux/cgroup"],
    "nfs": ["fs/nfs/", "include/linux/nfs", "include/linux/sunrpc"],
    "usb": ["drivers/usb/", "include/linux/usb"],
    "pci": ["drivers/pci/", "include/linux/pci"],
    "nvme": ["drivers/nvme/", "include/linux/nvme"],
    "scsi": ["drivers/scsi/", "include/scsi/"],
    "crypto": ["crypto/", "include/crypto/"],
    "power": ["kernel/power/", "include/linux/power", "drivers/acpi/"],
}

# 子系统层级关系 (父 → 子)
SUBSYSTEM_HIERARCHY = {
    "kernel": ["rcu", "cgroup", "bpf", "irq"],
    "drivers": ["usb", "pci", "nvme", "scsi"],
    "fs": ["nfs"],
    "arch": ["kvm"],
}

# 相关子系统映射 (协同关系)
RELATED_SUBSYSTEMS = {
    "mm": ["fs", "block", "kernel"],
    "net": ["drivers", "kernel", "bpf"],
    "fs": ["mm", "block", "kernel", "nfs"],
    "block": ["mm", "fs", "drivers", "scsi", "nvme"],
    "deadlock": ["kernel", "mm", "fs", "net", "block"],
}

# Bug 类型 → 相关子系统
BUG_TYPE_RELATED_SUBSYSTEMS = {
    "use_after_free": ["mm", "net", "fs", "kernel", "rcu"],
    "null_pointer": ["kernel", "drivers", "mm", "fs", "net"],
    "deadlock": ["kernel", "mm", "fs", "net", "block", "drivers"],
    "race_condition": ["kernel", "mm", "net", "fs", "drivers"],
    "buffer_overflow": ["fs", "net", "drivers", "kernel"],
    "memory_leak": ["mm", "net", "fs", "drivers"],
    "memory_corruption": ["mm", "kernel", "fs", "net"],
    "double_free": ["mm", "net", "drivers"],
    "out_of_bound": ["mm", "net", "fs", "kernel"],
    "hang": ["kernel", "drivers", "fs", "block", "net"],
    "crash": ["kernel", "arch", "mm", "drivers"],
    "security": ["kernel", "security", "arch", "net"],
}


# ============================================================================
# 过滤器实现
# ============================================================================

@dataclass
class FilterResult:
    """过滤结果"""
    passed: List[Dict[str, Any]] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    uncertain: List[Dict[str, Any]] = field(default_factory=list)  # 无法判断的候选项
    filter_name: str = ""
    reject_reasons: List[str] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return len(self.passed)

    @property
    def reject_count(self) -> int:
        return len(self.rejected)

    @property
    def uncertain_count(self) -> int:
        return len(self.uncertain)


def filter_by_subsystem(
    candidates: List[Dict[str, Any]],
    target_subsystem: str,
    include_related: bool = True,
    include_parent: bool = True,
) -> FilterResult:
    """按子系统过滤候选

    Args:
        candidates: 候选列表
        target_subsystem: 目标子系统 (如 "mm")
        include_related: 是否包含相关子系统
        include_parent: 是否包含父子系统

    Returns:
        FilterResult — passed 中为匹配的候选

    Example:
        >>> filtered = filter_by_subsystem(candidates, "mm")
        >>> print(f"Passed: {filtered.pass_count}, Rejected: {filtered.reject_count}")
    """
    if not target_subsystem or target_subsystem == "unknown":
        return FilterResult(passed=candidates, filter_name="subsystem_filter")

    # 构造允许的子系统集合
    allowed: Set[str] = {target_subsystem}

    if include_parent:
        for parent, children in SUBSYSTEM_HIERARCHY.items():
            if target_subsystem in children:
                allowed.add(parent)

    if include_related:
        related = RELATED_SUBSYSTEMS.get(target_subsystem, [])
        allowed.update(related)

    passed = []
    rejected = []
    for cand in candidates:
        cand_subsys = cand.get("subsystem", "unknown")
        if cand_subsys in allowed:
            passed.append(cand)
        else:
            rejected.append(cand)

    return FilterResult(
        passed=passed,
        rejected=rejected,
        filter_name=f"subsystem_filter(target={target_subsystem}, allowed={sorted(allowed)})",
        reject_reasons=[f"subsystem mismatch: {c.get('subsystem')}" for c in rejected[:5]],
    )


def filter_by_bug_type(
    candidates: List[Dict[str, Any]],
    target_bug_type: str,
    exact_match: bool = False,
) -> FilterResult:
    """按 Bug 类型过滤

    Args:
        candidates: 候选列表
        target_bug_type: 目标 Bug 类型 (如 "use_after_free")
        exact_match: True 时严格匹配，False 时允许相关 bug 类型

    Returns:
        FilterResult
    """
    if not target_bug_type or target_bug_type == "unknown":
        return FilterResult(passed=candidates, filter_name="bug_type_filter")

    # 相关的 bug 类型组
    bug_type_groups = {
        "use_after_free": {"use_after_free", "double_free", "memory_corruption"},
        "null_pointer": {"null_pointer", "crash"},
        "deadlock": {"deadlock", "hang", "concurrency"},
        "race_condition": {"race_condition", "concurrency", "deadlock"},
        "memory_leak": {"memory_leak", "resource_leak"},
        "buffer_overflow": {"buffer_overflow", "out_of_bound"},
        "hang": {"hang", "deadlock", "concurrency"},
        "crash": {"crash", "null_pointer"},
        "security": {"security"},
    }

    if exact_match:
        allowed = {target_bug_type}
    else:
        allowed = bug_type_groups.get(target_bug_type, {target_bug_type})

    passed = []
    rejected = []
    for cand in candidates:
        cand_bug_type = cand.get("bug_type", "unknown")
        if cand_bug_type in allowed:
            passed.append(cand)
        else:
            rejected.append(cand)

    return FilterResult(
        passed=passed,
        rejected=rejected,
        filter_name=f"bug_type_filter(target={target_bug_type}, allowed={sorted(allowed)})",
    )


def filter_by_kernel_version(
    candidates: List[Dict[str, Any]],
    kernel_version: str,
    version_tolerance: int = 1,
    strict: bool = False,
) -> FilterResult:
    """按内核版本过滤

    Linux 内核版本格式: major.minor.patch (如 6.1.0, 5.15.72)

    采用三分类策略:
    - passed: 版本信息可确认且匹配
    - rejected: 版本信息可确认但不匹配
    - uncertain: 无法从提交中提取版本信息（非严格模式保留，严格模式拒绝）

    版本匹配优先级:
    1. 候选的显式 kernel_version_major/minor 元数据 (最可靠)
    2. 候选 subject/body 中的版本号正则提取
    3. 基于 commit 日期的版本推断 (降级策略)

    Args:
        candidates: 候选列表
        kernel_version: 目标内核版本 (支持 "6.1.0" 或 "6.1.0-15-amd64" 等格式)
        version_tolerance: 版本容忍度 (允许 ±N 个 minor 版本)
        strict: 无法判断时直接拒绝而非放入 uncertain

    Returns:
        FilterResult
    """
    if not kernel_version:
        return FilterResult(passed=candidates, filter_name="kernel_version_filter(no_target)")

    # 归一化输入版本号
    from ...collector.versioning import normalize_kernel_version
    normalized = normalize_kernel_version(kernel_version)
    if normalized:
        parts = normalized.split(".")
    else:
        parts = kernel_version.split(".")
    try:
        target_major = int(parts[0])
        target_minor = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return FilterResult(passed=candidates, filter_name="kernel_version_filter(bad_format)")

    passed = []
    rejected = []
    uncertain = []
    for cand in candidates:
        # 策略0: 优先使用显式版本元数据 (最可靠，离线索引时已预计算)
        # 宽松匹配：同主版本内不过滤，由 weight_by_kernel_version 做软加权
        cand_major = cand.get("kernel_version_major")
        cand_minor = cand.get("kernel_version_minor")
        if cand_major is not None and cand_minor is not None:
            if cand_major == target_major:
                # 同主版本 — 全部保留，让软加权去调分
                passed.append(cand)
            elif cand_major > target_major:
                # 跨主版本更新 — 可能不兼容，放入 uncertain
                uncertain.append(cand)
            else:
                # 旧主版本 — 可能是 backport 来源，保留
                passed.append(cand)
            continue

        cand_subject = cand.get("subject", "")

        # 策略1: 从 subject 和 body 中提取版本信息 (如 "6.1", "v5.15")
        cand_body = cand.get("body", "") or cand.get("embedding_text", "") or ""
        ver_match = re.search(r'(?:^|\s)(?:v|linux-)?(\d+)\.(\d+)', cand_subject + " " + cand_body)
        if ver_match:
            try:
                cand_major = int(ver_match.group(1))
                cand_minor = int(ver_match.group(2))
                if cand_major == target_major and abs(cand_minor - target_minor) <= version_tolerance:
                    passed.append(cand)
                else:
                    rejected.append(cand)
                continue
            except ValueError:
                pass

        # 策略2: 基于提交日期推断（映射已知内核版本发布日期）
        compat = _version_from_date_compatible(
            cand.get("date", ""), target_major, target_minor, version_tolerance
        )
        if compat is True:
            passed.append(cand)
        elif compat is False:
            rejected.append(cand)
        elif strict:
            rejected.append(cand)
        else:
            uncertain.append(cand)

    return FilterResult(
        passed=passed,
        rejected=rejected,
        uncertain=uncertain,
        filter_name=f"kernel_version_filter(target={kernel_version}, strict={strict})",
    )


# ── 内核版本发布日期映射（辅助 filter_by_kernel_version 策略2）────
_KERNEL_RELEASE_DATES: Dict[tuple, str] = {
    (6, 12): "2024-12-01", (6, 11): "2024-09-15", (6, 10): "2024-07-14",
    (6, 9):  "2024-05-12", (6, 8):  "2024-03-10", (6, 7):  "2024-01-07",
    (6, 6):  "2023-10-29", (6, 5):  "2023-08-27", (6, 4):  "2023-06-25",
    (6, 3):  "2023-04-23", (6, 2):  "2023-02-19", (6, 1):  "2022-12-11",
    (6, 0):  "2022-10-02",
    (5, 19): "2022-07-31", (5, 18): "2022-05-22", (5, 17): "2022-03-20",
    (5, 16): "2022-01-09", (5, 15): "2021-10-31", (5, 14): "2021-08-29",
    (5, 13): "2021-06-27", (5, 12): "2021-04-25", (5, 11): "2021-02-14",
    (5, 10): "2020-12-13", (5, 9):  "2020-10-11", (5, 8):  "2020-08-02",
    (5, 7):  "2020-05-31", (5, 6):  "2020-03-29", (5, 5):  "2020-01-26",
    (5, 4):  "2019-11-24", (5, 3):  "2019-09-15", (5, 2):  "2019-07-07",
    (5, 1):  "2019-05-05", (5, 0):  "2019-03-03",
    (4, 20): "2018-12-23", (4, 19): "2018-10-22", (4, 18): "2018-08-12",
    (4, 17): "2018-06-03", (4, 16): "2018-04-01", (4, 15): "2018-01-28",
    (4, 14): "2017-11-12", (4, 13): "2017-09-03", (4, 12): "2017-07-02",
    (4, 11): "2017-04-30", (4, 10): "2017-02-19", (4, 9):  "2016-12-11",
}


def _version_from_date_compatible(
    date_str: str,
    target_major: int,
    target_minor: int,
    tolerance: int,
) -> Optional[bool]:
    """基于提交日期判断是否可能与目标内核版本兼容。

    Returns:
        True:  提交对应的版本 ≤ 目标版本+容差 → 可能兼容
        False: 提交远新于目标 → 不兼容
        None:  无法解析日期或提交早于所有已知版本
    """
    if not date_str:
        return None
    try:
        commit_date = date_str[:10]  # YYYY-MM-DD
        # 找到提交日期对应的最新内核版本
        closest = None
        for (maj, min_), rel_date in sorted(_KERNEL_RELEASE_DATES.items(), reverse=True):
            if rel_date <= commit_date:
                closest = (maj, min_)
                break
        if closest is None:
            return None  # 提交日期早于已知的最早版本

        c_major, c_minor = closest
        if c_major > target_major:
            if c_major - target_major > 1:
                return False
            return None  # 跨一个主版本，无法确定
        elif c_major == target_major:
            return c_minor <= target_minor + tolerance
        else:
            return True  # 旧主版本的补丁通常兼容
    except Exception:
        return None


# ============================================================================
# 版本软加权 — 非破坏性分数调整
# ============================================================================

def weight_by_kernel_version(
    candidates: List[Dict[str, Any]],
    target_version: str,
) -> List[Dict[str, Any]]:
    """根据 commit 版本与目标版本的"距离"对候选进行软加权。

    与 filter_by_kernel_version (硬过滤) 不同，此函数不做剔除，
    而是调整 _boosted_score 来影响最终排序。

    加权策略:
        精确同版本 → ×1.30 (可能是直接修复)
        同主版本, minor 差 1~2 → ×1.15 (Fixes backport 候选)
        同主版本, minor 差 3~5 → ×1.00 (中性)
        同主版本, minor 差 ≥6 → ×0.70 (弱信号)
        跨主版本更新 → ×0.80 (可能不兼容)
        旧版本 → ×1.00 (中性, backport 来源)
        版本未知 → ×0.90 (略微降权)

    Args:
        candidates: 候选列表，每条需包含 kernel_version_major / kernel_version_minor
        target_version: 归一化目标版本 "major.minor.0"

    Returns:
        调整后的候选列表 (原地修改 _boosted_score)
    """
    if not target_version or not candidates:
        return candidates

    # 归一化输入版本号
    from ...collector.versioning import normalize_kernel_version, parse_version_tuple
    normalized = normalize_kernel_version(target_version) or target_version
    parsed = parse_version_tuple(normalized)
    if not parsed:
        return candidates
    target_major, target_minor, _ = parsed

    for cand in candidates:
        # 优先使用显式版本元数据
        cand_major = cand.get("kernel_version_major")
        cand_minor = cand.get("kernel_version_minor")

        if cand_major is None or cand_minor is None:
            # 回退：从 kernel_version 字符串解析
            kv = cand.get("kernel_version", "")
            if kv:
                kv_parts = kv.split(".")
                try:
                    cand_major = int(kv_parts[0])
                    cand_minor = int(kv_parts[1])
                except (ValueError, IndexError):
                    pass

        if cand_major is None or cand_minor is None:
            # 版本未知 — 略微降权
            base_score = cand.get("_boosted_score", cand.get("score", 1.0))
            cand["_boosted_score"] = base_score * 0.90
            cand["_version_weight"] = 0.90
            continue

        # 计算版本距离
        dist = (cand_major - target_major) * 1000 + (cand_minor - target_minor)

        if dist == 0:
            weight = 1.30
        elif 1 <= dist <= 2:
            weight = 1.15
        elif 3 <= dist <= 5:
            weight = 1.00
        elif dist >= 6:
            weight = 0.70
        elif dist < 0:
            weight = 1.00
        else:
            weight = 0.90

        base_score = cand.get("_boosted_score", cand.get("score", 1.0))
        cand["_boosted_score"] = base_score * weight
        cand["_version_weight"] = weight

    return candidates


def filter_duplicates(
    candidates: List[Dict[str, Any]],
) -> FilterResult:
    """去重 — 基于 commit_hash"""
    seen = set()
    passed = []
    rejected = []
    for cand in candidates:
        h = cand.get("commit_hash", "")
        if h and h not in seen:
            seen.add(h)
            passed.append(cand)
        elif not h:
            passed.append(cand)
        else:
            rejected.append(cand)

    return FilterResult(
        passed=passed,
        rejected=rejected,
        filter_name="dedup_filter",
    )


def filter_by_keywords(
    candidates: List[Dict[str, Any]],
    required_keywords: List[str],
    match_any: bool = True,
    field: str = "subject",
) -> FilterResult:
    """按关键词过滤

    Args:
        candidates: 候选列表
        required_keywords: 必须包含的关键词
        match_any: True = 匹配任意一个即可; False = 必须匹配全部
        field: 搜索的字段名

    Returns:
        FilterResult
    """
    if not required_keywords:
        return FilterResult(passed=candidates, filter_name="keyword_filter")

    passed = []
    rejected = []
    for cand in candidates:
        text = str(cand.get(field, "")).lower()
        if match_any:
            if any(kw.lower() in text for kw in required_keywords):
                passed.append(cand)
            else:
                rejected.append(cand)
        else:
            if all(kw.lower() in text for kw in required_keywords):
                passed.append(cand)
            else:
                rejected.append(cand)

    return FilterResult(
        passed=passed,
        rejected=rejected,
        filter_name=f"keyword_filter(kw={required_keywords}, match_any={match_any})",
    )


def boost_security_fixes(
    candidates: List[Dict[str, Any]],
    boost_factor: float = 1.2,
) -> List[Dict[str, Any]]:
    """安全补丁加权 — CVE/Fixes 标签的 commit 分数上浮

    Args:
        candidates: 候选列表
        boost_factor: 加权系数

    Returns:
        加权后的候选列表 (新增 _boosted_score 字段)
    """
    for cand in candidates:
        fix_tags = str(cand.get("fix_tags", "")).lower()
        subject = str(cand.get("subject", "")).lower()
        score = cand.get("score", 0.5)

        boost = 1.0
        if "cve" in fix_tags:
            boost = boost_factor * 1.2
        elif "fixes:" in subject or "fixes" in fix_tags:
            boost = boost_factor
        elif "security" in fix_tags:
            boost = boost_factor * 1.1

        cand["_boosted_score"] = score * boost

    return candidates


# ============================================================================
# 过滤流水线
# ============================================================================

def apply_filters(
    candidates: List[Dict[str, Any]],
    target_subsystem: Optional[str] = None,
    target_bug_type: Optional[str] = None,
    kernel_version: Optional[str] = None,
    required_keywords: Optional[List[str]] = None,
    dedup: bool = True,
    boost_security: bool = True,
) -> List[Dict[str, Any]]:
    """应用完整的规则过滤流水线

    过滤顺序 (按优先级):
    1. 去重
    2. 子系统过滤
    3. Bug 类型过滤
    4. 内核版本过滤
    5. 关键词过滤
    6. 安全补丁加权

    Args:
        candidates: 候选列表
        target_subsystem: 目标子系统
        target_bug_type: 目标 Bug 类型
        kernel_version: 内核版本
        required_keywords: 必须包含的关键词
        dedup: 是否去重
        boost_security: 是否加权安全补丁

    Returns:
        过滤并排序后的候选列表

    Example:
        >>> filtered = apply_filters(
        ...     candidates,
        ...     target_subsystem="mm",
        ...     target_bug_type="use_after_free",
        ... )
    """
    items = list(candidates)

    # 1. 去重
    if dedup:
        result = filter_duplicates(items)
        items = result.passed

    # 2. 子系统过滤
    if target_subsystem and target_subsystem != "unknown":
        result = filter_by_subsystem(items, target_subsystem)
        items = result.passed

    # 3. Bug 类型过滤
    if target_bug_type and target_bug_type != "unknown":
        result = filter_by_bug_type(items, target_bug_type)
        items = result.passed

    # 4. 内核版本过滤（uncertain 项的默认策略：保留）
    if kernel_version:
        result = filter_by_kernel_version(items, kernel_version)
        items = result.passed + result.uncertain

    # 5. 关键词过滤
    if required_keywords:
        result = filter_by_keywords(items, required_keywords)
        items = result.passed

    # 6. 安全补丁加权
    if boost_security:
        items = boost_security_fixes(items)

    # 7. 版本软加权 (非破坏性 — 调整 _boosted_score)
    if kernel_version:
        items = weight_by_kernel_version(items, kernel_version)

    # 按加权后分数排序
    items.sort(key=lambda c: c.get("_boosted_score", c.get("score", 0)), reverse=True)

    return items


def build_milvus_filter_expr(
    subsystem: Optional[str] = None,
    bug_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_score: Optional[float] = None,
) -> Optional[str]:
    """构造 Milvus 混合检索的标量过滤表达式

    用于在向量检索阶段就进行标量过滤，减少后处理开销。

    Args:
        subsystem: 子系统过滤
        bug_type: Bug 类型过滤
        date_from: 起始日期
        date_to: 截止日期
        min_score: 最低分数

    Returns:
        Milvus filter expression 或 None

    Example:
        >>> expr = build_milvus_filter_expr(
        ...     subsystem="mm",
        ...     bug_type="use_after_free",
        ... )
        >>> print(expr)
        'subsystem=="mm" && bug_type=="use_after_free"'
    """
    parts = []

    if subsystem and subsystem != "unknown":
        # 包含相关子系统
        related = RELATED_SUBSYSTEMS.get(subsystem, [subsystem])
        all_subsystems = [subsystem] + list(related)
        sub_conditions = [f'subsystem=="{s}"' for s in all_subsystems[:5]]
        parts.append(f"({' || '.join(sub_conditions)})")

    if bug_type and bug_type != "unknown":
        parts.append(f'bug_type=="{bug_type}"')

    if date_from:
        parts.append(f'date>="{date_from}"')

    if date_to:
        parts.append(f'date<="{date_to}"')

    if min_score is not None:
        parts.append(f"score>={min_score}")

    if not parts:
        return None

    return " && ".join(parts)


# ============================================================================
# ★ 可解释性增强 — 版本感知分析
# ============================================================================

def compute_version_analysis(
    crash_kernel_version: str,
    patch_commit_info: Dict[str, Any],
    patch_date: str = "",
) -> Dict[str, Any]:
    """计算版本感知分析

    将补丁版本与崩溃内核版本进行对比，生成面向前端 VersionAnalysis 面板的 dict。

    Args:
        crash_kernel_version: 崩溃内核版本，如 "6.6.0"
        patch_commit_info: 补丁的 commit dict，至少包含:
            kernel_version_major, kernel_version_minor, kernel_version
        patch_date: 补丁提交日期 (YYYY-MM-DD)

    Returns:
        Dict 可直接序列化为 VersionAnalysis pydantic 模型
    """
    # ── 1. 解析补丁内核版本 ────────────────────
    patch_major = patch_commit_info.get("kernel_version_major")
    patch_minor = patch_commit_info.get("kernel_version_minor")

    if patch_major is None or patch_minor is None:
        # 回退：从 kernel_version 字符串解析
        kv = patch_commit_info.get("kernel_version", "")
        if kv:
            kv_parts = kv.split(".")
            try:
                patch_major = int(kv_parts[0])
                patch_minor = int(kv_parts[1]) if len(kv_parts) > 1 else 0
            except (ValueError, IndexError):
                pass

    # ── 2. 解析崩溃内核版本 ────────────────────
    crash_major = 0
    crash_minor = 0
    crash_version_valid = False
    if crash_kernel_version:
        crash_parts = crash_kernel_version.split(".")
        try:
            crash_major = int(crash_parts[0])
            crash_minor = int(crash_parts[1]) if len(crash_parts) > 1 else 0
            # ★ 合理性校验: Linux 内核主版本号范围 2~7
            if 2 <= crash_major <= 7:
                crash_version_valid = True
        except (ValueError, IndexError):
            pass

    # ── 3. 计算距离 ────────────────────────────
    # ★ 当 crash_kernel_version 缺失或无效时，不计算荒谬距离
    if not crash_version_valid:
        patch_ver_str = f"{patch_major}.{patch_minor}.0" if patch_major is not None else None
        return {
            "crash_kernel_version": crash_kernel_version or None,
            "patch_kernel_version": patch_ver_str,
            "version_distance": "Unknown — Crash Kernel Version 未提供",
            "distance_value": -1,  # -1 表示未知
            "compatibility": "Unknown",
            "compatibility_reason": (
                "无法评估版本兼容性，因为崩溃日志中未提供 Kernel Version。"
                "建议在分析时手动输入内核版本以获得准确的版本匹配。"
            ),
            "patch_release_date": patch_date or None,
            "crash_release_date": None,
        }

    if patch_major is None or patch_minor is None:
        version_distance = "Unknown"
        compatibility = "Unknown"
        compatibility_reason = "补丁版本信息缺失，无法评估兼容性"
        distance_value = 0
    else:
        distance = (patch_major - crash_major) * 1000 + (patch_minor - crash_minor)

        if distance == 0:
            version_distance = "Same Version"
            compatibility = "High"
            compatibility_reason = "补丁与崩溃内核版本一致，直接适用"
            distance_value = 0
        elif 1 <= distance <= 2:
            version_distance = f"{distance} Minor Release"
            compatibility = "High"
            compatibility_reason = "补丁版本略新于崩溃内核，大概率可直接 backport"
            distance_value = distance
        elif 3 <= distance <= 5:
            version_distance = f"{distance} Minor Release"
            compatibility = "Medium"
            compatibility_reason = "版本差距较大，需确认补丁依赖的 API 在目标内核中仍存在"
            distance_value = distance
        elif distance > 5:
            version_distance = f"{distance} Minor Release (Cross Minor)"
            compatibility = "Low"
            compatibility_reason = "跨多个 minor release，补丁依赖的内核基础设施可能已变更，需人工审查"
            distance_value = distance
        elif distance < 0:
            version_distance = f"{abs(distance)} Minor Release Behind"
            compatibility = "Medium"
            compatibility_reason = "补丁版本比崩溃内核旧，可能是修复的原始提交，需确认后续是否有补充修复"
            distance_value = abs(distance)
        else:
            version_distance = "Unknown"
            compatibility = "Unknown"
            compatibility_reason = "无法确定版本关系"
            distance_value = 0

    # ── 4. 获取崩溃内核发布日期 ────────────────
    crash_date = None
    if crash_major > 0:
        for (maj, min_), rel_date in _KERNEL_RELEASE_DATES.items():
            if maj == crash_major and min_ == crash_minor:
                crash_date = rel_date
                break

    patch_ver_str = f"{patch_major}.{patch_minor}.0" if patch_major is not None else None

    return {
        "crash_kernel_version": crash_kernel_version or None,
        "patch_kernel_version": patch_ver_str,
        "version_distance": version_distance,
        "distance_value": distance_value,
        "compatibility": compatibility,
        "compatibility_reason": compatibility_reason,
        "patch_release_date": patch_date or None,
        "crash_release_date": crash_date,
    }


__all__ = [
    # 数据结构
    "FilterResult",
    # 基础过滤器
    "filter_by_subsystem",
    "filter_by_bug_type",
    "filter_by_kernel_version",
    "filter_duplicates",
    "filter_by_keywords",
    # 加权
    "boost_security_fixes",
    "weight_by_kernel_version",
    # 流水线
    "apply_filters",
    # 工具
    "build_milvus_filter_expr",
    # ★ 可解释性增强
    "compute_version_analysis",
    # 常量
    "SUBSYSTEM_PATH_MAP",
    "SUBSYSTEM_HIERARCHY",
    "RELATED_SUBSYSTEMS",
    "BUG_TYPE_RELATED_SUBSYSTEMS",
]
