"""根因抽象模型模块 — Root Cause Abstraction Layer

负责将提取的宕机特征抽象为结构化的根因描述，是连接"日志理解"与"补丁检索"的关键桥梁。

核心职责:
1. 专家规则匹配 — 基于 20+ 条内核领域专家规则进行根因推断
2. 调用栈结构分析 — 从 Call Trace 中识别锁/内存/RCU/调度等关键函数
3. 修复模式推断 — 从故障特征推断需要什么样的修复 (lock_added, refcount_fix, rcu_fix 等)
4. 检索查询构造 — 生成优化的检索查询语句，用于下游向量检索

设计原则:
- 规则可扩展: 通过 expert_rules 列表即可添加新规则，无需修改核心逻辑
- 优先级分层: 精确匹配 > 调用栈分析 > 通用抽象，逐层降级
- 与知识模块协同: 调用 knowledge/ 下的 bug_patterns, lock_rules 等模块增强分析
"""

from typing import List, Dict, Any, Optional, Tuple
from ..models import CrashFeature, RootCauseResult


# ============================================================================


EXPERT_RULES: List[Dict[str, Any]] = [
    # ── 死锁与并发 ──────────────────────────────────────────────
    {
        "id": "R001",
        "name": "Spinlock Deadlock",
        "bug_type": "deadlock",
        "severity": 9,
        "keywords": [
            "spin_lock", "queued_spin_lock_slowpath",
            "native_queued_spin_lock_slowpath", "_raw_spin_lock",
            "_raw_spin_lock_irqsave", "__raw_spin_lock_irqsave",
        ],
        "panic_patterns": [],
        "description": "自旋锁死锁 — 通常发生在中断上下文持有锁时再次申请同一把锁，或锁获取顺序不一致导致 ABBA 死锁。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "检查锁获取顺序，确保中断上下文中使用 spin_lock_irqsave 而非 spin_lock",
        },
        "related_subsystems": ["kernel", "core"],
    },
    {
        "id": "R004",
        "name": "Mutex Deadlock",
        "bug_type": "deadlock",
        "severity": 9,
        "keywords": [
            "mutex_lock", "mutex_lock_interruptible", "mutex_lock_killable",
            "__mutex_lock_slowpath", "mutex_lock_nested",
        ],
        "panic_patterns": [r"possible recursive locking", r"circular locking dependency"],
        "description": "互斥锁死锁 — 进程上下文中的锁循环依赖，lockdep 通常会提前检测到。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "重新设计锁获取顺序，降低锁粒度，或使用 try_lock 机制",
        },
        "related_subsystems": ["kernel", "core", "fs", "mm"],
    },
    {
        "id": "R015",
        "name": "RCU Stall / SRCU Stall",
        "bug_type": "hang",
        "severity": 8,
        "keywords": [
            "rcu_sched", "rcu_bh", "rcu_preempt", "rcu_sched self-detected stall",
            "rcu_sched detected stalls", "SRCU", "srcu",
        ],
        "panic_patterns": [
            r"rcu_sched.*stall",
            r"rcu_bh.*stall",
            r"INFO: rcu_sched self-detected stall on CPU",
            r"INFO: rcu_sched detected stalls on CPUs",
        ],
        "description": "RCU 宽限期停滞 — RCU 回调在宽限期内未能完成，通常是某个 CPU 在 RCU 读临界区中阻塞或死循环。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": True,
            "fix_pattern": "检查 RCU 读临界区是否过长、是否有阻塞操作（如 mutex_lock）、是否遗漏 rcu_read_unlock",
        },
        "related_subsystems": ["kernel", "rcu"],
    },

    # ── 内存错误 ──────────────────────────────────────────────
    {
        "id": "R002",
        "name": "Null Pointer Dereference",
        "bug_type": "null_pointer",
        "severity": 8,
        "keywords": [
            "unable to handle kernel NULL pointer dereference",
            "unable to handle kernel paging request",
            "NULL pointer dereference",
        ],
        "panic_patterns": [
            r"unable to handle kernel NULL pointer dereference at",
            r"PGD.*0000000000000000",
        ],
        "description": "空指针解引用 — 内核代码尝试访问地址 0 附近的内存，通常是因为指针未初始化或函数返回 NULL 未检查。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "在解引用前添加 NULL 检查，或确保调用方不可能返回 NULL",
        },
        "related_subsystems": ["core", "drivers"],
    },
    {
        "id": "R003",
        "name": "Use After Free (KASAN)",
        "bug_type": "use_after_free",
        "severity": 9,
        "keywords": [
            "KASAN: use-after-free", "slub_debug", "use-after-free",
            "kasan", "use after free",
        ],
        "panic_patterns": [
            r"KASAN: use-after-free in",
            r"BUG .*use-after-free",
        ],
        "description": "释放后使用 — 内存已被释放但仍被访问。KASAN 检测到 slab/slub 对象在 free 后被使用。常见原因：引用计数错误、RCU 保护不足、竞态条件。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": True,
            "rcu_fix": True,
            "fix_pattern": "增加引用计数保护，或使用 RCU 延迟释放 (kfree_rcu)，或修复竞态条件",
        },
        "related_subsystems": ["mm", "core", "net"],
    },
    {
        "id": "R005",
        "name": "Double Free (KASAN)",
        "bug_type": "double_free",
        "severity": 9,
        "keywords": [
            "KASAN: double-free", "double free", "double-free",
            "slab double free",
        ],
        "panic_patterns": [
            r"KASAN: double-free",
            r"kernel BUG at mm/slub.c",
            r"Slab double-free detected",
        ],
        "description": "重复释放 — 同一内存区域被释放了两次，表明内存生命周期管理存在缺陷。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": True,
            "rcu_fix": False,
            "fix_pattern": "在释放后将指针置 NULL，或使用引用计数确保只有最后一个使用者释放",
        },
        "related_subsystems": ["mm", "net", "drivers"],
    },
    {
        "id": "R006",
        "name": "Out-Of-Bounds Access (KASAN)",
        "bug_type": "out_of_bound",
        "severity": 9,
        "keywords": [
            "KASAN: slab-out-of-bounds", "KASAN: global-out-of-bounds",
            "KASAN: stack-out-of-bounds", "out-of-bounds",
        ],
        "panic_patterns": [
            r"KASAN: slab-out-of-bounds (Read|Write) in",
            r"KASAN: global-out-of-bounds",
            r"KASAN: stack-out-of-bounds",
        ],
        "description": "越界访问 — 数组/缓冲区索引超出分配范围。KASAN 检测到对 slab/全局/栈对象的越界读写。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "添加边界检查，确保索引/偏移在合法范围内",
        },
        "related_subsystems": ["mm", "core", "net", "fs"],
    },
    {
        "id": "R007",
        "name": "Memory Corruption (List)",
        "bug_type": "memory_corruption",
        "severity": 8,
        "keywords": [
            "list_del corruption", "list_add corruption",
            "list_add double add", "list corruption",
        ],
        "panic_patterns": [
            r"list_del corruption.*(LIST_POISON|prev->next|next->prev)",
            r"list_add corruption.*prev->next should be",
            r"list_add double add",
        ],
        "description": "链表损坏 — 内核链表操作检测到不一致状态。通常由竞态条件导致（多 CPU 同时修改同一链表而未加锁），或 UAF 导致链表节点被覆写。",
        "fix_hints": {
            "lock_added": True,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "在链表操作前后添加适当的锁保护 (spin_lock)，确保链表操作的原子性",
        },
        "related_subsystems": ["core", "mm", "net", "fs"],
    },
    {
        "id": "R008",
        "name": "Page Fault / Bad Area",
        "bug_type": "memory_corruption",
        "severity": 8,
        "keywords": [
            "unable to handle kernel paging request",
            "BUG: unable to handle page fault",
            "bad_area", "bad_area_nosemaphore",
        ],
        "panic_patterns": [
            r"unable to handle kernel paging request at",
            r"BUG: unable to handle page fault",
        ],
        "description": "页错误 — 内核尝试访问无效的虚拟地址。原因包括：空指针、已释放的内存、物理内存损坏、页表损坏。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": True,
            "rcu_fix": False,
            "fix_pattern": "验证指针有效性，使用 mmap_lock 保护地址空间操作，检查内存映射生命周期",
        },
        "related_subsystems": ["mm", "arch"],
    },
    {
        "id": "R009",
        "name": "Out of Memory (OOM)",
        "bug_type": "memory_leak",
        "severity": 7,
        "keywords": [
            "Out of memory", "OOM", "oom-killer", "oom killer",
            "Killed process", "invoked oom-killer", "Memory cgroup out of memory",
        ],
        "panic_patterns": [
            r"Out of memory: Killed process",
            r"oom-killer.*invoked",
            r"Memory cgroup out of memory",
        ],
        "description": "内存耗尽 — 系统所有可用内存（包括 swap）已被耗尽，OOM Killer 被迫杀死进程。可能是内存泄漏或工作负载超出系统容量。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": True,
            "rcu_fix": False,
            "fix_pattern": "检查内存泄漏点（kmalloc/kzalloc 缺少对应的 kfree），限制 cgroup 内存，优化内存回收",
        },
        "related_subsystems": ["mm"],
    },
    {
        "id": "R010",
        "name": "Buffer Overflow (Non-KASAN)",
        "bug_type": "buffer_overflow",
        "severity": 8,
        "keywords": [
            "buffer overflow", "stack buffer overflow",
            "heap buffer overflow", "buffer overrun",
        ],
        "panic_patterns": [],
        "description": "缓冲区溢出 — 写操作超出了分配缓冲区的大小，破坏相邻内存。可能是字符串操作缺少长度检查（strcpy/strcat/sprintf）。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "使用 strscpy 替代 strcpy/strncpy，使用 snprintf 替代 sprintf，添加长度检查",
        },
        "related_subsystems": ["core", "fs", "drivers"],
    },
    {
        "id": "R011",
        "name": "Refcount Underflow / Overflow",
        "bug_type": "use_after_free",
        "severity": 9,
        "keywords": [
            "refcount_t", "refcount underflow", "refcount overflow",
            "refcount saturation", "refcount saturated",
        ],
        "panic_patterns": [
            r"refcount_t.*underflow",
            r"refcount_t.*saturated",
            r"refcount_t: underflow",
        ],
        "description": "引用计数下溢/溢出 — refcount_t 检测到引用计数操作异常。下溢意味着 put 多于 get（会导致 UAF），溢出意味着引用计数爆满。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": True,
            "rcu_fix": False,
            "fix_pattern": "检查 get/put 配对，确保每次 kref_get/kref_init 都有对应的 kref_put",
        },
        "related_subsystems": ["core", "mm", "net", "fs"],
    },

    # ── CPU/调度异常 ──────────────────────────────────────────
    {
        "id": "R012",
        "name": "Hardlockup (NMI Watchdog)",
        "bug_type": "hang",
        "severity": 10,
        "keywords": [
            "NMI watchdog", "hardlockup", "hard lockup",
            "Watchdog detected hard LOCKUP",
        ],
        "panic_patterns": [
            r"Watchdog detected hard LOCKUP on cpu",
            r"NMI watchdog: BUG: soft lockup",
        ],
        "description": "硬锁死 — CPU 在内核态死循环且中断被长时间禁用。NMI 看门狗也无法触发调度。通常是自旋锁死锁或中断禁用时间过长。",
        "fix_hints": {
            "lock_added": True,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "减少关中断临界区长度，检查自旋锁持有时间，使用 spin_lock_irqsave 时确保尽快释放",
        },
        "related_subsystems": ["kernel", "core", "arch"],
    },
    {
        "id": "R013",
        "name": "Softlockup",
        "bug_type": "hang",
        "severity": 8,
        "keywords": [
            "softlockup", "soft lockup", "BUG: soft lockup",
            "soft lockup - CPU",
        ],
        "panic_patterns": [
            r"BUG: soft lockup - CPU#\d+ stuck for \d+s",
        ],
        "description": "软锁死 — CPU 在内核态长时间运行而未调用 schedule()。可能是循环条件错误、自旋锁持有时间过长、或中断风暴。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "在长循环中添加 cond_resched() 调度点，检查循环退出条件，限制自旋锁持有时间",
        },
        "related_subsystems": ["kernel", "core", "drivers"],
    },
    {
        "id": "R014",
        "name": "Hungtask",
        "bug_type": "hang",
        "severity": 8,
        "keywords": [
            "hungtask", "hung_task", "hung task",
            "INFO: task .* blocked for more than",
            "task .* blocked",
        ],
        "panic_patterns": [
            r"INFO: task .* blocked for more than \d+ seconds",
            r"blocked for more than",
        ],
        "description": "任务挂起 — 进程在 D (UNINTERRUPTIBLE_SLEEP) 状态阻塞超过 120 秒。通常是 I/O 操作卡住、死锁、或 NFS 等服务不可达。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "添加 I/O 超时机制，检查 NFS/RPC 连接状态，检查锁依赖链",
        },
        "related_subsystems": ["fs", "block", "net", "nfs"],
    },
    {
        "id": "R020",
        "name": "Workqueue Stall",
        "bug_type": "hang",
        "severity": 7,
        "keywords": [
            "workqueue", "work queue", "worker",
            "workqueue stall",
        ],
        "panic_patterns": [
            r"workqueue: .* stuck",
        ],
        "description": "工作队列停滞 — workqueue worker 线程卡住，无法处理队列中的工作项。可能是工作者函数死锁或长时间运行未返回。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "检查工作者函数是否有死锁可能，使用 flush_workqueue 时的同步机制",
        },
        "related_subsystems": ["kernel", "core"],
    },

    # ── 异常与错误 ────────────────────────────────────────────
    {
        "id": "R016",
        "name": "General Protection Fault (GPF)",
        "bug_type": "crash",
        "severity": 9,
        "keywords": [
            "general protection fault", "general protection",
            "GPF", "iret exception",
        ],
        "panic_patterns": [
            r"general protection fault:",
            r"general protection fault, probably for non-canonical address",
        ],
        "description": "通用保护错误 — CPU 检测到权限违规（如用户态代码执行特权指令）、段限制违规、或非规范地址访问。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "检查内存访问权限，确保没有将内核指针泄漏到用户态，检查 SMAP/SMEP 相关设置",
        },
        "related_subsystems": ["arch", "core", "mm"],
    },
    {
        "id": "R017",
        "name": "Machine Check Exception (MCE)",
        "bug_type": "crash",
        "severity": 10,
        "keywords": [
            "Machine Check Exception", "MCE", "machine check",
            "Hardware Error", "mcelog",
        ],
        "panic_patterns": [
            r"Machine Check Exception",
            r"Hardware Error:",
            r"mce:.*hardware error",
        ],
        "description": "机器检查异常 — CPU 检测到致命硬件错误（内存 ECC 错误、缓存错误、总线错误）。通常是硬件故障而非软件 Bug。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "检查硬件健康状态（内存 DIMM、CPU 缓存），使用 mcelog 解码 MCE 记录，可能需要更换硬件",
        },
        "related_subsystems": ["arch", "x86"],
    },
    {
        "id": "R018",
        "name": "Kernel BUG / BUG_ON",
        "bug_type": "crash",
        "severity": 9,
        "keywords": [
            "kernel BUG at", "BUG: unable to handle kernel",
            "BUG_ON", "------------[ cut here ]------------",
        ],
        "panic_patterns": [
            r"kernel BUG at",
            r"BUG: unable to handle kernel",
            r"------------\[ cut here \]------------",
        ],
        "description": "内核 BUG — BUG_ON() 或 WARN_ON() 条件被触发，表明内核代码到达了不应执行到的路径（'impossible' condition）。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "分析 BUG_ON 的条件为何为真 — 通常意味着上游逻辑已损坏或并发访问导致状态不一致",
        },
        "related_subsystems": ["core"],
    },
    {
        "id": "R019",
        "name": "Stack Overflow",
        "bug_type": "buffer_overflow",
        "severity": 9,
        "keywords": [
            "stack overflow", "stack segment", "stack overrun",
            "recursion",
        ],
        "panic_patterns": [
            r"stack segment:",
            r"stack overflow",
            r"do_IRQ: stack overflow",
        ],
        "description": "栈溢出 — 内核栈（通常 8KB-16KB）被耗尽。原因：过深的递归调用、栈上分配大缓冲区、中断嵌套。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "将大缓冲区从栈移至堆 (kmalloc)，消除递归或限制递归深度，使用 CONFIG_FRAME_WARN 编译检查",
        },
        "related_subsystems": ["core", "arch", "fs"],
    },
    {
        "id": "R021",
        "name": "Division Error / Divide by Zero",
        "bug_type": "crash",
        "severity": 7,
        "keywords": [
            "division error", "divide error", "divide by zero",
            "div0",
        ],
        "panic_patterns": [
            r"divide error:",
            r"division by zero",
        ],
        "description": "除零错误 — CPU 执行除法指令且除数为 0。通常是因为模块参数未校验、或计算逻辑中存在边界情况。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "在执行除法前检查除数不为 0，添加参数合法性校验",
        },
        "related_subsystems": ["core", "drivers"],
    },
    {
        "id": "R022",
        "name": "UBSAN Detected Undefined Behavior",
        "bug_type": "crash",
        "severity": 7,
        "keywords": [
            "UBSAN", "ubsan", "undefined behavior",
            "UBSAN: shift-out-of-bounds", "UBSAN: array-index-out-of-bounds",
        ],
        "panic_patterns": [
            r"UBSAN: (shift-out-of-bounds|array-index-out-of-bounds|null-ptr-deref|signed-integer-overflow)",
        ],
        "description": "UBSAN 检测到未定义行为 — 编译器未定义行为检测器发现移位越界、数组越界、空指针、有符号整数溢出等问题。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "修正导致未定义行为的代码：添加范围检查、使用无符号类型、检查指针非空",
        },
        "related_subsystems": ["core"],
    },

    # ── 特殊场景 ──────────────────────────────────────────────
    {
        "id": "R023",
        "name": "Kernel Panic — Not Syncing",
        "bug_type": "crash",
        "severity": 10,
        "keywords": [
            "Kernel panic - not syncing",
            "Kernel panic",
        ],
        "panic_patterns": [
            r"Kernel panic - not syncing:",
        ],
        "description": "内核 Panic — 内核遇到不可恢复的错误主动停止。需要结合 panic 消息和 Call Trace 才能确定具体原因。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "分析 panic 消息中的具体原因字符串，结合 Call Trace 定位触发点",
        },
        "related_subsystems": ["core"],
    },
    {
        "id": "R024",
        "name": "Kernel Oops",
        "bug_type": "crash",
        "severity": 8,
        "keywords": [
            "Oops:", "unable to handle kernel",
        ],
        "panic_patterns": [
            r"Oops: \d+",
        ],
        "description": "内核 Oops — 内核检测到非致命错误。Oops 后系统可能继续运行但处于不稳定状态，后续可能触发 Panic。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "分析 Oops 的错误码和 Call Trace，定位并修复错误路径",
        },
        "related_subsystems": ["core"],
    },
    {
        "id": "R025",
        "name": "Bad Mode / Undefined Instruction",
        "bug_type": "crash",
        "severity": 9,
        "keywords": [
            "Bad mode", "undefined instruction", "illegal instruction",
            "Oops - undefined instruction",
        ],
        "panic_patterns": [
            r"Bad mode in .* handler detected",
            r"Oops - undefined instruction:",
            r"undefined instruction",
        ],
        "description": "非法指令/异常模式 — CPU 尝试执行无效的指令或切换到非法的处理器模式。栈溢出导致返回地址损坏时常见。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "检查栈是否溢出（导致的返回地址损坏），确认内核和模块编译架构匹配 (ARM64 vs x86_64)",
        },
        "related_subsystems": ["arch", "core"],
    },
    {
        "id": "R026",
        "name": "Data Abort / Alignment Fault",
        "bug_type": "crash",
        "severity": 8,
        "keywords": [
            "data abort", "alignment fault", "unaligned memory access",
            "Unhandled fault: alignment fault",
        ],
        "panic_patterns": [
            r"Unhandled fault: alignment fault",
            r"Unable to handle kernel .* at virtual address",
        ],
        "description": "对齐错误 — 非对齐内存访问（主要在 ARM/ARM64 架构）。访问地址不是数据类型大小的倍数。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "使用 get_unaligned()/put_unaligned() 进行非对齐访问，或确保数据结构对齐到自然边界",
        },
        "related_subsystems": ["arch", "drivers"],
    },
    {
        "id": "R027",
        "name": "Spectre / Meltdown Mitigation Check",
        "bug_type": "security",
        "severity": 6,
        "keywords": [
            "spectre", "meltdown", "speculative execution",
            "retpoline", "SPEC_CTRL",
        ],
        "panic_patterns": [],
        "description": "侧信道缓解相关 — 与 Spectre/Meltdown 等 CPU 安全漏洞的缓解措施相关的问题或警告。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "检查 CPU 微码更新，确认内核启动了正确的缓解措施，更新编译器 (retpoline 支持)",
        },
        "related_subsystems": ["arch", "x86"],
    },
    {
        "id": "R028",
        "name": "IRQ / Interrupt Storm",
        "bug_type": "hang",
        "severity": 7,
        "keywords": [
            "irq", "interrupt", "IRQ storm", "nobody cared",
            "irq.*nobody cared",
        ],
        "panic_patterns": [
            r"irq \d+: nobody cared",
            r"Disabling IRQ #\d+",
        ],
        "description": "中断风暴/无人响应中断 — IRQ 线路上产生了大量中断但无驱动处理，或中断处理程序返回 IRQ_NONE。系统可能被中断风暴拖垮。",
        "fix_hints": {
            "lock_added": False,
            "refcount_fix": False,
            "rcu_fix": False,
            "fix_pattern": "检查中断处理程序是否正确返回 IRQ_HANDLED，确认设备固件/驱动匹配，添加中断共享支持",
        },
        "related_subsystems": ["kernel", "drivers"],
    },
]

# 严重程度 → 文本描述
SEVERITY_MAP = {
    10: "Critical — 系统无法恢复，必须立即定位修复",
    9: "Severe — 极可能导致数据损坏或安全漏洞",
    8: "High — 显著影响系统稳定性",
    7: "Medium-High — 需要及时修复",
    6: "Medium — 建议修复",
    5: "Low — 优化或改进",
}


# ============================================================================
# 调用栈结构分析 — 从 Call Trace 中提取语义信号
# ============================================================================

# 锁相关函数的调用栈特征
LOCK_TRACE_FUNCTIONS = [
    "spin_lock", "spin_lock_irq", "spin_lock_irqsave", "spin_lock_bh",
    "spin_unlock", "spin_unlock_irq", "spin_unlock_irqrestore",
    "mutex_lock", "mutex_lock_interruptible", "mutex_lock_killable",
    "mutex_unlock", "mutex_trylock",
    "rwlock", "read_lock", "write_lock",
    "down_read", "down_write", "up_read", "up_write",
    "_raw_spin_lock", "_raw_spin_lock_irqsave",
    "queued_spin_lock_slowpath", "native_queued_spin_lock_slowpath",
    "__mutex_lock_slowpath", "mutex_lock_nested",
    "rt_mutex_lock", "rt_mutex_unlock",
    "lock_acquire", "lock_release", "lock_contended",
]

# 内存相关函数的调用栈特征
MEMORY_TRACE_FUNCTIONS = [
    "kmalloc", "kzalloc", "kfree", "vmalloc", "vfree",
    "kmem_cache_alloc", "kmem_cache_free", "kmem_cache_create",
    "__slab_alloc", "__slab_free", "slab_alloc", "slab_free",
    "alloc_pages", "__alloc_pages", "__alloc_pages_nodemask",
    "free_pages", "__free_pages", "page_frag_alloc",
    "kasan", "kasan_report", "kasan_check_read", "kasan_check_write",
    "page_fault", "do_page_fault", "handle_mm_fault",
    "handle_pte_fault", "__handle_mm_fault",
    "mmap", "munmap", "do_mmap", "do_munmap",
    "get_user_pages", "put_page", "__get_free_pages",
    "oom_kill_process", "out_of_memory", "page_alloc",
]

# RCU 相关函数的调用栈特征
RCU_TRACE_FUNCTIONS = [
    "rcu_read_lock", "rcu_read_unlock",
    "synchronize_rcu", "synchronize_rcu_expedited",
    "call_rcu", "call_rcu_sched",
    "rcu_barrier", "rcu_barrier_sched",
    "rcu_assign_pointer", "rcu_dereference",
    "rcu_dereference_protected", "rcu_access_pointer",
    "rcu_report_dead", "rcu_cpu_stall_reset",
    "__rcu_read_lock", "__rcu_read_unlock",
    "srcu_read_lock", "srcu_read_unlock", "synchronize_srcu",
    "rcu_do_batch", "rcu_core", "rcu_process_callbacks",
    "rcu_sched_clock_irq", "rcu_check_callbacks",
    "kfree_rcu", "__kfree_rcu",
]

# 调度相关函数的调用栈特征
SCHED_TRACE_FUNCTIONS = [
    "schedule", "__schedule", "_cond_resched", "cond_resched",
    "schedule_timeout", "schedule_timeout_interruptible",
    "schedule_timeout_killable", "schedule_hrtimeout_range",
    "schedule_timeout_uninterruptible",
    "wait_for_completion", "wait_for_completion_interruptible",
    "wait_for_completion_timeout",
    "io_schedule", "io_schedule_timeout",
    "msleep", "msleep_interruptible", "ssleep",
    "do_nanosleep", "hrtimer_nanosleep",
    "__wait_event", "__wait_event_interruptible",
    "wake_up_process", "try_to_wake_up",
    "wake_up", "wake_up_interruptible",
    "do_exit", "do_group_exit",
    "__might_sleep", "__might_resched",
]


def _find_functions_in_trace(trace_lines: List[str], function_set: List[str]) -> List[str]:
    """在调用栈行中查找匹配的函数名"""
    found = []
    trace_text = "\n".join(trace_lines).lower()
    for func in function_set:
        if func.lower() in trace_text:
            found.append(func)
    return found


def analyze_call_trace_structure(trace_lines: List[str]) -> Dict[str, Any]:
    """对调用栈进行结构化分析，提取语义信号

    Returns:
        Dict containing:
        - lock_functions: 调用栈中出现的锁相关函数
        - memory_functions: 调用栈中出现的内存相关函数
        - rcu_functions: 调用栈中出现的 RCU 相关函数
        - sched_functions: 调用栈中出现的调度相关函数
        - inferred_issue: 基于调用栈推断的问题类型
        - involved_subsystem: 推断涉及的子系统
    """
    if not trace_lines:
        return {
            "lock_functions": [],
            "memory_functions": [],
            "rcu_functions": [],
            "sched_functions": [],
            "inferred_issue": "unknown",
            "involved_subsystem": "unknown",
        }

    lock_funcs = _find_functions_in_trace(trace_lines, LOCK_TRACE_FUNCTIONS)
    memory_funcs = _find_functions_in_trace(trace_lines, MEMORY_TRACE_FUNCTIONS)
    rcu_funcs = _find_functions_in_trace(trace_lines, RCU_TRACE_FUNCTIONS)
    sched_funcs = _find_functions_in_trace(trace_lines, SCHED_TRACE_FUNCTIONS)

    # 推断问题类型
    inferred = "unknown"
    if lock_funcs and sched_funcs:
        inferred = "deadlock_or_lock_contention"
    elif lock_funcs:
        inferred = "possible_lock_issue"
    elif rcu_funcs:
        inferred = "rcu_related"
    elif memory_funcs:
        inferred = "memory_related"
    elif sched_funcs:
        inferred = "scheduling_related"

    # 推断子系统
    trace_text = "\n".join(trace_lines).lower()
    subsystem_hints = {
        "mm": ["mm/", "slab", "page_", "alloc_pages", "folio", "mmap", "vma", "swap"],
        "fs": ["fs/", "ext4", "xfs", "btrfs", "vfs_", "file_", "inode", "dentry", "nfs"],
        "net": ["net/", "tcp_", "udp_", "sk_", "sock_", "dev_queue_xmit", "napi_", "netif_"],
        "block": ["block/", "blk_", "bio_", "request_queue", "scsi_", "nvme_"],
        "kernel": ["kernel/", "sched_", "rcu_", "irq_", "time_"],
        "drivers": ["drivers/", "pci_", "usb_", "i2c_", "spi_", "dma_"],
        "arch": ["arch/", "entry_", "syscall", "do_sys", "x86_", "arm64_"],
    }
    involved = "unknown"
    for subsys, hints in subsystem_hints.items():
        if any(hint in trace_text for hint in hints):
            involved = subsys
            break

    return {
        "lock_functions": lock_funcs,
        "memory_functions": memory_funcs,
        "rcu_functions": rcu_funcs,
        "sched_functions": sched_funcs,
        "inferred_issue": inferred,
        "involved_subsystem": involved,
    }


# ============================================================================
# 修复模式推断 — 从故障特征映射到需要的修复类型
# ============================================================================

def infer_fix_patterns(
    bug_type: str,
    call_trace_analysis: Dict[str, Any],
    panic_msg: str = "",
) -> Dict[str, Any]:
    """从故障特征推断需要什么样的修复模式

    这是连接"日志理解"和"补丁检索"的关键 — 它告诉检索器应该优先检索
    包含哪种修复模式的 commit（如添加锁的 commit、修复引用计数的 commit 等）。

    Returns:
        Dict with:
        - needs_lock_fix: 是否需要锁相关的修复
        - needs_refcount_fix: 是否需要引用计数修复
        - needs_rcu_fix: 是否需要 RCU 相关修复
        - needs_null_check: 是否需要空指针检查
        - needs_bound_check: 是否需要边界检查
        - suggested_search_keywords: 建议的搜索关键词
    """
    result = {
        "needs_lock_fix": False,
        "needs_refcount_fix": False,
        "needs_rcu_fix": False,
        "needs_null_check": False,
        "needs_bound_check": False,
        "suggested_search_keywords": [],
    }

    # 基于 bug_type 推断
    bug_type_hints = {
        "deadlock": {"needs_lock_fix": True, "keywords": ["spin_lock", "mutex_lock", "lock order", "lockdep"]},
        "race_condition": {"needs_lock_fix": True, "needs_rcu_fix": True, "keywords": ["spin_lock", "mutex_lock", "atomic", "synchronization", "rcu"]},
        "use_after_free": {"needs_refcount_fix": True, "needs_rcu_fix": True, "keywords": ["kref", "refcount", "kfree_rcu", "synchronize_rcu"]},
        "double_free": {"needs_refcount_fix": True, "keywords": ["kref_put", "refcount_dec", "NULL after free"]},
        "null_pointer": {"needs_null_check": True, "keywords": ["NULL check", "null check", "error handling"]},
        "buffer_overflow": {"needs_bound_check": True, "keywords": ["strscpy", "snprintf", "bounds check", "size check"]},
        "out_of_bound": {"needs_bound_check": True, "keywords": ["bounds check", "index check", "array size"]},
        "memory_leak": {"needs_refcount_fix": True, "keywords": ["kfree", "memory leak", "free", "put"]},
        "memory_corruption": {"needs_lock_fix": True, "needs_refcount_fix": True, "keywords": ["spin_lock", "mutex_lock", "refcount", "synchronization"]},
        "hang": {"needs_lock_fix": True, "keywords": ["cond_resched", "schedule_timeout", "timeout", "spin_unlock"]},
        "concurrency": {"needs_lock_fix": True, "keywords": ["spin_lock", "mutex_lock", "atomic", "cmpxchg"]},
        "security": {"needs_lock_fix": True, "needs_refcount_fix": True, "needs_bound_check": True, "keywords": ["CVE", "security", "privilege", "bounds"]},
    }

    hints = bug_type_hints.get(bug_type, {})
    for key in ["needs_lock_fix", "needs_refcount_fix", "needs_rcu_fix", "needs_null_check", "needs_bound_check"]:
        if hints.get(key):
            result[key] = True
    if hints.get("keywords"):
        result["suggested_search_keywords"].extend(hints["keywords"])

    # 基于调用栈分析补充
    lock_funcs = call_trace_analysis.get("lock_functions", [])
    rcu_funcs = call_trace_analysis.get("rcu_functions", [])
    memory_funcs = call_trace_analysis.get("memory_functions", [])

    if lock_funcs:
        result["needs_lock_fix"] = True
        if "spin_lock" not in str(result["suggested_search_keywords"]):
            result["suggested_search_keywords"].extend(["spin_lock", "mutex_lock"])

    if rcu_funcs:
        result["needs_rcu_fix"] = True
        if "rcu" not in str(result["suggested_search_keywords"]):
            result["suggested_search_keywords"].append("kfree_rcu")

    if memory_funcs and "kfree" in str(memory_funcs):
        result["needs_refcount_fix"] = True

    # 基于 Panic 消息补充
    panic_lower = panic_msg.lower()
    if "null pointer" in panic_lower:
        result["needs_null_check"] = True
    if "out of bound" in panic_lower or "overflow" in panic_lower:
        result["needs_bound_check"] = True

    # 去重
    result["suggested_search_keywords"] = list(set(result["suggested_search_keywords"]))

    return result


# ============================================================================
# 检索查询构造 — 为下游向量检索模块生成优化的查询文本
# ============================================================================

def build_retrieval_query(
    feature: CrashFeature,
    root_cause: str,
    bug_type: str,
    causal_chain: List[str],
    fix_hints: Dict[str, Any],
    trace_analysis: Dict[str, Any],
) -> str:
    """构造优化的检索查询语句

    生成的查询文本用于 BGE-M3 嵌入编码后送入 Milvus 向量检索。
    查询结构融合了多层语义信息，以桥接"宕机现象"与"补丁描述"的表述鸿沟。

    策略:
    1. 以根因描述为主干（语义层）
    2. 附加 Bug 类型和子系统信息（领域知识层）
    3. 附加调用栈关键函数名（结构层）
    4. 附加修复模式提示（修复语义层）
    """
    parts = []

    # 1. 根因描述（核心语义）
    parts.append(f"RootCause: {root_cause}")

    # 2. 结构化领域知识
    if bug_type and bug_type != "unknown":
        parts.append(f"BugType: {bug_type.replace('_', ' ')}")
    if feature.subsystem and feature.subsystem != "unknown":
        parts.append(f"Subsystem: {feature.subsystem}")
    if feature.kernel_version:
        parts.append(f"KernelVersion: {feature.kernel_version}")

    # 3. Panic 消息摘要
    if feature.panic_msg:
        parts.append(f"PanicInfo: {feature.panic_msg}")

    # 4. 调用栈关键函数
    key_funcs = (
        trace_analysis.get("lock_functions", [])[:3]
        + trace_analysis.get("memory_functions", [])[:3]
        + trace_analysis.get("rcu_functions", [])[:3]
    )
    if key_funcs:
        parts.append(f"KeyFunctions: {', '.join(key_funcs)}")

    # 5. 修复模式提示 — 这是关键：告诉检索器要找什么类型的修复
    fix_pattern_parts = []
    if fix_hints.get("needs_lock_fix"):
        fix_pattern_parts.append("adds spin_lock or mutex_lock synchronization")
    if fix_hints.get("needs_refcount_fix"):
        fix_pattern_parts.append("adds refcount_inc/kref_get or fixes kref_put pairing")
    if fix_hints.get("needs_rcu_fix"):
        fix_pattern_parts.append("adds kfree_rcu or synchronize_rcu protection")
    if fix_hints.get("needs_null_check"):
        fix_pattern_parts.append("adds NULL pointer check or error handling")
    if fix_hints.get("needs_bound_check"):
        fix_pattern_parts.append("adds boundary check or buffer size validation")

    if fix_pattern_parts:
        parts.append(f"FixPattern: commit that {'; '.join(fix_pattern_parts)}")

    # 6. 因果链摘要
    if causal_chain:
        parts.append(f"CausalChain: {' -> '.join(causal_chain[:5])}")

    return "\n".join(parts)


# ============================================================================
# 知识模块集成 — 尝试加载知识库增强分析
# ============================================================================

def _try_load_knowledge() -> Dict[str, Any]:
    """加载知识模块，返回可用的知识查询接口

    返回值包含实际可调用的知识查询函数，而非布尔标志。
    每个模块独立加载，单个模块失败不影响其他模块。
    """
    knowledge: Dict[str, Any] = {
        "bug_patterns_available": False,
        "lock_rules_available": False,
        "subsystem_graph_available": False,
        # 实际的知识查询函数引用
        "search_bug_by_symptom": None,
        "get_bug_pattern": None,
        "get_all_bug_types": None,
        "analyze_lock_usage": None,
        "match_deadlock_pattern": None,
        "get_lock_type": None,
        "get_subsystem_info": None,
        "get_related_subsystems": None,
        "get_all_subsystems": None,
        "list_subsystems_by_bug_type": None,
    }

    # ── 加载 Bug 模式知识库 ──────────────────────────────────────
    try:
        from ...knowledge.bug_patterns import (
            search_bug_by_symptom,
            get_bug_pattern,
            get_all_bug_types,
        )
        knowledge["bug_patterns_available"] = True
        knowledge["search_bug_by_symptom"] = search_bug_by_symptom
        knowledge["get_bug_pattern"] = get_bug_pattern
        knowledge["get_all_bug_types"] = get_all_bug_types
    except ImportError:
        pass

    # ── 加载锁规则知识库 ────────────────────────────────────────
    try:
        from ...knowledge.lock_rules import (
            analyze_lock_usage,
            match_deadlock_pattern,
            get_lock_type,
        )
        knowledge["lock_rules_available"] = True
        knowledge["analyze_lock_usage"] = analyze_lock_usage
        knowledge["match_deadlock_pattern"] = match_deadlock_pattern
        knowledge["get_lock_type"] = get_lock_type
    except ImportError:
        pass

    # ── 加载子系统关系图 ────────────────────────────────────────
    try:
        from ...knowledge.subsystem_graph import (
            get_subsystem_info,
            get_related_subsystems,
            get_all_subsystems,
            list_subsystems_by_bug_type,
        )
        knowledge["subsystem_graph_available"] = True
        knowledge["get_subsystem_info"] = get_subsystem_info
        knowledge["get_related_subsystems"] = get_related_subsystems
        knowledge["get_all_subsystems"] = get_all_subsystems
        knowledge["list_subsystems_by_bug_type"] = list_subsystems_by_bug_type
    except ImportError:
        pass

    return knowledge


# ============================================================================
# 根因分析器 — 核心分析引擎
# ============================================================================

class RootCauseAnalyzer:
    """根因分析器 — 融合专家经验与语义理解的核心引擎

    采用分层分析策略（从精确到模糊，逐层降级）:
    Layer 1: 专家规则精确匹配 (Exact Rule Match)
    Layer 2: 调用栈结构分析 (Call Trace Structure Analysis)
    Layer 3: 通用 Bug 类型抽象 (Generic Bug Type Abstraction)
    Layer 4: Panic 消息关键词推断 (Panic Message Keyword Inference)
    """

    def __init__(self):
        self.rules = EXPERT_RULES
        self.knowledge = _try_load_knowledge()

    def _match_rules(
        self, feature: CrashFeature
    ) -> Optional[Tuple[Dict[str, Any], float, str]]:
        """Layer 1: 专家规则匹配

        优先级: panic_msg 精确匹配 > panic_msg 关键词 > call_trace 关键词
        """
        trace_text = "\n".join(feature.call_trace).lower() if feature.call_trace else ""
        panic_text = feature.panic_msg.lower() if feature.panic_msg else ""
        combined_text = f"{panic_text}\n{trace_text}"

        best_match = None
        best_score = 0.0
        best_match_type = ""

        for rule in self.rules:
            score = 0.0
            match_type = ""

            # 1) panic_patterns 精确匹配 (最高权重)
            for pattern in rule.get("panic_patterns", []):
                if pattern and feature.panic_msg:
                    import re
                    if re.search(pattern, feature.panic_msg, re.IGNORECASE):
                        score = 0.95
                        match_type = f"panic_pattern:{pattern[:50]}"
                        break

            # 2) panic_msg 关键词匹配
            if score < 0.9:
                for kw in rule.get("keywords", []):
                    if kw.lower() in panic_text:
                        score = max(score, 0.85)
                        match_type = f"panic_keyword:{kw}"
                        break

            # 3) call_trace 关键词匹配
            if score < 0.8:
                for kw in rule.get("keywords", []):
                    if kw.lower() in trace_text:
                        score = max(score, 0.70)
                        match_type = f"trace_keyword:{kw}"
                        break

            # 4) 组合文本匹配 (panic + trace 联合检查)
            if score < 0.7:
                for kw in rule.get("keywords", []):
                    if kw.lower() in combined_text:
                        score = max(score, 0.60)
                        match_type = f"combined_keyword:{kw}"
                        break

            if score > best_score:
                best_score = score
                best_match = rule
                best_match_type = match_type

        if best_match and best_score > 0:
            return best_match, best_score, best_match_type

        return None

    def _match_by_trace_structure(
        self, trace_analysis: Dict[str, Any], feature: CrashFeature
    ) -> Optional[Tuple[str, str, float]]:
        """Layer 2: 基于调用栈结构推断根因"""
        inferred = trace_analysis.get("inferred_issue", "unknown")

        if inferred == "deadlock_or_lock_contention":
            return (
                "Lock Contention / Potential Deadlock",
                "调用栈中同时出现锁函数和调度函数，推断发生了锁竞争或死锁。",
                0.65,
            )
        elif inferred == "possible_lock_issue":
            return (
                "Possible Lock-Related Issue",
                "调用栈中检测到锁相关函数，推断与锁操作有关。",
                0.55,
            )
        elif inferred == "rcu_related":
            return (
                "RCU-Related Issue",
                "调用栈中检测到 RCU 相关函数，推断与 RCU 保护或宽限期有关。",
                0.55,
            )
        elif inferred == "memory_related":
            return (
                "Memory Management Issue",
                "调用栈中检测到内存分配/释放相关函数，推断与内存管理有关。",
                0.50,
            )
        elif inferred == "scheduling_related":
            return (
                "Scheduling-Related Issue",
                "调用栈中检测到调度相关函数，可能涉及 hungtask 或调度延迟。",
                0.50,
            )

        return None

    def _match_by_bug_type(self, feature: CrashFeature) -> Optional[Tuple[str, str, float]]:
        """Layer 3: 基于 bug_type 的通用抽象"""
        if feature.bug_type and feature.bug_type != "unknown":
            bug_type_descriptions = {
                "deadlock": ("Kernel Deadlock", "检测到死锁特征，需要分析锁依赖关系。", 0.50),
                "race_condition": ("Kernel Race Condition", "检测到竞态条件特征，需要添加同步机制。", 0.50),
                "use_after_free": ("Use-After-Free", "检测到释放后使用特征，需要修复内存生命周期管理。", 0.50),
                "null_pointer": ("Null Pointer Dereference", "检测到空指针特征，需要添加空指针检查。", 0.50),
                "double_free": ("Double Free", "检测到重复释放特征，需要修复释放逻辑。", 0.50),
                "buffer_overflow": ("Buffer Overflow", "检测到缓冲区溢出特征，需要添加边界检查。", 0.50),
                "out_of_bound": ("Out-of-Bounds Access", "检测到越界访问特征，需要添加索引检查。", 0.50),
                "memory_leak": ("Memory Leak", "检测到内存泄漏特征，需要修复资源释放逻辑。", 0.45),
                "memory_corruption": ("Memory Corruption", "检测到内存损坏特征，可能由竞态或缓冲区问题引起。", 0.50),
                "hang": ("System Hang", "检测到系统挂起特征，需要分析阻塞点。", 0.50),
                "crash": ("Kernel Crash", "检测到内核崩溃特征，需要结合 Call Trace 定位原因。", 0.45),
                "security": ("Security Vulnerability", "检测到安全漏洞特征，需优先修复。", 0.55),
                "regression": ("Kernel Regression", "检测到回归问题，需要 bisect 定位引入的 commit。", 0.40),
                "concurrency": ("Concurrency Issue", "检测到并发问题，需要分析同步机制。", 0.50),
            }

            desc = bug_type_descriptions.get(feature.bug_type)
            if desc:
                return desc

        return None

    def _match_by_panic_keywords(self, feature: CrashFeature) -> Optional[Tuple[str, str, float]]:
        """Layer 4: 基于 panic 消息中的关键字进行最后兜底推断"""
        if not feature.panic_msg:
            return None

        msg_lower = feature.panic_msg.lower()

        panic_hints = [
            (r"spin.?lock", "Possible Spinlock Issue", "Panic 消息包含自旋锁相关关键词", 0.45),
            (r"mutex", "Possible Mutex Issue", "Panic 消息包含互斥锁相关关键词", 0.45),
            (r"deadlock", "Possible Deadlock", "Panic 消息包含死锁关键词", 0.50),
            (r"race", "Possible Race Condition", "Panic 消息包含竞态关键词", 0.45),
            (r"uaf|use.?after.?free", "Possible Use-After-Free", "Panic 消息包含 UAF 关键词", 0.50),
            (r"double.?free", "Possible Double Free", "Panic 消息包含 double-free 关键词", 0.50),
            (r"null.*pointer", "Possible Null Pointer", "Panic 消息包含空指针关键词", 0.50),
            (r"oob|out.?of.?bound", "Possible Out-of-Bounds", "Panic 消息包含越界关键词", 0.45),
            (r"overflow", "Possible Overflow", "Panic 消息包含溢出关键词", 0.40),
            (r"corruption|corrupt", "Possible Memory Corruption", "Panic 消息包含损坏关键词", 0.45),
            (r"timeout|timed.?out", "Possible Timeout", "Panic 消息包含超时关键词", 0.40),
            (r"stall|stuck|hung", "Possible Task Stall", "Panic 消息包含停滞关键词", 0.45),
            (r"oom|out.?of.?memory", "Possible OOM", "Panic 消息包含 OOM 关键词", 0.50),
        ]

        import re
        for pattern, name, desc, score in panic_hints:
            if re.search(pattern, msg_lower):
                return (name, desc, score)

        return None

    def _apply_knowledge_enhancement(
        self,
        result: RootCauseResult,
        feature: CrashFeature,
        trace_analysis: Dict[str, Any],
    ) -> None:
        """★ 知识库增强分析 — 使用领域知识增强根因推理结果

        在 Layer 2 (调用栈结构推断) 之后调用，利用 knowledge/ 下的
        bug_patterns / lock_rules / subsystem_graph 增强分析结果。

        增强维度:
        1. Bug 模式匹配 → 提升置信度、补充修复模式
        2. 锁使用分析 → 检测调用栈中的锁问题
        3. 子系统关系推断 → 扩展影响范围
        """
        k = self.knowledge  # 已在 __init__ 中通过 _try_load_knowledge() 加载

        # ── 1. Bug 模式匹配 — 增强置信度 ──────────────────────────
        if k.get("bug_patterns_available") and k.get("search_bug_by_symptom"):
            if feature.panic_msg:
                bug_info = k["search_bug_by_symptom"](feature.panic_msg)
                if bug_info:
                    result.extra_info["knowledge_bug_match"] = bug_info
                    if not result.root_cause:
                        # 知识库作为主要推断来源（Layer 2.5）
                        result.root_cause = bug_info[0]["name"]
                        result.bug_type = bug_info[0]["bug_type"]
                        result.score = min(0.90, bug_info[0]["match_score"] * 0.2 + 0.6)
                        result.reason = f"匹配到知识库中的 {bug_info[0]['name']} 模式"
                        result.causal_chain.append(
                            f"Knowledge Base: {bug_info[0]['name']} "
                            f"(score={bug_info[0]['match_score']})"
                        )
                    else:
                        # 已有根因时，知识库提供双重确认
                        result.score = max(result.score, 0.85)

        # ── 2. 锁规则分析 — 补充调用栈中的锁使用信息 ──────────────
        if k.get("lock_rules_available") and k.get("analyze_lock_usage"):
            if feature.call_trace:
                lock_analysis = k["analyze_lock_usage"](feature.call_trace)
                if lock_analysis.get("lock_types") or lock_analysis.get("potential_issues"):
                    result.extra_info["lock_analysis"] = lock_analysis
                    if lock_analysis.get("potential_issues"):
                        for issue in lock_analysis["potential_issues"]:
                            result.causal_chain.append(f"Lock Issue: {issue}")

        # ── 3. 子系统关系推断 — 扩展影响范围 ──────────────────────
        if k.get("subsystem_graph_available"):
            if feature.subsystem and feature.subsystem != "unknown":
                if k.get("get_subsystem_info"):
                    subsystem_info = k["get_subsystem_info"](feature.subsystem)
                    if subsystem_info:
                        result.extra_info["subsystem_info"] = subsystem_info
                if k.get("get_related_subsystems"):
                    related_subsystems = k["get_related_subsystems"](feature.subsystem)
                    if related_subsystems and len(related_subsystems) > 1:
                        result.extra_info["related_subsystems"] = related_subsystems
                        result.causal_chain.append(
                            f"Related Subsystems: {', '.join(related_subsystems)}"
                        )

    def analyze(self, feature: CrashFeature) -> RootCauseResult:
        """执行分层根因分析

        分析流程:
        1. 调用栈结构分析（始终执行，提供底层信号）
        2. Layer 1: 专家规则匹配
        3. Layer 2: 调用栈结构推断
        4. Layer 3: Bug 类型通用抽象
        5. Layer 4: Panic 消息关键词推断
        6. 修复模式推断
        7. 检索查询构造
        """
        result = RootCauseResult(crash_feature=feature)

        # Step 0: 调用栈结构分析 — 始终执行
        trace_analysis = analyze_call_trace_structure(feature.call_trace)
        result.extra_info["trace_analysis"] = trace_analysis

        # 如果 dmesg 层已经识别了 subsystem，优先使用
        if feature.subsystem == "unknown" and trace_analysis["involved_subsystem"] != "unknown":
            feature.subsystem = trace_analysis["involved_subsystem"]

        # Layer 1: 专家规则匹配
        rule_match = self._match_rules(feature)
        if rule_match:
            rule, score, match_info = rule_match
            result.root_cause = rule["name"]
            result.bug_type = rule.get("bug_type", feature.bug_type)
            result.score = score
            result.reason = rule["description"]
            result.causal_chain.append(f"Expert Rule: {rule['id']} ({match_info})")
            result.causal_chain.append(f"Severity: {SEVERITY_MAP.get(rule.get('severity', 5), 'Unknown')}")
            result.extra_info["rule_id"] = rule["id"]
            result.extra_info["severity"] = rule.get("severity", 5)
            result.extra_info["fix_hints"] = rule.get("fix_hints", {})
            result.extra_info["related_subsystems"] = rule.get("related_subsystems", [])

        # Layer 2: 调用栈结构推断
        if not result.root_cause:
            trace_match = self._match_by_trace_structure(trace_analysis, feature)
            if trace_match:
                name, desc, score = trace_match
                result.root_cause = name
                result.bug_type = trace_analysis.get("inferred_issue", feature.bug_type)
                result.score = score
                result.reason = desc
                result.causal_chain.append(f"Trace Structure: {name}")
                if trace_analysis.get("lock_functions"):
                    result.causal_chain.append(
                        f"Lock Functions in trace: {', '.join(trace_analysis['lock_functions'][:5])}"
                    )
                if trace_analysis.get("memory_functions"):
                    result.causal_chain.append(
                        f"Memory Functions in trace: {', '.join(trace_analysis['memory_functions'][:5])}"
                    )
                if trace_analysis.get("rcu_functions"):
                    result.causal_chain.append(
                        f"RCU Functions in trace: {', '.join(trace_analysis['rcu_functions'][:5])}"
                    )

        # ★ Step 2.5: 知识库增强分析 — 领域知识 (bug_patterns + lock_rules + subsystem_graph)
        self._apply_knowledge_enhancement(result, feature, trace_analysis)

        # Layer 3: Bug 类型通用抽象
        if not result.root_cause:
            bug_match = self._match_by_bug_type(feature)
            if bug_match:
                name, desc, score = bug_match
                result.root_cause = name
                result.bug_type = feature.bug_type
                result.score = score
                result.reason = desc
                result.causal_chain.append(f"Bug Type: {feature.bug_type}")

        # Layer 4: Panic 消息关键词推断
        if not result.root_cause:
            panic_match = self._match_by_panic_keywords(feature)
            if panic_match:
                name, desc, score = panic_match
                result.root_cause = name
                result.bug_type = feature.bug_type
                result.score = score
                result.reason = desc
                result.causal_chain.append(f"Panic Keyword: {name}")
            else:
                # 最终兜底
                result.root_cause = "Unknown Root Cause"
                result.bug_type = feature.bug_type if feature.bug_type != "unknown" else "crash"
                result.score = 0.10
                result.reason = "无法从可用特征中确定根因。建议人工检查 vmcore 和完整 dmesg。"
                result.causal_chain.append("Insufficient information for root cause determination")

        # Step 5: 构建因果链补充信息
        if feature.subsystem and feature.subsystem != "unknown":
            if not any("Subsystem" in c for c in result.causal_chain):
                result.causal_chain.append(f"Affected Subsystem: {feature.subsystem}")
        if feature.kernel_version:
            result.causal_chain.append(f"Kernel Version: {feature.kernel_version}")
        if feature.modules:
            result.causal_chain.append(f"Loaded Modules: {', '.join(feature.modules[:10])}")

        # Step 6: 修复模式推断 — 始终调用以补全 suggested_search_keywords
        rule_fix_hints = result.extra_info.get("fix_hints", {})
        inferred_fix = infer_fix_patterns(
            bug_type=result.bug_type,
            call_trace_analysis=trace_analysis,
            panic_msg=feature.panic_msg,
        )
        # 合并: 规则 fix_hints 优先（精确），补充推断结果中的 suggested_keywords
        fix_hints = {**inferred_fix, **rule_fix_hints}
        # 确保 suggested_search_keywords 综合了规则信息和推断结果
        rule_keywords = rule_fix_hints.get("suggested_search_keywords", [])
        inferred_keywords = inferred_fix.get("suggested_search_keywords", [])
        fix_hints["suggested_search_keywords"] = list(set(rule_keywords + inferred_keywords))
        result.extra_info["fix_hints"] = fix_hints

        # Step 7: 构造检索查询
        retrieval_query = build_retrieval_query(
            feature=feature,
            root_cause=result.root_cause,
            bug_type=result.bug_type,
            causal_chain=result.causal_chain,
            fix_hints=fix_hints,
            trace_analysis=trace_analysis,
        )
        result.retrieval_query = retrieval_query
        result.suggested_keywords = fix_hints.get("suggested_search_keywords", [])

        return result


# ============================================================================
# 公共 API
# ============================================================================

# 模块级单例（避免重复初始化规则列表）
_analyzer: Optional[RootCauseAnalyzer] = None


def get_analyzer() -> RootCauseAnalyzer:
    """获取根因分析器单例"""
    global _analyzer
    if _analyzer is None:
        _analyzer = RootCauseAnalyzer()
    return _analyzer


def abstract_root_cause(feature: CrashFeature) -> RootCauseResult:
    """根因抽象主入口

    将 CrashFeature 转化为包含根因诊断、因果链、检索查询的 RootCauseResult。
    这是连接 dmesg/vmcore 解析与向量检索的关键环节。

    Args:
        feature: 从 dmesg/vmcore 中提取的结构化特征

    Returns:
        RootCauseResult: 包含根因诊断、因果链、置信度评分、检索查询等完整信息

    Example:
        >>> feature = CrashFeature(panic_msg="BUG: list_del corruption", call_trace=[...])
        >>> result = abstract_root_cause(feature)
        >>> print(result.root_cause)     # "Memory Corruption (List)"
        >>> print(result.retrieval_query) # 优化后的检索查询文本
    """
    analyzer = get_analyzer()
    return analyzer.analyze(feature)


def list_all_rules() -> List[Dict[str, Any]]:
    """列出所有已注册的专家规则"""
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "bug_type": r["bug_type"],
            "severity": r.get("severity", 5),
            "description": r["description"],
        }
        for r in EXPERT_RULES
    ]


def get_rule_by_id(rule_id: str) -> Optional[Dict[str, Any]]:
    """根据 ID 获取专家规则详情"""
    for r in EXPERT_RULES:
        if r["id"] == rule_id:
            return r
    return None


__all__ = [
    "RootCauseAnalyzer",
    "abstract_root_cause",
    "get_analyzer",
    "list_all_rules",
    "get_rule_by_id",
    "analyze_call_trace_structure",
    "infer_fix_patterns",
    "build_retrieval_query",
    "EXPERT_RULES",
    "LOCK_TRACE_FUNCTIONS",
    "MEMORY_TRACE_FUNCTIONS",
    "RCU_TRACE_FUNCTIONS",
    "SCHED_TRACE_FUNCTIONS",
]
