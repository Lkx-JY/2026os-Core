"""子系统关系图知识库 — Subsystem Relationship Graph

包含 Linux 内核各子系统之间的依赖关系、层级结构和交互模式。
用于辅助跨子系统的问题分析和补丁检索。

知识来源:
- Linux 内核 MAINTAINERS 文件中的子系统划分
- 内核源代码目录结构
- 子系统间的 API 依赖关系
- 历史 Bug 的跨子系统修复模式

设计要点:
- 父子系统关系: 逻辑分组 (如 drivers 包含 usb, pci, nvme)
- 协同关系: Bug 经常跨越的子系统边界 (如 mm + fs)
- 调用关系: 子系统间的 API 调用方向
- 为索引过滤和检索提供子系统扩展建议
"""

from typing import List, Dict, Any, Optional, Set


# ============================================================================
# 子系统完整定义
# ============================================================================

SUBSYSTEMS: Dict[str, Dict[str, Any]] = {
    "mm": {
        "name": "Memory Management",
        "description": "内核内存管理子系统：page allocator, slab allocator, vmalloc, swap, OOM killer",
        "path_prefix": ["mm/", "include/linux/mm.h", "include/linux/slab.h"],
        "key_functions": [
            "kmalloc", "kfree", "kzalloc", "vmalloc", "vfree",
            "__get_free_pages", "free_pages", "alloc_pages",
            "kmem_cache_alloc", "kmem_cache_free",
            "kref_get", "kref_put", "kref_init",
        ],
        "maintainers": ["Andrew Morton"],
        "mailing_list": "linux-mm@kvack.org",
        "related_bug_types": [
            "use_after_free", "null_pointer", "double_free",
            "memory_leak", "memory_corruption", "out_of_bound",
        ],
    },
    "fs": {
        "name": "File Systems / VFS",
        "description": "虚拟文件系统 (VFS) 和具体文件系统实现",
        "path_prefix": ["fs/", "include/linux/fs.h"],
        "key_functions": [
            "vfs_read", "vfs_write", "d_alloc", "d_instantiate",
            "iget_locked", "iput", "dput", "mntget",
            "file_open", "filp_close", "sync_filesystem",
        ],
        "maintainers": ["Alexander Viro"],
        "mailing_list": "linux-fsdevel@vger.kernel.org",
        "related_bug_types": [
            "deadlock", "race_condition", "use_after_free",
            "buffer_overflow", "null_pointer", "hang",
        ],
    },
    "net": {
        "name": "Networking",
        "description": "内核网络协议栈：TCP/IP, UDP, socket layer, netfilter",
        "path_prefix": ["net/", "include/net/", "include/linux/netdevice.h"],
        "key_functions": [
            "sock_create", "sock_release", "tcp_sendmsg", "tcp_recvmsg",
            "dev_queue_xmit", "netif_rx", "skb_get", "kfree_skb",
            "dev_alloc_skb", "skb_queue_tail", "__netif_receive_skb",
        ],
        "maintainers": ["David S. Miller", "Jakub Kicinski"],
        "mailing_list": "netdev@vger.kernel.org",
        "related_bug_types": [
            "use_after_free", "race_condition", "memory_leak",
            "null_pointer", "deadlock", "buffer_overflow",
        ],
    },
    "block": {
        "name": "Block Layer",
        "description": "块设备 I/O 层：bio, request queue, I/O scheduler",
        "path_prefix": ["block/", "include/linux/blkdev.h"],
        "key_functions": [
            "bio_alloc", "bio_add_page", "submit_bio",
            "blk_mq_start_request", "blk_mq_end_request",
            "blk_get_request", "blk_put_request",
        ],
        "maintainers": ["Jens Axboe"],
        "mailing_list": "linux-block@vger.kernel.org",
        "related_bug_types": [
            "deadlock", "race_condition", "memory_leak",
            "use_after_free", "hang",
        ],
    },
    "kernel": {
        "name": "Core Kernel",
        "description": "核心内核：调度器、锁、irq、定时器、信号、cgroup",
        "path_prefix": ["kernel/", "include/linux/sched.h"],
        "key_functions": [
            "schedule", "wake_up_process", "do_exit",
            "spin_lock", "mutex_lock", "rcu_read_lock",
            "synchronize_rcu", "call_rcu",
            "add_timer", "del_timer", "mod_timer",
        ],
        "maintainers": ["Ingo Molnar", "Peter Zijlstra"],
        "mailing_list": "linux-kernel@vger.kernel.org",
        "related_bug_types": [
            "deadlock", "race_condition", "rcu_stall",
            "hang", "crash",
        ],
    },
    "drivers": {
        "name": "Device Drivers",
        "description": "设备驱动框架和各类硬件驱动 (父系统)",
        "path_prefix": ["drivers/"],
        "key_functions": [
            "driver_register", "driver_unregister",
            "probe", "remove", "suspend", "resume",
        ],
        "maintainers": ["Greg Kroah-Hartman"],
        "mailing_list": "linux-kernel@vger.kernel.org",
        "related_bug_types": [
            "null_pointer", "use_after_free", "memory_leak",
            "race_condition", "crash",
        ],
    },
    "arch": {
        "name": "Architecture-Specific",
        "description": "架构相关代码：x86, ARM, ARM64, RISC-V, etc.",
        "path_prefix": ["arch/"],
        "key_functions": [
            "do_page_fault", "handle_mm_fault",
            "syscall_init", "trap_init",
        ],
        "maintainers": ["Architecture Maintainers"],
        "mailing_list": "linux-arch@vger.kernel.org",
        "related_bug_types": [
            "crash", "null_pointer", "buffer_overflow",
        ],
    },
    "bpf": {
        "name": "BPF / eBPF",
        "description": "Berkeley Packet Filter: 内核内虚拟机 + 验证器",
        "path_prefix": ["kernel/bpf/", "include/linux/bpf.h", "include/uapi/linux/bpf.h"],
        "key_functions": [
            "bpf_prog_alloc", "bpf_prog_free",
            "bpf_map_lookup_elem", "bpf_map_update_elem",
            "__bpf_call_base",
        ],
        "maintainers": ["Alexei Starovoitov", "Daniel Borkmann"],
        "mailing_list": "bpf@vger.kernel.org",
        "related_bug_types": [
            "use_after_free", "race_condition", "null_pointer",
            "out_of_bound", "memory_leak",
        ],
    },
    "security": {
        "name": "Security / LSMs",
        "description": "Linux Security Modules: SELinux, AppArmor, capabilities",
        "path_prefix": ["security/", "include/linux/lsm_hooks.h", "include/linux/security.h"],
        "key_functions": [
            "security_inode_permission", "security_file_ioctl",
            "selinux_inode_setattr", "apparmor_file_open",
        ],
        "maintainers": ["Paul Moore", "James Morris"],
        "mailing_list": "linux-security-module@vger.kernel.org",
        "related_bug_types": [
            "null_pointer", "use_after_free", "memory_leak",
        ],
    },
    "kvm": {
        "name": "KVM Virtualization",
        "description": "Kernel-based Virtual Machine: CPU + 内存虚拟化",
        "path_prefix": ["virt/kvm/", "arch/x86/kvm/", "arch/arm64/kvm/"],
        "key_functions": [
            "kvm_vcpu_ioctl", "kvm_mmu_page_fault",
            "kvm_arch_vcpu_ioctl_run", "kvm_mmu_free_page",
        ],
        "maintainers": ["Paolo Bonzini"],
        "mailing_list": "kvm@vger.kernel.org",
        "related_bug_types": [
            "use_after_free", "null_pointer", "race_condition",
        ],
    },
    "rcu": {
        "name": "RCU Subsystem",
        "description": "Read-Copy-Update 同步机制",
        "path_prefix": ["kernel/rcu/", "include/linux/rcupdate.h"],
        "key_functions": [
            "rcu_read_lock", "rcu_read_unlock",
            "synchronize_rcu", "call_rcu", "rcu_barrier",
            "rcu_assign_pointer", "rcu_dereference",
        ],
        "maintainers": ["Paul E. McKenney"],
        "mailing_list": "rcu@vger.kernel.org",
        "related_bug_types": [
            "rcu_stall", "race_condition", "use_after_free",
            "hang",
        ],
    },
    "cgroup": {
        "name": "Control Groups",
        "description": "cgroup v1/v2 资源管理",
        "path_prefix": ["kernel/cgroup/", "include/linux/cgroup.h"],
        "key_functions": [
            "cgroup_init", "cgroup_exit",
            "css_get", "css_put", "cgroup_add_file",
        ],
        "maintainers": ["Tejun Heo"],
        "mailing_list": "cgroups@vger.kernel.org",
        "related_bug_types": [
            "deadlock", "race_condition", "memory_leak",
            "use_after_free",
        ],
    },
}


# ============================================================================
# 子系统关系图
# ============================================================================

# 父子系统关系 (父 → [子])
SUBSYSTEM_HIERARCHY: Dict[str, List[str]] = {
    "kernel": ["rcu", "cgroup", "bpf", "irq"],
    "drivers": ["usb", "pci", "nvme", "scsi", "net"],
    "drivers/net": ["ethernet", "wireless", "bluetooth"],
    "fs": ["nfs", "ext4", "btrfs", "xfs"],
    "arch": ["kvm"],
    "security": ["crypto"],
    "mm": ["slab", "page_alloc", "swap", "compaction"],
}

# 紧耦合子系统关系 (经常一起修改/一起出 Bug)
COUPLED_SUBSYSTEMS: Dict[str, List[str]] = {
    "mm": ["fs", "block", "kernel", "arch"],
    "fs": ["mm", "block", "kernel", "security"],
    "net": ["kernel", "bpf", "drivers", "cgroup"],
    "block": ["mm", "fs", "drivers", "scsi", "nvme"],
    "kernel": ["mm", "rcu", "cgroup", "bpf", "irq", "arch"],
    "drivers": ["kernel", "arch", "mm", "net"],
    "rcu": ["kernel", "mm", "net"],
    "bpf": ["net", "kernel", "security"],
    "kvm": ["arch", "mm", "kernel"],
    "cgroup": ["mm", "kernel", "net"],
    "security": ["fs", "kernel", "net", "arch"],
}

# 调用关系 (调用方 → [被调用方])
CALL_RELATIONS: Dict[str, List[str]] = {
    "fs": ["mm", "block", "security"],
    "net": ["mm", "kernel"],
    "block": ["mm", "kernel"],
    "drivers": ["mm", "kernel", "arch"],
    "kvm": ["mm", "kernel", "arch"],
    "bpf": ["kernel", "net"],
}


# ============================================================================
# 子系统查询接口
# ============================================================================

def get_subsystem_info(subsystem: str) -> Optional[Dict[str, Any]]:
    """获取子系统详细信息

    Args:
        subsystem: 子系统名 (如 "mm")

    Returns:
        子系统定义字典
    """
    if subsystem in SUBSYSTEMS:
        return dict(SUBSYSTEMS[subsystem])
    return None


def get_children(subsystem: str) -> List[str]:
    """获取子系统的所有直接子节点

    Args:
        subsystem: 子系统名

    Returns:
        子节点列表
    """
    if subsystem in SUBSYSTEM_HIERARCHY:
        return list(SUBSYSTEM_HIERARCHY[subsystem])

    # 模糊匹配 (如 "drivers/net" 的父是 "drivers")
    for parent, children in SUBSYSTEM_HIERARCHY.items():
        if subsystem.startswith(parent + "/"):
            return []

    return []


def get_parent(subsystem: str) -> Optional[str]:
    """获取子系统的父节点

    Args:
        subsystem: 子系统名

    Returns:
        父节点名 或 None
    """
    for parent, children in SUBSYSTEM_HIERARCHY.items():
        if subsystem in children:
            return parent
    return None


def get_ancestors(subsystem: str) -> List[str]:
    """获取所有祖先节点

    Args:
        subsystem: 子系统名

    Returns:
        祖先节点列表 (从远到近)
    """
    ancestors = []
    current = subsystem
    while True:
        parent = get_parent(current)
        if parent is None:
            break
        ancestors.append(parent)
        current = parent
    return ancestors


def get_related_subsystems(subsystem: str, include_children: bool = True) -> List[str]:
    """获取所有相关子系统 (扩展检索范围)

    包含:
    - 紧耦合子系统
    - 父系统
    - 子节点 (可选)
    - 被调用方

    Args:
        subsystem: 目标子系统
        include_children: 是否包含子节点

    Returns:
        相关子系统列表
    """
    related: Set[str] = {subsystem}

    # 紧耦合
    coupled = COUPLED_SUBSYSTEMS.get(subsystem, [])
    related.update(coupled)

    # 父系统
    parent = get_parent(subsystem)
    if parent:
        related.add(parent)
        related.update(COUPLED_SUBSYSTEMS.get(parent, []))

    # 子节点
    if include_children:
        children = get_children(subsystem)
        related.update(children)
        for child in children:
            coupled = COUPLED_SUBSYSTEMS.get(child, [])
            related.update(coupled)

    # 被调用方
    callees = CALL_RELATIONS.get(subsystem, [])
    related.update(callees)

    return sorted(related)


def detect_subsystem_by_path(file_path: str) -> Optional[str]:
    """根据文件路径检测所属子系统

    Args:
        file_path: 文件路径 (如 "mm/slab.c")

    Returns:
        子系统名 或 None
    """
    for name, info in SUBSYSTEMS.items():
        for prefix in info.get("path_prefix", []):
            if file_path.startswith(prefix.rstrip("/")):
                return name
    return None


def detect_subsystem_by_function(func_name: str) -> Optional[str]:
    """根据函数名检测所属子系统

    Args:
        func_name: 函数名 (如 "kmalloc")

    Returns:
        子系统名 或 None
    """
    func_lower = func_name.lower()
    for name, info in SUBSYSTEMS.items():
        for func in info.get("key_functions", []):
            if func.lower() in func_lower:
                return name
    return None


def get_all_subsystems() -> List[str]:
    """获取所有已知子系统列表"""
    return sorted(SUBSYSTEMS.keys())


def list_subsystems_by_bug_type(bug_type: str) -> List[str]:
    """获取与指定 Bug 类型最常相关的子系统

    Args:
        bug_type: Bug 类型

    Returns:
        子系统列表
    """
    related = []
    for name, info in SUBSYSTEMS.items():
        if bug_type in info.get("related_bug_types", []):
            related.append(name)
    return related


def generate_subsystem_context_for_llm(
    subsystem: str,
    include_related: bool = True,
) -> str:
    """生成用于 LLM 的子系统上下文

    Args:
        subsystem: 子系统名
        include_related: 是否包含相关子系统信息

    Returns:
        子系统上下文文本
    """
    info = get_subsystem_info(subsystem)
    if not info:
        return f"Subsystem '{subsystem}' not found."

    lines = [
        f"## Subsystem: {info['name']} ({subsystem})",
        f"",
        f"**Description**: {info['description']}",
        f"",
        f"**Key Functions**: {', '.join(info['key_functions'][:8])}",
        f"**Common Bug Types**: {', '.join(info.get('related_bug_types', []))}",
        f"",
    ]

    if include_related:
        related = get_related_subsystems(subsystem)
        lines.append(f"**Related Subsystems**: {', '.join(r for r in related if r != subsystem)}")

    return "\n".join(lines)


__all__ = [
    # 知识库
    "SUBSYSTEMS",
    "SUBSYSTEM_HIERARCHY",
    "COUPLED_SUBSYSTEMS",
    "CALL_RELATIONS",
    # 查询接口
    "get_subsystem_info",
    "get_children",
    "get_parent",
    "get_ancestors",
    "get_related_subsystems",
    "detect_subsystem_by_path",
    "detect_subsystem_by_function",
    "get_all_subsystems",
    "list_subsystems_by_bug_type",
    "generate_subsystem_context_for_llm",
]
