#!/usr/bin/env python3
"""从完整向量库中提取轻量级 Demo 数据集，用于提交到 Git 仓库。

策略:
    - 按 committer_date 降序排列，保留最近的 ~40,000 条 commit
    - 保持 FAISS 索引与元数据的一致性
    - 总大小控制在 500MB 以内

使用方式:
    source venv/bin/activate
    python scripts/build_demo_data.py

    # 指定条目数和数据目录
    python scripts/build_demo_data.py --count 40000 --data-dir ./data --source-dir /path/to/full/data
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

# 将项目根目录加入 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def load_full_data(data_dir: str) -> tuple[dict, np.ndarray]:
    """加载完整数据集。

    Args:
        data_dir: 完整数据所在目录

    Returns:
        (meta_dict, faiss_vectors): 元数据字典和 FAISS 向量矩阵 (N, 1024)
    """
    meta_path = os.path.join(data_dir, "faiss_index.meta.json")
    index_path = os.path.join(data_dir, "faiss_index.index")

    print(f"📖 加载元数据: {meta_path}")
    t0 = time.time()
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    size_mb = os.path.getsize(meta_path) / (1024 * 1024)
    print(f"   ✅ {len(meta['metadata']):,} 条 ({size_mb:.0f} MB, {time.time()-t0:.1f}s)")

    print(f"📖 加载 FAISS 索引: {index_path}")
    t0 = time.time()
    import faiss
    index = faiss.read_index(index_path)
    print(f"   ✅ {index.ntotal:,} 条向量, 维度={index.d} ({time.time()-t0:.1f}s)")

    # 重建向量: FAISS IndexIVFFlat 的 reconstruct 方法
    print("🔄 提取向量...")
    t0 = time.time()
    vectors = index.reconstruct_n(0, index.ntotal)
    print(f"   ✅ shape={vectors.shape} ({time.time()-t0:.1f}s)")

    return meta, vectors


def select_stratified_entries(
    meta: dict,
    vectors: np.ndarray,
    max_count: int,
) -> tuple[list, np.ndarray, list[int]]:
    """按内核版本分层采样，保证 Demo 数据的多样性。

    每个主版本分配大致相同的条目数，版本内按日期取最新的。
    这样 Demo 覆盖从 4.9 到 6.13 的全版本范围。

    Args:
        meta: 完整元数据字典
        vectors: 完整向量矩阵
        max_count: 保留条目上限

    Returns:
        (selected_entries, selected_vectors, selected_indices)
    """
    from collections import defaultdict

    entries = meta["metadata"]

    # 按 kernel_version (major.minor) 分组
    version_groups: dict[str, list[int]] = defaultdict(list)
    for i, entry in enumerate(entries):
        kv = entry.get("kernel_version") or "0.0"
        # 提取 major.minor 作为分组键
        parts = kv.split(".")
        group_key = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else kv
        version_groups[group_key].append(i)

    # 计算每组分配数量
    num_groups = len(version_groups)
    base_per_group = max(1, max_count // num_groups)

    print(f"   版本组数: {num_groups}, 每组约 {base_per_group} 条")

    selected_indices = []
    for group_key in sorted(version_groups.keys(), reverse=True):
        group = version_groups[group_key]
        group_size = len(group)

        # 配额: base_per_group，但不能超过组大小
        quota = min(base_per_group, group_size)

        # 组内按日期排序取最新
        def _date_key(idx: int) -> str:
            e = entries[idx]
            return e.get("committer_date") or e.get("date", "0000-00-00")

        group.sort(key=_date_key, reverse=True)
        selected_indices.extend(group[:quota])

    # 截断到 max_count (优先保留更多版本的覆盖)
    selected_indices = selected_indices[:max_count]

    # 提取子集
    selected_entries = [entries[i] for i in selected_indices]
    selected_vectors = vectors[selected_indices]

    return selected_entries, selected_vectors, selected_indices


def build_demo_index(vectors: np.ndarray, nlist: int = 50) -> "faiss.Index":
    """构建 Demo 用的小型 FAISS IVF 索引。

    ★ 关键: 对向量做 L2 归一化，确保内积 = 余弦相似度，范围 [-1, 1]。
    未归一化向量会导致内积 >> 1，所有分数被 clamp 到 1.0，失去区分度。

    Args:
        vectors: (N, 1024) float32 向量矩阵
        nlist: IVF 聚类数 (Demo 用小 nlist)

    Returns:
        训练好的 FAISS IndexIVFFlat
    """
    import faiss

    # ★ 必须归一化: 确保 FAISS IP 搜索返回余弦相似度
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / (norms + 1e-8)
    print(f"   ✓ 向量已归一化 (L2 norm)")

    dim = vectors.shape[1]
    quantizer = faiss.IndexFlatIP(dim)
    index = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)

    print(f"   🏋️  训练 IVF 索引 (nlist={nlist})...")
    t0 = time.time()
    index.train(vectors)
    index.add(vectors)
    print(f"   ✅ 训练完成, ntotal={index.ntotal} ({time.time()-t0:.1f}s)")

    return index


def save_demo_data(
    meta: dict,
    selected_entries: list,
    index: "faiss.Index",
    output_dir: str,
    count: int,
) -> None:
    """保存 Demo 数据集。

    Args:
        meta: 原始元数据字典 (会复制并替换 metadata)
        selected_entries: 选中的条目列表
        index: Demo FAISS 索引
        output_dir: 输出目录
        count: 保留条目数
    """
    os.makedirs(output_dir, exist_ok=True)

    # 构建新的元数据
    demo_meta = dict(meta)
    demo_meta["metadata"] = selected_entries
    demo_meta["id_counter"] = len(selected_entries)
    demo_meta["nlist"] = 50

    # 保存元数据
    meta_path = os.path.join(output_dir, "faiss_index.meta.json")
    print(f"\n💾 写入 Demo 元数据: {meta_path}")
    t0 = time.time()
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(demo_meta, f, ensure_ascii=False)
    meta_mb = os.path.getsize(meta_path) / (1024 * 1024)
    print(f"   ✅ {meta_mb:.0f} MB ({time.time()-t0:.1f}s)")

    # 保存 FAISS 索引
    index_path = os.path.join(output_dir, "faiss_index.index")
    print(f"💾 写入 Demo FAISS 索引: {index_path}")
    t0 = time.time()
    import faiss
    faiss.write_index(index, index_path)
    idx_mb = os.path.getsize(index_path) / (1024 * 1024)
    print(f"   ✅ {idx_mb:.0f} MB ({time.time()-t0:.1f}s)")

    # 保存进度文件
    progress = {
        "indexed": count,
        "collected": count,
        "total_in_db": count,
        "completed": True,
        "is_demo": True,
        "demo_description": f"轻量级 Demo 数据集 ({count:,} 条最近期 commit)",
        "full_data_available_at": "FULL_DATA_URL_PLACEHOLDER",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    progress_path = os.path.join(output_dir, "index_progress.json")
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

    # 总计
    total_mb = meta_mb + idx_mb
    print(f"\n{'='*60}")
    print(f"  Demo 数据集构建完成!")
    print(f"  条目数:  {count:,}")
    print(f"  元数据:  {meta_mb:.0f} MB")
    print(f"  索引:    {idx_mb:.0f} MB")
    print(f"  总计:    {total_mb:.0f} MB")
    if total_mb > 500:
        print(f"  ⚠️  超过 500MB 限制! 建议减少条目数")
    else:
        print(f"  ✅ 满足 500MB 限制")
    print(f"{'='*60}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从完整向量库中提取轻量级 Demo 数据集"
    )
    parser.add_argument(
        "--source-dir",
        default=None,
        help="完整数据源目录 (默认: 项目 data/ 目录)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Demo 数据输出目录 (默认: data_demo/)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=40000,
        help="保留的条目数 (默认: 40000)",
    )
    args = parser.parse_args()

    source_dir = args.source_dir or os.path.join(str(_PROJECT_ROOT), "data")
    output_dir = args.output_dir or os.path.join(str(_PROJECT_ROOT), "data_demo")

    print("=" * 60)
    print("  构建轻量级 Demo 数据集")
    print("=" * 60)
    print(f"  源目录:   {source_dir}")
    print(f"  输出目录: {output_dir}")
    print(f"  保留条数: {args.count:,}")
    print()

    # 加载
    meta, vectors = load_full_data(source_dir)

    # 选择
    print(f"\n🔍 选择最近 {args.count:,} 条 commit...")
    t0 = time.time()
    selected_entries, selected_vectors, _ = select_stratified_entries(
        meta, vectors, args.count
    )
    print(f"   ✅ 选中 {len(selected_entries):,} 条 ({time.time()-t0:.1f}s)")

    # 日期分布
    dates = [e.get("committer_date") or e.get("date", "") for e in selected_entries]
    if dates:
        print(f"   日期范围: {min(dates)[:10]} ~ {max(dates)[:10]}")

    # 构建索引
    print(f"\n🔧 构建 Demo FAISS 索引...")
    index = build_demo_index(selected_vectors)

    # 保存
    save_demo_data(meta, selected_entries, index, output_dir, len(selected_entries))


if __name__ == "__main__":
    main()
