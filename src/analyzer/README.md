# Analyzer 模块

宕机分析核心模块，负责从 `dmesg` 日志和 `vmcore` 文件中提取故障特征，并进行根因抽象分析。

## 模块架构

```text
analyzer/
├── __init__.py       # 模块入口，整合所有子模块
├── models/           # 数据模型定义 (CrashFeature, RootCauseResult)
├── dmesg/            # dmesg 日志正则解析模块
├── vmcore/           # vmcore 深度解析模块 (基于 drgn)
├── rootcause/        # 根因抽象模型 (专家规则 + 语义理解)
└── pipeline/         # 分析流水线编排模块
```

## 功能说明

### 1. 特征提取 (Feature Extraction)

- **dmesg 解析**: 使用正则表达式快速定位 `Call Trace`，提取 `Panic` 消息、子系统和初步 Bug 类型。
- **vmcore 解析**: 预留 `drgn` 接口，支持从内核转储文件中提取完整的内核对象状态、寄存器信息和调用栈。

### 2. 根因抽象 (Root Cause Abstraction)

- **语义理解**: 跨越宕机现象与补丁描述的表述鸿沟，将原始日志抽象为结构化的根因。
- **领域知识融合**: 内置专家规则库，识别典型的内核故障模式（如 `Spinlock Deadlock`, `UAF`, `NULL Pointer Dereference`）。
- **因果链构建**: 记录分析过程中的推导逻辑，提升结果的可解释性。

### 3. 分析流水线 (Pipeline)

- 提供统一的 `run_analysis_pipeline` 接口，支持多模态输入（dmesg, vmcore），自动协调解析与抽象流程。

## 使用示例

```python
from src.analyzer import run_analysis_pipeline

# 运行分析流水线
result = run_analysis_pipeline(
    dmesg_content="Kernel panic - not syncing: BUG: unable to handle kernel NULL pointer dereference...",
    vmcore_path="/path/to/vmcore",
    vmlinux_path="/path/to/vmlinux"
)

print(f"Root Cause: {result.root_cause}")
print(f"Reason: {result.reason}")
print(f"Causal Chain: {result.causal_chain}")
```

## 检索算法亮点符合度

- **语义理解能力**: 通过 `RootCauseResult` 消除原始日志的表述偏差。
- **领域知识融合**: `rootcause` 模块集成了 Linux 内核专家经验。
- **场景泛化性**: 模块化设计支持扩展更多宕机类型（hardlockup/hungtask 等）。
