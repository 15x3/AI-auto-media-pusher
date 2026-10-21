"""OpenAI 兼容 API 客户端：chat / embeddings。transport 可注入供测试。"""
import time

import httpx

from ..config import EmbeddingConfig, LLMConfig

MAX_RETRIES = 2


def _post_with_retry(client: httpx.Client, url: str, payload: dict, what: str) -> dict:
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.post(url, json=payload)
            if resp.status_code < 500:
                resp.raise_for_status()
                return resp.json()
            last_exc = RuntimeError(f"{what} 服务端错误 {resp.status_code}")
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"{what} 请求失败 {exc.response.status_code}: {exc.response.text[:200]}") from exc
        except httpx.HTTPError as exc:
            last_exc = exc
        if attempt < MAX_RETRIES:
            time.sleep(0.5 * (2**attempt))
    raise RuntimeError(f"{what} 重试 {MAX_RETRIES} 次后仍失败: {last_exc}")


class OpenAIChatClient:
    """满足 LLMClient 协议：complete(system, user) -> str。"""

    def __init__(self, cfg: LLMConfig, transport: httpx.BaseTransport | None = None) -> None:
        self._cfg = cfg
        self._client = httpx.Client(
            base_url=cfg.base_url,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=120,
            transport=transport,
        )

    def complete(self, system: str, user: str) -> str:
        data = _post_with_retry(
            self._client,
            "/chat/completions",
            {
                "model": self._cfg.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            "chat/completions",
        )
        return data["choices"][0]["message"]["content"]


class OpenAIEmbedder:
    """满足 Embedder 协议：embed(texts) -> list[list[float]]。"""

    def __init__(self, cfg: EmbeddingConfig, transport: httpx.BaseTransport | None = None) -> None:
        self._cfg = cfg
        self._client = httpx.Client(
            base_url=cfg.base_url,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=60,
            transport=transport,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        data = _post_with_retry(
            self._client,
            "/embeddings",
            {"model": self._cfg.model, "input": texts},
            "embeddings",
        )
        by_index = {item["index"]: item["embedding"] for item in data["data"]}
        return [by_index[i] for i in range(len(texts))]
