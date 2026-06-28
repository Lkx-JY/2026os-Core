# Common — 公共模块

> **Exceptions + Logging + Utilities**

提供项目中各模块共用的基础设施层。

---

## 目录

1. [模块架构](#1-模块架构)
2. [子模块说明](#2-子模块说明)
3. [使用指南](#3-使用指南)

---

## 1. 模块架构

```
src/common/
├── __init__.py                # 模块入口 — 统一导出所有公共 API
├── exceptions/__init__.py     # ★ 层次化异常类体系 (7 大类 21 种异常)
├── logging/__init__.py        # ★ 统一日志系统 (loguru)
├── utils/__init__.py          # ★ 工具函数集合 (30+ 函数)
├── config.py                  # ★ 统一配置中心 (环境变量 + YAML)
├── taxonomy.py                # ★ Bug 类型标准分类体系 (跨模块标准化)
└── README.md                  # 本文档
```

---

## 2. 子模块说明

### 2.1 exceptions — 异常类体系

**职责**: 定义层次化的异常类，便于统一错误处理。

**异常层次结构**:

```
CoreLinuxCommitError (E000)       # 基础异常
├── ConfigurationError (E001)     # 配置异常
│   ├── MissingConfigError        # 缺少配置
│   └── InvalidConfigError        # 配置无效
├── DataError (E010)              # 数据异常
│   ├── ParsingError (E011)       # 解析失败
│   └── InvalidDataFormat (E012)  # 格式无效
├── AnalysisError (E020)          # 分析异常
│   ├── DmesgParsingError         # dmesg 解析
│   ├── VmcoreAnalysisError       # vmcore 解析
│   └── RootCauseAnalysisError    # 根因分析
├── IndexingError (E030)          # 索引异常
│   ├── EmbeddingError            # 向量编码
│   └── VectorDBError             # 向量库操作
├── RetrievalError (E040)         # 检索异常
├── LLMError (E050)               # LLM 异常
│   ├── LLMUnavailableError       # 服务不可用
│   └── LLMResponseError          # 响应解析
└── DependencyError (E060)        # 依赖异常
    ├── GitRepoError              # Git 操作
    ├── DrgnError                 # drgn 工具
    └── ModelNotAvailableError    # 模型不可用
```

**使用示例**:
```python
from src.common import MissingConfigError, LLMUnavailableError

raise MissingConfigError("database.path")
raise LLMUnavailableError(model="deepseek-chat", reason="Connection timeout")
```

### 2.2 logging — 日志系统

**职责**: 基于 loguru 的统一日志管理。

**核心功能**:

| 功能 | 说明 |
|------|------|
| **多级别输出** | DEBUG (文件) + INFO (控制台) + ERROR (单独文件) |
| **自动轮转** | 按大小/时间自动轮转，旧日志自动压缩 |
| **结构化日志** | 支持 JSON 格式用于日志收集分析 |
| **性能计时** | `log_time()` 和 `@timed` 自动记录执行时间 |
| **事件日志** | `log_event()` 记录结构化事件 |
| **降级方案** | loguru 不可用时自动使用标准 logging |

**使用示例**:
```python
from src.common import get_logger, log_time, log_event, timed

logger = get_logger()

# 性能计时 — 上下文管理器
with log_time("vector_search"):
    results = client.search(query_vec)
# 输出: vector_search completed in 12.34ms

# 性能计时 — 装饰器
@timed(level="INFO")
def heavy_operation():
    ...

# 结构化事件
log_event("diagnosis_completed", {
    "bug_type": "use_after_free",
    "confidence": 0.85,
    "duration_ms": 1234,
})
```

### 2.3 utils — 工具函数

**职责**: 项目各模块共用的纯函数工具集。

**函数分类**:

| 类别 | 函数 | 用途 |
|------|------|------|
| **字符串** | `truncate_text`, `clean_text`, `extract_commit_hash`, `extract_cve_ids`, `extract_email` | 文本处理 |
| **文件** | `ensure_dir`, `safe_filename`, `get_file_size_mb` | 文件操作 |
| **哈希** | `hash_text`, `short_hash`, `generate_id` | 哈希与 ID 生成 |
| **数值** | `safe_divide`, `sigmoid`, `normalize_scores`, `softmax` | 数值计算 |
| **时间** | `format_duration`, `parse_kernel_version`, `compare_kernel_versions` | 时间/版本 |
| **批处理** | `batch_iterate`, `chunk_list` | 批量数据分批 |
| **转换** | `flatten_dict`, `safe_json_loads`, `to_bool` | 数据转换 |
| **缓存** | `memoize` | 函数结果缓存装饰器 |
| **调试** | `get_call_info`, `memory_usage_mb`, `profile` | 开发调试 |

### 2.4 config — 统一配置中心

**职责**: 所有 LLM、Milvus、应用配置的中心入口。支持环境变量覆盖，优先级: 环境变量 > config.yaml。

**核心功能**:

| 功能 | 说明 |
|------|------|
| **单例模式** | `get_config()` 全局共享，`@lru_cache` 缓存 |
| **环境变量覆盖** | 所有配置项支持 `ENV_VAR` 覆盖 YAML |
| **API Key 管理** | 用户通过 `OPENAI_API_KEY` 自行配置，用户承担费用 |
| **项目根目录** | `get_project_root()` 自动检测 |

**使用示例**:
```python
from src.common.config import get_config, get_project_root

config = get_config()
print(config["model"]["embedding"])   # "BAAI/bge-m3"
print(config["database"]["type"])     # "milvus"

root = get_project_root()  # → Path("/path/to/project3136859-388917")
```

### 2.5 taxonomy — Bug 类型标准分类体系

**职责**: 解决跨模块 bug_type 命名不一致问题。`BugType` 枚举为权威来源 (Single Source of Truth)。

**核心功能**:

| 功能 | 说明 |
|------|------|
| **BugType 枚举** | 25 种标准 Bug 类型 (内存 10 + 并发 4 + 稳定性 5 + 安全 2 + 其他 4) |
| **别名映射** | `BUG_TYPE_ALIASES` — 旧名 → 标准名自动映射 |
| **标准化** | `normalize_bug_type()` — 任意输入 → BugType 枚举 |

**使用示例**:
```python
from src.common.taxonomy import BugType, normalize_bug_type

# 标准化任意输入
bug_type = normalize_bug_type("UAF")          # → BugType.USE_AFTER_FREE
bug_type = normalize_bug_type("null pointer") # → BugType.NULL_POINTER

# 枚举使用
if bug_type == BugType.USE_AFTER_FREE:
    print("Critical memory error")
```

---

## 3. 使用指南

### 3.1 配置加载

```python
from src.common.config import get_config, get_project_root

config = get_config()
root = get_project_root()
```

### 3.2 统一错误处理

```python
from src.common import (
    CoreLinuxCommitError,
    ConfigurationError,
    AnalysisError,
    log_error_with_context,
)

try:
    result = run_diagnosis(dmesg_log)
except ConfigurationError as e:
    log_error_with_context(e, {"config_file": "config.yaml"})
    raise
except AnalysisError as e:
    log_error_with_context(e, {"dmesg_preview": dmesg_log[:200]})
    # 降级处理
```

### 3.3 日志配置

```python
from src.common import setup_logging

logger = setup_logging(
    log_dir="logs",
    console_level="INFO",
    file_level="DEBUG",
    rotation="50 MB",
    retention="14 days",
)
```

### 3.4 工具函数使用

```python
from src.common import (
    parse_kernel_version,
    format_duration,
    normalize_scores,
    batch_iterate,
)

# 版本比较
major, minor, patch = parse_kernel_version("6.1.0-rc3")

# 时间格式化
print(format_duration(123456))  # "2m 3s"

# 批量处理
for batch in batch_iterate(items, batch_size=64):
    vectors = encoder.encode(batch)
```
