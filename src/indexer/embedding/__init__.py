"""向量编码模块

负责使用 BGE-M3 等模型将文本转换为高维向量。
"""

import numpy as np
from typing import List, Union


class BaseEncoder:
    """编码器基类"""
    def encode(self, texts: Union[str, List[str]]) -> np.ndarray:
        raise NotImplementedError


class BGEEncoder(BaseEncoder):
    """基于 BGE-M3 的编码器实现"""
    
    def __init__(self, model_name: str = "BAAI/bge-m3", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self._initialized = False

    def _lazy_init(self):
        """延迟初始化模型，减少启动开销"""
        if not self._initialized:
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(self.model_name, device=self.device)
                self._initialized = True
            except ImportError:
                print(f"Warning: sentence_transformers not installed. Using mock encoder.")
                self.model = None
                self._initialized = True

    def encode(self, texts: Union[str, List[str]]) -> np.ndarray:
        self._lazy_init()
        
        if isinstance(texts, str):
            texts = [texts]
            
        if self.model:
            # 实际使用 BGE 模型进行编码
            embeddings = self.model.encode(texts, normalize_embeddings=True)
            return np.array(embeddings)
        else:
            # Mock 实现：返回随机向量 (1024维，BGE-M3 标准维度)
            return np.random.rand(len(texts), 1024).astype(np.float32)


# 全局单例编码器
_encoder = BGEEncoder()

def get_encoder() -> BGEEncoder:
    return _encoder

def encode_text(texts: Union[str, List[str]]) -> np.ndarray:
    """便捷函数：编码文本"""
    return _encoder.encode(texts)
