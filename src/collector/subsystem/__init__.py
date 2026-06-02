"""子系统识别模块

负责根据修改的文件路径识别 commit 所属的子系统，主要针对 Linux 内核项目。
"""

import re
from typing import Dict, List
from datatypes import CommitInfo


# Linux 内核子系统映射表
SUBSYSTEM_MAP: Dict[str, List[str]] = {
    'mm': ['mm/', 'mmap/', 'slab/', 'vmalloc/', 'page_alloc/'],
    'fs': ['fs/', 'ext2/', 'ext3/', 'ext4/', 'btrfs/', 'xfs/', 'vfs/'],
    'net': ['net/', 'socket/', 'tcp/', 'udp/', 'ipv4/', 'ipv6/'],
    'block': ['block/', 'bio/'],
    'driver': ['drivers/', 'driver/'],
    'usb': ['drivers/usb/', 'usb/'],
    'pci': ['drivers/pci/', 'pci/'],
    'scsi': ['drivers/scsi/', 'scsi/'],
    'nvme': ['drivers/nvme/', 'nvme/'],
    'crypto': ['crypto/', 'drivers/crypto/'],
    'security': ['security/', 'selinux/', 'apparmor/'],
    'kernel': ['kernel/', 'sched/', 'locking/', 'time/'],
    'irq': ['kernel/irq/', 'irq/'],
    'rcu': ['kernel/rcu/', 'rcu/'],
    'kvm': ['virt/kvm/', 'kvm/'],
    'virt': ['virt/', 'hypervisor/'],
    'power': ['power/', 'pm/'],
    'acpi': ['acpi/', 'drivers/acpi/'],
    'dt': ['devicetree/', 'dt-bindings/'],
    'firmware': ['firmware/', 'drivers/firmware/'],
    'lib': ['lib/', 'lib/string/', 'lib/list/'],
    'tools': ['tools/', 'scripts/'],
    'doc': ['Documentation/', 'doc/'],
    'arch': ['arch/', 'arch/x86/', 'arch/arm/', 'arch/arm64/'],
    'bpf': ['bpf/', 'kernel/bpf/', 'tools/bpf/'],
    'cgroup': ['kernel/cgroup/', 'cgroup/'],
    'nfs': ['fs/nfs/', 'nfs/'],
    'smb': ['fs/cifs/', 'smb/'],
}


def detect_subsystem(commit: CommitInfo) -> str:
    """根据修改的文件识别子系统"""
    if not commit.files_changed:
        return "unknown"
    
    # 先从 subject 前缀识别
    if commit.subject and ':' in commit.subject:
        prefix = commit.subject.split(':', 1)[0].strip()
        if prefix in SUBSYSTEM_MAP:
            return prefix
    
    # 根据文件路径识别
    for subsystem, patterns in SUBSYSTEM_MAP.items():
        for file_path in commit.files_changed:
            for pattern in patterns:
                if file_path.startswith(pattern):
                    return subsystem
    
    # 尝试从文件名中提取
    for file_path in commit.files_changed:
        parts = file_path.split('/')
        if parts:
            first_part = parts[0]
            if first_part in SUBSYSTEM_MAP:
                return first_part
    
    return "unknown"


def get_subsystem_hierarchy(subsystem: str) -> List[str]:
    """获取子系统的层级结构"""
    hierarchy = []
    
    if subsystem == 'unknown':
        return hierarchy
    
    hierarchy.append(subsystem)
    
    # 一些子系统的层级关系
    parent_map = {
        'usb': 'driver',
        'pci': 'driver',
        'scsi': 'driver',
        'nvme': 'driver',
        'irq': 'kernel',
        'rcu': 'kernel',
        'bpf': 'kernel',
        'cgroup': 'kernel',
        'acpi': 'power',
        'kvm': 'virt',
        'crypto': 'security',
    }
    
    parent = parent_map.get(subsystem)
    if parent:
        hierarchy.append(parent)
    
    return hierarchy


def get_all_subsystems() -> List[str]:
    """获取所有已知子系统列表"""
    return list(SUBSYSTEM_MAP.keys())


def guess_subsystem_from_content(content: str) -> str:
    """从内容中猜测子系统"""
    subsystem_keywords = {
        'mm': ['page', 'memory', 'alloc', 'free', 'slab', 'vmalloc', 'kmem'],
        'fs': ['file', 'inode', 'super', 'mount', 'vfs', 'dentry'],
        'net': ['socket', 'tcp', 'udp', 'ip', 'sk_buff', 'network'],
        'block': ['bio', 'block', 'request', 'queue'],
        'crypto': ['crypt', 'hash', 'cipher', 'sha', 'md5'],
        'rcu': ['rcu', 'synchronize_rcu', 'rcu_read_lock'],
        'irq': ['irq', 'interrupt', 'handler'],
        'power': ['power', 'pm', 'sleep', 'wakeup'],
        'bpf': ['bpf', 'ebpf'],
    }
    
    content_lower = content.lower()
    scores = {}
    
    for subsystem, keywords in subsystem_keywords.items():
        score = sum(1 for kw in keywords if kw in content_lower)
        if score > 0:
            scores[subsystem] = score
    
    if scores:
        return max(scores, key=scores.get)
    
    return "unknown"