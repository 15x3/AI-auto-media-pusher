import json

import httpx
import pytest

from worker.config import EmbeddingConfig, LLMConfig
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


def test_chat_retries_on_5xx_then_succeeds():
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


def test_chat_gives_up_after_max_retries():
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
