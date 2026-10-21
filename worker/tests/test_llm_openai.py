import base64
import json

import httpx
import pytest

from worker.config import EmbeddingConfig, LLMConfig
from worker.llm import openai_compat
from worker.llm.openai_compat import OpenAIChatClient, OpenAIEmbedder


def test_chat_complete_posts_and_parses():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "正文内容"}}]
        })

    cfg = LLMConfig("https://api.example.com/v1", "sk-test", "glm-4.6")
    client = OpenAIChatClient(cfg, transport=httpx.MockTransport(handler))
    out = client.complete("你是写手", "写一篇")
    assert out == "正文内容"
    assert seen["url"].endswith("/chat/completions")
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["model"] == "glm-4.6"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "你是写手"}


def test_chat_retries_on_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr(openai_compat.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = OpenAIChatClient(LLMConfig("https://api.example.com/v1", "k", "m"),
                              transport=httpx.MockTransport(handler))
    assert client.complete("s", "u") == "ok"
    assert calls["n"] == 2


def test_chat_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(openai_compat.time, "sleep", lambda s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = OpenAIChatClient(LLMConfig("https://api.example.com/v1", "k", "m"),
                              transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="chat/completions"):
        client.complete("s", "u")


def test_embedder_returns_vectors():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["input"] == ["文本一", "文本二"]
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [0.2, 0.4]},
            {"index": 0, "embedding": [0.1, 0.3]},
        ]})

    cfg = EmbeddingConfig("https://api.example.com/v1", "k", "embedding-3", 2)
    client = OpenAIEmbedder(cfg, transport=httpx.MockTransport(handler))
    vecs = client.embed(["文本一", "文本二"])
    assert vecs == [[0.1, 0.3], [0.2, 0.4]]   # 按 index 排序还原


def test_image_client_writes_png(tmp_path):
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["prompt"].startswith("封面图：")
        assert body["size"] == "768x1024"   # 3:4 竖版封面
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png_bytes).decode()}]})

    from worker.config import ImageConfig
    from worker.llm.openai_compat import OpenAIImageClient

    client = OpenAIImageClient(ImageConfig("https://api.example.com/v1", "k", "cogview-4"),
                               transport=httpx.MockTransport(handler))
    out = tmp_path / "imgs" / "d1" / "cover.png"
    result = client.generate(prompt="封面图：AI Agent 一周动态", out_path=out)
    assert result == out and out.exists() and out.read_bytes() == png_bytes


def test_retry_429_respects_retry_after(monkeypatch):
    """决策 #17：429 参与重试并尊重 Retry-After 头。"""
    import worker.llm.openai_compat as mod

    sleeps = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = mod.OpenAIChatClient(LLMConfig("https://api.example.com/v1", "k", "m"),
                                  transport=httpx.MockTransport(handler))
    assert client.complete("s", "u") == "ok"
    assert calls["n"] == 2
    assert sleeps == [3.0]      # 用了 Retry-After 而非指数退避


def test_non_json_200_wrapped_as_runtime_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway error</html>")

    client = OpenAIChatClient(LLMConfig("https://api.example.com/v1", "k", "m"),
                              transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="chat/completions"):
        client.complete("s", "u")


def test_connect_timeout_configured():
    """决策 #17：timeout 元组化，connect=10。注入 MockTransport 避免真实 SSL 初始化开销。"""
    from worker.config import ImageConfig
    from worker.llm.openai_compat import OpenAIChatClient, OpenAIEmbedder, OpenAIImageClient
    idle = httpx.MockTransport(lambda request: httpx.Response(200))
    for cls, cfg in [
        (OpenAIChatClient, LLMConfig("https://x", "k", "m")),
        (OpenAIEmbedder, EmbeddingConfig("https://x", "k", "m", 8)),
        (OpenAIImageClient, ImageConfig("https://x", "k", "m")),
    ]:
        client = cls(cfg, transport=idle)
        assert client._client.timeout.connect == 10
