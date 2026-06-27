"""dmesg 日志解析模块 — 正则定位 + LLM 深度分析

负责从 dmesg 日志中提取 Call Trace 和故障特征，并通过 LLM 进行深度语义分析。

两阶段处理:
Phase 1 — 正则快速定位: 使用简单正则（Regex）快速定位 Call Trace 开始和结束的位置
Phase 2 — LLM 深度分析: 将定位后的文本喂给 LLM，提取规范化描述
    - 结构化特征: {"subsystem": "net", "bug_type": "race_condition"}
    - 根因推断: 从调用栈模式推断根本原因
    - 修复模式识别: 识别需要的修复类型

支持的 Panic 模式:
- Kernel panic - not syncing: ...
- BUG: ...
- Oops: ...
- general protection fault: ...
- KASAN: use-after-free / double-free / slab-out-of-bounds
- WARNING: ...
- INFO: task blocked for more than ...
- NMI watchdog: ...
- list_del corruption ...
- Unable to handle kernel ...
"""

import re
import json
from typing import List, Optional, Tuple, Dict, Any
from ..models import CrashFeature


# ============================================================================
# Phase 1: 正则快速定位 Call Trace
# ============================================================================

# Call Trace 起始标记模式
CALL_TRACE_START_PATTERNS = [
    r"Call Trace:",
    r"call trace:",
    r"Call trace:",
    r"Stack trace:",
    r"Backtrace:",
    r"---\[ end trace [\da-fA-F]+ \]---",
]

# Call Trace 行格式 — 支持多种内核版本和架构:
#   [<ffffffff81001234>] func+0x12/0x34  (x86_64 标准格式)
#   [  245.123472]  func+0x36/0x70       (带时间戳前缀，ARM64/新内核)
#   [  245.123472] [<ffffffff81001234>] func+0x12/0x34  (时间戳+地址)
#   ? func+0x12/0x34                     (不确定帧)
_CALL_TRACE_FUNC_PATTERN = re.compile(
    r'(?:\w+|0x[0-9a-fA-F]+)\+0x[0-9a-fA-F]+/0x[0-9a-fA-F]+'
)
CALL_TRACE_LINE_PATTERN = re.compile(
    r"\[\s*<[\da-fA-F]+>\]\s+"  # [<hex>] 前缀格式
)
# 带时间戳的 Call Trace 行: 以 [时间戳] 开头 + 函数+偏移/大小
_TIMESTAMP_TRACE_PATTERN = re.compile(
    r'^\[\s*[\d]+\.[\d]+\]\s+'  # [  seconds.usecs]
)

# 非 Call Trace 行的结束标记
CALL_TRACE_END_PATTERNS = [
    r"Code: (?:Bad RIP value\.|[0-9a-fA-F].+)",  # Code: 反汇编行
    r"Kernel panic - not syncing:",                # 新的 panic
    r"---\[ end trace",                            # 结束标记
    r"^\s*$",                                      # 连续空行
]
# 注意: RIP: 行已从 CALL_TRACE_END_PATTERNS 移除 —
#   RIP 包含崩溃精确函数名 (如 ext4_writepages+0x1a2/0x3b0)，
#   应作为关键证据提取而非丢弃

# 扩展 Panic/Oops/BUG 匹配模式
PANIC_OPS_PATTERNS = {
    "kernel_panic": re.compile(r"Kernel panic - not syncing:\s*(.*)", re.IGNORECASE),
    "kernel_bug": re.compile(r"(?:kernel\s+)?BUG\s*:\s*(.*)", re.IGNORECASE),
    "kernel_oops": re.compile(r"Oops:\s*(.*)", re.IGNORECASE),
    "general_protection": re.compile(r"general protection fault:\s*(.*)", re.IGNORECASE),
    "null_pointer_deref": re.compile(
        r"unable to handle kernel (?:NULL pointer dereference|paging request)\s*(?:at\s*(\S+))?",
        re.IGNORECASE,
    ),
    "kasan_uaf": re.compile(r"KASAN: use-after-free in\s*(\S+)", re.IGNORECASE),
    "kasan_double_free": re.compile(r"KASAN: double-free or invalid free in\s*(\S+)", re.IGNORECASE),
    "kasan_oob": re.compile(
        r"KASAN: (?:slab|global|stack)-out-of-bounds (?:Read|Write) in\s*(\S+)",
        re.IGNORECASE,
    ),
    "list_corruption": re.compile(r"list_(?:del|add) corruption[.:]\s*(.*)", re.IGNORECASE),
    "hardlockup": re.compile(
        r"(?:NMI watchdog:\s*)?Watchdog detected hard LOCKUP on cpu\s*(\d+)",
        re.IGNORECASE,
    ),
    "softlockup": re.compile(
        r"BUG: soft lockup - CPU#(\d+) stuck for (\d+)s",
        re.IGNORECASE,
    ),
    "hungtask": re.compile(
        r"INFO: task\s*(\S+)\s*blocked for more than (\d+) seconds",
        re.IGNORECASE,
    ),
    "rcu_stall": re.compile(
        r"(?:INFO:\s*)?rcu_(\S+) (?:self-detected stall|detected stalls) on (?:CPU|cpus)",
        re.IGNORECASE,
    ),
    "refcount_underflow": re.compile(r"refcount_t[:.]\s*(underflow|overflow|saturated)", re.IGNORECASE),
    "bug_on": re.compile(r"kernel BUG at (\S+):(\d+)", re.IGNORECASE),
    "warning": re.compile(r"WARNING:\s*(.*)", re.IGNORECASE),
    "machine_check": re.compile(r"Machine Check Exception[.:]\s*(.*)", re.IGNORECASE),
    "divide_error": re.compile(r"divide error:\s*(.*)", re.IGNORECASE),
    "ubsan": re.compile(r"UBSAN:\s*(.*)", re.IGNORECASE),
    "bad_mode": re.compile(r"Bad mode in\s*(\S+)\s*handler detected", re.IGNORECASE),
    "alignment_fault": re.compile(r"Unhandled fault: alignment fault\s*\((\S+)\)", re.IGNORECASE),
    "irq_storm": re.compile(r"irq\s*(\d+):\s*nobody cared", re.IGNORECASE),
    "stack_overflow": re.compile(r"(?:do_IRQ:\s*)?stack (?:overflow|segment):", re.IGNORECASE),
}


def _is_call_trace_line(line: str) -> bool:
    """判断一行是否是有效的调用栈帧

    支持三种格式:
    1. [<ffffffff81001234>] func+0x12/0x34  (x86_64 标准)
    2. [  245.123472]  func+0x36/0x70       (带时间戳, ARM64/新内核)
    3. [  245.123472] [<ffffffff81001234>] func+0x12/0x34  (时间戳+地址)
    4. ? func+0x12/0x34                      (不确定帧)
    """
    stripped = line.strip()
    if not stripped:
        return False
    # 不确定帧
    if stripped.startswith('?'):
        return bool(_CALL_TRACE_FUNC_PATTERN.search(stripped))
    # 带时间戳前缀: 去掉时间戳后检查是否包含函数+偏移
    if _TIMESTAMP_TRACE_PATTERN.match(stripped):
        # 去掉时间戳前缀
        after_ts = _TIMESTAMP_TRACE_PATTERN.sub('', stripped, count=1).strip()
        # 检查是否包含 <hex> 地址格式 或 func+offset/size
        if CALL_TRACE_LINE_PATTERN.search(after_ts):
            return True
        if _CALL_TRACE_FUNC_PATTERN.search(after_ts):
            return True
        return False
    # 标准 [<hex>] 格式
    if CALL_TRACE_LINE_PATTERN.search(stripped):
        return True
    # 纯 func+offset/size 格式 (无地址、无时间戳)
    if _CALL_TRACE_FUNC_PATTERN.search(stripped):
        return True
    return False


def locate_call_trace_bounds(dmesg_content: str) -> Tuple[int, int]:
    """使用正则定位 Call Trace 的开始行号和结束行号

    策略:
    1. 查找 "Call Trace:" 等起始标记
    2. 从起始行开始收集调用栈帧 (支持多格式)
    3. 遇到结束标记或非栈帧行时终止
    4. 如果没有显式标记，查找函数+偏移行作为降级

    Args:
        dmesg_content: 完整的 dmesg 日志文本

    Returns:
        (start_line, end_line) — 0-based 行号，(-1, -1) 表示未找到
    """
    lines = dmesg_content.split('\n')

    # 策略 1: 查找 "Call Trace:" 等起始标记
    for i, line in enumerate(lines):
        stripped = line.strip()
        for pattern in CALL_TRACE_START_PATTERNS:
            if re.search(pattern, stripped):
                start = i
                end = i
                for j in range(i + 1, len(lines)):
                    next_line = lines[j].strip()
                    if _is_call_trace_line(next_line):
                        end = j
                    elif any(re.search(p, next_line) for p in CALL_TRACE_END_PATTERNS):
                        break
                    else:
                        # 非调用栈行，如果已收集了帧则终止
                        if end > start:
                            break
                return (start, end)

    # 策略 2: 降级 — 找第一个包含 func+offset/size 格式的行
    for i, line in enumerate(lines):
        if _is_call_trace_line(line):
            start = i
            end = i
            for j in range(i + 1, len(lines)):
                next_line = lines[j].strip()
                if _is_call_trace_line(next_line):
                    end = j
                elif any(re.search(p, next_line) for p in CALL_TRACE_END_PATTERNS):
                    break
                else:
                    if end > start:
                        break
            return (start, end)

    return (-1, -1)


def extract_call_trace(dmesg_content: str) -> List[str]:
    """使用正则定位并提取 Call Trace

    增强版 — 使用 locate_call_trace_bounds 精确定位边界。

    Args:
        dmesg_content: dmesg 日志内容

    Returns:
        调用栈帧列表，每行为一个栈帧
    """
    start, end = locate_call_trace_bounds(dmesg_content)
    if start < 0 or end < start:
        return []

    lines = dmesg_content.split('\n')
    trace_lines = lines[start:end + 1]

    # 过滤，只保留栈帧行
    call_trace = []
    for line in trace_lines:
        stripped = line.strip()
        if _is_call_trace_line(stripped):
            call_trace.append(stripped)

    return call_trace


def extract_call_trace_region(dmesg_content: str, context_lines: int = 2) -> str:
    """提取 Call Trace 及其上下文文本（用于 LLM 分析）

    不仅提取栈帧，还包含前后各 context_lines 行的上下文，
    以便 LLM 能够理解错误的完整上下文。

    Args:
        dmesg_content: dmesg 日志内容
        context_lines: Call Trace 前后的上下文行数

    Returns:
        Call Trace 及其上下文的完整文本
    """
    start, end = locate_call_trace_bounds(dmesg_content)
    if start < 0:
        return ""

    lines = dmesg_content.split('\n')
    ctx_start = max(0, start - context_lines)
    ctx_end = min(len(lines), end + context_lines + 1)

    return '\n'.join(lines[ctx_start:ctx_end])


def extract_panic_msg(dmesg_content: str) -> str:
    """提取 Panic/Oops/BUG 消息 — 支持 20+ 种内核错误类型

    Args:
        dmesg_content: dmesg 日志内容

    Returns:
        匹配到的 Panic/Oops 消息原文
    """
    for line in dmesg_content.split('\n'):
        for name, pattern in PANIC_OPS_PATTERNS.items():
            match = pattern.search(line)
            if match:
                return match.group(0).strip()
    return ""


def extract_all_panic_info(dmesg_content: str) -> Dict[str, Any]:
    """提取所有可识别的 Panic/Oops/BUG 信息

    返回一个字典，包含所有匹配到的错误类型及其详细信息。

    Args:
        dmesg_content: dmesg 日志内容

    Returns:
        {
            "panic_type": "kernel_panic" | "null_pointer_deref" | ...,
            "panic_msg": "原始消息",
            "panic_details": {"detail_key": "value", ...},
            "matched_patterns": ["pattern1", "pattern2", ...],
        }
    """
    result: Dict[str, Any] = {
        "panic_type": "unknown",
        "panic_msg": "",
        "panic_details": {},
        "matched_patterns": [],
    }

    for line in dmesg_content.split('\n'):
        for name, pattern in PANIC_OPS_PATTERNS.items():
            match = pattern.search(line)
            if match:
                result["panic_type"] = result["panic_type"] if result["panic_msg"] else name
                result["panic_msg"] = result["panic_msg"] or match.group(0).strip()
                result["matched_patterns"].append(name)
                # 提取详细匹配组
                for i, val in enumerate(match.groups()):
                    if val:
                        result["panic_details"][f"group_{i}"] = val

    return result


def parse_dmesg(dmesg_content: str) -> CrashFeature:
    """解析 dmesg 内容并提取特征 — 增强版

    两阶段处理:
    1. 正则快速定位 Call Trace + Panic 消息
    2. 关键词匹配初步识别 subsystem 和 bug_type

    Args:
        dmesg_content: dmesg 日志内容

    Returns:
        CrashFeature — 包含 call_trace, subsystem, bug_type, panic_msg 等
    """
    feature = CrashFeature()

    # Phase 1: 正则快速定位
    feature.call_trace = extract_call_trace(dmesg_content)
    panic_info = extract_all_panic_info(dmesg_content)
    feature.panic_msg = panic_info["panic_msg"]
    feature.extra_info["panic_type"] = panic_info["panic_type"]
    feature.extra_info["panic_details"] = panic_info["panic_details"]
    feature.extra_info["matched_patterns"] = panic_info["matched_patterns"]

    # 提取 Call Trace 区域（用于 LLM 分析）
    trace_region = extract_call_trace_region(dmesg_content)
    feature.extra_info["call_trace_region"] = trace_region

    # Phase 2: 关键词初步识别 subsystem 和 bug_type
    feature.subsystem = _detect_subsystem_from_dmesg(dmesg_content)
    feature.bug_type = _detect_bug_type_from_dmesg(dmesg_content)

    # ★ 提取内核版本 — 支持多种格式:
    #   "Linux version 5.4.0-150-generic" (标准)
    #   "Tainted: G  OE  5.4.0-150-generic #167-Ubuntu" (嵌入在 CPU/Tainted 行)
    #   "Linux version 6.1.0-rc3+" (rc/next 版本)
    feature.kernel_version = _extract_kernel_version(dmesg_content)

    # ★ 提取 RIP 函数名 — 崩溃发生的精确位置
    rip_func = _extract_rip_function(dmesg_content)
    if rip_func:
        feature.extra_info["rip_function"] = rip_func

    # 提取已加载模块
    module_pattern = re.findall(r"(\S+): loading out-of-tree module", dmesg_content)
    if module_pattern:
        feature.modules = module_pattern

    return feature


# ============================================================================
# Phase 2: LLM 深度分析
# ============================================================================

# LLM 深度分析的系统提示
DEEP_ANALYSIS_SYSTEM_PROMPT = """You are a Linux kernel debugging expert. Analyze the kernel crash log and extract structured information.

Output ONLY valid JSON with this exact structure:
{
    "subsystem": "<one of: mm, fs, net, block, kernel, drivers, arch, security, bpf, cgroup, rcu, kvm, crypto, unknown>",
    "bug_type": "<one of: use_after_free, null_pointer, buffer_overflow, memory_leak, deadlock, race_condition, integer_overflow, out_of_bound, double_free, memory_corruption, hang, crash, security, unknown>",
    "severity": "<critical|high|medium|low>",
    "root_cause_hypothesis": "<1-2 sentence hypothesis about the root cause>",
    "trigger_function": "<function name where the crash likely originated>",
    "confidence": <0.0 to 1.0>,
    "keywords": ["<relevant kernel terms>"],
    "fix_type_hints": ["<one or more of: lock_added, refcount_fix, rcu_fix, null_check, bound_check, error_handling>"]
}

Rules:
- subsystem: Infer from file paths (mm/slab.c → mm, net/tcp.c → net), function names (ext4_* → fs, bpf_* → bpf), or error context
- bug_type: Infer from error message patterns AND call trace function patterns
- severity: critical for hard lockup/MCE/kernel panic, high for UAF/null pointer/GPF, medium for soft lockup/hung task, low for warnings
- confidence: Be honest about uncertainty. Clear error message + call trace → 0.8-0.95. Ambiguous → 0.3-0.5
- fix_type_hints: Infer from the nature of the bug (e.g., list corruption → lock_added, UAF → refcount_fix+rcu_fix)"""


def build_llm_analysis_prompt(
    dmesg_content: str,
    call_trace: List[str],
    panic_msg: str,
    trace_region: str,
) -> str:
    """构造发送给 LLM 的分析提示

    将定位后的 Call Trace 文本和上下文喂给 LLM，引导其提取结构化信息。

    Args:
        dmesg_content: 完整的 dmesg 日志（可能被截断）
        call_trace: 已提取的调用栈帧
        panic_msg: 已提取的 Panic 消息
        trace_region: Call Trace 及其上下文

    Returns:
        构造好的 LLM 提示文本
    """
    # 限制输入长度
    dmesg_snippet = dmesg_content[-3000:] if len(dmesg_content) > 3000 else dmesg_content
    trace_text = '\n'.join(call_trace[-30:])  # 最近的 30 帧

    prompt = f"""## Kernel Crash Log (last {min(len(dmesg_content), 3000)} chars):

```
{dmesg_snippet}
```

## Error/Panic Message:
{panic_msg or '(no explicit panic message found)'}

## Call Trace (last {min(len(call_trace), 30)} frames):
```
{trace_text}
```

## Call Trace Context:
```
{trace_region}
```

Analyze the above kernel crash and extract the structured information as specified."""
    return prompt


def llm_deep_analysis(
    dmesg_content: str,
    model_name: str = "deepseek-chat",
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> Dict[str, Any]:
    """使用 LLM 对 dmesg 进行深度分析

    将正则定位后的 Call Trace 文本喂给 LLM，提取规范化的结构化描述。
    输出格式: {"subsystem": "net", "bug_type": "race_condition", ...}

    这是 dmesg 深度分析的核心函数。

    Args:
        dmesg_content: dmesg 日志内容
        model_name: LLM 模型名称 (deepseek-chat / qwen2.5 / gpt-4)
        temperature: LLM 温度参数
        max_tokens: 最大输出 token 数

    Returns:
        {
            "subsystem": str,
            "bug_type": str,
            "severity": str,
            "root_cause_hypothesis": str,
            "trigger_function": str,
            "confidence": float,
            "keywords": List[str],
            "fix_type_hints": List[str],
        }

    Example:
        >>> analysis = llm_deep_analysis(dmesg_log)
        >>> print(analysis["subsystem"])   # "net"
        >>> print(analysis["bug_type"])    # "race_condition"
        >>> print(analysis["confidence"])   # 0.85
    """
    # Phase 1: 正则定位
    call_trace = extract_call_trace(dmesg_content)
    panic_msg = extract_panic_msg(dmesg_content)
    trace_region = extract_call_trace_region(dmesg_content)

    # 如果没有任何可分析的内容，返回空结果
    if not call_trace and not panic_msg:
        return {
            "subsystem": "unknown",
            "bug_type": "unknown",
            "severity": "low",
            "root_cause_hypothesis": "No call trace or panic message found in dmesg",
            "trigger_function": "",
            "confidence": 0.1,
            "keywords": [],
            "fix_type_hints": [],
        }

    # Phase 2: 构造提示并调用 LLM
    prompt = build_llm_analysis_prompt(
        dmesg_content, call_trace, panic_msg, trace_region,
    )

    try:
        raw_response = _call_llm_for_analysis(
            system_prompt=DEEP_ANALYSIS_SYSTEM_PROMPT,
            user_prompt=prompt,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        result = _parse_llm_analysis_response(raw_response)
        return result
    except Exception as e:
        # LLM 调用失败时降级到关键词规则
        print(f"LLM deep analysis failed: {e}, falling back to keyword rules")
        return _fallback_analysis(dmesg_content, call_trace, panic_msg)


def _call_llm_for_analysis(
    system_prompt: str,
    user_prompt: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """调用 LLM API 进行分析 — 委托给统一的 LLMClient"""
    try:
        from ...generator.llm import get_llm_client
        return get_llm_client().chat(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model_name,
        )
    except Exception as e:
        raise RuntimeError(f"LLM API call failed: {e}")


def _parse_llm_analysis_response(response: str) -> Dict[str, Any]:
    """解析 LLM 返回的 JSON 响应"""
    # 尝试直接解析 JSON
    try:
        result = json.loads(response)
        return _validate_llm_analysis(result)
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 JSON 块
    json_match = re.search(r'\{[\s\S]*\}', response)
    if json_match:
        try:
            result = json.loads(json_match.group())
            return _validate_llm_analysis(result)
        except json.JSONDecodeError:
            pass

    # 无法解析
    return {
        "subsystem": "unknown",
        "bug_type": "unknown",
        "severity": "low",
        "root_cause_hypothesis": f"Failed to parse LLM response: {response[:200]}",
        "trigger_function": "",
        "confidence": 0.1,
        "keywords": [],
        "fix_type_hints": [],
        "raw_response": response[:500],
    }


def _validate_llm_analysis(result: Dict[str, Any]) -> Dict[str, Any]:
    """验证和规范化 LLM 分析结果"""
    valid_subsystems = {
        "mm", "fs", "net", "block", "kernel", "drivers",
        "arch", "security", "bpf", "cgroup", "rcu", "kvm",
        "crypto", "power", "unknown",
    }
    valid_bug_types = {
        "use_after_free", "null_pointer", "buffer_overflow",
        "memory_leak", "deadlock", "race_condition", "integer_overflow",
        "out_of_bound", "double_free", "memory_corruption",
        "hang", "crash", "security", "concurrency",
        "regression", "resource_leak", "logic_error", "unknown",
    }
    valid_severities = {"critical", "high", "medium", "low"}
    valid_fix_hints = {
        "lock_added", "refcount_fix", "rcu_fix",
        "null_check", "bound_check", "error_handling",
    }

    return {
        "subsystem": result.get("subsystem", "unknown")
        if result.get("subsystem") in valid_subsystems else "unknown",
        "bug_type": result.get("bug_type", "unknown")
        if result.get("bug_type") in valid_bug_types else "unknown",
        "severity": result.get("severity", "medium")
        if result.get("severity") in valid_severities else "medium",
        "root_cause_hypothesis": str(result.get("root_cause_hypothesis", ""))[:500],
        "trigger_function": str(result.get("trigger_function", ""))[:200],
        "confidence": float(min(max(result.get("confidence", 0.5), 0.0), 1.0)),
        "keywords": list(result.get("keywords", [])[:10]),
        "fix_type_hints": [
            h for h in result.get("fix_type_hints", [])
            if h in valid_fix_hints
        ][:5],
    }


def _fallback_analysis(
    dmesg_content: str,
    call_trace: List[str],
    panic_msg: str,
) -> Dict[str, Any]:
    """LLM 不可用时的降级分析 — 基于关键词规则"""
    feature = parse_dmesg(dmesg_content)

    severity = "medium"
    panic_lower = panic_msg.lower()
    if any(w in panic_lower for w in ["hard lockup", "machine check", "kernel panic"]):
        severity = "critical"
    elif any(w in panic_lower for w in ["use-after-free", "use after free", "double free",
                                         "general protection", "bug:", "null pointer"]):
        severity = "high"
    elif any(w in panic_lower for w in ["soft lockup", "hung", "blocked for more"]):
        severity = "medium"

    return {
        "subsystem": feature.subsystem,
        "bug_type": feature.bug_type,
        "severity": severity,
        "root_cause_hypothesis": f"Fallback analysis: {panic_msg[:200]}",
        "trigger_function": call_trace[0] if call_trace else "",
        "confidence": 0.4,
        "keywords": [feature.subsystem, feature.bug_type],
        "fix_type_hints": [],
    }


# ============================================================================
# 关键词识别辅助函数
# ============================================================================

def _detect_subsystem_from_dmesg(dmesg_content: str) -> str:
    """从 dmesg 内容中识别内核子系统"""
    dmesg_lower = dmesg_content.lower()

    subsystem_hints = [
        ("mm", ["mm/", "slab", "page_alloc", "folio", "vm_area", "swap", "kswapd",
                "oom", "out of memory", "memcg", "cma", "hugepage", "hugetlb"]),
        ("fs", ["fs/", "ext4", "xfs", "btrfs", "vfs", "inode", "dentry",
                "nfs", "cifs", "overlay", "fuse", "writeback"]),
        ("net", ["net/", "tcp", "udp", "socket", "skb", "dev_queue",
                 "napi", "netif", "bridge", "iptables", "nf_", "conntrack"]),
        ("block", ["block/", "blk_", "bio_", "request_queue", "scsi", "nvme", "dm_"]),
        ("kernel", ["kernel/", "sched", "rcu", "irq", "timer", "workqueue",
                    "futex", "signal", "syscall"]),
        ("drivers", ["drivers/", "pci", "usb", "i2c", "spi", "dma", "acpi",
                     "gpio", "regulator", "clk_"]),
        ("arch", ["arch/", "x86", "arm64", "entry_", "syscall", "page_fault",
                  "do_page_fault", "handle_mm_fault"]),
        ("bpf", ["bpf", "bpf_prog", "bpf_check"]),
        ("security", ["security/", "selinux", "apparmor", "lsm"]),
        ("cgroup", ["cgroup", "cgroupv2", "cgroupv1"]),
        ("kvm", ["kvm", "kvm_arch", "kvm_vcpu"]),
    ]

    for subsys, hints in subsystem_hints:
        if any(hint in dmesg_lower for hint in hints):
            return subsys
    return "unknown"


def _detect_bug_type_from_dmesg(dmesg_content: str) -> str:
    """从 dmesg 内容中识别 Bug 类型"""
    dmesg_lower = dmesg_content.lower()

    bug_type_hints = [
        ("use_after_free", ["use-after-free", "use after free", "kasan: use-after-free"]),
        ("null_pointer", ["null pointer dereference", "null pointer", "unable to handle kernel null"]),
        ("buffer_overflow", ["buffer overflow", "stack overflow", "buffer overrun"]),
        ("memory_leak", ["out of memory", "oom", "memory leak", "invoked oom-killer"]),
        ("deadlock", ["deadlock", "circular locking dependency", "possible recursive locking",
                      "lockdep", "spinlock", "mutex_lock"]),
        ("race_condition", ["race condition", "race window", "race"]),
        ("double_free", ["double free", "double-free", "kasan: double-free"]),
        ("out_of_bound", ["out-of-bounds", "out of bounds", "kasan: slab-out-of-bounds",
                          "kasan: global-out-of-bounds"]),
        ("memory_corruption", ["list_del corruption", "list_add corruption",
                               "memory corruption", "list corruption"]),
        ("hang", ["hard lockup", "soft lockup", "hung task", "blocked for more",
                  "rcu_sched stall", "nmi watchdog"]),
        ("crash", ["kernel panic", "general protection fault", "kernel bug",
                   "machine check", "oops:", "divide error"]),
        ("concurrency", ["race", "lock contention", "synchronization"]),
        ("security", ["cve", "spectre", "meltdown", "retpoline"]),
    ]

    for bug_type, hints in bug_type_hints:
        if any(hint in dmesg_lower for hint in hints):
            # 标准化为 taxonomy.BugType
            from ...common.taxonomy import normalize_bug_type
            return normalize_bug_type(bug_type).value
    return "unknown"


# ============================================================================
# 完整的 LLM 增强解析
# ============================================================================

def parse_dmesg_with_llm(
    dmesg_content: str,
    use_llm: bool = True,
    model_name: str = "deepseek-chat",
) -> CrashFeature:
    """LLM 增强的完整 dmesg 解析

    两阶段处理:
    Phase 1: 正则快速定位 Call Trace 和 Panic 消息
    Phase 2: LLM 深度分析提取规范化描述

    结果融入 CrashFeature，供下游 rootcause 分析。

    Args:
        dmesg_content: dmesg 日志内容
        use_llm: 是否启用 LLM 深度分析 (False 时只做正则解析)
        model_name: LLM 模型名称

    Returns:
        CrashFeature — 包含正则提取 + LLM 分析结果

    Example:
        >>> feature = parse_dmesg_with_llm(dmesg_log)
        >>> print(feature.subsystem)    # "net" (LLM 或关键词识别)
        >>> print(feature.bug_type)     # "race_condition"
        >>> print(feature.extra_info["llm_analysis"]["confidence"])  # 0.85
    """
    # Phase 1: 正则快速定位
    feature = parse_dmesg(dmesg_content)

    # Phase 2: LLM 深度分析
    if use_llm:
        try:
            llm_result = llm_deep_analysis(
                dmesg_content,
                model_name=model_name,
            )

            # 融入 LLM 分析结果
            feature.extra_info["llm_analysis"] = llm_result

            # LLM 置信度高时覆盖关键词推断结果
            if llm_result.get("confidence", 0) >= 0.5:
                if llm_result.get("subsystem", "unknown") != "unknown":
                    feature.subsystem = llm_result["subsystem"]
                if llm_result.get("bug_type", "unknown") != "unknown":
                    feature.bug_type = llm_result["bug_type"]

            # 附加 LLM 推断的修复提示
            feature.extra_info["llm_fix_type_hints"] = llm_result.get("fix_type_hints", [])
            feature.extra_info["llm_root_cause_hypothesis"] = llm_result.get(
                "root_cause_hypothesis", ""
            )
            feature.extra_info["llm_keywords"] = llm_result.get("keywords", [])

        except Exception as e:
            feature.extra_info["llm_error"] = str(e)

    return feature


# ============================================================================
# 辅助提取函数
# ============================================================================

def _extract_kernel_version(dmesg_content: str) -> str:
    """从 dmesg 中提取内核版本 — 支持多种格式

    支持的格式:
    1. "Linux version 5.4.0-150-generic (buildd@...) #167-Ubuntu ..."
    2. "Linux version 6.1.0-rc3+"
    3. "CPU: ... Tainted: G  OE  5.4.0-150-generic #167-Ubuntu" (嵌入式)
    4. "Kernel: 5.15.0-91-generic x86_64"
    """
    patterns = [
        # 标准格式: Linux version X.Y.Z-variant
        re.compile(r"Linux version (\d+\.\d+[\.\d]*[-\w+]*)", re.IGNORECASE),
        # Tainted 嵌入格式: Tainted: ... X.Y.Z-version #N
        re.compile(r"Tainted:\s*.*?\s+(\d+\.\d+[\.\d]*[-\w]*)", re.IGNORECASE),
        # Kernel: X.Y.Z 格式
        re.compile(r"Kernel:\s*(\d+\.\d+[\.\d]*[-\w]*)", re.IGNORECASE),
    ]

    for pat in patterns:
        match = pat.search(dmesg_content)
        if match:
            return match.group(1)
    return ""


def _extract_rip_function(dmesg_content: str) -> str:
    """从 dmesg 中提取 RIP 指令指针指向的函数名

    RIP 行格式: RIP: 0010:ext4_writepages+0x1a2/0x3b0
    包含崩溃发生的精确函数名和偏移，是检索的关键信号。

    Returns:
        函数名 (如 "ext4_writepages") 或空字符串
    """
    # RIP: xxxx:func_name+offset/size
    rip_match = re.search(
        r'RIP:\s*(?:[0-9a-fA-F]+:)?(\w+)\+0x[0-9a-fA-F]+/0x[0-9a-fA-F]+',
        dmesg_content, re.IGNORECASE
    )
    if rip_match:
        return rip_match.group(1)
    return ""


__all__ = [
    # Phase 1 — 正则定位
    "locate_call_trace_bounds",
    "extract_call_trace",
    "extract_call_trace_region",
    "extract_panic_msg",
    "extract_all_panic_info",
    "parse_dmesg",
    # Phase 2 — LLM 深度分析
    "DEEP_ANALYSIS_SYSTEM_PROMPT",
    "build_llm_analysis_prompt",
    "llm_deep_analysis",
    # 完整解析
    "parse_dmesg_with_llm",
    # 辅助
    "PANIC_OPS_PATTERNS",
]
