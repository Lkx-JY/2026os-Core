#!/bin/bash
# ============================================================================
# Linux 内核宕机自动诊断与补丁匹配系统 — 一键启动脚本
# 同时启动后端 FastAPI 服务和前端 Vite 开发服务器
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║   Linux 内核宕机自动诊断与补丁匹配系统 — 开发环境启动脚本              ║"
echo "╚══════════════════════════════════════════════════════════╝"

# ── 启动后端 ─────────────────────────────────────
echo ""
echo ">>> 启动后端 FastAPI 服务..."
cd "$PROJECT_DIR"

# 检查虚拟环境
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "    已激活虚拟环境: venv"
fi

# 安装后端依赖 (如需要)
if [ ! -f ".deps_installed" ]; then
    echo "    安装后端 Python 依赖..."
    pip install -r requirements.txt -q
    touch .deps_installed
    echo "    依赖安装完成"
fi

# 后台启动 FastAPI
python -m src.main &
BACKEND_PID=$!
echo "    后端 PID: $BACKEND_PID (端口 8000)"

# ── 启动前端 ─────────────────────────────────────
echo ""
echo ">>> 启动前端 Vite 开发服务器..."
cd "$PROJECT_DIR/frontend"

# 安装前端依赖 (如需要)
if [ ! -d "node_modules" ]; then
    echo "    安装前端 npm 依赖..."
    npm install
    echo "    依赖安装完成"
fi

# 启动 Vite
npm run dev &
FRONTEND_PID=$!
echo "    前端 PID: $FRONTEND_PID (端口 5173)"

# ── 等待服务就绪 ────────────────────────────────
echo ""
echo ">>> 等待服务就绪..."
sleep 3

# 检查后端
if kill -0 $BACKEND_PID 2>/dev/null; then
    echo "    ✓ 后端服务运行中: http://localhost:8000"
    echo "    ✓ API 文档: http://localhost:8000/api/docs"
else
    echo "    ✗ 后端启动失败"
fi

# 检查前端
if kill -0 $FRONTEND_PID 2>/dev/null; then
    echo "    ✓ 前端服务运行中: http://localhost:5173"
else
    echo "    ✗ 前端启动失败"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  按 Ctrl+C 停止所有服务                                 ║"
echo "╚══════════════════════════════════════════════════════════╝"

# ── 清理函数 ────────────────────────────────────
cleanup() {
    echo ""
    echo ">>> 停止所有服务..."
    [ -n "$BACKEND_PID" ] && kill $BACKEND_PID 2>/dev/null
    [ -n "$FRONTEND_PID" ] && kill $FRONTEND_PID 2>/dev/null
    echo "    服务已停止"
}

trap cleanup EXIT INT TERM

# 等待任意子进程退出
wait
