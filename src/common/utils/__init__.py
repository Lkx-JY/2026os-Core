"""工具函数模块 — Utility Functions

提供项目中各模块共用的辅助函数和工具类。

设计要点:
- 纯函数: 无副作用，便于测试
- 类型安全: 完善的类型标注
- 无外部依赖: 核心功能不依赖第三方库
"""

from __future__ import annotations
import hashlib
import re
import time
import json
import os
from typing import List, Dict, Any, Optional, Tuple, Iterator, Callable
from functools import lru_cache


# ============================================================================
# 字符串处理
# ============================================================================

def truncate_text(text: str, max_len: int = 200, suffix: str = "...") -> str:
    """截断文本到指定长度，保留完整单词

    Args:
        text: 原文
        max_len: 最大长度
        suffix: 截断后缀

    Returns:
        截断后的文本
    """
    if len(text) <= max_len:
        return text

    # 尝试在单词边界截断
    truncated = text[:max_len - len(suffix)]
    last_space = truncated.rfind(" ")
    if last_space > max_len // 2:
        truncated = truncated[:last_space]

    return truncated + suffix


def clean_text(text: str, remove_extra_whitespace: bool = True) -> str:
    """清理文本 — 移除控制字符、统一换行

    Args:
        text: 原文
        remove_extra_whitespace: 是否移除多余空白

    Returns:
        清理后的文本
    """
    # 移除 ANSI 转义序列
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    # 统一换行为 \n
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    if remove_extra_whitespace:
        # 压缩多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        # 移除行尾空白
        text = '\n'.join(line.rstrip() for line in text.split('\n'))

    return text.strip()


def extract_commit_hash(text: str) -> Optional[str]:
    """从文本中提取 commit hash (40-hex 或 12-hex)

    Args:
        text: 任意文本

    Returns:
        commit hash 或 None
    """
    # 先尝试 40 位
    match = re.search(r'\b([0-9a-fA-F]{40})\b', text)
    if match:
        return match.group(1)
    # 再尝试 12 位
    match = re.search(r'\b([0-9a-fA-F]{12})\b', text)
    if match:
        return match.group(1)
    return None


def extract_cve_ids(text: str) -> List[str]:
    """从文本中提取 CVE 编号

    Args:
        text: 任意文本

    Returns:
        CVE 编号列表 (去重)
    """
    pattern = r'CVE-\d{4}-\d{4,}'
    matches = re.findall(pattern, text, re.IGNORECASE)
    return list(dict.fromkeys(matches))  # 去重保序


def extract_email(text: str) -> List[str]:
    """从文本中提取邮箱地址

    Args:
        text: 任意文本

    Returns:
        邮箱列表
    """
    pattern = r'[\w.+-]+@[\w-]+\.[\w.-]+'
    return list(dict.fromkeys(re.findall(pattern, text)))


# ============================================================================
# 文件与路径
# ============================================================================

def ensure_dir(path: str) -> str:
    """确保目录存在，不存在则创建

    Args:
        path: 目录路径

    Returns:
        规范化的绝对路径
    """
    os.makedirs(path, exist_ok=True)
    return os.path.abspath(path)


def safe_filename(name: str, max_len: int = 120) -> str:
    """将字符串转换为安全的文件名

    替换非法字符、限制长度。

    Args:
        name: 原始名称
        max_len: 最大长度

    Returns:
        安全的文件名
    """
    # 替换路径分隔符
    name = name.replace('/', '_').replace('\\', '_')
    # 替换其他非法字符
    name = re.sub(r'[<>:"|?*]', '_', name)
    # 去除前后空格和点
    name = name.strip('. ')
    # 截断
    if len(name) > max_len:
        base, ext = os.path.splitext(name)
        base = base[:max_len - len(ext)]
        name = base + ext
    # 空文件名处理
    return name or "unnamed"


def get_file_size_mb(file_path: str) -> float:
    """获取文件大小 (MB)

    Args:
        file_path: 文件路径

    Returns:
        文件大小 (MB)
    """
    try:
        return os.path.getsize(file_path) / (1024 * 1024)
    except OSError:
        return 0.0


# ============================================================================
# 哈希与校验
# ============================================================================

def hash_text(text: str, algorithm: str = "sha256") -> str:
    """计算文本的哈希值

    Args:
        text: 输入文本
        algorithm: 哈希算法 — "md5", "sha1", "sha256"

    Returns:
        十六进制哈希字符串
    """
    h = hashlib.new(algorithm)
    h.update(text.encode('utf-8'))
    return h.hexdigest()


def short_hash(text: str, length: int = 8) -> str:
    """计算文本的短哈希 (用于日志和显示)

    Args:
        text: 输入文本
        length: 输出长度

    Returns:
        短哈希字符串
    """
    return hash_text(text, "md5")[:length]


def generate_id(prefix: str = "", length: int = 12) -> str:
    """生成唯一 ID

    Args:
        prefix: 前缀
        length: 随机部分长度

    Returns:
        唯一 ID 字符串
    """
    import random
    import string
    chars = string.ascii_lowercase + string.digits
    random_part = ''.join(random.choices(chars, k=length))
    return f"{prefix}_{random_part}" if prefix else random_part


# ============================================================================
# 数值计算
# ============================================================================

def safe_divide(a: float, b: float, default: float = 0.0) -> float:
    """安全除法 — 除零返回默认值

    Args:
        a: 被除数
        b: 除数
        default: 除零时的默认返回值

    Returns:
        结果
    """
    return a / b if b != 0 else default


def sigmoid(x: float) -> float:
    """Sigmoid 函数 — 用于分数归一化

    Args:
        x: 输入值

    Returns:
        (0, 1) 之间的值
    """
    import math
    return 1.0 / (1.0 + math.exp(-x))


def normalize_scores(scores: List[float]) -> List[float]:
    """归一化分数列表到 [0, 1]

    Args:
        scores: 分数列表

    Returns:
        归一化后的分数
    """
    if not scores:
        return []

    min_s = min(scores)
    max_s = max(scores)

    if max_s == min_s:
        return [0.5] * len(scores)

    return [(s - min_s) / (max_s - min_s) for s in scores]


def softmax(scores: List[float]) -> List[float]:
    """Softmax 函数 — 转换为概率分布

    Args:
        scores: 分数列表

    Returns:
        概率分布 (总和为 1)
    """
    import math
    if not scores:
        return []

    # 减去最大值防止溢出
    max_s = max(scores)
    exp_scores = [math.exp(s - max_s) for s in scores]
    sum_exp = sum(exp_scores)

    return [e / sum_exp for e in exp_scores]


# ============================================================================
# 时间与日期
# ============================================================================

def format_duration(ms: float) -> str:
    """格式化时间间隔为人类可读格式

    Args:
        ms: 毫秒

    Returns:
        格式化的字符串 (如 "1.23s", "456ms", "12m 34s")
    """
    if ms < 1:
        return f"{ms * 1000:.0f}μs"
    if ms < 1000:
        return f"{ms:.0f}ms"
    if ms < 60000:
        return f"{ms / 1000:.2f}s"

    seconds = ms / 1000
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"


def parse_kernel_version(version_str: str) -> Tuple[int, int, int]:
    """解析 Linux 内核版本号

    Args:
        version_str: 版本字符串 (如 "6.1.0-rc3", "5.15.72")

    Returns:
        (major, minor, patch) 元组
    """
    # 移除前缀和 rc 后缀
    v = re.sub(r'^[^\d]*', '', version_str)
    v = re.sub(r'-rc\d+.*', '', v)
    parts = v.split('.')

    major = int(parts[0]) if len(parts) > 0 else 0
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int(parts[2]) if len(parts) > 2 else 0

    return (major, minor, patch)


def compare_kernel_versions(ver1: str, ver2: str) -> int:
    """比较两个内核版本号

    Args:
        ver1: 版本 1
        ver2: 版本 2

    Returns:
        -1 (ver1 < ver2), 0 (相等), 1 (ver1 > ver2)
    """
    v1 = parse_kernel_version(ver1)
    v2 = parse_kernel_version(ver2)

    for a, b in zip(v1, v2):
        if a < b:
            return -1
        if a > b:
            return 1
    return 0


# ============================================================================
# 批处理
# ============================================================================

def batch_iterate(
    items: List[Any],
    batch_size: int,
) -> Iterator[List[Any]]:
    """将列表切分为固定大小的批次

    Args:
        items: 输入列表
        batch_size: 批次大小

    Returns:
        批次列表

    Example:
        >>> list(batch_iterate([1,2,3,4,5], 2))
        [[1, 2], [3, 4], [5]]
    """
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def chunk_list(lst: List[Any], n_chunks: int) -> List[List[Any]]:
    """将列表均匀分为 n 个块

    Args:
        lst: 输入列表
        n_chunks: 块数

    Returns:
        块列表
    """
    if n_chunks <= 0:
        return [lst]
    k, m = divmod(len(lst), n_chunks)
    return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n_chunks)]


# ============================================================================
# 数据转换
# ============================================================================

def flatten_dict(d: Dict[str, Any], parent_key: str = "", sep: str = ".") -> Dict[str, Any]:
    """展平嵌套字典

    Args:
        d: 嵌套字典
        parent_key: 父键前缀
        sep: 分隔符

    Returns:
        展平后的字典

    Example:
        >>> flatten_dict({"a": {"b": 1, "c": 2}, "d": 3})
        {"a.b": 1, "a.c": 2, "d": 3}
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def safe_json_loads(text: str, default: Any = None) -> Any:
    """安全的 JSON 解析 — 失败时返回默认值

    Args:
        text: JSON 字符串
        default: 解析失败时的默认值

    Returns:
        解析后的对象
    """
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def to_bool(value: Any) -> bool:
    """将各种类型的值转换为布尔值

    支持: bool, int, str ("true"/"yes"/"1"/"on"), None
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1", "on", "y")
    return bool(value)


# ============================================================================
# 调试与开发
# ============================================================================

def get_call_info(depth: int = 1) -> str:
    """获取当前调用位置信息 (调试用)

    Args:
        depth: 调用栈深度

    Returns:
        "filename:lineno:func_name" 格式的字符串
    """
    import inspect
    frame = inspect.currentframe()
    try:
        for _ in range(depth + 1):
            if frame:
                frame = frame.f_back
        if frame:
            return f"{frame.f_code.co_filename}:{frame.f_lineno}:{frame.f_code.co_name}"
    finally:
        del frame
    return "unknown"


def memory_usage_mb() -> float:
    """获取当前进程的内存使用量 (MB)

    Returns:
        内存使用 (MB)
    """
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except (ImportError, AttributeError):
        try:
            import psutil
            return psutil.Process().memory_info().rss / (1024 * 1024)
        except ImportError:
            return 0.0


def profile(func: Optional[Callable] = None, *, n_runs: int = 1):
    """性能分析装饰器

    Args:
        func: 被装饰的函数
        n_runs: 运行次数 (用于测量平均时间)

    Example:
        >>> @profile(n_runs=100)
        ... def my_func():
        ...     pass
    """
    def decorator(f: Callable):
        def wrapper(*args, **kwargs):
            times = []
            result = None
            for _ in range(n_runs):
                t0 = time.perf_counter()
                result = f(*args, **kwargs)
                times.append((time.perf_counter() - t0) * 1000)
            avg_ms = sum(times) / len(times)
            print(f"[PROFILE] {f.__name__}() avg over {n_runs} runs: {avg_ms:.3f}ms")
            return result
        return wrapper

    if func:
        return decorator(func)
    return decorator


# ============================================================================
# 缓存
# ============================================================================

def memoize(maxsize: int = 128):
    """LRU 缓存装饰器

    Args:
        maxsize: 最大缓存条目数
    """
    return lru_cache(maxsize=maxsize)


__all__ = [
    # 字符串
    "truncate_text",
    "clean_text",
    "extract_commit_hash",
    "extract_cve_ids",
    "extract_email",
    # 文件
    "ensure_dir",
    "safe_filename",
    "get_file_size_mb",
    # 哈希
    "hash_text",
    "short_hash",
    "generate_id",
    # 数值
    "safe_divide",
    "sigmoid",
    "normalize_scores",
    "softmax",
    # 时间
    "format_duration",
    "parse_kernel_version",
    "compare_kernel_versions",
    # 批处理
    "batch_iterate",
    "chunk_list",
    # 转换
    "flatten_dict",
    "safe_json_loads",
    "to_bool",
    # 调试
    "get_call_info",
    "memory_usage_mb",
    "profile",
    "memoize",
]
