"""LLM / Embedding 客户端协议与离线桩实现。真实 API 客户端在计划 2 接入。"""
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class StubLLM:
    """确定性桩：返回可预测的演示成文。"""

    def complete(self, system: str, user: str) -> str:
        return f"《{user[:24]}》——这是 StubLLM 生成的演示正文。"


class StubEmbedder:
    """确定性桶哈希向量：相同文本→相同向量，测试可复现。"""

    def __init__(self, dims: int = 8) -> None:
        self.dims = dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dims
            for byte in text.encode("utf-8"):
                vec[byte % self.dims] += 1.0
            norm = sum(vec) or 1.0
            out.append([v / norm for v in vec])
        return out
