from pathlib import Path

import pytest

from worker.config import AppConfig, EmbeddingConfig, ImageConfig, LLMConfig, load_config


def _write_cfg(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_full_config(tmp_path):
    p = _write_cfg(tmp_path, """
[llm]
base_url = "https://api.example.com/v1"
api_key = "sk-test"
model = "glm-4.6"

[embedding]
base_url = "https://api.example.com/v1"
api_key = "sk-test"
model = "embedding-3"
dims = 2048

[image]
base_url = "https://api.example.com/v1"
api_key = "sk-test"
model = "cogview-4"

[browser]
headless = false
""")
    cfg = load_config(p)
    assert cfg == AppConfig(
        llm=LLMConfig("https://api.example.com/v1", "sk-test", "glm-4.6"),
        embedding=EmbeddingConfig("https://api.example.com/v1", "sk-test", "embedding-3", 2048),
        image=ImageConfig("https://api.example.com/v1", "sk-test", "cogview-4"),
        headless=False,
    )


def test_defaults_and_missing_file(tmp_path):
    p = _write_cfg(tmp_path, """
[llm]
base_url = "https://api.example.com/v1"
api_key = "sk-test"
model = "m"
""")
    cfg = load_config(p)
    assert cfg.embedding is None      # 未配置段为 None → 装配层回退桩
    assert cfg.image is None
    assert cfg.headless is False      # 默认有头（扫码登录需要可见浏览器）

    with pytest.raises(FileNotFoundError, match="config.toml"):
        load_config(tmp_path / "nope.toml")
