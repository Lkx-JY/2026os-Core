"""向量编码模块 — Embedding Engine

负责使用 BGE-M3 等模型将文本转换为高维向量，是连接"语义理解"与"向量检索"的核心编码层。

设计要点:
- BGE-M3 (BAAI/bge-m3) 作为首选模型: 中英双语、1024 维、长文本支持 (8192 tokens)
- 批量编码: 支持 configurable batch_size，避免百万级数据 OOM
- GPU 加速: 自动检测 CUDA 可用性，支持 device 配置
- 降级策略: sentence-transformers 不可用时使用 mock 编码器，不阻塞流程
- 维度配置: 支持 BGE-M3 (1024d) / GTE-Qwen2 (1536d / 2048d) / bce-embedding (768d)

"""

import numpy as np
from typing import List, Union, Optional, Callable


# BGE-M3 标准输出维度
BGE_M3_DIM = 1024
# 支持的模型维度映射
MODEL_DIMENSIONS = {
    "BAAI/bge-m3": 1024,
    "BAAI/bge-large-en-v1.5": 1024,
    "BAAI/bge-large-zh-v1.5": 1024,
    "Alibaba-NLP/gte-Qwen2-1.5B-instruct": 1536,
    "Alibaba-NLP/gte-Qwen2-7B-instruct": 3584,
    "maidalun1020/bce-embedding-base_v1": 768,
    "thenlper/gte-large": 1024,
    "intfloat/e5-large-v2": 1024,
}


class BaseEncoder:
    """编码器基类 — 定义编码接口"""
    def encode(self, texts: Union[str, List[str]]) -> np.ndarray:
        raise NotImplementedError

    @property
    def dimension(self) -> int:
        raise NotImplementedError


class BGEEncoder(BaseEncoder):
    """基于 BGE-M3 的编码器实现

    特性:
    - 延迟初始化 (lazy init): 减少启动开销，仅在首次编码时加载模型
    - 批量编码: 自动分批处理，支持进度回调
    - 向量归一化: normalize_embeddings=True 确保余弦相似度检索精度
    - GPU 加速: 自动检测 CUDA，也可手动指定 device

    Example:
        >>> encoder = BGEEncoder()
        >>> vecs = encoder.encode(["text1", "text2"], batch_size=32)
        >>> print(vecs.shape)  # (2, 1024)
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        device: Optional[str] = None,
        dimension: Optional[int] = None,
        normalize: bool = True,
    ):
        """
        Args:
            model_name: HuggingFace 模型名称
            device: 设备 — "cpu", "cuda", "cuda:0" 等；None 时自动检测
            dimension: 向量维度；None 时从 MODEL_DIMENSIONS 查找，默认 1024
            normalize: 是否归一化向量 (推荐 True 以使用内积相似度)
        """
        self.model_name = model_name
        self.normalize = normalize

        # 自动检测 device
        if device is None:
            self.device = self._auto_detect_device()
        else:
            self.device = device

        # 确定维度
        if dimension is not None:
            self._dimension = dimension
        else:
            self._dimension = MODEL_DIMENSIONS.get(model_name, BGE_M3_DIM)

        self.model = None
        self._initialized = False
        self._init_error = None

    @staticmethod
    def _auto_detect_device() -> str:
        """自动检测最佳可用设备"""
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def is_available(self) -> bool:
        """检查真实模型是否可用"""
        self._lazy_init()
        return self.model is not None

    @property
    def init_error(self) -> Optional[str]:
        """获取初始化错误信息（如果有）"""
        return self._init_error

    def _lazy_init(self):
        """延迟初始化模型 — 减少启动开销"""
        if self._initialized:
            return

        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(
                self.model_name,
                device=self.device,
                trust_remote_code=True,
            )
            # 验证实际输出维度
            test_vec = self.model.encode(["test"], normalize_embeddings=False)
            actual_dim = test_vec.shape[1]
            if actual_dim != self._dimension:
                print(
                    f"Warning: Model {self.model_name} output dim={actual_dim}, "
                    f"expected {self._dimension}. Using actual dim."
                )
                self._dimension = actual_dim
            self._initialized = True
        except ImportError:
            self._init_error = "sentence_transformers not installed"
            self._initialized = True
        except Exception as e:
            self._init_error = str(e)
            self._initialized = True

    def encode(
        self,
        texts: Union[str, List[str]],
        batch_size: int = 64,
        show_progress: bool = False,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> np.ndarray:
        """将文本编码为向量

        Args:
            texts: 单个字符串或字符串列表
            batch_size: 批量编码大小 — 百万级数据建议 32-128
            show_progress: 是否显示 tqdm 进度条
            progress_callback: 自定义进度回调，签名为 (current, total)

        Returns:
            np.ndarray: shape (n_texts, dimension) 的 float32 向量数组
        """
        self._lazy_init()

        if isinstance(texts, str):
            texts = [texts]

        if not texts:
            return np.array([], dtype=np.float32).reshape(0, self._dimension)

        if self.model:
            # 真实模型编码
            if show_progress:
                try:
                    from tqdm import tqdm
                    embeddings = self.model.encode(
                        texts,
                        batch_size=batch_size,
                        normalize_embeddings=self.normalize,
                        show_progress_bar=True,
                        convert_to_numpy=True,
                    )
                except ImportError:
                    embeddings = self.model.encode(
                        texts,
                        batch_size=batch_size,
                        normalize_embeddings=self.normalize,
                        show_progress_bar=False,
                        convert_to_numpy=True,
                    )
            else:
                embeddings = self.model.encode(
                    texts,
                    batch_size=batch_size,
                    normalize_embeddings=self.normalize,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                )

            # 进度回调
            if progress_callback and len(texts) > batch_size:
                total_batches = (len(texts) + batch_size - 1) // batch_size
                for i in range(total_batches):
                    progress_callback(
                        min((i + 1) * batch_size, len(texts)),
                        len(texts),
                    )

            return np.array(embeddings, dtype=np.float32)
        else:
            # Mock 降级 — 返回归一化的随机向量
            n = len(texts)
            vecs = np.random.randn(n, self._dimension).astype(np.float32)
            if self.normalize:
                norms = np.linalg.norm(vecs, axis=1, keepdims=True)
                vecs = vecs / (norms + 1e-8)
            return vecs

    def encode_single(self, text: str) -> np.ndarray:
        """编码单个文本 — 便捷方法"""
        return self.encode([text])[0]

    def get_info(self) -> dict:
        """获取编码器状态信息"""
        self._lazy_init()
        return {
            "model_name": self.model_name,
            "device": self.device,
            "dimension": self._dimension,
            "normalize": self.normalize,
            "available": self.model is not None,
            "init_error": self._init_error,
        }


# ============================================================================
# 全局单例 & 便捷函数
# ============================================================================

_encoder: Optional[BGEEncoder] = None


def get_encoder(
    model_name: str = "BAAI/bge-m3",
    device: Optional[str] = None,
    dimension: Optional[int] = None,
) -> BGEEncoder:
    """获取/创建全局编码器单例

    Args:
        model_name: 模型名称
        device: 设备
        dimension: 向量维度

    Returns:
        BGEEncoder 实例
    """
    global _encoder
    if _encoder is None:
        _encoder = BGEEncoder(
            model_name=model_name,
            device=device,
            dimension=dimension,
        )
    return _encoder


def reset_encoder():
    """重置编码器单例（切换模型时使用）"""
    global _encoder
    _encoder = None


def encode_text(
    texts: Union[str, List[str]],
    batch_size: int = 64,
    show_progress: bool = False,
) -> np.ndarray:
    """便捷函数：编码文本为向量

    Args:
        texts: 文本或文本列表
        batch_size: 批量大小
        show_progress: 是否显示进度条

    Returns:
        np.ndarray: 向量数组
    """
    return get_encoder().encode(
        texts,
        batch_size=batch_size,
        show_progress=show_progress,
    )


def encode_texts_batch(
    texts: List[str],
    batch_size: int = 64,
    callback: Optional[Callable[[int, int], None]] = None,
) -> np.ndarray:
    """批量编码 — 带进度回调的版本，适合百万级数据

    Args:
        texts: 文本列表
        batch_size: 批量大小 (建议 32-128)
        callback: 进度回调 (current, total)

    Returns:
        np.ndarray: 向量数组
    """
    return get_encoder().encode(
        texts,
        batch_size=batch_size,
        progress_callback=callback,
    )


__all__ = [
    "BaseEncoder",
    "BGEEncoder",
    "get_encoder",
    "reset_encoder",
    "encode_text",
    "encode_texts_batch",
    "BGE_M3_DIM",
    "MODEL_DIMENSIONS",
]
