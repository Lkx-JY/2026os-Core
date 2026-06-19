"""Core.LinuxCommit — 启动脚本

Usage:
    python -m src.main                    # 开发模式启动
    uvicorn src.api:app --reload          # 热重载开发
    gunicorn src.main:app -w 4 -k uvicorn.workers.UvicornWorker  # 生产模式
"""

import os
import sys

# 确保项目根目录在 sys.path 中
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.api import app


def main():
    """开发模式入口"""
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    reload = os.environ.get("RELOAD", "true").lower() == "true"

    # ★ 启动前检查 API Key
    skip_check = os.environ.get("SKIP_API_KEY_CHECK", "").strip() in ("1", "true", "yes")
    if not skip_check:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            print("""
╔══════════════════════════════════════════════════════════╗
║  ❌ 未配置 OPENAI_API_KEY                               ║
╠══════════════════════════════════════════════════════════╣
║  请设置环境变量:                                        ║
║    export OPENAI_API_KEY=sk-your-api-key-here            ║
║                                                        ║
║  API Key 获取:                                          ║
║    https://platform.deepseek.com/api_keys               ║
║                                                        ║
║  ⚠️  费用: 用户自行承担 LLM API 调用费用               ║
║                                                        ║
║  跳过检查 (仅本地测试):                                 ║
║    export SKIP_API_KEY_CHECK=1                          ║
╚══════════════════════════════════════════════════════════╝
""")
            sys.exit(1)

    print(f"""
╔══════════════════════════════════════════════════════════╗
║        Core.LinuxCommit — API Server                    ║
║        Kernel Crash → Patch Matching System             ║
╠══════════════════════════════════════════════════════════╣
║  API Docs:  http://{host}:{port}/api/docs              ║
║  Health:    http://{host}:{port}/health                ║
╚══════════════════════════════════════════════════════════╝
""")

    uvicorn.run(
        "src.api:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
