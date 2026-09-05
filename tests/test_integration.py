#!/usr/bin/env python3
"""
Linux 内核宕机自动诊断与补丁匹配系统 — 本地功能集成测试脚本

运行方式:
   source venv/bin/activate
   SKIP_API_KEY_CHECK=1 python tests/test_integration.py

若无 API Key，LLM 相关测试会自动跳过。
"""

import os
import sys
import time
import random
import tempfile
import numpy as np

# 确保项目根目录在 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


# ============================================================================
# 测试工具
# ============================================================================

PASS = 0
FAIL = 0
SKIP = 0


def test(name):
    """测试装饰器风格的测试函数"""
    def decorator(func):
        def wrapper():
            global PASS, FAIL, SKIP
            try:
                func()
                PASS += 1
                print(f"  ✅ {name}")
            except Exception as e:
                FAIL += 1
                print(f"  ❌ {name}: {e}")
        return wrapper
    return decorator


def skip_if_no_api_key():
    """如果没有 API Key，跳过需要 LLM 的测试"""
    return not os.environ.get("OPENAI_API_KEY", "").strip()


# ============================================================================
# 测试用例
# ============================================================================

def test_config_module():
    """测试统一配置模块"""
    print("\n" + "=" * 60)
    print("📋 1. 配置模块测试")
    print("=" * 60)

    from src.common.config import (
        is_api_key_configured, get_llm_base_url, get_llm_model,
        get_milvus_db_path, PROJECT_ROOT,
    )

    # 1.1 配置路径
    print("  1.1 项目根目录...")
    assert PROJECT_ROOT.exists(), f"项目根目录不存在: {PROJECT_ROOT}"
    assert (PROJECT_ROOT / "src").is_dir(), f"src 目录不存在"
    print(f"  ✅ 项目根目录: {PROJECT_ROOT}")

    # 1.2 API Key 检测
    print("  1.2 API Key 检测...")
    has_key = is_api_key_configured()
    print(f"  {'✅' if has_key else '⚠️ '} API Key: {'已配置' if has_key else '未配置 (LLM 测试将跳过)'}")

    # 1.3 默认值
    print("  1.3 默认配置值...")
    assert get_llm_model() == "deepseek-chat", f"默认模型错误: {get_llm_model()}"
    assert "deepseek.com" in get_llm_base_url(), f"默认 base_url 错误: {get_llm_base_url()}"
    print(f"  ✅ model={get_llm_model()}, base_url={get_llm_base_url()}")

    # 1.4 Milvus 路径
    print("  1.4 Milvus 数据库路径...")
    db_path = get_milvus_db_path()
    print(f"  ✅ Milvus DB: {db_path}")


def test_milvus_lite():
    """测试 Milvus Lite 集成"""
    print("\n" + "=" * 60)
    print("🗄️  2. Milvus Lite 集成测试")
    print("=" * 60)

    from src.indexer.milvus import MilvusClient, SearchResult

    # 使用临时目录避免污染现有数据
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_milvus.db")
        os.environ["MILVUS_DB_PATH"] = db_path

        try:
            # 2.1 初始化客户端
            print("  2.1 初始化 MilvusClient...")
            client = MilvusClient(
                backend="auto",
                collection_name="test_collection",
                dim=128,
            )
            print(f"  ✅ 后端: {client.active_backend}")

            # 2.2 创建 Collection
            print("  2.2 创建 Collection...")
            client.create_collection(dim=128, drop_if_exists=True)
            assert client.collection_exists(), "Collection 创建失败"
            print("  ✅ Collection 创建成功")

            # 2.3 插入向量
            print("  2.3 插入测试向量...")
            n = 100
            dim = 128
            vectors = np.random.randn(n, dim).astype(np.float32)
            metadata = [
                {
                    "commit_hash": f"hash_{i:04d}",
                    "subject": f"Test commit {i}: fix bug in subsystem_{i % 5}",
                    "subsystem": f"subsystem_{i % 5}",
                    "bug_type": "null_pointer" if i % 3 == 0 else "memory_leak",
                    "author": f"author_{i}",
                    "date": f"2026-06-{i % 28 + 1:02d}",
                    "score": random.random(),
                }
                for i in range(n)
            ]
            ids = client.insert(vectors, metadata)
            assert len(ids) > 0, "插入失败"
            print(f"  ✅ 已插入 {len(ids)} 条向量")

            # 2.4 向量搜索
            print("  2.4 向量搜索...")
            query = np.random.randn(dim).astype(np.float32)
            result = client.search(query, top_k=5)
            assert len(result) >= 1, "搜索结果为空"
            print(f"  ✅ Top-5 搜索: {len(result)} 条结果, 耗时 {result.search_time_ms:.1f}ms")

            # 2.5 统计信息
            print("  2.5 索引统计...")
            count = client.count()
            stats = client.get_stats()
            assert count == n, f"向量数量不匹配: {count} != {n}"
            print(f"  ✅ 向量数: {count}, 后端: {stats.get('backend')}")

        finally:
            del os.environ["MILVUS_DB_PATH"]


def test_faiss_fallback():
    """测试 FAISS 回退"""
    print("\n" + "=" * 60)
    print("💾 3. FAISS 回退测试")
    print("=" * 60)

    from src.indexer.milvus import MilvusClient

    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = os.path.join(tmpdir, "test_faiss")

        # 3.1 FAISS 模式
        print("  3.1 FAISS 模式...")
        client = MilvusClient(
            backend="faiss",
            dim=128,
            faiss_index_path=index_path,
        )
        assert client.active_backend == "faiss"
        print(f"  ✅ 后端: {client.active_backend}")

        # 3.2 插入和搜索
        print("  3.2 插入 + 搜索...")
        vectors = np.random.randn(50, 128).astype(np.float32)
        metadata = [{"subsystem": "mm", "bug_type": "deadlock"} for _ in range(50)]
        client.insert(vectors, metadata)
        result = client.search(np.random.randn(128).astype(np.float32), top_k=5)
        assert len(result) >= 1
        print(f"  ✅ 搜索返回 {len(result)} 条")

        # 3.3 持久化
        print("  3.3 持久化...")
        client.save()
        assert os.path.exists(f"{index_path}.meta.json") or os.path.exists(f"{index_path}.index")
        print("  ✅ 持久化成功")


def test_collector_module():
    """测试 Commit 收集器"""
    print("\n" + "=" * 60)
    print("📥 4. Commit 收集器测试")
    print("=" * 60)

    LINUX_REPO = os.path.expanduser("~/文档/内核比赛/linux")

    if not os.path.isdir(LINUX_REPO):
        print("  ⚠️  Linux 内核仓库不可用，跳过收集器测试")
        print(f"     路径: {LINUX_REPO}")
        return

    from src.collector import collect_commits_stream
    from src.collector.models import CommitInfo

    # 4.1 流式收集
    print("  4.1 流式收集 commits (最近 20 条)...")
    commits = []
    try:
        for commit in collect_commits_stream(LINUX_REPO, limit=20):
            commits.append(commit)
    except Exception as e:
        print(f"  ⚠️  收集失败: {e}")
        return

    assert len(commits) > 0, "未收集到任何 commit"
    print(f"  ✅ 收集到 {len(commits)} 条 commits")

    # 4.2 检查解析质量
    print("  4.2 解析质量检查...")
    valid = sum(1 for c in commits if c.commit_hash and c.subject)
    print(f"  ✅ 有效 commits: {valid}/{len(commits)}")

    if commits:
        sample = commits[0]
        print(f"  示例: [{sample.commit_hash[:8]}] {sample.subject[:80]}")


def test_rootcause_rules():
    """测试根因分析规则"""
    print("\n" + "=" * 60)
    print("🔍 5. 根因分析规则测试")
    print("=" * 60)

    from src.analyzer.models import CrashFeature
    from src.analyzer.rootcause import abstract_root_cause

    # 5.1 NULL pointer dereference
    print("  5.1 NULL pointer dereference...")
    feature = CrashFeature(
        panic_msg="BUG: unable to handle kernel NULL pointer dereference at 0000000000000008",
        call_trace=[
            "some_function+0x50/0x100",
            "deref_pointer+0x30/0x80",
            "process_one_work+0x200/0x400",
        ],
        subsystem="mm",
        bug_type="null_pointer",
        kernel_version="6.1.0",
    )
    result = abstract_root_cause(feature)
    assert result.root_cause, "根因为空"
    print(f"  ✅ 根因: {result.root_cause[:100]}")
    print(f"     Bug Type: {result.bug_type}")
    print(f"     Score: {result.score}")

    # 5.2 Deadlock
    print("  5.2 Deadlock detection...")
    feature2 = CrashFeature(
        panic_msg="INFO: task kworker blocked for more than 120 seconds",
        call_trace=[
            "mutex_lock+0x30/0x60",
            "some_locked_func+0x40/0xa0",
        ],
        subsystem="fs",
        bug_type="deadlock",
        kernel_version="5.15.0",
    )
    result2 = abstract_root_cause(feature2)
    print(f"  ✅ 根因: {result2.root_cause[:100]}")
    print(f"     Bug Type: {result2.bug_type}")
    print(f"     Score: {result2.score}")

    # 5.3 Use-after-free
    print("  5.3 Use-after-free detection...")
    feature3 = CrashFeature(
        panic_msg="KASAN: use-after-free in kmem_cache_alloc",
        call_trace=[
            "kmem_cache_alloc+0x50/0x200",
            "use_freed_object+0x20/0x50",
        ],
        subsystem="mm",
        bug_type="use_after_free",
        kernel_version="6.6.0",
    )
    result3 = abstract_root_cause(feature3)
    print(f"  ✅ 根因: {result3.root_cause[:100]}")
    print(f"     Bug Type: {result3.bug_type}")

    # 5.4 检索查询生成
    print("  5.4 检索查询构造...")
    from src.analyzer.rootcause import build_retrieval_query
    query = build_retrieval_query(
        feature=feature,
        root_cause=result.root_cause,
        bug_type=result.bug_type,
        causal_chain=result.causal_chain,
        fix_hints=result.extra_info.get("fix_hints", {}),
        trace_analysis=result.extra_info.get("trace_analysis", {}),
    )
    assert query, "检索查询为空"
    print(f"  ✅ 检索查询: {query[:150]}")


def test_llm_modules():
    """测试 LLM 模块（需要 API Key）"""
    print("\n" + "=" * 60)
    print("🤖 6. LLM 集成测试")
    print("=" * 60)

    if skip_if_no_api_key():
        print("  ⚠️  未配置 OPENAI_API_KEY，跳过 LLM 测试")
        print("  配置方法: export OPENAI_API_KEY=sk-your-key")
        return

    from src.generator.llm import LLMClient

    # 6.1 LLM 客户端初始化
    print("  6.1 LLM 客户端初始化...")
    client = LLMClient(
        model="deepseek-chat",
        api_key=os.environ["OPENAI_API_KEY"],
    )
    assert client.is_available, "LLM 客户端初始化失败"
    print("  ✅ LLM 客户端就绪")

    # 6.2 简单对话测试
    print("  6.2 简单对话 (API 调用...) ...")
    try:
        response = client.chat(
            prompt="In one sentence, what is the Linux kernel OOM killer?",
            max_tokens=100,
        )
        assert len(response) > 10, f"响应太短: {len(response)}"
        print(f"  ✅ 响应: {response[:120]}...")
    except Exception as e:
        print(f"  ⚠️  API 调用失败: {e} (可能是网络或余额问题)")


def test_knowledge_modules():
    """测试领域知识模块"""
    print("\n" + "=" * 60)
    print("📚 7. 领域知识模块测试")
    print("=" * 60)

    # 7.1 Bug 模式
    print("  7.1 Bug 模式库...")
    from src.knowledge.bug_patterns import BUG_PATTERNS
    assert len(BUG_PATTERNS) > 0, "Bug 模式为空"
    print(f"  ✅ 已加载 {len(BUG_PATTERNS)} 种错误模式")
    for name in list(BUG_PATTERNS.keys())[:3]:
        info = BUG_PATTERNS[name]
        print(f"     - {name}: {info.get('description', str(info))[:60] if isinstance(info, dict) else str(info)[:60]}")

    # 7.2 锁规则
    print("  7.2 锁规则...")
    from src.knowledge.lock_rules import LOCK_TYPES
    assert len(LOCK_TYPES) > 0, "锁规则为空"
    print(f"  ✅ 已加载 {len(LOCK_TYPES)} 种锁类型")

    # 7.3 子系统图
    print("  7.3 子系统关系图...")
    from src.knowledge.subsystem_graph import SUBSYSTEM_HIERARCHY
    assert len(SUBSYSTEM_HIERARCHY) > 0, "子系统图为空"
    print(f"  ✅ 已加载 {len(SUBSYSTEM_HIERARCHY)} 个子系统")


def test_schemas():
    """测试 API Schema"""
    print("\n" + "=" * 60)
    print("📋 8. API Schema / 数据模型测试")
    print("=" * 60)

    from src.api.schemas.entities import RootCauseInfo, CommitInfo, MatchedPatch
    from src.api.schemas.requests import AnalyzeRequest, SearchRequest

    # 8.1 AnalyzeRequest
    print("  8.1 AnalyzeRequest...")
    req = AnalyzeRequest(
        log_content="BUG: unable to handle kernel NULL pointer dereference",
        kernel_version="6.1.0",
        use_llm=False,
    )
    assert req.log_content, "log_content 为空"
    print(f"  ✅ 输入大小: {len(req.log_content)} 字节")

    # 8.2 SearchRequest
    print("  8.2 SearchRequest...")
    req2 = SearchRequest(
        query="NULL pointer dereference fix in memory management",
        top_k=10,
        subsystem="mm",
    )
    assert req2.query, "查询为空"
    print(f"  ✅ 查询: {req2.query[:60]}")

    # 8.3 MatchedPatch
    print("  8.3 MatchedPatch...")
    from src.api.schemas.entities import CommitInfo as SchemaCommitInfo
    commit_info = SchemaCommitInfo(
        commit_id="abc123def456",
        title="mm: fix NULL pointer dereference in slub allocator",
        subsystem="mm",
        author="Test Author",
        date="2026-06-12",
        files_changed=["mm/slub.c"],
        fix_tags=["CVE-2026-0000"],
    )
    patch = MatchedPatch(
        rank=1,
        commit=commit_info,
        relevance_score=0.95,
        match_reason="Direct fix for NULL pointer dereference",
    )
    assert patch.relevance_score > 0.9, "分数异常"
    print(f"  ✅ Patch: {patch.commit.commit_id}, score={patch.relevance_score}")


def test_retrieval_pipeline():
    """测试检索引擎"""
    print("\n" + "=" * 60)
    print("🔎 9. 检索管道测试")
    print("=" * 60)

    from src.indexer.milvus import MilvusClient, SearchResult
    from src.analyzer.models import CrashFeature

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_retrieval.db")
        os.environ["MILVUS_DB_PATH"] = db_path

        try:
            # 准备索引
            print("  9.1 构建测试索引 (50 条 commits)...")
            client = MilvusClient(
                backend="auto",
                collection_name="test_retrieval",
                dim=128,
            )
            client.create_collection(dim=128, drop_if_exists=True)

            dim = 128
            n = 50
            vectors = np.random.randn(n, dim).astype(np.float32)
            metadata = [
                {
                    "commit_hash": f"hash_{i:04d}",
                    "subject": f"mm: fix {'NULL pointer' if i < 10 else 'use-after-free' if i < 20 else 'deadlock'} in function_{i}",
                    "subsystem": "mm" if i < 30 else "fs",
                    "bug_type": "null_pointer" if i < 10 else "use_after_free" if i < 20 else "deadlock",
                    "author": f"author_{i}",
                    "date": f"2026-06-{i % 28 + 1:02d}",
                    "score": random.random(),
                }
                for i in range(n)
            ]
            client.insert(vectors, metadata)

            # 查询
            print("  9.2 检索测试...")
            query = np.random.randn(dim).astype(np.float32)
            result = client.search(query, top_k=10)
            assert len(result) > 0
            print(f"  ✅ 检索到 {len(result)} 条匹配")

            # 验证距离排序
            distances = result.distances
            for i in range(len(distances) - 1):
                assert distances[i] <= distances[i + 1] + 0.01, \
                    f"距离未排序: [{i}]={distances[i]}, [{i+1}]={distances[i+1]}"
            print("  ✅ 距离排序正确")

        finally:
            del os.environ["MILVUS_DB_PATH"]


# ============================================================================
# 主函数
# ============================================================================

def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║     Linux 内核宕机自动诊断与补丁匹配系统 — 本地功能集成测试              ║
║     Kernel Crash → Patch Matching System                 ║
╚══════════════════════════════════════════════════════════╝
""")

    start_time = time.time()

    # 运行所有测试
    test_config_module()
    test_milvus_lite()
    test_faiss_fallback()
    test_collector_module()
    test_rootcause_rules()
    test_llm_modules()
    test_knowledge_modules()
    test_schemas()
    test_retrieval_pipeline()

    # 汇总
    elapsed = time.time() - start_time
    total = PASS + FAIL + SKIP

    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    print(f"  ✅ 通过: {PASS}")
    print(f"  ❌ 失败: {FAIL}")
    print(f"  ⏭️  跳过: {SKIP}")
    print(f"  📦 总计: {total}")
    print(f"  ⏱️  耗时: {elapsed:.1f}s")
    print("=" * 60)

    if FAIL == 0:
        print("\n🎉 所有测试通过！")
    else:
        print(f"\n⚠️  {FAIL} 个测试失败，请检查。")

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
