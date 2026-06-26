#!/bin/bash
# ============================================================================
# 完整向量库下载脚本
# 从云存储下载预构建的完整 FAISS 向量库 (~2.9GB, 312K 条 commit)
#
# 使用方式:
#     bash scripts/download_full_data.sh
#
# 注意:
#     - 仓库自带轻量级 Demo 数据 (44K 条, ~360MB)，开箱即用
#     - 完整数据提供更高的检索覆盖率和版本多样性
#     - 此脚本会覆盖 data/ 目录下的 Demo 数据
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_DIR/data"

echo "========================================"
echo "  Core.LinuxCommit 完整向量库下载"
echo "========================================"
echo ""
echo "  目标目录: $DATA_DIR"
echo "  预计大小: ~2.5GB (312,632 条 commit, 18 个内核版本)"
echo ""

# ────────────────────────────────────────────────────────────────
# ★ 下载地址 — 请替换为你的实际云存储地址
# ────────────────────────────────────────────────────────────────
# 方案 A: 阿里云 OSS / 腾讯云 COS 等对象存储直链
# DOWNLOAD_BASE="https://your-bucket.oss-cn-xxx.aliyuncs.com/core-linuxcommit-data"
#
# 方案 B: HuggingFace Datasets
# DOWNLOAD_BASE="https://huggingface.co/datasets/your-org/core-linuxcommit-data/resolve/main"
#
# 方案 C: 百度网盘 / 123 云盘 (需手动下载，脚本仅校验)
# 手动下载后放到 data/ 目录，运行此脚本会自动检测并跳过

DOWNLOAD_BASE="${DOWNLOAD_BASE:-}"

FILES=(
    "faiss_index.index"
    "faiss_index.meta.json"
    "index_progress.json"
)

# ── 检查是否已有完整数据 ──────────────────────────────────────
if [ -f "$DATA_DIR/index_progress.json" ]; then
    CURRENT_COUNT=$(python3 -c "import json; print(json.load(open('$DATA_DIR/index_progress.json')).get('total_in_db', 0))" 2>/dev/null || echo "0")
    if [ "$CURRENT_COUNT" -ge 300000 ] 2>/dev/null; then
        echo "✅ 完整数据已存在 ($CURRENT_COUNT 条)，跳过下载"
        ls -lh "$DATA_DIR"/faiss_index.*
        exit 0
    else
        echo "📦 当前是 Demo 数据 ($CURRENT_COUNT 条)，将下载完整数据覆盖"
        echo ""
    fi
fi

# ── 下载 ────────────────────────────────────────────────────────
if [ -z "$DOWNLOAD_BASE" ]; then
    echo "⚠️  未配置下载地址"
    echo ""
    echo "请选择以下方式之一获取完整向量库："
    echo ""
    echo "  方式 1: 设置环境变量指定下载地址"
    echo "    export DOWNLOAD_BASE=https://your-storage.com/path"
    echo "    bash scripts/download_full_data.sh"
    echo ""
    echo "  方式 2: 手动下载以下文件到 data/ 目录"
    echo "    - faiss_index.index      (~1.2GB)"
    echo "    - faiss_index.meta.json  (~1.7GB, 含版本元数据)"
    echo "    - index_progress.json"
    echo ""
    echo "  方式 3: 自行构建 (需要 Linux 内核 Git 仓库 + BGE-M3 模型)"
    echo "    python scripts/index_all_commits.py --repo-path /path/to/linux --limit 312632"
    exit 1
fi

mkdir -p "$DATA_DIR"

for f in "${FILES[@]}"; do
    if [ -f "$DATA_DIR/$f" ]; then
        # 检查是否为完整版（粗略判断：文件大于 500MB 说明是完整版）
        SIZE=$(stat -c%s "$DATA_DIR/$f" 2>/dev/null || echo "0")
        if [ "$SIZE" -gt 500000000 ] 2>/dev/null; then
            echo "  ⏭  跳过 $f (已是完整版, $(numfmt --to=iec $SIZE))"
            continue
        fi
        echo "  ⚠️  覆盖 Demo 版 $f ..."
    fi
    echo "  ⬇  下载 $f ..."
    curl -fSL --progress-bar -o "$DATA_DIR/$f" "$DOWNLOAD_BASE/$f"
    echo "  ✅ $f 下载完成"
done

# ── 验证 ──────────────────────────────────────────────────────────
echo ""
echo "验证下载结果..."
for f in "${FILES[@]}"; do
    if [ -f "$DATA_DIR/$f" ]; then
        SIZE=$(du -h "$DATA_DIR/$f" | cut -f1)
        echo "  ✅ $f ($SIZE)"
    else
        echo "  ❌ $f 缺失!"
        exit 1
    fi
done

python3 -c "
import faiss, json, os
d = '$DATA_DIR'
idx = faiss.read_index(os.path.join(d, 'faiss_index.index'))
with open(os.path.join(d, 'index_progress.json')) as f:
    prog = json.load(f)
print(f'  ✅ 向量数: {idx.ntotal:,}, 维度: {idx.d}')
print(f'  ✅ 索引进度: {prog[\"indexed\"]}/{prog[\"total_in_db\"]} 条已索引')
print(f'  🎉 完整向量库就绪!')
"

echo ""
echo "现在可以启动完整版服务:"
echo "  source venv/bin/activate"
echo "  source .env"
echo "  MILVUS_FORCE_FAISS=1 python -m src.main"
