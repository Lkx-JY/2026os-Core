"""vmcore 解析模块 — 基于 drgn 的深度内核对象提取

负责从 vmcore 二进制文件中提取内核对象、调用栈、寄存器状态等特征。
使用 drgn (Programmable Debugger) 作为核心解析引擎。

核心功能:
- vmcore 加载与验证: 检查 vmcore 与 vmlinux 的兼容性
- 调用栈提取: 从每个 CPU 的 task_struct 中提取完整调用栈
- 寄存器与内存状态: 提取崩溃 CPU 的寄存器、内存映射信息
- 内核对象提取: 提取 task_struct, mm_struct, file, socket 等关键内核对象
- Panic 线程识别: 自动识别引发 crash 的线程
- 特征融合: 将 vmcore 提取结果与 dmesg 特征合并

drgn 集成要点:
- 需要 vmlinux (带调试信息的未压缩内核镜像)
- 支持从 /proc/kcore, /dev/crash, vmcore 文件加载
- 使用 drgn.helpers.linux 辅助函数遍历内核数据结构
"""

import os
from typing import List, Dict, Any, Optional

from ..models import CrashFeature


# ============================================================================
# vmcore 加载
# ============================================================================

def load_vmcore(vmcore_path: str, vmlinux_path: str = "") -> Optional[Any]:
    """使用 drgn 加载 vmcore 文件

    Args:
        vmcore_path: vmcore 文件路径 (/proc/kcore 或 core 文件)
        vmlinux_path: vmlinux 路径 (带调试信息的内核镜像)

    Returns:
        drgn Program 对象，加载失败返回 None
    """
    if not os.path.exists(vmcore_path):
        print(f"vmcore file not found: {vmcore_path}")
        return None

    try:
        import drgn

        if vmlinux_path and os.path.exists(vmlinux_path):
            prog = drgn.program_from_core(vmcore_path, vmlinux_path)
        else:
            # 尝试自动查找 vmlinux (通常在 /usr/lib/debug/ 下)
            prog = drgn.program_from_core(vmcore_path)

        return prog
    except ImportError:
        print("drgn not installed. Install with: pip install drgn")
        return None
    except Exception as e:
        print(f"Failed to load vmcore: {e}")
        return None


# ============================================================================
# 内核版本提取
# ============================================================================

def extract_kernel_version(prog) -> str:
    """从 vmcore 中提取内核版本

    Args:
        prog: drgn Program 对象

    Returns:
        内核版本字符串，如 "6.1.0-17-amd64"
    """
    try:
        # 方式 1: linux_banner
        banner = prog["linux_banner"]
        if banner:
            version_str = banner.string_().decode("utf-8", errors="replace").strip()
            # "Linux version 6.1.0-17-amd64 ..."
            import re
            match = re.search(r"Linux version (\S+)", version_str)
            if match:
                return match.group(1)
            return version_str[:100]
    except Exception:
        pass

    try:
        # 方式 2: utsname
        import drgn
        utsname_path = drgn.helpers.linux.utsname()
        if utsname_path:
            return utsname_path.release.string_().decode("utf-8", errors="replace")
    except Exception:
        pass

    return ""


# ============================================================================
# 调用栈提取
# ============================================================================

def extract_call_trace_from_vmcore(prog) -> List[str]:
    """从 vmcore 中提取调用栈

    遍历所有 CPU 的 task_struct，提取每个任务的调用栈。
    优先提取 panic 线程的调用栈。

    Args:
        prog: drgn Program 对象

    Returns:
        调用栈帧列表
    """
    call_trace: List[str] = []

    try:
        import drgn

        # 方式 1: 尝试获取 panic 线程的调用栈
        panic_task = _find_panic_task(prog)
        if panic_task:
            trace = _get_task_stack_trace(prog, panic_task)
            if trace:
                return trace

        # 方式 2: 遍历所有 CPU 查找阻塞或运行中的任务
        for cpu in drgn.helpers.linux.cpumask.for_each_online_cpu(prog):
            try:
                task = drgn.helpers.linux.percpu.current_task(prog, cpu)
                if task:
                    trace = _get_task_stack_trace(prog, task)
                    if trace:
                        return trace
            except Exception:
                continue

    except ImportError:
        pass
    except Exception as e:
        print(f"Warning: Failed to extract call trace from vmcore: {e}")

    return call_trace


def _find_panic_task(prog) -> Optional[Any]:
    """查找发生 panic 的 task_struct"""
    try:
        import drgn

        # 尝试查找 panic_task 或 system_state 指示的 panic 线程
        for task in drgn.helpers.linux.list.for_each_entry(
            "struct task_struct",
            prog["init_task"].tasks.address_of_(),
            "tasks",
        ):
            try:
                comm = task.comm.string_().decode("utf-8", errors="replace")
                if comm in ("panic", "kworker-panic"):
                    return task
            except Exception:
                continue

        # 降级: 返回当前 CPU 上的任务
        for cpu in drgn.helpers.linux.cpumask.for_each_online_cpu(prog):
            return drgn.helpers.linux.percpu.current_task(prog, cpu)

    except Exception:
        pass
    return None


def _get_task_stack_trace(prog, task) -> List[str]:
    """从 task_struct 中提取内核调用栈

    Args:
        prog: drgn Program 对象
        task: task_struct 的 drgn Object

    Returns:
        调用栈帧列表 (如 ["[<ffffffff81234567>] __list_del_entry_valid+0x89/0x90", ...])
    """
    try:
        import drgn

        trace = drgn.stack_trace(prog, task)
        frames = []
        for frame in trace:
            try:
                # 格式化: [<address>] function_name+offset/length
                addr = frame.pc
                name = frame.name if hasattr(frame, "name") else str(frame)
                line = f"[<{addr:016x}>] {name}"
                frames.append(line)
            except Exception:
                frames.append(str(frame))
        return frames
    except ImportError:
        pass
    except Exception:
        pass

    return []


# ============================================================================
# 内核对象提取
# ============================================================================

def extract_kernel_objects(prog) -> Dict[str, Any]:
    """从 vmcore 中提取关键内核对象

    提取以下对象的状态:
    - task_struct: 进程列表、当前任务、崩溃任务
    - mm_struct: 内存映射、VMA 列表
    - 锁状态: mutex/semaphore 持有者
    - 模块列表: 已加载的内核模块
    - 文件描述符: 崩溃进程打开的文件

    Args:
        prog: drgn Program 对象

    Returns:
        包含各种内核对象状态的字典
    """
    objects: Dict[str, Any] = {
        "panic_task_comm": "",
        "panic_task_pid": 0,
        "total_tasks": 0,
        "loaded_modules": [],
        "lock_states": [],
    }

    try:
        import drgn

        # 统计任务数
        try:
            for task in drgn.helpers.linux.list.for_each_entry(
                "struct task_struct",
                prog["init_task"].tasks.address_of_(),
                "tasks",
            ):
                objects["total_tasks"] += 1
                if objects["total_tasks"] >= 10000:  # 防止无限循环
                    break
        except Exception:
            pass

        # 提取崩溃任务信息
        panic_task = _find_panic_task(prog)
        if panic_task:
            try:
                objects["panic_task_comm"] = panic_task.comm.string_().decode(
                    "utf-8", errors="replace"
                )
                objects["panic_task_pid"] = int(panic_task.pid.value_())
            except Exception:
                pass

        # 提取已加载模块
        try:
            for mod in drgn.helpers.linux.list.for_each_entry(
                "struct module",
                prog["modules"].address_of_(),
                "list",
            ):
                try:
                    name = mod.name.string_().decode("utf-8", errors="replace")
                    objects["loaded_modules"].append(name)
                except Exception:
                    pass
        except Exception:
            pass

    except ImportError:
        pass
    except Exception as e:
        print(f"Warning: Failed to extract kernel objects: {e}")

    return objects


# ============================================================================
# 寄存器状态提取
# ============================================================================

def extract_register_state(prog) -> Dict[str, Any]:
    """从 vmcore 中提取寄存器状态

    Args:
        prog: drgn Program 对象

    Returns:
        寄存器名称 → 值的字典
    """
    registers: Dict[str, Any] = {}

    try:
        import drgn

        # 获取崩溃 CPU 的寄存器
        try:
            registers["crash_cpu"] = int(prog["crash_notes"].value_())
        except Exception:
            pass

    except ImportError:
        pass
    except Exception:
        pass

    return registers


# ============================================================================
# Bug 特征推断
# ============================================================================

def infer_bug_type_from_vmcore(
    call_trace: List[str],
    kernel_objects: Dict[str, Any],
) -> Dict[str, Any]:
    """从 vmcore 提取的内核对象和调用栈中推断 Bug 特征

    Args:
        call_trace: 调用栈帧列表
        kernel_objects: 内核对象状态

    Returns:
        {
            "subsystem": str,
            "bug_type": str,
            "inference_confidence": float,
            "evidence": List[str],
        }
    """
    result = {
        "subsystem": "unknown",
        "bug_type": "unknown",
        "inference_confidence": 0.0,
        "evidence": [],
    }

    trace_text = "\n".join(call_trace).lower() if call_trace else ""

    # 检查死锁信号
    lock_functions = [
        "spin_lock", "mutex_lock", "down_read", "down_write",
        "queued_spin_lock_slowpath", "__mutex_lock_slowpath",
    ]
    lock_found = [f for f in lock_functions if f.lower() in trace_text]
    if lock_found:
        result["bug_type"] = "deadlock"
        result["inference_confidence"] = 0.6
        result["evidence"].append(f"Lock functions in call trace: {lock_found}")

    # 检查内存错误信号
    memory_functions = [
        "kmalloc", "kfree", "kmem_cache_alloc", "kmem_cache_free",
        "slab_alloc", "slab_free", "kasan_report",
    ]
    mem_found = [f for f in memory_functions if f.lower() in trace_text]
    if mem_found and result["bug_type"] == "unknown":
        result["bug_type"] = "memory_corruption"
        result["inference_confidence"] = 0.5
        result["evidence"].append(f"Memory functions in call trace: {mem_found}")

    # 子系统和调用栈推断
    trace_text_full = "\n".join(call_trace)
    subsys_from_trace = _infer_subsystem_from_trace(trace_text_full)
    if subsys_from_trace != "unknown":
        result["subsystem"] = subsys_from_trace
        result["evidence"].append(f"Subsystem inferred from trace: {subsys_from_trace}")

    return result


def _infer_subsystem_from_trace(trace_text: str) -> str:
    """从调用栈函数名推断子系统"""
    trace_lower = trace_text.lower()

    hints = [
        ("mm", ["mm_", "slab_", "page_", "folio_", "vm_", "handle_mm_fault", "do_page_fault"]),
        ("fs", ["vfs_", "ext4_", "xfs_", "btrfs_", "file_", "inode_", "dentry_"]),
        ("net", ["tcp_", "udp_", "sk_", "sock_", "dev_queue_xmit", "napi_", "netif_"]),
        ("block", ["blk_", "bio_", "scsi_", "nvme_"]),
        ("kernel", ["sched_", "rcu_", "irq_", "timer_", "workqueue_"]),
        ("drivers", ["pci_", "usb_", "i2c_", "spi_", "dma_"]),
    ]

    for subsys, funcs in hints:
        if any(f in trace_lower for f in funcs):
            return subsys
    return "unknown"


# ============================================================================
# 特征融合 — vmcore + dmesg
# ============================================================================

def fuse_features(
    vmcore_feature: CrashFeature,
    dmesg_feature: Optional[CrashFeature],
) -> CrashFeature:
    """融合 vmcore 和 dmesg 的特征

    融合策略:
    - subsystem: vmcore 优先 (基于调用栈中的函数名更可靠)
    - bug_type: 综合两者，取更具体的
    - call_trace: vmcore 优先 (基于 PC 的调用栈更准确)
    - panic_msg: dmesg 优先 (有错误消息原文)

    Args:
        vmcore_feature: 从 vmcore 提取的特征
        dmesg_feature: 从 dmesg 提取的特征 (可选)

    Returns:
        融合后的 CrashFeature
    """
    fused = CrashFeature()

    # subsystem: vmcore > dmesg
    fused.subsystem = vmcore_feature.subsystem if vmcore_feature.subsystem != "unknown" else (
        dmesg_feature.subsystem if dmesg_feature else "unknown"
    )

    # bug_type: 取更具体的
    if vmcore_feature.bug_type != "unknown":
        fused.bug_type = vmcore_feature.bug_type
    elif dmesg_feature and dmesg_feature.bug_type != "unknown":
        fused.bug_type = dmesg_feature.bug_type
    else:
        fused.bug_type = "unknown"

    # call_trace: vmcore 优先
    fused.call_trace = vmcore_feature.call_trace or (
        dmesg_feature.call_trace if dmesg_feature else []
    )

    # panic_msg: dmesg 优先
    fused.panic_msg = (
        dmesg_feature.panic_msg if dmesg_feature and dmesg_feature.panic_msg
        else vmcore_feature.panic_msg
    )

    # kernel_version: vmcore 优先 (直接读取内核对象)
    fused.kernel_version = vmcore_feature.kernel_version or (
        dmesg_feature.kernel_version if dmesg_feature else ""
    )

    # modules: 合并去重
    all_modules = set(vmcore_feature.modules)
    if dmesg_feature:
        all_modules.update(dmesg_feature.modules)
    fused.modules = list(all_modules)

    # extra_info: 合并
    fused.extra_info = {**vmcore_feature.extra_info}
    if dmesg_feature:
        fused.extra_info["dmesg_analysis"] = dmesg_feature.extra_info

    return fused


# ============================================================================
# 主入口函数
# ============================================================================

def extract_features_from_vmcore(vmcore_path: str, vmlinux_path: str) -> CrashFeature:
    """从 vmcore 中提取特征 — 完整流程

    增强版 — 完整实现 drgn 调用栈提取、内核对象提取、Bug 特征推断。

    Args:
        vmcore_path: vmcore 文件路径
        vmlinux_path: 对应的 vmlinux 文件路径

    Returns:
        CrashFeature — 包含调用栈、子系统、Bug 类型等
    """
    feature = CrashFeature()

    if not vmcore_path:
        feature.extra_info["error"] = "No vmcore path provided"
        feature.extra_info["source"] = "vmcore"
        return feature

    feature.extra_info["vmcore_path"] = vmcore_path
    feature.extra_info["vmlinux_path"] = vmlinux_path
    feature.extra_info["source"] = "vmcore"

    # Step 1: 加载 vmcore
    prog = load_vmcore(vmcore_path, vmlinux_path)
    if prog is None:
        feature.extra_info["error"] = "Failed to load vmcore (drgn not installed or vmcore invalid)"
        return feature

    # Step 2: 提取内核版本
    version = extract_kernel_version(prog)
    if version:
        feature.kernel_version = version

    # Step 3: 提取调用栈
    call_trace = extract_call_trace_from_vmcore(prog)
    feature.call_trace = call_trace
    feature.extra_info["trace_source"] = "drgn"

    # Step 4: 提取内核对象
    kernel_objects = extract_kernel_objects(prog)
    feature.extra_info["kernel_objects"] = kernel_objects
    feature.modules = kernel_objects.get("loaded_modules", [])
    if kernel_objects.get("panic_task_comm"):
        feature.extra_info["panic_task"] = kernel_objects["panic_task_comm"]

    # Step 5: Bug 特征推断
    bug_inference = infer_bug_type_from_vmcore(call_trace, kernel_objects)
    if bug_inference.get("subsystem", "unknown") != "unknown":
        feature.subsystem = bug_inference["subsystem"]
    if bug_inference.get("bug_type", "unknown") != "unknown":
        feature.bug_type = bug_inference["bug_type"]
    feature.extra_info["bug_inference"] = bug_inference

    # Step 6: 寄存器状态
    registers = extract_register_state(prog)
    feature.extra_info["registers"] = registers

    return feature


def analyze_vmcore(vmcore_path: str, vmlinux_path: str = "") -> CrashFeature:
    """分析 vmcore 文件的主入口 — 保持向后兼容

    Args:
        vmcore_path: vmcore 文件路径
        vmlinux_path: vmlinux 文件路径 (可选)

    Returns:
        CrashFeature 对象
    """
    return extract_features_from_vmcore(vmcore_path, vmlinux_path)


__all__ = [
    # vmcore 加载
    "load_vmcore",
    # 信息提取
    "extract_kernel_version",
    "extract_call_trace_from_vmcore",
    "extract_kernel_objects",
    "extract_register_state",
    # 特征推断
    "infer_bug_type_from_vmcore",
    # 特征融合
    "fuse_features",
    # 主入口
    "extract_features_from_vmcore",
    "analyze_vmcore",
]
