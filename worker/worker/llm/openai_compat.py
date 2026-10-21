"""OpenAI 兼容 API 客户端：chat / embeddings / images。transport 可注入供测试。"""
import time
from pathlib import Path

import httpx

from ..config import EmbeddingConfig, ImageConfig, LLMConfig

MAX_RETRIES = 2


def _post_with_retry(client: httpx.Client, url: str, payload: dict, what: str) -> dict:
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.post(url, json=payload)
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                last_exc = RuntimeError(f"{what} 服务端错误 {resp.status_code}")
                if attempt < MAX_RETRIES:
                    if retry_after is not None and str(retry_after).isdigit():
                        time.sleep(float(retry_after))
                    else:
                        time.sleep(0.5 * (2**attempt))
                continue
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError as exc:  # 200 但非 JSON（网关错误页等）
                raise RuntimeError(f"{what} 响应非 JSON: {resp.text[:200]}") from exc
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
            timeout=httpx.Timeout(120, connect=10),
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
            timeout=httpx.Timeout(60, connect=10),
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


class OpenAIImageClient:
    """文生图：generate(prompt, out_path) -> Path（b64 响应落盘为 PNG）。"""

    def __init__(self, cfg: ImageConfig, transport: httpx.BaseTransport | None = None) -> None:
        self._cfg = cfg
        self._client = httpx.Client(
            base_url=cfg.base_url,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=httpx.Timeout(180, connect=10),
            transport=transport,
        )

    def generate(self, prompt: str, out_path: Path) -> Path:
        import base64 as _b64

        data = _post_with_retry(
            self._client,
            "/images/generations",
            {"model": self._cfg.model, "prompt": prompt, "size": "768x1024", "response_format": "b64_json"},
            "images/generations",
        )
        raw = _b64.b64decode(data["data"][0]["b64_json"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
        return out_path
