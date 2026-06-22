"""统一配置模块 — Centralized Configuration

所有 LLM、Milvus、应用配置的中心入口。
API Key 由用户通过环境变量 OPENAI_API_KEY 自行配置，用户承担费用。

设计原则:
- API Key 必须由用户配置，启动时检查，未配置则报错
- 所有配置支持环境变量覆盖，优先级: 环境变量 > config.yaml
- 提供单例模式，全局共享配置实例
"""

import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from functools import lru_cache

# 配置缓存大小（1 = 只缓存单例配置结果）
_CONFIG_CACHE_SIZE = 1


# ============================================================================
# 项目根目录
# ============================================================================

def get_project_root() -> Path:
    """获取项目根目录（src/common/config.py → src/common → src → project_root）"""
    return Path(__file__).resolve().parent.parent.parent


PROJECT_ROOT = get_project_root()


# ============================================================================
# API Key 校验
# ============================================================================

def _check_api_key(api_key: Optional[str]) -> str:
    """校验 API Key 是否已配置

    Args:
        api_key: 从环境变量读取的值

    Returns:
        非空的 API Key 字符串

    Raises:
        ValueError: 如果未配置 API Key 且未设置 SKIP_API_KEY_CHECK
    """
    skip_check = os.environ.get("SKIP_API_KEY_CHECK", "").strip() in ("1", "true", "yes")

    if not api_key:
        if skip_check:
            return ""  # 跳过检查，返回空字符串
        raise ValueError(
            "\n"
            "=" * 60 + "\n"
            "  ❌ 未配置 OPENAI_API_KEY\n"
            "=" * 60 + "\n"
            "  请设置环境变量 OPENAI_API_KEY 来配置你的 LLM API Key。\n"
            "\n"
            "  配置方法:\n"
            "    1. 临时设置 (仅当前终端):\n"
            "       export OPENAI_API_KEY=sk-your-api-key-here\n"
            "\n"
            "    2. 永久设置 (推荐):\n"
            "       在 ~/.bashrc 或 ~/.zshrc 中添加:\n"
            "       export OPENAI_API_KEY=sk-your-api-key-here\n"
            "\n"
            "    3. 使用 .env 文件 (项目根目录):\n"
            "       创建 .env 文件并写入:\n"
            "       OPENAI_API_KEY=sk-your-api-key-here\n"
            "\n"
            "  💡 API Key 获取地址:\n"
            "       DeepSeek:  https://platform.deepseek.com/api_keys\n"
            "       OpenAI:    https://platform.openai.com/api-keys\n"
            "       Qwen:      https://dashscope.console.aliyun.com/apiKey\n"
            "\n"
            "  ⚠️  费用说明: 用户自行承担 LLM API 调用费用。\n"
            "     本项目不会记录或上传你的 API Key。\n"
            "\n"
            "  如需跳过检查 (仅本地测试):\n"
            "       export SKIP_API_KEY_CHECK=1\n"
            "=" * 60 + "\n"
        )
    return api_key


# ============================================================================
# 配置加载
# ============================================================================

@lru_cache(maxsize=_CONFIG_CACHE_SIZE)
def load_yaml_config() -> Dict[str, Any]:
    """加载 config.yaml 配置（带缓存）

    Returns:
        配置字典，如果文件不存在则返回空字典
    """
    import yaml

    config_paths = [
        os.environ.get("CONFIG_PATH", ""),
        str(PROJECT_ROOT / "configs" / "config.yaml"),
    ]

    for path in config_paths:
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}

    return {}


# ============================================================================
# 核心配置
# ============================================================================

@lru_cache(maxsize=_CONFIG_CACHE_SIZE)
def get_config() -> Dict[str, Any]:
    """获取完整配置（环境变量 + YAML 合并）

    环境变量优先级高于 YAML 配置。

    Raises:
        ValueError: 如果 OPENAI_API_KEY 未配置
    """
    yaml_config = load_yaml_config()

    # ── LLM 配置 ──────────────────────────────────────
    llm_config = yaml_config.get("llm", {})

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        llm_config.get("base_url") or "https://api.deepseek.com/v1",
    ).strip()
    model = os.environ.get(
        "OPENAI_MODEL",
        llm_config.get("model") or "deepseek-chat",
    ).strip()
    provider = os.environ.get(
        "OPENAI_PROVIDER",
        llm_config.get("provider") or "deepseek",
    ).strip()

    # ★ 启动时校验 — 用户必须自行配置 API Key
    api_key = _check_api_key(api_key)

    # ── 数据库配置 ────────────────────────────────────
    db_config = yaml_config.get("database", {})

    milvus_db_path = os.environ.get(
        "MILVUS_DB_PATH",
        str(PROJECT_ROOT / "data" / "milvus_lite.db"),
    )
    milvus_host = os.environ.get(
        "MILVUS_HOST",
        db_config.get("host", "localhost"),
    )
    milvus_port = os.environ.get(
        "MILVUS_PORT",
        str(db_config.get("port", "19530")),
    )
    force_faiss = os.environ.get("MILVUS_FORCE_FAISS", "").strip() in ("1", "true", "yes")

    # ── 模型配置 ──────────────────────────────────────
    model_config = yaml_config.get("model", {})
    embedding_model = os.environ.get(
        "EMBEDDING_MODEL",
        model_config.get("embedding", "BAAI/bge-m3"),
    )
    reranker_model = os.environ.get(
        "RERANKER_MODEL",
        model_config.get("reranker", "BAAI/bge-reranker-v2-m3"),
    )

    # ── 服务器配置 ────────────────────────────────────
    server_config = yaml_config.get("server", {})
    server_host = os.environ.get("HOST", server_config.get("host", "0.0.0.0"))
    server_port = int(os.environ.get("PORT", str(server_config.get("port", "8000"))))

    return {
        "llm": {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "provider": provider,
        },
        "database": {
            "type": db_config.get("type", "milvus"),
            "host": milvus_host,
            "port": milvus_port,
            "collection_name": db_config.get("collection_name", "linux_commits"),
            "milvus_db_path": milvus_db_path,
            "force_faiss": force_faiss,
        },
        "model": {
            "embedding": embedding_model,
            "reranker": reranker_model,
        },
        "server": {
            "host": server_host,
            "port": server_port,
        },
        "app": yaml_config.get("app", {"name": "core-linuxcommit", "version": "1.0.0"}),
    }


# ============================================================================
# 便捷访问函数
# ============================================================================

def get_llm_api_key() -> str:
    """获取 LLM API Key（已校验）"""
    return get_config()["llm"]["api_key"]


def get_llm_base_url() -> str:
    """获取 LLM API Base URL"""
    return get_config()["llm"]["base_url"]


def get_llm_model() -> str:
    """获取 LLM 模型名称"""
    return get_config()["llm"]["model"]


def get_milvus_db_path() -> str:
    """获取 Milvus Lite 数据库路径"""
    return get_config()["database"]["milvus_db_path"]


def is_api_key_configured() -> bool:
    """检查 API Key 是否已配置（不抛异常）"""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    return len(key) > 0


__all__ = [
    "get_config",
    "get_llm_api_key",
    "get_llm_base_url",
    "get_llm_model",
    "get_milvus_db_path",
    "is_api_key_configured",
    "PROJECT_ROOT",
]
