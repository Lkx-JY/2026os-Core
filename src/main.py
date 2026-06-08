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
