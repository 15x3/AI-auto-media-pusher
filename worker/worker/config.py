"""本地配置加载：config.toml（gitignored）。未配置的段为 None，装配层据此回退桩实现。"""
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class EmbeddingConfig:
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class ImageConfig:
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class AppConfig:
    llm: LLMConfig | None = None
    embedding: EmbeddingConfig | None = None
    image: ImageConfig | None = None
    headless: bool = False
    profiles_root: Path = Path("data/profiles")
    images_root: Path = Path("data/images")


def load_config(path: str | Path = "config.toml") -> AppConfig:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"配置文件不存在: {p}（复制 config.example.toml 为 config.toml 并填入 key）")
    raw = tomllib.loads(p.read_text(encoding="utf-8"))
    llm = raw.get("llm")
    emb = raw.get("embedding")
    img = raw.get("image")
    browser = raw.get("browser", {})
    return AppConfig(
        llm=LLMConfig(llm["base_url"], llm["api_key"], llm["model"]) if llm else None,
        embedding=EmbeddingConfig(emb["base_url"], emb["api_key"], emb["model"]) if emb else None,
        image=ImageConfig(img["base_url"], img["api_key"], img["model"]) if img else None,
        headless=bool(browser.get("headless", False)),
    )
