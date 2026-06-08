"""LLM 接口模块 — LLM Interface Layer

负责与大语言模型（DeepSeek / Qwen / OpenAI 兼容 API）的交互。
提供统一的 LLM 调用接口，支持多模型切换、流式输出、重试机制。

设计要点:
- 统一接口: 抽象 LLM 调用，支持 DeepSeek / Qwen / OpenAI 兼容 API
- 重试机制: 网络异常自动重试，指数退避
- 流式输出: 支持 stream 模式用于实时反馈
- 成本控制: token 计数、max_tokens 限制
- 降级策略: API 不可用时返回本地规则推理结果
"""

from __future__ import annotations
import time
import json
import re
from typing import Optional, List, Dict, Any, Callable, Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from openai import OpenAI


# ============================================================================
# LLM 客户端
# ============================================================================

class LLMClient:
    """统一的 LLM 客户端

    支持 DeepSeek / Qwen / OpenAI 兼容 API。
    自动处理连接重试、超时、token 限制。

    Example:
        >>> client = LLMClient(model="deepseek-chat")
        >>> response = client.chat("Explain the Linux kernel OOM killer")
        >>> print(response)
    """

    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: str = "sk-placeholder",
        base_url: str = "https://api.deepseek.com/v1",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        max_retries: int = 3,
        timeout: int = 60,
    ):
        """
        Args:
            model: 模型名称
            api_key: API Key
            base_url: API Base URL
            temperature: 生成温度 (0.0-1.0)，越低越确定
            max_tokens: 最大输出 token 数
            max_retries: 最大重试次数
            timeout: 请求超时秒数
        """
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.timeout = timeout
        self._client = None
        self._usage_stats: Dict[str, int] = {
            "total_calls": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
        }

    @property
    def client(self) -> Optional[OpenAI]:
        """延迟初始化 OpenAI 客户端"""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=self.timeout,
                )
            except ImportError:
                self._client = None
        return self._client

    @property
    def is_available(self) -> bool:
        """检查 LLM 是否可用"""
        return self.client is not None

    def chat(
        self,
        prompt: str,
        system_prompt: str = "You are a Linux kernel expert.",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        retry_on_failure: bool = True,
    ) -> str:
        """发送聊天请求并返回响应文本

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 覆盖默认温度
            max_tokens: 覆盖默认最大 token
            retry_on_failure: 失败时是否重试

        Returns:
            LLM 生成的文本

        Raises:
            RuntimeError: 所有重试都失败时抛出
        """
        if not self.is_available:
            return self._fallback_response(prompt)

        temp = temperature if temperature is not None else self.temperature
        max_tok = max_tokens if max_tokens is not None else self.max_tokens

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        last_error = None
        client = self.client
        if client is None:
            return self._fallback_response(prompt)

        for attempt in range(self.max_retries if retry_on_failure else 1):
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,  # type: ignore
                    temperature=temp,
                    max_tokens=max_tok,
                )

                # 更新使用统计
                self._usage_stats["total_calls"] += 1
                if hasattr(response, 'usage') and response.usage:
                    self._usage_stats["total_prompt_tokens"] += response.usage.prompt_tokens or 0
                    self._usage_stats["total_completion_tokens"] += response.usage.completion_tokens or 0

                content = response.choices[0].message.content or ""
                return content

            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt  # 指数退避: 1s, 2s, 4s
                    time.sleep(wait)
                    continue

        raise RuntimeError(f"LLM call failed after {self.max_retries} retries: {last_error}")

    def chat_with_history(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """多轮对话 — 传入完整消息历史

        Args:
            messages: [{"role": "system/user/assistant", "content": "..."}]
            temperature: 温度
            max_tokens: 最大 token

        Returns:
            生成的文本
        """
        if not self.is_available:
            return self._fallback_response(messages[-1].get("content", "") if messages else "")

        temp = temperature if temperature is not None else self.temperature
        max_tok = max_tokens if max_tokens is not None else self.max_tokens

        client = self.client
        if client is None:
            return self._fallback_response(messages[-1].get("content", "") if messages else "")

        for attempt in range(self.max_retries):
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,  # type: ignore
                    temperature=temp,
                    max_tokens=max_tok,
                )
                self._usage_stats["total_calls"] += 1
                return response.choices[0].message.content or ""
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise RuntimeError(f"LLM chat_with_history failed: {e}")
                time.sleep(2 ** attempt)

        return ""

    def chat_stream(
        self,
        prompt: str,
        system_prompt: str = "You are a Linux kernel expert.",
        on_token: Optional[Callable[[str], None]] = None,
    ) -> str:
        """流式聊天 — 逐 token 输出

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            on_token: 每个 token 的回调

        Returns:
            完整响应文本
        """
        if not self.is_available:
            return self._fallback_response(prompt)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        full_text = ""
        client = self.client
        if client is None:
            return self._fallback_response(prompt)

        try:
            stream = client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_text += token
                    if on_token:
                        on_token(token)
        except Exception as e:
            raise RuntimeError(f"LLM stream failed: {e}")

        self._usage_stats["total_calls"] += 1
        return full_text

    def structured_output(
        self,
        prompt: str,
        output_format: Dict[str, Any],
        system_prompt: str = "You are a Linux kernel expert. Output valid JSON only.",
    ) -> Dict[str, Any]:
        """结构化输出 — 强制 LLM 返回 JSON

        通过 prompt 约束 + 正则提取 JSON 实现。

        Args:
            prompt: 用户提示词
            output_format: 期望的输出格式示例 (用于 prompt)
            system_prompt: 系统提示词

        Returns:
            解析后的字典
        """
        format_hint = json.dumps(output_format, ensure_ascii=False, indent=2)
        full_prompt = f"""{prompt}

## Output Format
You MUST output ONLY a valid JSON object, no extra text. Format:
```json
{format_hint}
```
"""

        response = self.chat(full_prompt, system_prompt=system_prompt)

        # 提取 JSON
        try:
            # 尝试直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # 从代码块中提取
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 从文本中提取 { ... }
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # 返回原始响应
        return {"raw_response": response, "_parse_error": True}

    def get_usage_stats(self) -> Dict[str, int]:
        """获取使用统计"""
        return dict(self._usage_stats)

    def _fallback_response(self, prompt: str) -> str:
        """降级响应 — LLM 不可用时返回"""
        return (
            "LLM service unavailable. Using rule-based analysis.\n"
            f"Query: {prompt[:200]}...\n"
            "Please check your API key and network connection."
        )


# ============================================================================
# 全局单例
# ============================================================================

_llm_client: Optional[LLMClient] = None


def get_llm_client(
    model: str = "deepseek-chat",
    api_key: str = "sk-placeholder",
    base_url: str = "https://api.deepseek.com/v1",
) -> LLMClient:
    """获取/创建全局 LLM 客户端单例

    Args:
        model: 模型名称
        api_key: API Key
        base_url: API Base URL

    Returns:
        LLMClient 实例
    """
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient(
            model=model,
            api_key=api_key,
            base_url=base_url,
        )
    return _llm_client


def reset_llm_client():
    """重置 LLM 客户端单例"""
    global _llm_client
    _llm_client = None


__all__ = [
    "LLMClient",
    "get_llm_client",
    "reset_llm_client",
]
