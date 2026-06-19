"""Milvus 向量库操作模块 — Vector Database Layer

负责向量数据的存储、索引建立和相似度检索。支持 Milvus (生产) 和 FAISS (本地开发) 双后端。

设计要点:
- Milvus 生产模式: 支持百万级向量、IVF_FLAT/HNSW 索引、混合检索 (向量 + 标量过滤)
- FAISS 本地模式: 零依赖快速启动，适合开发测试和小规模验证
- 统一接口: 两个后端共享相同的 insert/search API，无缝切换
- Schema 设计: 包含 commit_hash, subsystem, bug_type, files, date 等标量字段用于混合检索

参考赛题要求:
- Milvus: 最推荐的生产向量库，支持百万向量 + 高性能
- FAISS: 本地开发推荐，简单快速
- 需要支持按子系统/版本/日期等标量字段过滤 (混合检索)
"""

import os
import json
import time
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field


# ============================================================================
# 向量库后端枚举
# ============================================================================

class BackendType:
    MILVUS = "milvus"
    FAISS = "faiss"
    AUTO = "auto"


# ============================================================================
# Milvus Schema 设计 — 用于混合检索的标量字段
# ============================================================================

# Milvus Collection Schema 字段定义
COLLECTION_SCHEMA_FIELDS = [
    {"name": "id", "dtype": "INT64", "is_primary": True, "auto_id": True},
    {"name": "commit_hash", "dtype": "VARCHAR", "max_length": 64},
    {"name": "subject", "dtype": "VARCHAR", "max_length": 512},
    {"name": "subsystem", "dtype": "VARCHAR", "max_length": 64},
    {"name": "bug_type", "dtype": "VARCHAR", "max_length": 64},
    {"name": "author", "dtype": "VARCHAR", "max_length": 128},
    {"name": "date", "dtype": "VARCHAR", "max_length": 32},
    {"name": "files_changed", "dtype": "VARCHAR", "max_length": 2048},
    {"name": "fix_tags", "dtype": "VARCHAR", "max_length": 512},
    {"name": "score", "dtype": "FLOAT"},
    {"name": "embedding", "dtype": "FLOAT_VECTOR", "dim": 1024},
]

# 可构建索引的标量字段 (用于混合检索过滤)
FILTERABLE_FIELDS = ["subsystem", "bug_type", "date", "commit_hash"]


@dataclass
class SearchResult:
    """向量检索结果"""
    ids: List[int] = field(default_factory=list)
    distances: List[float] = field(default_factory=list)
    metadata: List[Dict[str, Any]] = field(default_factory=list)
    vectors: Optional[np.ndarray] = None
    search_time_ms: float = 0.0

    def __len__(self) -> int:
        return len(self.ids)

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """转换为字典列表，便于下游使用"""
        results = []
        for i in range(len(self.ids)):
            item = {
                "id": self.ids[i],
                "distance": self.distances[i] if i < len(self.distances) else 0.0,
                "score": 1.0 - self.distances[i] if i < len(self.distances) else 0.0,
            }
            if i < len(self.metadata):
                item.update(self.metadata[i])
            results.append(item)
        return results


# ============================================================================
# FAISS 后端 — 本地开发/小规模验证
# ============================================================================

class FAISSBackend:
    """基于 FAISS 的本地向量检索引擎

    支持:
    - IndexFlatIP (内积搜索，配合归一化向量 = 余弦相似度)
    - IndexIVFFlat (倒排索引，大规模数据加速)
    - 标量字段存储 (JSON 元数据)
    - 持久化 (save/load)

    Example:
        >>> backend = FAISSBackend(dim=1024)
        >>> backend.insert(vectors, metadata_list)
        >>> result = backend.search(query_vec, top_k=10)
    """

    def __init__(self, dim: int = 1024, index_type: str = "flat"):
        """
        Args:
            dim: 向量维度
            index_type: 索引类型 — "flat" (精确) 或 "ivf" (近似)
        """
        self.dim = dim
        self.index_type = index_type
        self.index = None
        self.metadata_store: List[Dict[str, Any]] = []
        self._id_counter = 0
        self._vectors_np: Optional[np.ndarray] = None  # 纯 numpy 降级时的向量存储

    def _ensure_index(self, n_total: int = 0):
        """确保索引已初始化

        FAISS 本地模式始终使用 IndexFlatIP (精确检索，无需训练)。
        IVF 索引仅用于 Milvus 生产模式。
        """
        if self.index is not None:
            return

        try:
            import faiss
            # ★ FAISS 本地模式始终使用 FlatIP (精确内积搜索)
            # 对于开发测试和小规模验证场景，FlatIP 足够快且无需训练
            self.index = faiss.IndexFlatIP(self.dim)

        except ImportError:
            # FAISS 不可用时的纯 numpy 降级实现
            self.index = None

    def insert(
        self,
        vectors: np.ndarray,
        metadata: List[Dict[str, Any]],
    ) -> List[int]:
        """插入向量和元数据

        Args:
            vectors: shape (n, dim) 的 float32 向量
            metadata: 每条向量的元数据

        Returns:
            分配的 ID 列表
        """
        vectors = np.asarray(vectors, dtype=np.float32)
        n = vectors.shape[0]

        if n == 0:
            return []

        # 确保向量已归一化
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / (norms + 1e-8)

        self._ensure_index(n_total=n)

        ids = list(range(self._id_counter, self._id_counter + n))
        self._id_counter += n

        if self.index is not None:
            self.index.add(vectors)
        else:
            # 纯 numpy 降级: 累积存储向量
            if self._vectors_np is None:
                self._vectors_np = vectors
            else:
                self._vectors_np = np.vstack([self._vectors_np, vectors])

        # 存储元数据
        for i, meta in enumerate(metadata):
            meta_copy = dict(meta)
            meta_copy["_internal_id"] = ids[i]
            self.metadata_store.append(meta_copy)

        return ids

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> SearchResult:
        """向量相似度检索

        Args:
            query_vector: 查询向量 shape (dim,)
            top_k: 返回的 Top-K 数量
            filter_expr: 标量过滤表达式 (FAISS 模式下仅做简单后过滤)

        Returns:
            SearchResult 对象
        """
        t0 = time.time()

        # 归一化查询向量
        query = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)
        norm = np.linalg.norm(query)
        if norm > 0:
            query = query / norm

        total = len(self.metadata_store)
        if total == 0:
            return SearchResult(search_time_ms=(time.time() - t0) * 1000)

        actual_k = min(top_k, total)

        if self.index is not None:
            # 显式转换类型以匹配 FAISS 接口要求
            x = query.astype(np.float32)
            distances, indices = self.index.search(x, actual_k)
            distances = distances[0].tolist()
            indices = indices[0].tolist()
        else:
            # 纯 numpy 降级: 暴力计算余弦相似度
            if self._vectors_np is None:
                return SearchResult(search_time_ms=(time.time() - t0) * 1000)

            sims = np.dot(self._vectors_np, query.T).flatten()
            top_indices = np.argsort(sims)[::-1][:actual_k]
            distances = sims[top_indices].tolist()
            indices = top_indices.tolist()

        # 收集元数据
        metas = []
        for idx in indices:
            if 0 <= idx < len(self.metadata_store):
                metas.append(self.metadata_store[idx])
            else:
                metas.append({})

        # 简单后过滤
        if filter_expr and metas:
            metas, distances, indices = self._apply_post_filter(
                filter_expr, metas, distances, indices
            )

        elapsed_ms = (time.time() - t0) * 1000

        return SearchResult(
            ids=indices,
            distances=distances,
            metadata=metas,
            search_time_ms=elapsed_ms,
        )

    def _apply_post_filter(
        self,
        filter_expr: str,
        metas: List[Dict],
        distances: List[float],
        indices: List[int],
    ) -> Tuple[List[Dict], List[float], List[int]]:
        """简单后过滤 — 支持 field=value 格式"""
        filtered_metas = []
        filtered_distances = []
        filtered_indices = []
        for i, meta in enumerate(metas):
            # 简单解析: "subsystem==mm" 或 "bug_type==deadlock"
            if "==" in filter_expr:
                field, value = filter_expr.split("==", 1)
                field = field.strip()
                value = value.strip().strip("'\"")
                if str(meta.get(field, "")) == value:
                    filtered_metas.append(meta)
                    filtered_distances.append(distances[i])
                    filtered_indices.append(indices[i])
            else:
                # 不支持复杂表达式，全返回
                filtered_metas.append(meta)
                filtered_distances.append(distances[i])
                filtered_indices.append(indices[i])

        return filtered_metas, filtered_distances, filtered_indices

    def save(self, path: str):
        """持久化索引到磁盘"""
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)

        if self.index is not None:
            try:
                import faiss
                faiss.write_index(self.index, f"{path}.index")
            except Exception as e:
                print(f"Warning: Failed to save FAISS index: {e}")

        # 保存元数据 (处理 set 等不可 JSON 序列化的类型)
        def _make_serializable(obj):
            if isinstance(obj, dict):
                return {str(k): _make_serializable(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_make_serializable(v) for v in obj]
            if isinstance(obj, set):
                return list(obj)
            if isinstance(obj, (str, int, float, bool)) or obj is None:
                return obj
            return str(obj)

        with open(f"{path}.meta.json", "w") as f:
            json.dump({
                "dim": self.dim,
                "index_type": self.index_type,
                "id_counter": self._id_counter,
                "metadata": _make_serializable(self.metadata_store),
            }, f, ensure_ascii=False, indent=2)

    def load(self, path: str):
        """从磁盘加载索引"""
        try:
            import faiss
            self.index = faiss.read_index(f"{path}.index")
        except Exception as e:
            print(f"Warning: Failed to load FAISS index: {e}")
            self.index = None

        try:
            with open(f"{path}.meta.json", "r") as f:
                data = json.load(f)
                self.dim = data.get("dim", self.dim)
                self.index_type = data.get("index_type", self.index_type)
                self._id_counter = data.get("id_counter", 0)
                self.metadata_store = data.get("metadata", [])
        except FileNotFoundError:
            pass

    def count(self) -> int:
        """返回索引中的向量总数"""
        return len(self.metadata_store)

    def get_stats(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        return {
            "backend": "faiss",
            "index_type": self.index_type,
            "dimension": self.dim,
            "total_vectors": self.count(),
            "has_index": self.index is not None,
        }


# ============================================================================
# Milvus 后端 — 生产环境
# ============================================================================

class MilvusBackend:
    """基于 PyMilvus 的生产级向量检索引擎

    支持:
    - Collection 管理 (create/drop/exists)
    - 混合检索 (向量相似度 + 标量过滤)
    - IVF_FLAT / HNSW 索引
    - 分区 (按子系统/日期)
    - 批量插入 (flush 保证持久化)

    Example:
        >>> backend = MilvusBackend(host="localhost", port="19530")
        >>> backend.create_collection(dim=1024)
        >>> backend.insert(vectors, metadata_list)
        >>> result = backend.search(query_vec, top_k=10, filter_expr='subsystem=="mm"')
    """

    def __init__(
        self,
        host: str = "localhost",
        port: str = "19530",
        collection_name: str = "linux_commits",
    ):
        self.host = host
        self.port = str(port)
        self.collection_name = collection_name
        self._connected = False
        self._collection = None
        self._dim = 1024

    # ── 连接管理 ──────────────────────────────────────────────

    def connect(self, timeout: int = 3) -> bool:
        """建立 Milvus 连接

        添加真实连接验证: 通过 list_collections 确认服务器可达,
        避免 "连接成功但服务器不可用" 的假象。

        Args:
            timeout: 连接超时秒数

        Returns:
            bool: 连接是否成功且服务器可达
        """
        if self._connected:
            return True

        try:
            from pymilvus import connections, MilvusClient as PyMilvusClient

            # 尝试用新版 MilvusClient 验证连通性
            try:
                import asyncio
                uri = f"http://{self.host}:{self.port}"
                client = PyMilvusClient(uri=uri, timeout=timeout)
                # 验证服务器是否真实可达 (新版本 list_collections 是 async)
                asyncio.run(client.list_collections())
            except Exception:
                # 新版 API 不可用, 尝试旧版
                try:
                    connections.connect(
                        alias="default",
                        host=self.host,
                        port=self.port,
                        timeout=timeout,
                    )
                    from pymilvus import utility
                    utility.list_collections()
                except Exception:
                    # Milvus 服务不可达
                    return False

            self._connected = True
            return True
        except ImportError:
            return False
        except Exception:
            return False

    def disconnect(self):
        """断开连接"""
        if self._connected:
            try:
                from pymilvus import connections
                connections.disconnect("default")
            except Exception:
                pass
            self._connected = False
            self._collection = None

    # ── Collection 管理 ───────────────────────────────────────

    def collection_exists(self) -> bool:
        """检查 Collection 是否存在"""
        if not self.connect():
            return False
        try:
            from pymilvus import utility
            # 使用 cast 或 Any 绕过 SDK 版本带来的复杂类型推导报错
            res: Any = utility.has_collection(self.collection_name)
            if hasattr(res, "result") and callable(res.result):
                return bool(res.result())
            return bool(res)
        except Exception:
            return False

    def create_collection(
        self,
        dim: int = 1024,
        index_type: str = "IVF_FLAT",
        metric_type: str = "IP",
        nlist: int = 1024,
        drop_if_exists: bool = False,
    ):
        """创建 Milvus Collection 及索引

        Args:
            dim: 向量维度 (BGE-M3 = 1024)
            index_type: 索引类型 — "IVF_FLAT", "HNSW", "FLAT"
            metric_type: 距离度量 — "IP" (内积/余弦), "L2" (欧氏距离)
            nlist: IVF 聚类数 (HNSW 时无效)
            drop_if_exists: 是否删除已存在的同名 Collection
        """
        if not self.connect():
            return

        self._dim = dim

        try:
            from pymilvus import (
                Collection, CollectionSchema, FieldSchema, DataType, utility,
            )

            # 检查是否存在
            if self.collection_exists():
                if drop_if_exists:
                    try:
                        # 显式忽略异步返回值的报错
                        _ = utility.drop_collection(self.collection_name)
                    except Exception:
                        pass
                else:
                    self._collection = Collection(self.collection_name)
                    try:
                        _ = self._collection.load()
                    except Exception:
                        pass
                    return

            # 定义 Schema
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="commit_hash", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="subject", dtype=DataType.VARCHAR, max_length=512),
                FieldSchema(name="subsystem", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="bug_type", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="author", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="date", dtype=DataType.VARCHAR, max_length=32),
                FieldSchema(name="files_changed", dtype=DataType.VARCHAR, max_length=2048),
                FieldSchema(name="fix_tags", dtype=DataType.VARCHAR, max_length=512),
                FieldSchema(name="score", dtype=DataType.FLOAT),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
            ]

            schema = CollectionSchema(fields, description="Linux Kernel Commits Vector Index")

            # 创建 Collection
            self._collection = Collection(name=self.collection_name, schema=schema)

            # 创建索引
            index_params = self._build_index_params(index_type, metric_type, nlist)
            try:
                _ = self._collection.create_index(
                    field_name="embedding",
                    index_params=index_params,
                )
            except Exception:
                pass

            # 加载到内存
            try:
                _ = self._collection.load()
            except Exception:
                pass

            print(f"Milvus collection '{self.collection_name}' created (dim={dim}, index={index_type})")

        except ImportError:
            pass
        except Exception as e:
            print(f"Milvus create_collection error: {e}")

    def _build_index_params(
        self,
        index_type: str,
        metric_type: str,
        nlist: int,
    ) -> Dict[str, Any]:
        """构建索引参数"""
        if index_type == "HNSW":
            return {
                "index_type": "HNSW",
                "metric_type": metric_type,
                "params": {"M": 16, "efConstruction": 200},
            }
        elif index_type == "IVF_FLAT":
            return {
                "index_type": "IVF_FLAT",
                "metric_type": metric_type,
                "params": {"nlist": nlist},
            }
        elif index_type == "FLAT":
            return {
                "index_type": "FLAT",
                "metric_type": metric_type,
                "params": {},
            }
        else:
            return {
                "index_type": "IVF_FLAT",
                "metric_type": metric_type,
                "params": {"nlist": nlist},
            }

    def drop_collection(self):
        """删除 Collection"""
        if not self.connect():
            return
        try:
            from pymilvus import utility
            if self.collection_exists():
                _ = utility.drop_collection(self.collection_name)
                self._collection = None
        except Exception as e:
            print(f"Milvus drop_collection error: {e}")

    # ── 数据操作 ──────────────────────────────────────────────

    def insert(
        self,
        vectors: np.ndarray,
        metadata: List[Dict[str, Any]],
        partition_name: Optional[str] = None,
        batch_size: int = 1000,
    ) -> List[int]:
        """批量插入向量和元数据

        Args:
            vectors: shape (n, dim) 的 float32 向量
            metadata: 元数据列表，键需与 Schema 字段匹配
            partition_name: 分区名 (可选，如 "subsystem_mm")
            batch_size: 批量插入大小

        Returns:
            分配的 ID 列表 (Milvus auto_id 模式下可能为空)
        """
        if not self.connect() or self._collection is None:
            return []

        vectors = np.asarray(vectors, dtype=np.float32)
        n = vectors.shape[0]
        if n == 0:
            return []

        try:
            # 准备插入数据
            insert_data = self._prepare_insert_data(vectors, metadata)

            # 分批插入
            total_inserted = 0
            for i in range(0, n, batch_size):
                batch = {
                    k: v[i:i + batch_size]
                    for k, v in insert_data.items()
                }

                if partition_name:
                    try:
                        self._collection.insert(batch, partition_name=partition_name)
                    except Exception:
                        pass
                else:
                    try:
                        self._collection.insert(batch)
                    except Exception:
                        pass

                total_inserted += len(batch.get("embedding", []))

            # Flush 确保持久化
            try:
                _ = self._collection.flush()
            except Exception:
                pass

            return list(range(total_inserted))  # auto_id 模式下实际 ID 由 Milvus 分配

        except Exception as e:
            print(f"Milvus insert error: {e}")
            return []

    def _prepare_insert_data(
        self,
        vectors: np.ndarray,
        metadata: List[Dict[str, Any]],
    ) -> Dict[str, List]:
        """准备符合 Schema 的插入数据"""
        n = vectors.shape[0]

        data = {
            "embedding": [vectors[i].tolist() for i in range(n)],
            "commit_hash": [],
            "subject": [],
            "subsystem": [],
            "bug_type": [],
            "author": [],
            "date": [],
            "files_changed": [],
            "fix_tags": [],
            "score": [],
        }

        for meta in metadata:
            data["commit_hash"].append(str(meta.get("commit_hash", ""))[:64])
            data["subject"].append(str(meta.get("subject", ""))[:512])
            data["subsystem"].append(str(meta.get("subsystem", "unknown"))[:64])
            data["bug_type"].append(str(meta.get("bug_type", "unknown"))[:64])
            data["author"].append(str(meta.get("author", ""))[:128])
            data["date"].append(str(meta.get("date", ""))[:32])
            data["files_changed"].append(
                ", ".join(meta.get("files_changed", [])[:20])[:2048]
            )
            data["fix_tags"].append(
                ", ".join(meta.get("fix_tags", [])[:10])[:512]
            )
            data["score"].append(float(meta.get("score", 0.0)))

        return data

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 10,
        filter_expr: Optional[str] = None,
        output_fields: Optional[List[str]] = None,
        nprobe: int = 16,
    ) -> SearchResult:
        """向量相似度检索 (混合检索)

        Args:
            query_vector: 查询向量 shape (dim,)
            top_k: Top-K
            filter_expr: Milvus 标量过滤表达式，如 'subsystem=="mm" && bug_type=="deadlock"'
            output_fields: 需要返回的标量字段
            nprobe: IVF 探测的聚类数

        Returns:
            SearchResult 对象
        """
        t0 = time.time()

        if not self.connect() or self._collection is None:
            return SearchResult(search_time_ms=(time.time() - t0) * 1000)

        query = np.asarray(query_vector, dtype=np.float32).reshape(1, -1).tolist()

        if output_fields is None:
            output_fields = [
                "commit_hash", "subject", "subsystem",
                "bug_type", "author", "date", "score", "fix_tags",
            ]

        search_params = {
            "metric_type": "IP",
            "params": {"nprobe": nprobe},
        }

        try:
            # 兼容异步/同步返回
            results: Any = self._collection.search(
                data=query,
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=filter_expr,
                output_fields=output_fields,
            )

            # 强制等待结果 (针对某些异步返回的 SDK 版本)
            if hasattr(results, "result") and callable(results.result):
                results = results.result()

            elapsed_ms = (time.time() - t0) * 1000

            if results is None:
                return SearchResult(search_time_ms=elapsed_ms)
            
            # 检查长度
            try:
                res_len = len(results)
            except Exception:
                res_len = 0

            if res_len == 0:
                return SearchResult(search_time_ms=elapsed_ms)

            hits = results[0]
            ids = [hit.id for hit in hits]
            distances = [hit.distance for hit in hits]
            metas = []
            for hit in hits:
                meta = {}
                for field in output_fields:
                    try:
                        meta[field] = hit.entity.get(field)
                    except Exception:
                        meta[field] = ""
                metas.append(meta)

            return SearchResult(
                ids=ids,
                distances=distances,
                metadata=metas,
                search_time_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = (time.time() - t0) * 1000
            print(f"Milvus search error: {e}")
            return SearchResult(search_time_ms=elapsed_ms)

    def count(self) -> int:
        """返回 Collection 中的向量总数"""
        if not self.connect() or self._collection is None:
            return 0
        try:
            self._collection.flush()
            return self._collection.num_entities
        except Exception:
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """获取 Collection 统计信息"""
        stats = {
            "backend": "milvus",
            "host": self.host,
            "port": self.port,
            "collection_name": self.collection_name,
            "connected": self._connected,
            "total_vectors": 0,
        }
        if self._connected and self._collection is not None:
            try:
                stats["total_vectors"] = self.count()
            except Exception:
                pass
        return stats


# ============================================================================
# 统一客户端 — 自动选择后端
# ============================================================================

class MilvusClient:
    """统一的向量数据库客户端

    自动选择后端:
    - MILVUS: 生产模式，需要 PyMilvus + 运行中的 Milvus 服务
    - FAISS: 本地模式，零依赖，适合开发测试
    - 自动降级: MILVUS 连接失败时自动切换到 FAISS

    Example:
        >>> client = MilvusClient(backend="auto")
        >>> client.create_collection(dim=1024)
        >>> client.insert(vectors, metadata)
        >>> result = client.search(query_vec, top_k=10, filter_expr='subsystem=="mm"')
    """

    def __init__(
        self,
        backend: str = "auto",
        host: str = "localhost",
        port: str = "19530",
        collection_name: str = "linux_commits",
        dim: int = 1024,
        faiss_index_path: str = "data/faiss_index",
    ):
        """
        Args:
            backend: "milvus", "faiss", 或 "auto" (自动检测)
            host: Milvus 主机
            port: Milvus 端口
            collection_name: Collection 名称
            dim: 向量维度
            faiss_index_path: FAISS 索引持久化路径
        """
        self.backend_type = backend
        self.dim = dim
        self.faiss_index_path = faiss_index_path
        self.collection_name = collection_name

        self._milvus = MilvusBackend(host, port, collection_name)
        self._faiss = FAISSBackend(dim=dim)
        self._active_backend: Optional[str] = None

        # Milvus Lite 客户端（本地文件模式）
        self._milvus_lite_client = None
        self._milvus_lite_path = None

        # 确定活跃后端
        self._resolve_backend()

    def _resolve_backend(self):
        """解析使用哪个后端

        优先级:
        1. 环境变量 MILVUS_FORCE_FAISS=1 → 强制 FAISS
        2. Milvus Lite 本地数据库 (MILVUS_DB_PATH 环境变量或默认路径)
        3. backend_type="faiss" → FAISS
        4. backend_type="milvus" → 先试 Milvus Docker, 不可用则试 Milvus Lite
        5. auto → Milvus Lite > Milvus Docker > FAISS
        """
        force_faiss = os.environ.get("MILVUS_FORCE_FAISS", "").strip() in ("1", "true", "yes")

        if force_faiss:
            self._active_backend = BackendType.FAISS
            print("FAISS 模式 (MILVUS_FORCE_FAISS=1)")
            self._try_load_faiss()
            return

        if self.backend_type == BackendType.FAISS:
            self._active_backend = BackendType.FAISS
            self._try_load_faiss()
            return

        # ── 尝试 Milvus Lite (本地文件模式) ──────────────
        milvus_db_path = os.environ.get(
            "MILVUS_DB_PATH",
            "data/milvus_lite.db",
        )
        if self._try_milvus_lite(milvus_db_path):
            return

        # ── 尝试 Milvus Docker (生产模式) ──────────────
        if self.backend_type == BackendType.MILVUS or self.backend_type == BackendType.AUTO:
            if self._milvus.connect(timeout=3):
                self._active_backend = BackendType.MILVUS
                print(f"Milvus Docker 模式 ({self._milvus.host}:{self._milvus.port})")
                return
            else:
                print("Info: Milvus Docker 不可达 (localhost:19530)")

        # ── 回退到 FAISS ─────────────────────────────────
        self._active_backend = BackendType.FAISS
        print("Auto → FAISS 模式 (Milvus 不可达)")
        self._try_load_faiss()

    def _try_milvus_lite(self, db_path: str) -> bool:
        """尝试使用 Milvus Lite (嵌入式本地文件模式)

        优点:
        - 无需 Docker，零配置
        - 与 FAISS 兼容的本地接口
        - 支持全部 Milvus API

        Returns:
            bool: 是否成功切换到 Milvus Lite
        """
        try:
            from pymilvus import MilvusClient as PyMilvusClient

            # 确保父目录存在
            import os as _os
            db_dir = _os.path.dirname(db_path)
            if db_dir:
                _os.makedirs(db_dir, exist_ok=True)

            # 测试连接：创建 MilvusClient 本地文件实例
            test_client = PyMilvusClient(db_path)
            # 尝试执行基本操作验证可用
            test_client.list_collections()

            # 连接成功，保存引用
            self._milvus_lite_client = test_client
            self._milvus_lite_path = db_path
            self._active_backend = BackendType.MILVUS
            print(f"Milvus Lite 模式 (本地文件: {db_path})")
            return True

        except ImportError:
            # Milvus Lite 未安装 (pymilvus >= 2.4.0 内置)
            print("Info: Milvus Lite 不可用 (需要 pymilvus >= 2.4.0)")
            return False
        except Exception as e:
            print(f"Info: Milvus Lite 连接失败: {e}")
            return False

    def _try_load_faiss(self):
        """尝试加载已有的 FAISS 索引"""
        if os.path.exists(f"{self.faiss_index_path}.meta.json"):
            self._faiss.load(self.faiss_index_path)
            print(f"  已加载 FAISS 索引: {self._faiss.count()} 条向量")

    @property
    def active_backend(self) -> str:
        """当前活跃的后端类型"""
        return self._active_backend or BackendType.FAISS

    # ── 接口统一 ──────────────────────────────────────────────

    def create_collection(
        self,
        dim: Optional[int] = None,
        index_type: str = "IVF_FLAT",
        drop_if_exists: bool = False,
    ):
        """创建 Collection / 初始化索引"""
        dim = dim or self.dim

        # ── Milvus Lite 模式 ─────────────────────────────
        if self._milvus_lite_client is not None:
            try:
                if drop_if_exists and self._milvus_lite_client.has_collection(self.collection_name):
                    self._milvus_lite_client.drop_collection(self.collection_name)

                if not self._milvus_lite_client.has_collection(self.collection_name):
                    # Milvus Lite 支持 metric_type: "COSINE", "L2", "IP"
                    self._milvus_lite_client.create_collection(
                        collection_name=self.collection_name,
                        dimension=dim,
                        metric_type="COSINE",
                        auto_id=True,
                    )
                    print(f"Milvus Lite collection '{self.collection_name}' created (dim={dim})")
                return
            except Exception as e:
                print(f"Milvus Lite create_collection error: {e}")
                return

        # ── Milvus Docker 模式 ───────────────────────────
        if self._active_backend == BackendType.MILVUS:
            self._milvus.create_collection(
                dim=dim,
                index_type=index_type,
                drop_if_exists=drop_if_exists,
            )
        else:
            # FAISS 无需显式创建，设置 index_type
            self._faiss.index_type = "flat" if index_type == "FLAT" else "ivf"

    def insert(
        self,
        vectors: np.ndarray,
        metadata: List[Dict[str, Any]],
        batch_size: int = 1000,
    ) -> List[int]:
        """插入向量和元数据"""
        # ── Milvus Lite 模式 ─────────────────────────────
        if self._milvus_lite_client is not None:
            try:
                vectors = np.asarray(vectors, dtype=np.float32)
                n = vectors.shape[0]
                if n == 0:
                    return []

                # row-wise list-of-dicts 格式
                data = []
                for i in range(n):
                    row = {
                        "vector": vectors[i].tolist(),
                        "commit_hash": str(metadata[i].get("commit_hash", ""))[:64] if i < len(metadata) else "",
                        "subject": str(metadata[i].get("subject", ""))[:512] if i < len(metadata) else "",
                        "subsystem": str(metadata[i].get("subsystem", "unknown"))[:64] if i < len(metadata) else "unknown",
                        "bug_type": str(metadata[i].get("bug_type", "unknown"))[:64] if i < len(metadata) else "unknown",
                        "author": str(metadata[i].get("author", ""))[:128] if i < len(metadata) else "",
                        "date": str(metadata[i].get("date", ""))[:32] if i < len(metadata) else "",
                        "score": float(metadata[i].get("score", 0.0)) if i < len(metadata) else 0.0,
                    }
                    data.append(row)

                res = self._milvus_lite_client.insert(
                    collection_name=self.collection_name,
                    data=data,
                )
                return list(range(res.get("insert_count", n)))
            except Exception as e:
                print(f"Milvus Lite insert error: {e}")
                return []

        # ── Milvus Docker 模式 ───────────────────────────
        if self._active_backend == BackendType.MILVUS:
            return self._milvus.insert(vectors, metadata, batch_size=batch_size)
        else:
            return self._faiss.insert(vectors, metadata)

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> SearchResult:
        """向量相似度检索

        Args:
            query_vector: 查询向量
            top_k: Top-K 数量
            filter_expr: 标量过滤表达式，如 'subsystem=="mm"'

        Returns:
            SearchResult 对象
        """
        t0 = time.time()

        # ── Milvus Lite 模式 ─────────────────────────────
        if self._milvus_lite_client is not None:
            try:
                query = np.asarray(query_vector, dtype=np.float32).tolist()

                results = self._milvus_lite_client.search(
                    collection_name=self.collection_name,
                    data=[query],
                    limit=top_k,
                    output_fields=["commit_hash", "subject", "subsystem",
                                   "bug_type", "author", "date", "score"],
                )

                elapsed_ms = (time.time() - t0) * 1000

                if not results or len(results) == 0:
                    return SearchResult(search_time_ms=elapsed_ms)

                hits = results[0]
                ids = [hit.get("id", i) for i, hit in enumerate(hits)]
                distances = [hit.get("distance", 0.0) for hit in hits]
                metas = [{k: v for k, v in hit.items() if k != "vector"}
                         for hit in hits]

                return SearchResult(
                    ids=ids,
                    distances=distances,
                    metadata=metas,
                    search_time_ms=elapsed_ms,
                )
            except Exception as e:
                elapsed_ms = (time.time() - t0) * 1000
                print(f"Milvus Lite search error: {e}")
                return SearchResult(search_time_ms=elapsed_ms)

        # ── Milvus Docker 模式 ───────────────────────────
        if self._active_backend == BackendType.MILVUS:
            return self._milvus.search(
                query_vector, top_k=top_k, filter_expr=filter_expr,
            )
        else:
            return self._faiss.search(
                query_vector, top_k=top_k, filter_expr=filter_expr,
            )

    def save(self):
        """持久化索引"""
        if self._active_backend == BackendType.FAISS:
            self._faiss.save(self.faiss_index_path)
        # Milvus Lite 自动持久化到文件

    def count(self) -> int:
        """返回索引总数"""
        # Milvus Lite
        if self._milvus_lite_client is not None:
            try:
                stats = self._milvus_lite_client.get_collection_stats(self.collection_name)
                return stats.get("row_count", 0)
            except Exception:
                return 0

        if self._active_backend == BackendType.MILVUS:
            return self._milvus.count()
        return self._faiss.count()

    def get_stats(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        # Milvus Lite
        if self._milvus_lite_client is not None:
            try:
                stats = self._milvus_lite_client.get_collection_stats(self.collection_name)
                return {
                    "backend": "milvus_lite",
                    "db_path": self._milvus_lite_path,
                    "collection_name": self.collection_name,
                    "total_vectors": stats.get("row_count", 0),
                    "connected": True,
                }
            except Exception:
                return {"backend": "milvus_lite", "connected": False}

        if self._active_backend == BackendType.MILVUS:
            return self._milvus.get_stats()
        return self._faiss.get_stats()

    def collection_exists(self) -> bool:
        """检查 Collection/索引是否存在"""
        # Milvus Lite
        if self._milvus_lite_client is not None:
            try:
                return self._milvus_lite_client.has_collection(self.collection_name)
            except Exception:
                return False

        if self._active_backend == BackendType.MILVUS:
            return self._milvus.collection_exists()
        return self._faiss.count() > 0


# ============================================================================
# 全局单例
# ============================================================================

_milvus_client: Optional[MilvusClient] = None


def get_milvus_client(
    backend: str = "auto",
    host: str = "localhost",
    port: str = "19530",
    collection_name: str = "linux_commits",
    dim: int = 1024,
) -> MilvusClient:
    """获取/创建全局 MilvusClient 单例

    Args:
        backend: "milvus", "faiss", 或 "auto"
        host: Milvus 主机
        port: Milvus 端口
        collection_name: Collection 名称
        dim: 向量维度

    Returns:
        MilvusClient 实例
    """
    global _milvus_client
    if _milvus_client is None:
        _milvus_client = MilvusClient(
            backend=backend,
            host=host,
            port=port,
            collection_name=collection_name,
            dim=dim,
        )
    return _milvus_client


def reset_milvus_client():
    """重置 MilvusClient 单例"""
    global _milvus_client
    _milvus_client = None


__all__ = [
    "MilvusClient",
    "MilvusBackend",
    "FAISSBackend",
    "SearchResult",
    "get_milvus_client",
    "reset_milvus_client",
    "BackendType",
    "COLLECTION_SCHEMA_FIELDS",
    "FILTERABLE_FIELDS",
]
