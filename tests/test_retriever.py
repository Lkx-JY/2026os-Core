"""Retriever module unit tests — recall, filter, rerank, pipeline."""

import pytest
import tempfile
import os
import numpy as np


class TestVersionFilter:
    """Test kernel version comparison and filtering."""

    def test_parse_kernel_version(self):
        from src.retriever.filter import parse_kernel_version
        v = parse_kernel_version("6.1.0-15-amd64")
        assert v == (6, 1, 0)
        v2 = parse_kernel_version("5.15.0")
        assert v2 == (5, 15, 0)

    def test_version_compatible_same_major(self):
        from src.retriever.filter import is_version_compatible
        assert is_version_compatible("6.1.0", "6.1.50") is True

    def test_version_incompatible_different_major(self):
        from src.retriever.filter import is_version_compatible
        assert is_version_compatible("5.15.0", "6.1.0") is False


class TestSubsystemFilter:
    """Test subsystem-based filtering."""

    def test_exact_subsystem_match(self):
        from src.retriever.filter import filter_by_subsystem
        candidates = [
            {"subsystem": "mm"},
            {"subsystem": "net"},
            {"subsystem": "fs"},
        ]
        result = filter_by_subsystem(candidates, "mm")
        assert len(result) == 1
        assert result[0]["subsystem"] == "mm"

    def test_subsystem_hierarchy_expansion(self):
        from src.retriever.filter import expand_subsystem_filter
        subs = expand_subsystem_filter("mm")
        assert "mm" in subs
        assert len(subs) >= 1


class TestReranker:
    """Test BGE-Reranker-v2 and fallback scoring."""

    def test_reranker_import(self):
        from src.retriever.rerank import BGEReranker, RankedItem
        reranker = BGEReranker()
        assert reranker.model_name == "BAAI/bge-reranker-v2-m3"

    def test_reranker_fallback_scoring(self):
        from src.retriever.rerank import BGEReranker
        reranker = BGEReranker()
        query = "NULL pointer dereference in memory management"
        documents = [
            "mm: add NULL check in slub allocator",
            "net: fix TCP checksum offload",
            "fs: add bounds check in ext4 writeback",
        ]
        scores = reranker.compute_scores(query, documents)
        assert len(scores) == 3
        for s in scores:
            assert 0.0 <= s <= 1.0

    def test_ranked_item_creation(self):
        from src.retriever.rerank import RankedItem
        item = RankedItem(
            rank=1, commit_hash="abc123", subject="mm: fix UAF",
            subsystem="mm", bug_type="use_after_free",
            vector_score=0.85, reranker_score=0.92, final_score=0.89,
        )
        assert item.rank == 1


class TestRecall:
    """Test vector recall module."""

    @pytest.fixture
    def temp_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = os.path.join(tmpdir, "faiss")
            from src.indexer.milvus import MilvusClient
            client = MilvusClient(backend="faiss", dim=128, faiss_index_path=index_path)
            vectors = np.random.randn(100, 128).astype(np.float32)
            metadata = [
                {
                    "commit_hash": f"hash_{i:04d}",
                    "subject": f"fix: {'NULL pointer' if i < 30 else 'deadlock' if i < 60 else 'memory leak'} in func_{i}",
                    "subsystem": "mm" if i < 50 else "fs",
                    "bug_type": "null_pointer" if i < 30 else "deadlock" if i < 60 else "memory_leak",
                }
                for i in range(100)
            ]
            client.insert(vectors, metadata)
            yield client, vectors

    def test_vector_recall_returns_results(self, temp_index):
        client, vectors = temp_index
        query = np.random.randn(128).astype(np.float32)
        result = client.search(query, top_k=10)
        assert len(result) == 10

    def test_vector_recall_with_metadata(self, temp_index):
        client, vectors = temp_index
        query = np.random.randn(128).astype(np.float32)
        result = client.search(query, top_k=10)
        for item in result.to_dict_list()[:3]:
            assert "commit_hash" in item
            assert "subsystem" in item


class TestRetrievalPipeline:
    """Test full retrieval pipeline integration."""

    def test_pipeline_imports(self):
        from src.retriever.pipeline import run_retrieval_pipeline, quick_search
        assert callable(run_retrieval_pipeline)
        assert callable(quick_search)

    def test_recall_module_exports(self):
        from src.retriever.recall import SearchResult, recall_candidates, recall_from_rootcause
        assert SearchResult is not None

    def test_filter_module_exports(self):
        from src.retriever.filter import (
            filter_by_kernel_version, filter_by_subsystem, build_milvus_filter_expr,
        )
        assert callable(filter_by_kernel_version)
        assert callable(filter_by_subsystem)
        assert callable(build_milvus_filter_expr)
