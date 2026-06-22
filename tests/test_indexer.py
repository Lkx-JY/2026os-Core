"""Indexer module unit tests — embedding, FAISS/Milvus, index pipeline."""

import pytest
import tempfile
import os
import numpy as np


class TestEmbeddingEngine:
    """Test BGE-M3 encoder and fallback behavior."""

    def test_encoder_module_imports(self):
        from src.indexer.embedding import (
            BGEEncoder, BaseEncoder, BGE_M3_DIM, MODEL_DIMENSIONS,
            get_encoder, reset_encoder,
        )
        assert BGE_M3_DIM == 1024
        assert "BAAI/bge-m3" in MODEL_DIMENSIONS
        assert MODEL_DIMENSIONS["BAAI/bge-m3"] == 1024

    def test_base_encoder_raises_not_implemented(self):
        from src.indexer.embedding import BaseEncoder
        encoder = BaseEncoder()
        with pytest.raises(NotImplementedError):
            encoder.encode(["test"])
        with pytest.raises(NotImplementedError):
            _ = encoder.dimension

    def test_encoder_singleton(self):
        from src.indexer.embedding import get_encoder, reset_encoder
        reset_encoder()
        e1 = get_encoder()
        e2 = get_encoder()
        assert e1 is e2

    def test_encoder_encode_returns_numpy_array(self):
        from src.indexer.embedding import get_encoder, reset_encoder
        reset_encoder()
        encoder = get_encoder()
        vec = encoder.encode(["test text for encoding"])
        assert isinstance(vec, np.ndarray)
        assert vec.ndim == 2
        assert vec.shape[1] == encoder.dimension


class TestMilvusClient:
    """Test FAISS/Milvus dual-backend client."""

    @pytest.fixture
    def temp_faiss_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield os.path.join(tmpdir, "test_faiss")

    def test_faiss_backend_selection(self, temp_faiss_index):
        from src.indexer.milvus import MilvusClient
        client = MilvusClient(backend="faiss", dim=128, faiss_index_path=temp_faiss_index)
        assert client.active_backend == "faiss"

    def test_faiss_insert_and_search(self, temp_faiss_index):
        from src.indexer.milvus import MilvusClient
        client = MilvusClient(backend="faiss", dim=128, faiss_index_path=temp_faiss_index)
        vectors = np.random.randn(50, 128).astype(np.float32)
        metadata = [
            {
                "commit_hash": f"hash_{i:04d}",
                "subject": f"fix bug in subsystem_{i % 5}",
                "subsystem": f"subsystem_{i % 5}",
                "bug_type": "null_pointer" if i % 3 == 0 else "memory_leak",
            }
            for i in range(50)
        ]
        ids = client.insert(vectors, metadata)
        assert len(ids) == 50
        query = np.random.randn(128).astype(np.float32)
        result = client.search(query, top_k=5)
        assert len(result) >= 1

    def test_faiss_persistence(self, temp_faiss_index):
        from src.indexer.milvus import MilvusClient
        client = MilvusClient(backend="faiss", dim=128, faiss_index_path=temp_faiss_index)
        vectors = np.random.randn(10, 128).astype(np.float32)
        metadata = [{"subsystem": "mm"} for _ in range(10)]
        client.insert(vectors, metadata)
        client.save()
        assert os.path.exists(f"{temp_faiss_index}.meta.json") or os.path.exists(f"{temp_faiss_index}.index")

    def test_count_and_stats(self, temp_faiss_index):
        from src.indexer.milvus import MilvusClient
        client = MilvusClient(backend="faiss", dim=128, faiss_index_path=temp_faiss_index)
        vectors = np.random.randn(30, 128).astype(np.float32)
        metadata = [{"subsystem": "mm"} for _ in range(30)]
        client.insert(vectors, metadata)
        assert client.count() == 30
        stats = client.get_stats()
        assert "backend" in stats


class TestIndexPipeline:
    """Test commit → embedding → index pipeline."""

    def test_prepare_embedding_text(self):
        from src.indexer.pipeline import prepare_commit_embedding_text
        from src.collector.models import CommitInfo
        commit = CommitInfo(
            commit_hash="abc123",
            subject="mm: fix use-after-free in slub",
            subsystem="mm",
            bug_type="use_after_free",
            body="This fixes a UAF by adding proper RCU protection.",
        )
        text = prepare_commit_embedding_text(commit, use_root_cause=True)
        assert "Fix:" in text
        assert "use-after-free" in text.lower()
        assert len(text) > 50

    def test_prepare_embedding_text_no_root_cause(self):
        from src.indexer.pipeline import prepare_commit_embedding_text
        from src.collector.models import CommitInfo
        commit = CommitInfo(commit_hash="abc123", subject="trivial: fix typo", subsystem="kernel")
        text = prepare_commit_embedding_text(commit, use_root_cause=False)
        assert len(text) > 0
