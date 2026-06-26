"""内核版本元数据解析模块 — Kernel Version Metadata Resolver.

基于 Linux 内核正式版本的发布日期映射表，通过 commit 日期推断所属内核版本。
用于离线索引时为每条 commit 标注 `kernel_version` 系列字段。

核心映射: (major, minor) → release_date
策略: commit_date 之前已发布的最新版本 + 1 个小版本 = 首次包含此 commit 的版本

设计依据:
- Linux 内核大约每 9-10 周发布一个新版本
- 合并窗口 (merge window) 持续约 2 周
- commit 的 author_date 在版本 V 的合并窗口内 → commit 首次出现在版本 V 中

References:
- https://www.kernel.org/category/releases.html
- https://en.wikipedia.org/wiki/Linux_kernel_version_history
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple
from datetime import date as DateType, timedelta


# ============================================================================
# 内核版本发布日期映射表
# 键: (major, minor)  值: 发布日期 (YYYY-MM-DD)
# 覆盖 4.9 ~ 6.12，来源为 kernel.org 官方发布公告
# ============================================================================

KERNEL_RELEASE_DATES: Dict[Tuple[int, int], str] = {
    # Linux 6.x
    (6, 12): "2024-12-01",
    (6, 11): "2024-09-15",
    (6, 10): "2024-07-14",
    (6, 9):  "2024-05-12",
    (6, 8):  "2024-03-10",
    (6, 7):  "2024-01-07",
    (6, 6):  "2023-10-29",
    (6, 5):  "2023-08-27",
    (6, 4):  "2023-06-25",
    (6, 3):  "2023-04-23",
    (6, 2):  "2023-02-19",
    (6, 1):  "2022-12-11",
    (6, 0):  "2022-10-02",
    # Linux 5.x
    (5, 19): "2022-07-31",
    (5, 18): "2022-05-22",
    (5, 17): "2022-03-20",
    (5, 16): "2022-01-09",
    (5, 15): "2021-10-31",
    (5, 14): "2021-08-29",
    (5, 13): "2021-06-27",
    (5, 12): "2021-04-25",
    (5, 11): "2021-02-14",
    (5, 10): "2020-12-13",
    (5, 9):  "2020-10-11",
    (5, 8):  "2020-08-02",
    (5, 7):  "2020-05-31",
    (5, 6):  "2020-03-29",
    (5, 5):  "2020-01-26",
    (5, 4):  "2019-11-24",
    (5, 3):  "2019-09-15",
    (5, 2):  "2019-07-07",
    (5, 1):  "2019-05-05",
    (5, 0):  "2019-03-03",
    # Linux 4.x (LTS 系列)
    (4, 20): "2018-12-23",
    (4, 19): "2018-10-22",
    (4, 18): "2018-08-12",
    (4, 17): "2018-06-03",
    (4, 16): "2018-04-01",
    (4, 15): "2018-01-28",
    (4, 14): "2017-11-12",
    (4, 13): "2017-09-03",
    (4, 12): "2017-07-02",
    (4, 11): "2017-04-30",
    (4, 10): "2017-02-19",
    (4, 9):  "2016-12-11",
}

# 按发布时间从新到旧排序的版本列表（预计算，加速查找）
_SORTED_RELEASES: Tuple[Tuple[Tuple[int, int], str], ...] = tuple(
    sorted(KERNEL_RELEASE_DATES.items(), key=lambda x: x[1], reverse=True)
)


def resolve_version_from_date(date_str: str) -> Optional[Dict[str, object]]:
    """通过 commit 日期推断其首次出现的内核版本。

    策略：
    1. 找到 commit_date 之前已发布的最新版本 (prev_major, prev_minor)
    2. commit 属于下一个版本 (prev_major, prev_minor + 1)
       （因为 Linux 的合并窗口在上一版本发布后立即开始）
    3. 如果 prev_version 是某大版本的最后一版（如 5.19 → 6.0），则跨越主版本号

    Args:
        date_str: commit 日期字符串 (YYYY-MM-DD 格式或其前缀)

    Returns:
        {
            "kernel_version": "6.1.0",
            "kernel_version_major": 6,
            "kernel_version_minor": 1,
            "kernel_version_patch": 0,
        }
        如果日期早于已知最早版本，返回 None

    Examples:
        >>> resolve_version_from_date("2023-01-15")
        {"kernel_version": "6.2.0", "kernel_version_major": 6, ...}
        # v6.1 发布于 2022-12-11，commit 在之后 → 属于 v6.2
    """
    if not date_str:
        return None

    commit_date_raw = date_str[:10]  # YYYY-MM-DD

    try:
        DateType.fromisoformat(commit_date_raw)
    except (ValueError, TypeError):
        return None

    # 找到 commit 之后发布的第一个版本
    # 即: release_date > commit_date 的最小版本
    for (maj, min_), rel_date in _SORTED_RELEASES:
        if rel_date < commit_date_raw:
            # rel_date 是 commit 之前的最新已发布版本
            # commit 属于下一版本
            next_major, next_minor = _next_version(maj, min_)
            return {
                "kernel_version": f"{next_major}.{next_minor}.0",
                "kernel_version_major": next_major,
                "kernel_version_minor": next_minor,
                "kernel_version_patch": 0,
            }

    # commit 日期早于最早已知版本 → 使用最早版本
    oldest = _SORTED_RELEASES[-1]
    oldest_major, oldest_minor = oldest[0]
    return {
        "kernel_version": f"{oldest_major}.{oldest_minor}.0",
        "kernel_version_major": oldest_major,
        "kernel_version_minor": oldest_minor,
        "kernel_version_patch": 0,
    }


def _next_version(major: int, minor: int) -> Tuple[int, int]:
    """计算下一个内核版本号。

    处理主版本号跨越：5.19 → 6.0, 6.x 最后 → 7.0
    """
    # Linux 通常在每个大版本的 minor 达到 ~19-20 时跳到下一个 major
    # 但实际上 6.x 在 6.12 后直接到了 6.13+
    # 这里做合理近似：minor >= 19 时才考虑跨越
    if minor >= 19:
        return (major + 1, 0)
    return (major, minor + 1)


def normalize_kernel_version(raw_version: str) -> Optional[str]:
    """将各种格式的内核版本字符串归一化为 'major.minor.0'。

    只保留 major.minor 精度，patch 位固定为 0。
    因为分发版的 patch 号（如 Debian 的 ABI 号 6.1.66-1）不等于上游 patch 级别。

    支持的格式:
        "6.1.0-15-amd64"     → "6.1.0"
        "6.1.66-1"           → "6.1.0"
        "5.15.72"            → "5.15.0"
        "Linux 6.1.0-rc5"    → "6.1.0"
        "Not tainted 6.1.66" → "6.1.0"
        "6.1"                → "6.1.0"

    Args:
        raw_version: 原始版本字符串

    Returns:
        归一化版本号 "major.minor.0"，解析失败返回 None
    """
    import re as _re

    if not raw_version or not isinstance(raw_version, str):
        return None

    # 匹配 major.minor[.anything] 模式
    match = _re.search(r'(\d+)\.(\d+)', raw_version)
    if not match:
        return None

    major = int(match.group(1))
    minor = int(match.group(2))

    # 过滤明显不是版本号的匹配
    if major > 99 or minor > 99:
        return None

    # 统一归一化为 major.minor.0
    return f"{major}.{minor}.0"


def parse_version_tuple(version_str: str) -> Optional[Tuple[int, int, int]]:
    """将版本字符串解析为 (major, minor, patch) 元组。

    Args:
        version_str: "6.1.0" 或 "6.1" 等

    Returns:
        (6, 1, 0) 或 None
    """
    parts = version_str.strip().split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)
    except (ValueError, IndexError):
        return None


def version_distance(
    v1_major: int, v1_minor: int,
    v2_major: int, v2_minor: int,
) -> int:
    """计算两个版本之间的"距离"。

    距离 = (主版本差 * 1000) + (次版本差)
    正数表示 v1 比 v2 新，负数表示 v1 比 v2 旧。

    Examples:
        >>> version_distance(6, 1, 6, 1)   # 6.1 vs 6.1 → 0
        >>> version_distance(6, 5, 6, 1)   # 6.5 vs 6.1 → 4
        >>> version_distance(5, 15, 6, 1)  # 5.15 vs 6.1 → -986
    """
    return (v1_major - v2_major) * 1000 + (v1_minor - v2_minor)


def get_version_weight(
    target_major: int,
    target_minor: int,
    commit_major: int,
    commit_minor: int,
) -> float:
    """根据版本距离计算加权系数。

    设计原则:
    - 精确同版本 → 最强信号 (可能是直接修复)
    - 同主版本的近未来版本 → 较强信号 (Fixes backport 候选)
    - 跨主版本或差距很大 → 弱信号 (可能不兼容)

    Args:
        target_major: 目标内核主版本号 (来自宕机日志)
        target_minor: 目标内核次版本号
        commit_major: commit 所属主版本号 (来自元数据)
        commit_minor: commit 所属次版本号

    Returns:
        权重系数 (0.0 ~ 2.0)
    """
    dist = version_distance(commit_major, commit_minor, target_major, target_minor)

    if dist == 0:
        return 1.30       # 精确同版本 — 最强信号
    elif 1 <= dist <= 2:
        return 1.15       # 近未来 — Fixes backport 候选
    elif 3 <= dist <= 5:
        return 1.00       # 中期 — 中性
    elif dist >= 6:
        return 0.70       # 远期 — 弱信号
    elif dist < 0:
        return 1.00       # 老版本 — 中性 (可能是 backport 来源)
    return 0.90           # 无法判断 — 略降


# ============================================================================
# 公开 API
# ============================================================================

__all__ = [
    "KERNEL_RELEASE_DATES",
    "resolve_version_from_date",
    "normalize_kernel_version",
    "parse_version_tuple",
    "version_distance",
    "get_version_weight",
]
