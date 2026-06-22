#!/usr/bin/env python3
"""
全量 Linux Kernel Commit 索引脚本
====================================

将 Linux 内核 Git 仓库中的 commit 进行:
1. 结构化采集 (PyDriller 一次遍历)
2. Root Cause 对称分析 (28 条专家规则)
3. BGE-M3 向量编码 (1024 维)
4. FAISS 向量库存储 + 持久化

Usage:
    # 测试: 索引前 100 条 commit
    python scripts/index_all_commits.py --repo-path /home/lkx/文档/内核比赛/linux --limit 100

    # 小规模验证: 索引前 10000 条
    python scripts/index_all_commits.py --repo-path /home/lkx/文档/内核比赛/linux --limit 10000

    # 全量索引 (需要 GPU, 预计 10+ 小时)
    python scripts/index_all_commits.py --repo-path /home/lkx/文档/内核比赛/linux --limit 0

    # 按日期范围索引
    python scripts/index_all_commits.py --repo-path /home/lkx/文档/内核比赛/linux --since 2024-01-01

    # 不使用 Root Cause 对称分析 (加速但降低语义质量)
    python scripts/index_all_commits.py --repo-path /home/lkx/文档/内核比赛/linux --no-root-cause

    # 使用 GPU 加速
    CUDA_VISIBLE_DEVICES=0 python scripts/index_all_commits.py --repo-path /home/lkx/文档/内核比赛/linux --limit 10000
"""

import sys
import os
import argparse
import time
import json
from datetime import datetime
from pathlib import Path

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def parse_args():
    parser = argparse.ArgumentParser(
        description="全量 Linux Kernel Commit 索引脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repo-path",
        required=True,
        help="Linux 内核 Git 仓库路径 (必填，例如: /path/to/linux)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="每批处理的 commit 数量 (默认: 1000)",
    )
    parser.add_argument(
        "--encode-batch",
        type=int,
        default=64,
        help="BGE-M3 编码时的批量大小 (默认: 64, GPU 可调至 128-256)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="最多索引的 commit 数量 (0=不限制, 默认: 0)",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="起始日期, 格式 YYYY-MM-DD (例如: 2024-01-01)",
    )
    parser.add_argument(
        "--to",
        type=str,
        default=None,
        help="结束日期, 格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--no-root-cause",
        action="store_true",
        help="禁用 Root Cause 对称分析 (加速但降低语义匹配质量)",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        default=True,
        help="排除 merge commit (默认: 开启)",
    )
    parser.add_argument(
        "--include-merge",
        action="store_true",
        help="包含 merge commit",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从上次中断位置恢复 (读取 data/index_progress.json)",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="设备选择: cuda, cpu (默认: 自动检测)",
    )
    return parser.parse_args()


def save_progress(progress_path: Path, data: dict):
    """保存索引进度，支持断点续跑"""
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    with open(progress_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_progress(progress_path: Path) -> dict:
    """加载上次索引进度"""
    if progress_path.exists():
        with open(progress_path, "r") as f:
            return json.load(f)
    return {"indexed": 0, "last_hash": None, "last_date": None}


def format_duration(seconds: float) -> str:
    """格式化时间"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}min"
    else:
        return f"{seconds / 3600:.2f}h"


def main():
    args = parse_args()
    repo_path = os.path.abspath(args.repo_path)
    progress_path = PROJECT_ROOT / "data" / "index_progress.json"

    # ── 验证仓库路径 ──────────────────────────────────────────────
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        print(f"[ERROR] 不是有效的 Git 仓库: {repo_path}")
        print("请确认 Linux 内核源码路径正确。")
        print(f"  当前设置: {repo_path}")
        print(f"  示例: python {__file__} --repo-path /path/to/linux")
        sys.exit(1)

    # ── 加载进度 (断点续跑) ─────────────────────────────────────────
    progress = {}
    if args.resume:
        progress = load_progress(progress_path)
        print(f"[resume] 上次索引到: {progress['indexed']} 条 commit")
        print(f"         最后 commit: {progress.get('last_hash', 'N/A')}")
        print(f"         最后日期:   {progress.get('last_date', 'N/A')}")

        # ★ P0-3 修复: 使用进度中的 last_date 作为 since 起点
        if progress.get("last_date") and not args.since:
            # 将 last_date 向前偏移 1 天，覆盖同一天内可能遗漏的 commit
            from datetime import timedelta
            last_dt = datetime.fromisoformat(progress["last_date"][:10])
            args.since = (last_dt - timedelta(days=1)).strftime("%Y-%m-%d")
            print(f"         自动设置 --since={args.since} (基于进度恢复)")

        # 保存 last_hash 用于精确定位
        if progress.get("last_hash"):
            print(f"         将从 {progress['last_hash'][:12]} 之后继续")

    # ── Step 1: 加载编码器 (预热模型) ──────────────────────────────
    print("\n" + "=" * 60)
    print("[Step 1/3] 加载 BGE-M3 编码器...")
    print("=" * 60)

    from src.indexer.embedding import get_encoder, reset_encoder
    from src.indexer.milvus import get_milvus_client, reset_milvus_client

    # 重置旧实例 (确保参数生效)
    reset_encoder()
    reset_milvus_client()

    # ★ 优先使用 FAISS (Milvus 需要单独部署服务)
    os.environ.setdefault("MILVUS_FORCE_FAISS", "1")

    encoder = get_encoder(device=args.device)
    print(f"  模型:     {encoder.model_name}")
    print(f"  设备:     {encoder.device}")
    print(f"  维度:     {encoder.dimension}")
    print(f"  已加载:   {encoder.is_available}")

    if encoder.init_error:
        print(f"  ⚠ 模型加载警告: {encoder.init_error}")
        print(f"  → 将使用 mock 编码器 (随机向量), 仅供流程验证!")

    # 预热编码
    _ = encoder.encode(["Linux kernel commit indexing warmup"], batch_size=1)
    print("  预热完成 ✓")

    # ── Step 2: 收集 + 索引 ────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"[Step 2/3] 开始收集并索引 Commit...")
    print(f"  仓库路径:   {repo_path}")
    print(f"  Root Cause: {'启用 (对称分析)' if not args.no_root_cause else '禁用'}")
    print(f"  批次大小:   {args.batch_size}")
    print(f"  编码批次:   {args.encode_batch}")
    if args.limit > 0:
        print(f"  限制数量:   {args.limit}")
    if args.since:
        print(f"  起始日期:   {args.since}")
    print("=" * 60)

    from src.collector import collect_commits_stream
    from src.indexer.pipeline import index_commits, index_commits_incremental, get_index_count
    from src.indexer.milvus import get_milvus_client

    # 解析日期
    since_date = datetime.fromisoformat(args.since) if args.since else None
    to_date = datetime.fromisoformat(args.to) if args.to else None
    only_no_merge = not args.include_merge

    # ★ P0-3 修复: 断点续跑 — 使用 last_hash 跳过已索引的 commit
    resume_last_hash = progress.get("last_hash") if args.resume else None

    # 初始化向量库
    total_before = get_index_count()
    print(f"  索引前向量数: {total_before}")

    batch = []
    total_indexed = 0
    total_collected = 0
    t_start = time.time()
    last_report_time = t_start
    last_report_count = 0

    try:
        commit_stream = collect_commits_stream(
            repo_path=repo_path,
            limit=args.limit if args.limit > 0 else None,
            since=since_date,
            to=to_date,
            only_no_merge=only_no_merge,
        )

        for commit in commit_stream:
            total_collected += 1

            # ★ P0-3 修复: 跳过断点之前已索引的 commit
            if resume_last_hash is not None:
                if commit.commit_hash == resume_last_hash:
                    # 找到了断点，此 commit 上次已索引，从下一个开始
                    last_hash_str = resume_last_hash[:12]
                    resume_last_hash = None
                    print(f"  [resume] 已跳过 {total_collected - 1} 条已索引 commit, "
                          f"从 {last_hash_str} 之后继续")
                    continue  # 跳过此 commit (上次已处理)
                continue  # 跳过此 commit (断点之前)

            batch.append(commit)

            if len(batch) >= args.batch_size:
                n = index_commits(
                    batch,
                    batch_size=args.encode_batch,
                    show_progress=False,
                    create_collection=(total_before + total_indexed == 0),
                    use_root_cause=not args.no_root_cause,
                )
                total_indexed += n

                # 保存进度
                save_progress(progress_path, {
                    "indexed": total_indexed,
                    "collected": total_collected,
                    "last_hash": batch[-1].commit_hash if batch else None,
                    "last_date": batch[-1].date if batch else None,
                    "timestamp": datetime.now().isoformat(),
                })

                # 速率报告
                now = time.time()
                elapsed_since_last = now - last_report_time
                if elapsed_since_last >= 30:  # 每 30 秒报告一次
                    batch_rate = (total_indexed - last_report_count) / elapsed_since_last
                    total_rate = total_indexed / (now - t_start) if (now - t_start) > 0 else 0
                    eta_seconds = (args.limit - total_indexed) / total_rate if args.limit > 0 and total_rate > 0 else 0
                    print(
                        f"  [{total_indexed} indexed, {total_collected} collected] "
                        f"速率: {batch_rate:.1f}/s (总平均: {total_rate:.1f}/s)"
                        + (f" | 预计剩余: {format_duration(eta_seconds)}" if eta_seconds > 0 else "")
                    )
                    last_report_time = now
                    last_report_count = total_indexed

                batch = []

            # 达到限制时退出
            if args.limit > 0 and total_collected >= args.limit:
                break

        # 处理剩余批次
        if batch:
            n = index_commits(
                batch,
                batch_size=args.encode_batch,
                create_collection=(total_before + total_indexed == 0),
                use_root_cause=not args.no_root_cause,
            )
            total_indexed += n

    except KeyboardInterrupt:
        print("\n\n⚠ 用户中断! 正在保存已索引的数据...")
        # 处理当前批次
        if batch:
            try:
                n = index_commits(
                    batch,
                    batch_size=args.encode_batch,
                    create_collection=(total_before + total_indexed == 0),
                    use_root_cause=not args.no_root_cause,
                )
                total_indexed += n
            except Exception as e:
                print(f"  保存批次时出错: {e}")
        save_progress(progress_path, {
            "indexed": total_indexed,
            "collected": total_collected,
            "last_hash": batch[-1].commit_hash if batch else None,
            "last_date": batch[-1].date if batch else None,
            "timestamp": datetime.now().isoformat(),
            "interrupted": True,
        })
        print(f"进度已保存到 {progress_path}")
        print(f"下次运行可使用 --resume 恢复")
        sys.exit(1)

    # ── Step 3: 持久化 + 统计 ──────────────────────────────────────
    print("\n" + "=" * 60)
    print("[Step 3/3] 持久化索引 & 统计...")
    print("=" * 60)

    client = get_milvus_client()
    client.save()

    total_elapsed = time.time() - t_start
    total_after = get_index_count()

    # ── 汇总报告 ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("✅ 索引完成!")
    print("=" * 60)
    print(f"  收集 Commit 总数:  {total_collected}")
    print(f"  成功索引数量:      {total_indexed}")
    print(f"  向量库总向量数:    {total_after}")
    print(f"  总耗时:            {format_duration(total_elapsed)}")
    if total_indexed > 0 and total_elapsed > 0:
        print(f"  平均速率:          {total_indexed / total_elapsed:.1f} commits/sec")
    print(f"  后端类型:          {client.active_backend}")
    print(f"  FAISS 索引路径:    {client.faiss_index_path}")

    # 子系统分布 (快速统计)
    stats = client.get_stats()
    print(f"\n  向量库统计:")
    for k, v in stats.items():
        print(f"    {k}: {v}")

    # 保存最终进度
    save_progress(progress_path, {
        "indexed": total_indexed,
        "collected": total_collected,
        "total_in_db": total_after,
        "completed": True,
        "elapsed_seconds": total_elapsed,
        "timestamp": datetime.now().isoformat(),
    })

    print(f"\n  进度已保存: {progress_path}")
    print(f"\n🎉 现在可以启动后端服务验证检索效果:")
    print(f"  cd {PROJECT_ROOT}")
    print(f"  source venv/bin/activate")
    print(f"  python -m uvicorn src.main:app --host 0.0.0.0 --port 8000")


if __name__ == "__main__":
    main()
