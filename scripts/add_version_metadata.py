#!/usr/bin/env python3
"""为已有的 FAISS 向量库元数据补充内核版本信息。

策略 (Option A — 日期推断):
    遍历 faiss_index.meta.json 中每条 commit，
    基于 commit 的 author_date 推断其首次出现的内核版本，
    将 kernel_version / kernel_version_major / kernel_version_minor / kernel_version_patch
    写入 metadata。

使用方式:
    source venv/bin/activate
    python scripts/add_version_metadata.py

    # 指定数据目录
    python scripts/add_version_metadata.py --data-dir /path/to/data

    # 干跑模式 (不实际写入)
    python scripts/add_version_metadata.py --dry-run

性能:
    312K 条 commit 约需 1-2 分钟 (纯内存计算，无网络 I/O)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 将项目根目录加入 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.collector.versioning import resolve_version_from_date


def load_metadata(meta_path: str) -> dict:
    """加载 FAISS 元数据 JSON 文件。

    Args:
        meta_path: faiss_index.meta.json 文件路径

    Returns:
        完整的元数据字典
    """
    t0 = time.time()
    print(f"📖 加载元数据: {meta_path}")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    elapsed = time.time() - t0
    size_mb = os.path.getsize(meta_path) / (1024 * 1024)
    print(f"   ✅ 加载完成 ({size_mb:.0f} MB, {elapsed:.1f}s)")
    return meta


def add_version_to_metadata(
    meta: dict,
    dry_run: bool = False,
) -> dict:
    """为元数据中每条 commit 补充版本信息。

    对每条 metadata 条目，从 date/committer_date 字段推断内核版本，
    写入 kernel_version / kernel_version_major / kernel_version_minor / kernel_version_patch。

    Args:
        meta: 元数据字典 (包含 metadata 列表)
        dry_run: True 时不实际修改，仅统计

    Returns:
        更新后的元数据字典，以及统计信息 (通过 side-effect 打印)
    """
    entries: list = meta.get("metadata", [])
    if not entries:
        print("   ⚠️  元数据中没有 metadata 列表，跳过")
        return meta

    total = len(entries)
    resolved = 0
    skipped = 0
    unknown_date = 0

    print(f"   🔄 处理 {total:,} 条 commit ...")

    for idx, entry in enumerate(entries):
        # 进度报告 (每 50000 条)
        if idx > 0 and idx % 50000 == 0:
            pct = idx / total * 100
            print(f"      ... {idx:,}/{total:,} ({pct:.0f}%)  resolved={resolved}")

        # 如果已有 kernel_version 字段，跳过 (增量更新友好)
        if entry.get("kernel_version"):
            skipped += 1
            continue

        # 优先使用 committer_date，其次 date
        date_str = entry.get("committer_date") or entry.get("date", "")

        version_info = resolve_version_from_date(date_str)
        if version_info is None:
            unknown_date += 1
            continue

        if not dry_run:
            entry["kernel_version"] = version_info["kernel_version"]
            entry["kernel_version_major"] = version_info["kernel_version_major"]
            entry["kernel_version_minor"] = version_info["kernel_version_minor"]
            entry["kernel_version_patch"] = version_info["kernel_version_patch"]

        resolved += 1

    print(f"   📊 统计:")
    print(f"      总计:      {total:>8,}")
    print(f"      已解析:    {resolved:>8,} ({resolved/total*100:.1f}%)")
    print(f"      已跳过:    {skipped:>8,} (已有版本信息)")
    print(f"      无法解析:  {unknown_date:>8,} (日期缺失/异常)")
    return meta


def save_metadata(meta: dict, meta_path: str) -> None:
    """保存元数据到磁盘。

    Args:
        meta: 更新后的元数据字典
        meta_path: 输出文件路径
    """
    t0 = time.time()
    print(f"\n💾 写入元数据: {meta_path}")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    elapsed = time.time() - t0
    size_mb = os.path.getsize(meta_path) / (1024 * 1024)
    print(f"   ✅ 写入完成 ({size_mb:.0f} MB, {elapsed:.1f}s)")


def update_progress_file(data_dir: str) -> None:
    """更新 index_progress.json，记录版本标注完成状态。

    Args:
        data_dir: 数据目录路径
    """
    progress_path = os.path.join(data_dir, "index_progress.json")
    if not os.path.exists(progress_path):
        return

    with open(progress_path, "r", encoding="utf-8") as f:
        progress = json.load(f)

    progress["version_annotated"] = True
    progress["version_annotation_method"] = "date_inference"
    progress["version_annotation_timestamp"] = datetime.now(timezone.utc).isoformat()

    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

    print(f"   ✅ 已更新索引进度文件")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="为 FAISS 向量库元数据补充内核版本信息 (日期推断模式)"
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="数据目录路径 (默认: 项目根目录下的 data/)",
    )
    parser.add_argument(
        "--meta-file",
        default=None,
        help="直接指定元数据文件路径 (优先级高于 --data-dir)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑模式: 仅统计，不实际修改文件",
    )
    args = parser.parse_args()

    # 确定元数据文件路径
    if args.meta_file:
        meta_path = args.meta_file
        data_dir = os.path.dirname(meta_path)
    elif args.data_dir:
        data_dir = args.data_dir
        meta_path = os.path.join(data_dir, "faiss_index.meta.json")
    else:
        data_dir = os.path.join(str(_PROJECT_ROOT), "data")
        meta_path = os.path.join(data_dir, "faiss_index.meta.json")

    if not os.path.exists(meta_path):
        print(f"❌ 元数据文件不存在: {meta_path}")
        sys.exit(1)

    print("=" * 60)
    print("  内核版本元数据补充工具 (日期推断模式)")
    print("=" * 60)
    print(f"  数据目录: {data_dir}")
    print(f"  元数据:   {os.path.basename(meta_path)}")
    print(f"  模式:     {'干跑 (不写入)' if args.dry_run else '正式运行'}")
    print()

    # 加载
    meta = load_metadata(meta_path)

    # 检查 metadata 列表
    entries = meta.get("metadata")
    if not entries:
        print("❌ 元数据文件格式异常: 缺少 'metadata' 字段")
        sys.exit(1)

    print(f"   📦 当前元数据条目: {len(entries):,}")
    existing_with_version = sum(1 for e in entries if e.get("kernel_version"))
    if existing_with_version:
        print(f"   ℹ️  已有版本信息的条目: {existing_with_version:,} (将跳过)")

    # 补充版本信息
    meta = add_version_to_metadata(meta, dry_run=args.dry_run)

    if args.dry_run:
        print("\n⚠️  干跑模式 — 未实际修改文件")
        return

    # 写入
    save_metadata(meta, meta_path)
    update_progress_file(data_dir)

    print("\n" + "=" * 60)
    print("  🎉 版本元数据补充完成!")
    print("=" * 60)
    print()
    print("  验证方式:")
    print(f"    python -c \"")
    print(f"    import json")
    print(f"    meta = json.load(open('{meta_path}'))")
    print(f"    e = meta['metadata']")
    print(f"    versions = set(m.get('kernel_version') for m in e[:100])")
    print(f"    print(f'前100条中的版本: {{versions}}')\"")
    print()


if __name__ == "__main__":
    main()
