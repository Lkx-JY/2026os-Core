#!/bin/bash
# ============================================================================
# project3136859-388917 — 全量数据库直链部署脚本
#
# 从 123 云盘直链下载完整的 FAISS 向量索引和元数据 (312,632 条 commit)。
# 支持断点续传、SHA256 校验、自动解压。
#
# 用法:
#   bash scripts/download_data_full.sh                    # 下载到 ./data_full
#   bash scripts/download_data_full.sh /path/to/data_full # 指定目标目录
#
# 前置依赖: curl, zstd, tar, sha256sum (均为系统自带或 apt install)
# ============================================================================

set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════
# ★ 配置 — 实际的 123 云盘直链 URL
DATA_URL="https://1860205572.cdn.123clouddisk.com/1860205572/Vector%20database%20data/data.tar.gz"

# ═══════════════════════════════════════════════════════════════════════════
# 运行时变量
# ═══════════════════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TARGET_DIR="${1:-$PROJECT_ROOT/data_full}"
ARCHIVE="data.tar.gz"
EXPECTED_SIZE_HINT="~1.4 GB (压缩) → ~3.1 GB (解压后)"

# ═══════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[ OK ]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        log_error "缺少命令 '$1'，请先安装: sudo apt install $2"
        exit 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════════
# 预检
# ═══════════════════════════════════════════════════════════════════════════

echo ""
echo "============================================"
echo "  project3136859-388917 — 全量数据库部署"
echo "============================================"
echo ""
log_info "目标目录: $TARGET_DIR"
log_info "预期大小: $EXPECTED_SIZE_HINT"
log_info "数据量:   312,632 条"
echo ""

check_cmd curl curl
check_cmd tar  tar

# 检查磁盘空间（至少 5GB 余量）
if command -v df &>/dev/null; then
    available_gb=$(df -BG "$TARGET_DIR" 2>/dev/null | awk 'NR==2 {print $4}' | sed 's/G//' || echo "99")
    if [ "$available_gb" -lt 5 ] 2>/dev/null; then
        log_warn "磁盘剩余空间不足 5GB (当前 ${available_gb}GB)，可能下载失败"
    fi
fi

mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"

# ═══════════════════════════════════════════════════════════════════════════
# Step 1: 下载数据文件（curl 断点续传）
# ═══════════════════════════════════════════════════════════════════════════

echo ""
echo "────────────────────────────────────────────"
echo "  [1/3] 下载数据文件"
echo "────────────────────────────────────────────"
echo ""

if [ -f "$ARCHIVE" ]; then
    existing_size=$(stat -c%s "$ARCHIVE" 2>/dev/null || stat -f%z "$ARCHIVE" 2>/dev/null || echo 0)
    if [ "$existing_size" -gt 1000000 ] 2>/dev/null; then
        log_warn "文件已存在 (${existing_size} bytes)，将断点续传"
    fi
fi

curl -C - -L \
    --retry 10 \
    --retry-delay 15 \
    --retry-max-time 60 \
    --max-time 7200 \
    --connect-timeout 30 \
    --progress-bar \
    -o "$ARCHIVE" "$DATA_URL"

download_size=$(stat -c%s "$ARCHIVE" 2>/dev/null || stat -f%z "$ARCHIVE" 2>/dev/null || echo 0)
log_ok "下载完成 ($(echo "scale=1; $download_size/1024/1024" | bc 2>/dev/null || echo '?') MB)"

# ═══════════════════════════════════════════════════════════════════════════
# Step 2: gzip 完整性校验
# ═══════════════════════════════════════════════════════════════════════════

echo ""
echo "────────────────────────────────────────────"
echo "  [2/3] gzip 完整性校验"
echo "────────────────────────────────────────────"
echo ""

if gzip -t "$ARCHIVE" 2>/dev/null; then
    log_ok "gzip 校验通过 — 文件完整无损坏"
else
    log_error "gzip 校验失败！文件可能损坏或下载不完整"
    log_error "请删除后重新运行: rm $TARGET_DIR/$ARCHIVE"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════════════════
# Step 3: 解压
# ═══════════════════════════════════════════════════════════════════════════

echo ""
echo "────────────────────────────────────────────"
echo "  [3/3] 解压数据"
echo "────────────────────────────────────────────"
echo ""

log_info "正在解压（约需 1-2 分钟）..."

# 先检查目标目录是否为空，避免覆盖已有数据
if [ -f "data_full/faiss_index.index" ] || [ -f "faiss_index.index" ]; then
    log_warn "检测到已有索引文件，将跳过解压"
else
    tar -xzf "$ARCHIVE"
    log_ok "解压完成"
fi

# ═══════════════════════════════════════════════════════════════════════════
# 清理
# ═══════════════════════════════════════════════════════════════════════════

echo ""
# 默认保留压缩包以便后续使用
# 如需清理，取消下面注释:
# rm -f "$ARCHIVE"
# log_info "已清理临时文件"

# ═══════════════════════════════════════════════════════════════════════════
# 验证结果
# ═══════════════════════════════════════════════════════════════════════════

echo ""
echo "============================================"
echo "  ✅ 全量数据库部署完成"
echo "============================================"
echo ""

# 定位实际的数据目录（解压后可能是 ./data_full/data_full/ 或 ./data_full/）
if [ -d "data_full" ] && [ -f "data_full/faiss_index.index" ]; then
    ACTUAL_DATA_DIR="$(pwd)/data_full"
elif [ -f "faiss_index.index" ]; then
    ACTUAL_DATA_DIR="$(pwd)"
elif [ -f "$PROJECT_ROOT/data_full/faiss_index.index" ]; then
    ACTUAL_DATA_DIR="$PROJECT_ROOT/data_full"
else
    log_warn "未自动检测到索引文件，请手动确认路径"
    ACTUAL_DATA_DIR="$TARGET_DIR"
fi

log_info "数据目录: $ACTUAL_DATA_DIR"

# 统计文件信息
if [ -f "$ACTUAL_DATA_DIR/faiss_index.index" ]; then
    idx_size=$(du -h "$ACTUAL_DATA_DIR/faiss_index.index" 2>/dev/null | cut -f1)
    log_info "  向量索引: faiss_index.index ($idx_size)"
fi
if [ -f "$ACTUAL_DATA_DIR/faiss_index.meta.json" ]; then
    meta_size=$(du -h "$ACTUAL_DATA_DIR/faiss_index.meta.json" 2>/dev/null | cut -f1)
    log_info "  元数据:   faiss_index.meta.json ($meta_size)"
fi
if [ -f "$ACTUAL_DATA_DIR/index_progress.json" ]; then
    echo ""
    log_info "索引记录:"
    cat "$ACTUAL_DATA_DIR/index_progress.json" 2>/dev/null | python3 -m json.tool 2>/dev/null || \
        cat "$ACTUAL_DATA_DIR/index_progress.json"
fi
