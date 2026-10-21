# 计划 2：真实集成 — 平台适配器与 AI 客户端 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用真实能力替换计划 1 的全部桩：小红书 / B站专栏的 Playwright 真实适配器（会话保持 + 错误分类 + 扫码登录），OpenAI 兼容的 LLM / Embedding / 文生图客户端，配置层与 CLI 真实装配。

**Architecture:** 配置层（config.toml，本地 gitignored）驱动客户端装配——有配置走真实 API，无配置回退桩（demo 离线工作流保持可用）。浏览器适配器共享 `PlaywrightBase` 基类（持久化用户数据目录保会话，不声明 platform_id）；选择器以**测试 fixture 页为契约**（本地 HTML + Playwright 路由拦截），真实页面选择器漂移由 `PublishError.SELECTOR_BROKEN` 分类捕获后校准。

**Tech Stack:** Python 3.12 · uv · pytest · Playwright（sync API，Chromium）· httpx · tomllib（标准库）

**依据规格:** [技术文档](../specs/2026-10-20-ai-social-media-agent-tool-tech.md) §2/§4 + [计划 1 决策清单 #1–#15](2026-10-20-plan1-python-worker-foundation.md)

**计划 1 基线:** master `c8ce011`（37 测试全绿；`Pipeline`/`AdapterRegistry`/`GlobalMemory` 等 API 以实现为准）

---

## 文件结构（本计划创建/修改）

```
worker/
├─ pyproject.toml                    # 修改：+httpx +playwright
├─ config.example.toml               # 新：配置模板（提交）
├─ .gitignore(根)                    # 修改：+config.toml +data/
├─ worker/
│  ├─ config.py                      # 新：配置加载（tomllib）
│  ├─ llm/
│  │  └─ openai_compat.py            # 新：OpenAIChatClient / OpenAIEmbedder / OpenAIImageClient
│  ├─ adapters/
│  │  ├─ base.py                     # 修改：load_adapters 加固（builder 钩子 + per-module 容错）
│  │  ├─ browser.py                  # 新：PlaywrightBase（会话/路由钩子/login）
│  │  ├─ xiaohongshu.py              # 新
│  │  └─ bilibili_column.py          # 新
│  ├─ pipeline.py                    # 修改：image_client 注入 + 决策 #7/#10/#12/#13
│  └─ cli.py                         # 修改：--config / login / 真实装配
└─ tests/
   ├─ test_config.py
   ├─ test_llm_openai.py             # httpx.MockTransport
   ├─ test_load_adapters_hardened.py
   ├─ test_browser_base.py
   ├─ test_xiaohongshu.py            # fixture 契约
   ├─ test_bilibili_column.py
   ├─ test_pipeline_v2.py
   ├─ test_cli_v2.py
   └─ fixtures/
      ├─ xhs_home_logged_in.html
      ├─ xhs_home_logged_out.html
      ├─ xhs_trends.html
      ├─ xhs_publish.html
      ├─ xhs_publish_success.html
      ├─ bili_home_logged_in.html
      ├─ bili_home_logged_out.html
      ├─ bili_trends.html
      ├─ bili_publish.html
      └─ bili_publish_success.html
```

---

### Task 1: 配置层

**Files:**
- Create: `worker/worker/config.py`
- Create: `worker/config.example.toml`
- Modify: 根 `.gitignore`（追加 `config.toml` 与 `data/`）
- Test: `worker/tests/test_config.py`
- Modify: `worker/pyproject.toml`（dependencies 追加 `"httpx>=0.27"`——本任务即用）

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_config.py -v`
Expected: FAIL（`No module named 'worker.config'`）

- [ ] **Step 3: 实现 config.py 与模板**

`worker/worker/config.py`：

```python
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
    dims: int


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
        embedding=EmbeddingConfig(emb["base_url"], emb["api_key"], emb["model"], int(emb.get("dims", 1024))) if emb else None,
        image=ImageConfig(img["base_url"], img["api_key"], img["model"]) if img else None,
        headless=bool(browser.get("headless", False)),
    )
```

`worker/config.example.toml`：

```toml
# 复制为 worker/config.toml 并填入真实 key（config.toml 已被 gitignore）
# 所有端点均为 OpenAI 兼容协议：智谱 / DeepSeek / OpenAI / 本地网关均可

[llm]
base_url = "https://open.bigmodel.cn/api/paas/v4"
api_key = "你的KEY"
model = "glm-4.6"

[embedding]
base_url = "https://open.bigmodel.cn/api/paas/v4"
api_key = "你的KEY"
model = "embedding-3"
dims = 2048

[image]
base_url = "https://open.bigmodel.cn/api/paas/v4"
api_key = "你的KEY"
model = "cogview-4"

[browser]
headless = false   # 扫码登录期间保持 false；日常发布可改 true
```

`pyproject.toml` 的 dependencies 改为：

```toml
dependencies = ["websockets>=13", "sqlite-vec>=0.1.6", "httpx>=0.27"]
```

根 `.gitignore` 追加两行：

```
config.toml
data/
```

- [ ] **Step 4: 运行确认通过**

Run: `cd worker && uv sync && uv run pytest tests/test_config.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add worker/worker/config.py worker/config.example.toml worker/tests/test_config.py worker/pyproject.toml worker/uv.lock .gitignore
git commit -m "feat(worker): 配置层——config.toml 加载与模板"
```

---

### Task 2: load_adapters 加固（builder 钩子 + per-module 容错）

**Files:**
- Modify: `worker/worker/adapters/base.py`（`load_adapters`）
- Test: `worker/tests/test_load_adapters_hardened.py`

决策依据：#3（配置注入缝）、#4（playwright 未装不应瘫痪 demo）、#2（共享基类不声明 platform_id——已由计划 1 落地，本任务的容错使其 import 失败时可跳过）。

- [ ] **Step 1: 写失败测试**

```python
"""builder 钩子与 per-module 容错。合成包方案沿袭计划 1 的 tests/synth_adapters 模式。"""
import sys
from pathlib import Path

from worker.adapters.base import AdapterRegistry, load_adapters

SYNTH = Path(__file__).parent / "synth_v2"


def _make_pkg(name: str, mod_name: str, body: str) -> None:
    pkg = SYNTH / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / f"{mod_name}.py").write_text(body, encoding="utf-8")


def test_builder_hook_injects_dependencies(tmp_path):
    _make_pkg("builder_case", "frozen", '''\
from worker.adapters.base import HealthReport, HealthStatus, PlatformAdapter, PlatformPost, PublishResult, Trend


class FrozenAdapter(PlatformAdapter):
    platform_id = "frozen"
    display_name = "注入适配器"

    def __init__(self, deps=None):
        self.deps = deps

    def check_health(self):
        return HealthReport(HealthStatus.OK)

    def fetch_trends(self):
        return [Trend("t", 1.0)]

    def compose_post(self, title, body, images):
        return PlatformPost(title=title, body=body)

    def execute_publish(self, post):
        return PublishResult(success=True)
''')
    sys.path.insert(0, str(SYNTH))
    try:
        registry = load_adapters("builder_case", builder=lambda cls: cls(deps={"pw": True}))
        assert registry.get("frozen").deps == {"pw": True}
    finally:
        sys.path.remove(str(SYNTH))


def test_broken_module_skipped_with_warning_not_fatal(capsys):
    _make_pkg("tolerant_case", "needs_playwright", "import playwright nonexistent_module_xyz  # noqa\n")
    _make_pkg("tolerant_case", "fine", '''\
from worker.adapters.base import HealthReport, HealthStatus, PlatformAdapter, PlatformPost, PublishResult, Trend


class FineAdapter(PlatformAdapter):
    platform_id = "fine"
    display_name = "正常适配器"

    def check_health(self):
        return HealthReport(HealthStatus.OK)

    def fetch_trends(self):
        return []

    def compose_post(self, title, body, images):
        return PlatformPost(title=title, body=body)

    def execute_publish(self, post):
        return PublishResult(success=True)
''')
    sys.path.insert(0, str(SYNTH))
    try:
        registry = load_adapters("tolerant_case")
        assert set(registry.all()) == {"fine"}   # 坏模块被跳过，好模块照常注册
        err = capsys.readouterr().err
        assert "needs_playwright" in err and "跳过" in err
    finally:
        sys.path.remove(str(SYNTH))
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_load_adapters_hardened.py -v`
Expected: FAIL（`load_adapters() got an unexpected keyword argument 'builder'`；第二个测试因 import 炸掉而非警告）

- [ ] **Step 3: 实现——替换 base.py 的 load_adapters**

```python
def load_adapters(
    package: str = "worker.adapters",
    builder: "Callable[[type[PlatformAdapter]], PlatformAdapter] | None" = None,
) -> "AdapterRegistry":
    """扫描适配器包目录，放即注册：凡继承 PlatformAdapter 且声明 platform_id 的具体类自动进入注册表。

    builder 可注入构造依赖（配置/浏览器参数）；单个模块 import 或构造失败时打印警告并跳过，
    不拖垮其余适配器（如未安装 playwright 时 demo 仍可用）。
    """
    registry = AdapterRegistry()
    pkg = importlib.import_module(package)
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        if mod_info.name == "base":
            continue
        try:
            module = importlib.import_module(f"{package}.{mod_info.name}")
            candidates = [
                obj
                for obj in vars(module).values()
                if (
                    isinstance(obj, type)
                    and issubclass(obj, PlatformAdapter)
                    and obj is not PlatformAdapter
                    and obj.__module__ == f"{package}.{mod_info.name}"
                    and not getattr(obj, "__abstractmethods__", None)
                    and getattr(obj, "platform_id", "")
                )
            ]
            for cls in candidates:
                registry.register(cls() if builder is None else builder(cls))
        except Exception as exc:  # noqa: BLE001 - 单模块失败不拖垮扫描
            print(f"[adapters] 模块 {package}.{mod_info.name} 加载失败，已跳过: {exc}", file=sys.stderr)
    return registry
```

（同时把 `import sys` 加入 base.py 顶部导入；`Callable` 从 `collections.abc` 导入并加入 TYPE_CHECKING 可省——直接运行时导入 `from collections.abc import Callable`。）

- [ ] **Step 4: 运行确认通过（含计划 1 全量回归）**

Run: `cd worker && uv run pytest -v`
Expected: 全绿（37 + 2 新增 = 39 passed；计划 1 的 registry 测试不受影响——默认 builder=None 路径行为不变）

- [ ] **Step 5: Commit**

```bash
git add worker/worker/adapters/base.py worker/tests/test_load_adapters_hardened.py worker/tests/synth_v2/ worker/uv.lock
git commit -m "feat(worker): load_adapters 支持 builder 注入与单模块容错"
```

---

### Task 3: OpenAI 兼容 Chat / Embedding 客户端

**Files:**
- Create: `worker/worker/llm/openai_compat.py`
- Test: `worker/tests/test_llm_openai.py`

- [ ] **Step 1: 写失败测试**

```python
import json

import httpx
import pytest

from worker.config import EmbeddingConfig, LLMConfig
from worker.llm.openai_compat import OpenAIChatClient, OpenAIEmbedder


def _mock_client(handler, cfg) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_llm_openai.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 openai_compat.py（Chat + Embedding 部分）**

```python
"""OpenAI 兼容 API 客户端：chat / embeddings / images。transport 可注入供测试。"""
import time

import httpx

from ..config import EmbeddingConfig, ImageConfig, LLMConfig

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
```

- [ ] **Step 4: 运行确认通过**

Run: `cd worker && uv run pytest tests/test_llm_openai.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add worker/worker/llm/openai_compat.py worker/tests/test_llm_openai.py
git commit -m "feat(worker): OpenAI 兼容 chat/embedding 客户端（重试与可注入 transport）"
```

---

### Task 4: OpenAI 兼容文生图客户端

**Files:**
- Modify: `worker/worker/llm/openai_compat.py`（追加 `OpenAIImageClient`）
- Test: `worker/tests/test_llm_openai.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
import base64


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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_llm_openai.py::test_image_client_writes_png -v`
Expected: FAIL（`OpenAIImageClient` 不存在）

- [ ] **Step 3: 实现（openai_compat.py 追加）**

```python
class OpenAIImageClient:
    """文生图：generate(prompt, out_path) -> Path（b64 响应落盘为 PNG）。"""

    def __init__(self, cfg: ImageConfig, transport: httpx.BaseTransport | None = None) -> None:
        self._cfg = cfg
        self._client = httpx.Client(
            base_url=cfg.base_url,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=180,
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
```

（`from pathlib import Path` 加入文件顶部导入。）

- [ ] **Step 4: 运行确认通过**

Run: `cd worker && uv run pytest tests/test_llm_openai.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add worker/worker/llm/openai_compat.py worker/tests/test_llm_openai.py
git commit -m "feat(worker): OpenAI 兼容文生图客户端（3:4 封面落盘）"
```

---

### Task 5: Playwright 依赖与 PlaywrightBase

**Files:**
- Modify: `worker/pyproject.toml`（dependencies 追加 `"playwright>=1.48"`）
- Create: `worker/worker/adapters/browser.py`
- Test: `worker/tests/test_browser_base.py`

- [ ] **Step 1: 安装依赖与浏览器**

```bash
cd worker && uv add "playwright>=1.48" && uv run playwright install chromium
```

Expected: 依赖写入 pyproject + uv.lock，Chromium 下载完成（约 120MB，一次安装）。

- [ ] **Step 2: 写失败测试**

```python
from pathlib import Path

from worker.adapters.browser import PlaywrightBase

FIXTURES = Path(__file__).parent / "fixtures"


def _local_page_adapter(routes: dict[str, Path]):
    """构造只挂 fixture 路由的测试基类实例（不声明 platform_id，不经注册表）。"""

    class _Local(PlaywrightBase):
        platform_id = "local-test"   # 仅测试用；不会被自动扫描（不在 worker.adapters 包内）

        def check_health(self):
            raise NotImplementedError

        def fetch_trends(self):
            raise NotImplementedError

        def compose_post(self, title, body, images):
            raise NotImplementedError

        def execute_publish(self, post):
            raise NotImplementedError

    a = _Local(profiles_root=Path(__file__).parent / "tmp_profiles", headless=True)
    a.FIXTURE_ROUTES = routes
    return a


def test_fixture_route_serves_local_html(tmp_path):
    (tmp_path / "page.html").write_text("<h1 class='marker'>本地页面</h1>", encoding="utf-8")
    a = _local_page_adapter({"**://fake.local/**": tmp_path / "page.html"})
    try:
        with a.browser_page() as page:
            page.goto("https://fake.local/anything", wait_until="domcontentloaded")
            assert page.locator(".marker").inner_text() == "本地页面"
    finally:
        a.close()


def test_persistent_profile_reused_across_pages(tmp_path):
    cookie_value = "session-marker-42"
    a = _local_page_adapter({"**://fake.local/**": tmp_path / "page.html"})
    (tmp_path / "page.html").write_text("<h1>ok</h1>", encoding="utf-8")
    try:
        with a.browser_page() as page:
            page.goto("https://fake.local/", wait_until="domcontentloaded")
            page.context.add_cookies([{"name": "sid", "value": cookie_value, "url": "https://fake.local"}])
        with a.browser_page() as page:   # 新 page，同一持久化上下文
            cookies = {c["name"]: c["value"] for c in page.context.cookies("https://fake.local")}
            assert cookies["sid"] == cookie_value
    finally:
        a.close()
```

- [ ] **Step 3: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_browser_base.py -v`
Expected: FAIL（`worker.adapters.browser` 不存在）

- [ ] **Step 4: 实现 browser.py**

```python
"""Playwright 浏览器适配器公共基类：持久化用户数据目录（会话保持）、fixture 路由钩子、扫码登录。

不声明 platform_id —— 自动扫描只收终端适配器（计划 1 决策 #2）。
FIXTURE_ROUTES 为空时直连真实平台；测试注入 {url模式: 本地HTML} 后全链路离线可测。
选择器契约：终端适配器的选择器以 fixture 页为唯一测试契约，真实页面漂移由
PublishError.SELECTOR_BROKEN 分类捕获后校准（见各适配器 SELECTORS 常量注释）。
"""
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from .base import HealthReport, HealthStatus, PlatformAdapter

LOGIN_TIMEOUT_SECONDS = 180


class PlaywrightBase(PlatformAdapter):
    LOGIN_URL: str = ""
    FIXTURE_ROUTES: dict[str, Path] = {}

    def __init__(self, profiles_root: Path | None = None, headless: bool = False) -> None:
        self._profiles_root = Path(profiles_root) if profiles_root else Path("data/profiles")
        self._headless = headless
        self._pw = None
        self._context = None

    @property
    def _profile_dir(self) -> Path:
        return self._profiles_root / self.platform_id

    @contextmanager
    def browser_page(self):
        from playwright.sync_api import sync_playwright

        if self._context is None:
            self._pw = sync_playwright().start()
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self._profile_dir),
                headless=self._headless,
                viewport={"width": 1280, "height": 860},
            )
            for pattern, fixture in self.FIXTURE_ROUTES.items():
                self._context.route(
                    pattern,
                    lambda route, f=fixture: route.fulfill(
                        status=200, content_type="text/html; charset=utf-8",
                        body=Path(f).read_text(encoding="utf-8"),
                    ),
                )
        page = self._context.new_page()
        try:
            yield page
        finally:
            page.close()

    def login(self) -> HealthReport:
        """打开登录页，人工扫码/输入，轮询 check_health 直到 OK 或超时。"""
        with self.browser_page() as page:
            page.goto(self.LOGIN_URL, wait_until="domcontentloaded")
            deadline = time.time() + LOGIN_TIMEOUT_SECONDS
            while time.time() < deadline:
                if self.check_health().status is HealthStatus.OK:
                    return HealthReport(HealthStatus.OK, "登录成功")
                page.wait_for_timeout(3000)
        return HealthReport(HealthStatus.NEEDS_LOGIN, f"{LOGIN_TIMEOUT_SECONDS} 秒内未完成登录")

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None
```

（`import sys` 实际未用到则不加——保持导入干净；如 linter 无配置，仅导入 `time`/`contextmanager`/`Path` 与 base 的两个类型。）

- [ ] **Step 5: 运行确认通过（全量回归）**

Run: `cd worker && uv run pytest -v`
Expected: 全绿（44 passed 左右：39 + 2 新增 + Task 3/4 的 5 个已计入……以实际为准，报告数字）

- [ ] **Step 6: Commit**

```bash
git add worker/pyproject.toml worker/uv.lock worker/worker/adapters/browser.py worker/tests/test_browser_base.py
git commit -m "feat(worker): PlaywrightBase——持久会话/fixture 路由/扫码登录基座"
```

---

### Task 6: 小红书适配器 — check_health + fetch_trends

**Files:**
- Create: `worker/worker/adapters/xiaohongshu.py`
- Create: `worker/tests/fixtures/xhs_home_logged_in.html`、`xhs_home_logged_out.html`、`xhs_trends.html`
- Test: `worker/tests/test_xiaohongshu.py`

- [ ] **Step 1: 建 fixture 页（选择器契约的载体）**

`xhs_home_logged_in.html`：

```html
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>小红书创作平台</title></head>
<body>
  <div class="creator-container">
    <a class="publish_entry" href="/publish/publish">发布笔记</a>
    <span class="user_name">测试创作者</span>
  </div>
</body></html>
```

`xhs_home_logged_out.html`：

```html
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>登录小红书</title></head>
<body><div class="login_container"><div class="qrcode"></div></div></body></html>
```

`xhs_trends.html`：

```html
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>热点</title></head>
<body>
  <ul class="trend_list">
    <li class="trend_item"><span class="title">AI Agent 一周动态</span><span class="heat">9.1</span></li>
    <li class="trend_item"><span class="title">桌面端工具极客界面</span><span class="heat">8.4</span></li>
    <li class="trend_item"><span class="title">多平台内容分发</span><span class="heat">7.6</span></li>
  </ul>
</body></html>
```

- [ ] **Step 2: 写失败测试**

```python
from pathlib import Path

import pytest

from worker.adapters.base import HealthStatus
from worker.adapters.xiaohongshu import XiaohongshuAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def make_adapter(tmp_path, **routes: Path) -> XiaohongshuAdapter:
    a = XiaohongshuAdapter(profiles_root=tmp_path / "profiles", headless=True)
    a.FIXTURE_ROUTES = dict(routes)
    return a


def test_check_health_ok_when_logged_in(tmp_path):
    a = make_adapter(tmp_path, **{"**://creator.xiaohongshu.com/**": FIXTURES / "xhs_home_logged_in.html"})
    try:
        assert a.check_health().status is HealthStatus.OK
    finally:
        a.close()


def test_check_health_needs_login_when_login_marker_present(tmp_path):
    # 登录态判定双保险：URL 含 /login（真实重定向）或页面出现登录容器（fixture 契约）
    a = make_adapter(tmp_path, **{"**://creator.xiaohongshu.com/**": FIXTURES / "xhs_home_logged_out.html"})
    try:
        report = a.check_health()
        assert report.status is HealthStatus.NEEDS_LOGIN
    finally:
        a.close()


def test_fetch_trends_parses_titles_and_heat(tmp_path):
    a = make_adapter(tmp_path, **{"**://www.xiaohongshu.com/hot**": FIXTURES / "xhs_trends.html"})
    try:
        trends = a.fetch_trends()
        assert [t.title for t in trends] == ["AI Agent 一周动态", "桌面端工具极客界面", "多平台内容分发"]
        assert trends[0].heat == pytest.approx(9.1)
    finally:
        a.close()
```

- [ ] **Step 3: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_xiaohongshu.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现 xiaohongshu.py（健康与热榜部分）**

```python
"""小红书适配器。选择器契约见 tests/fixtures/xhs_*.html——真实页面漂移时先改 SELECTORS。"""
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .base import HealthReport, HealthStatus, Trend
from .browser import PlaywrightBase

HOME_URL = "https://creator.xiaohongshu.com"
TRENDS_URL = "https://www.xiaohongshu.com/hot"

# ---- 选择器（fixture 契约；真实页面校准点）----
SEL_LOGIN_MARKER = ".login_container"
SEL_LOGGED_IN_MARKER = ".publish_entry"
SEL_TREND_ITEM = ".trend_item"
SEL_TREND_TITLE = ".title"
SEL_TREND_HEAT = ".heat"


class XiaohongshuAdapter(PlaywrightBase):
    platform_id = "xiaohongshu"
    display_name = "小红书"
    LOGIN_URL = "https://creator.xiaohongshu.com/login"

    def check_health(self) -> HealthReport:
        with self.browser_page() as page:
            page.goto(HOME_URL, wait_until="domcontentloaded")
            # 登录态判定：URL 跳转（真实场景）或登录容器可见（fixture 契约）
            if "/login" in page.url or page.locator(SEL_LOGIN_MARKER).count() > 0:
                return HealthReport(HealthStatus.NEEDS_LOGIN, "处于未登录状态，需要扫码")
            try:
                page.locator(SEL_LOGGED_IN_MARKER).first.wait_for(timeout=5000)
                return HealthReport(HealthStatus.OK)
            except PlaywrightTimeoutError:
                return HealthReport(HealthStatus.BROKEN, "登录态页面结构不符（选择器待校准）")

    def fetch_trends(self) -> list[Trend]:
        with self.browser_page() as page:
            page.goto(TRENDS_URL, wait_until="domcontentloaded")
            items = page.locator(SEL_TREND_ITEM).all()
            trends = []
            for item in items:
                title = item.locator(SEL_TREND_TITLE).inner_text().strip()
                heat_text = item.locator(SEL_TREND_HEAT).inner_text().strip()
                try:
                    heat = float(heat_text)
                except ValueError:
                    heat = 0.0
                trends.append(Trend(title=title, heat=heat))
            return trends
```

（compose_post / execute_publish 在 Task 7 补齐——本文件先留两个 `raise NotImplementedError` 存根方法以满足注册表契约；或直接继承抽象基类不实现会阻止实例化——**采用显式存根**：)

```python
    def compose_post(self, title: str, body: str, images: list[str]):
        raise NotImplementedError("Task 7 实现")

    def execute_publish(self, post):
        raise NotImplementedError("Task 7 实现")
```

- [ ] **Step 5: 运行确认通过**

Run: `cd worker && uv run pytest tests/test_xiaohongshu.py -v`
Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add worker/worker/adapters/xiaohongshu.py worker/tests/test_xiaohongshu.py worker/tests/fixtures/xhs_*.html
git commit -m "feat(worker): 小红书适配器——登录态检查与热榜解析"
```

---

### Task 7: 小红书适配器 — compose_post + execute_publish（错误分类）

**Files:**
- Modify: `worker/worker/adapters/xiaohongshu.py`
- Create: `worker/tests/fixtures/xhs_publish.html`、`xhs_publish_success.html`
- Test: `worker/tests/test_xiaohongshu.py`（追加）

- [ ] **Step 1: 建 fixture 页**

`xhs_publish.html`（发布页表单——上传/标题/正文/提交）：

```html
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>发布笔记</title></head>
<body>
  <div class="publish_page">
    <div class="tab_note">上传图文</div>
    <input type="file" class="upload_input" multiple accept="image/*">
    <input type="text" class="title_input" maxlength="20" placeholder="填写标题会有更多赞哦">
    <textarea class="body_input" maxlength="1000" placeholder="填写更多描述"></textarea>
    <div class="tag_container"></div>
    <button class="submit_btn">发布</button>
  </div>
</body></html>
```

`xhs_publish_success.html`：

```html
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>发布成功</title></head>
<body>
  <div class="publish_success" data-note-id="note-6510f2ab">发布成功</div>
</body></html>
```

- [ ] **Step 2: 追加失败测试**

```python
from worker.adapters.base import PlatformPost, PublishError


def _make_png(path: Path) -> Path:
    import base64

    path.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    ))
    return path


def test_compose_post_enforces_platform_specs(tmp_path):
    a = make_adapter(tmp_path)
    post = a.compose_post(
        title="这个标题很长很长很长很长很长很长很长很长很长很长很长很长",
        body="正文" * 600,   # 1200 字 → 截到 1000
        images=[str(_make_png(tmp_path / "c.png"))],
    )
    assert len(post.title) <= 20
    assert len(post.body) <= 1000
    assert post.title.startswith("这个标题很长")
    assert post.images == [str(tmp_path / "c.png")]


def test_execute_publish_success_flow(tmp_path, monkeypatch):
    a = make_adapter(tmp_path,
                     **{"**://creator.xiaohongshu.com/publish**": FIXTURES / "xhs_publish.html",
                        "**://creator.xiaohongshu.com/publish/success**": FIXTURES / "xhs_publish_success.html"})
    # 提交后跳转到成功页：在 fixture 的提交按钮上挂跳转
    monkeypatch_publish_redirect(a, FIXTURES / "xhs_publish.html")
    try:
        post = a.compose_post("标题", "正文", [str(_make_png(tmp_path / "c.png"))])
        result = a.execute_publish(post)
        assert result.success
        assert "note-6510f2ab" in result.post_url
    finally:
        a.close()


def monkeypatch_publish_redirect(a, publish_fixture: Path) -> None:
    """让提交按钮点击后进入成功页：改写 fixture 注入 onclick 跳转，并重新挂路由。"""
    html = publish_fixture.read_text(encoding="utf-8").replace(
        '<button class="submit_btn">发布</button>',
        '<button class="submit_btn" onclick="location.href=\'https://creator.xiaohongshu.com/publish/success\'">发布</button>',
    )
    rewritten = publish_fixture.parent / "xhs_publish_patched.html"
    rewritten.write_text(html, encoding="utf-8")
    a.FIXTURE_ROUTES["**://creator.xiaohongshu.com/publish**"] = rewritten


def test_execute_publish_classifies_login_expired(tmp_path):
    # 发布页落在未登录状态：路由到 logged_out fixture（登录容器可见）→ LOGIN_EXPIRED
    a = make_adapter(tmp_path,
                     **{"**://creator.xiaohongshu.com/publish**": FIXTURES / "xhs_home_logged_out.html"})
    try:
        post = a.compose_post("t", "b", [])
        result = a.execute_publish(post)
        assert not result.success
        assert result.error is PublishError.LOGIN_EXPIRED
    finally:
        a.close()


def test_execute_publish_classifies_selector_broken(tmp_path):
    a = make_adapter(tmp_path,
                     **{"**://creator.xiaohongshu.com/publish**": FIXTURES / "xhs_home_logged_in.html"})  # 页面没有表单
    try:
        post = a.compose_post("t", "b", [])
        result = a.execute_publish(post)
        assert not result.success
        assert result.error is PublishError.SELECTOR_BROKEN
    finally:
        a.close()
```

- [ ] **Step 3: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_xiaohongshu.py -v`
Expected: 新增 4 项 FAILED（NotImplementedError / 属性不存在）

- [ ] **Step 4: 实现（xiaohongshu.py 替换两个存根）**

```python
PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?source=official"

# ---- 发布页选择器（fixture 契约；真实页面校准点）----
SEL_TAB_NOTE = ".tab_note"
SEL_UPLOAD_INPUT = ".upload_input"
SEL_TITLE_INPUT = ".title_input"
SEL_BODY_INPUT = ".body_input"
SEL_SUBMIT = ".submit_btn"
SEL_SUCCESS = ".publish_success"

TITLE_MAX = 20
BODY_MAX = 1000
```

类内替换存根：

```python
    def compose_post(self, title: str, body: str, images: list[str]) -> PlatformPost:
        from .base import PlatformPost  # 顶部导入更佳：文件顶部 from .base import PlatformPost

        trimmed_title = title.strip()[:TITLE_MAX]
        trimmed_body = body.strip()[:BODY_MAX]
        tags = ["AI", "自动化"]
        return PlatformPost(title=trimmed_title, body=trimmed_body, tags=tags, images=list(images))

    def execute_publish(self, post) -> PublishResult:
        from .base import PublishResult  # 同上，顶部导入

        try:
            with self.browser_page() as page:
                page.goto(PUBLISH_URL, wait_until="domcontentloaded")
                if "/login" in page.url or page.locator(SEL_LOGIN_MARKER).count() > 0:
                    return PublishResult(success=False, error=PublishError.LOGIN_EXPIRED,
                                         detail="发布页处于未登录状态，请重新 login")
                page.locator(SEL_TAB_NOTE).click()
                if post.images:
                    page.locator(SEL_UPLOAD_INPUT).first.set_input_files(post.images)
                page.locator(SEL_TITLE_INPUT).fill(post.title)
                page.locator(SEL_BODY_INPUT).fill(post.body)
                page.locator(SEL_SUBMIT).click()
                page.locator(SEL_SUCCESS).first.wait_for(timeout=15000)
                note_id = page.locator(SEL_SUCCESS).first.get_attribute("data-note-id") or ""
                return PublishResult(success=True, post_url=f"https://www.xiaohongshu.com/explore/{note_id}")
        except PlaywrightTimeoutError:
            return PublishResult(success=False, error=PublishError.SELECTOR_BROKEN,
                                 detail="发布页选择器超时——页面结构可能已改版，需校准 SELECTORS")
        except Exception as exc:  # 平台侧拒绝（上传失败/内容审核弹窗等）
            return PublishResult(success=False, error=PublishError.PLATFORM_REJECTED, detail=str(exc)[:200])
```

（整理导入：文件顶部统一 `from .base import HealthReport, HealthStatus, PlatformPost, PublishError, PublishResult, Trend`。）

- [ ] **Step 5: 运行确认通过（含 Task 6 的 3 项 = 7 passed）**

Run: `cd worker && uv run pytest tests/test_xiaohongshu.py -v`
Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
git add worker/worker/adapters/xiaohongshu.py worker/tests/test_xiaohongshu.py worker/tests/fixtures/xhs_publish*.html
git commit -m "feat(worker): 小红书发布——表单填写/成功判定/三类错误分类"
```

---

### Task 8: B站专栏适配器（四方法）

**Files:**
- Create: `worker/worker/adapters/bilibili_column.py`
- Create: `worker/tests/fixtures/bili_*.html`（五张，结构同 xhs 系列但选择器不同）
- Test: `worker/tests/test_bilibili_column.py`

- [ ] **Step 1: 建 fixture 页**

`bili_home_logged_in.html`：

```html
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>B站创作中心</title></head>
<body><div class="member-container"><a class="create-entry" href="/platform/upload-text/edit">专栏投稿</a></div></body>
</html>
```

`bili_home_logged_out.html`：

```html
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>登录 - 哔哩哔哩</title></head>
<body><div class="bili-mini-login"><div class="login-qrcode"></div></div></body>
</html>
```

`bili_trends.html`：

```html
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>热门</title></head>
<body>
  <div class="hot-list">
    <div class="hot-rank-item"><span class="rank-title">AI Agent 进展盘点</span><span class="rank-score">289000</span></div>
    <div class="hot-rank-item"><span class="rank-title">编程工具评测</span><span class="rank-score">201000</span></div>
  </div>
</body>
</html>
```

`bili_publish.html`：

```html
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>专栏投稿</title></head>
<body>
  <div class="text-editor">
    <input type="file" class="cover-upload" accept="image/*">
    <input type="text" class="title-input" maxlength="80" placeholder="请输入标题（2-80字）">
    <textarea class="content-input" placeholder="请输入正文"></textarea>
    <button class="submit-btn">发布专栏</button>
  </div>
</body>
</html>
```

`bili_publish_success.html`：

```html
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>专栏发布成功</title></head>
<body><div class="success-toast" data-cv-id="cv3829104">专栏发布成功</div></body>
</html>
```

- [ ] **Step 2: 写失败测试**

```python
from pathlib import Path

import pytest

from worker.adapters.base import HealthStatus, PublishError
from worker.adapters.bilibili_column import BilibiliColumnAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def make_adapter(tmp_path, **routes: Path) -> BilibiliColumnAdapter:
    a = BilibiliColumnAdapter(profiles_root=tmp_path / "profiles", headless=True)
    a.FIXTURE_ROUTES = dict(routes)
    return a


def test_check_health_ok(tmp_path):
    a = make_adapter(tmp_path, **{"**://member.bilibili.com/**": FIXTURES / "bili_home_logged_in.html"})
    try:
        assert a.check_health().status is HealthStatus.OK
    finally:
        a.close()


def test_check_health_needs_login(tmp_path):
    # 登录容器可见（fixture 契约）→ NEEDS_LOGIN，无需真实重定向
    a = make_adapter(tmp_path, **{"**://member.bilibili.com/**": FIXTURES / "bili_home_logged_out.html"})
    try:
        assert a.check_health().status is HealthStatus.NEEDS_LOGIN
    finally:
        a.close()


def test_fetch_trends(tmp_path):
    a = make_adapter(tmp_path, **{"**://www.bilibili.com/v/hot**": FIXTURES / "bili_trends.html"})
    try:
        trends = a.fetch_trends()
        assert [t.title for t in trends] == ["AI Agent 进展盘点", "编程工具评测"]
        assert trends[0].heat == pytest.approx(289000.0)
    finally:
        a.close()


def test_compose_post_specs(tmp_path):
    a = make_adapter(tmp_path)
    post = a.compose_post(title="t" * 100, body="b" * 10, images=[])
    assert len(post.title) <= 80
    assert post.tags == ["B站专栏"]


def test_execute_publish_success(tmp_path):
    a = make_adapter(tmp_path,
                     **{"**://member.bilibili.com/platform/upload-text/edit**": FIXTURES / "bili_publish.html"})
    # 提交后成功判定：改写 fixture 注入 data-cv-id 的成功 toast（无需跳转）
    html = (FIXTURES / "bili_publish.html").read_text(encoding="utf-8").replace(
        '<button class="submit-btn">发布专栏</button>',
        '<button class="submit-btn" onclick="'
        "document.body.insertAdjacentHTML('beforeend', "
        '&quot;<div class=&quot;success-toast&quot; data-cv-id=&quot;cv3829104&quot;>成功</div>&quot;)">'
        '">发布专栏</button>',
    )
    patched = FIXTURES / "bili_publish_patched.html"
    patched.write_text(html, encoding="utf-8")
    a.FIXTURE_ROUTES["**://member.bilibili.com/platform/upload-text/edit**"] = patched
    try:
        post = a.compose_post("标题", "正文", [])
        result = a.execute_publish(post)
        assert result.success and "cv3829104" in result.post_url
    finally:
        a.close()


def test_execute_publish_selector_broken(tmp_path):
    a = make_adapter(tmp_path,
                     **{"**://member.bilibili.com/platform/upload-text/edit**": FIXTURES / "bili_home_logged_in.html"})
    try:
        post = a.compose_post("t", "b", [])
        result = a.execute_publish(post)
        assert result.error is PublishError.SELECTOR_BROKEN
    finally:
        a.close()
```

- [ ] **Step 3: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_bilibili_column.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现 bilibili_column.py**

```python
"""B站专栏适配器。选择器契约见 tests/fixtures/bili_*.html。"""
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .base import (
    HealthReport,
    HealthStatus,
    PlatformPost,
    PublishError,
    PublishResult,
    Trend,
)
from .browser import PlaywrightBase

HOME_URL = "https://member.bilibili.com/platform/home"
TRENDS_URL = "https://www.bilibili.com/v/popular/rank/all"
PUBLISH_URL = "https://member.bilibili.com/platform/upload-text/edit"

SEL_LOGIN_MARKER = ".bili-mini-login"
SEL_LOGGED_IN_MARKER = ".create-entry"
SEL_TREND_ITEM = ".hot-rank-item"
SEL_TREND_TITLE = ".rank-title"
SEL_TREND_HEAT = ".rank-score"
SEL_COVER_UPLOAD = ".cover-upload"
SEL_TITLE_INPUT = ".title-input"
SEL_CONTENT_INPUT = ".content-input"
SEL_SUBMIT = ".submit-btn"
SEL_SUCCESS = ".success-toast"

TITLE_MAX = 80


class BilibiliColumnAdapter(PlaywrightBase):
    platform_id = "bilibili_column"
    display_name = "B站专栏"
    LOGIN_URL = "https://passport.bilibili.com/login"

    def check_health(self) -> HealthReport:
        with self.browser_page() as page:
            page.goto(HOME_URL, wait_until="domcontentloaded")
            if "passport.bilibili.com" in page.url or page.locator(SEL_LOGIN_MARKER).count() > 0:
                return HealthReport(HealthStatus.NEEDS_LOGIN, "处于未登录状态")
            try:
                page.locator(SEL_LOGGED_IN_MARKER).first.wait_for(timeout=5000)
                return HealthReport(HealthStatus.OK)
            except PlaywrightTimeoutError:
                return HealthReport(HealthStatus.BROKEN, "创作中心页面结构不符（选择器待校准）")

    def fetch_trends(self) -> list[Trend]:
        with self.browser_page() as page:
            page.goto(TRENDS_URL, wait_until="domcontentloaded")
            trends = []
            for item in page.locator(SEL_TREND_ITEM).all():
                title = item.locator(SEL_TREND_TITLE).inner_text().strip()
                try:
                    heat = float(item.locator(SEL_TREND_HEAT).inner_text().strip().replace(",", ""))
                except ValueError:
                    heat = 0.0
                trends.append(Trend(title=title, heat=heat))
            return trends

    def compose_post(self, title: str, body: str, images: list[str]) -> PlatformPost:
        return PlatformPost(
            title=title.strip()[:TITLE_MAX],
            body=body.strip(),
            tags=["B站专栏"],
            images=list(images),
        )

    def execute_publish(self, post: PlatformPost) -> PublishResult:
        try:
            with self.browser_page() as page:
                page.goto(PUBLISH_URL, wait_until="domcontentloaded")
                if "passport.bilibili.com" in page.url:
                    return PublishResult(success=False, error=PublishError.LOGIN_EXPIRED, detail="需重新登录")
                if post.images:
                    page.locator(SEL_COVER_UPLOAD).first.set_input_files(post.images[0])
                page.locator(SEL_TITLE_INPUT).fill(post.title)
                page.locator(SEL_CONTENT_INPUT).fill(post.body)
                page.locator(SEL_SUBMIT).click()
                page.locator(SEL_SUCCESS).first.wait_for(timeout=15000)
                cv_id = page.locator(SEL_SUCCESS).first.get_attribute("data-cv-id") or ""
                return PublishResult(success=True, post_url=f"https://www.bilibili.com/read/{cv_id}")
        except PlaywrightTimeoutError:
            return PublishResult(success=False, error=PublishError.SELECTOR_BROKEN,
                                 detail="专栏编辑器选择器超时，需校准")
        except Exception as exc:
            return PublishResult(success=False, error=PublishError.PLATFORM_REJECTED, detail=str(exc)[:200])
```

- [ ] **Step 5: 运行确认通过**

Run: `cd worker && uv run pytest tests/test_bilibili_column.py -v`
Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
git add worker/worker/adapters/bilibili_column.py worker/tests/test_bilibili_column.py worker/tests/fixtures/bili_*.html
git commit -m "feat(worker): B站专栏适配器——健康/热榜/发布与错误分类"
```

---

### Task 9: Pipeline 升级（image_client 注入 + 决策 #7/#10/#12/#13）

**Files:**
- Modify: `worker/worker/pipeline.py`
- Test: `worker/tests/test_pipeline_v2.py`

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path

import pytest

from worker.adapters.base import AdapterRegistry
from worker.adapters.demo import DemoAdapter
from worker.llm.client import StubEmbedder, StubLLM
from worker.memory.store import connect
from worker.pipeline import Pipeline


class FakeImageClient:
    """落盘假 PNG，记录 prompt。"""

    def __init__(self):
        self.prompts = []

    def generate(self, prompt: str, out_path: Path) -> Path:
        self.prompts.append(prompt)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x89PNG-fake")
        return out_path


def make_pipeline(tmp_path, image_client=None, agent_id="tech-笔记官") -> Pipeline:
    con = connect(tmp_path / "a.db")
    registry = AdapterRegistry()
    registry.register(DemoAdapter(out_file=tmp_path / "demo_published.json"))
    return Pipeline(
        registry=registry,
        llm=StubLLM(),
        embedder=StubEmbedder(),
        con=con,
        agent_id=agent_id,
        image_client=image_client,
        images_root=tmp_path / "images",
    )


def test_real_image_client_generates_cover_file(tmp_path):
    fake = FakeImageClient()
    pipe = make_pipeline(tmp_path, image_client=fake)
    draft = pipe.run(platform_id="demo")
    assert draft.images and Path(draft.images[0]).exists()
    assert draft.images[0].startswith(str(tmp_path / "images")) or draft.images[0].startswith(
        str((tmp_path / "images").resolve())
    )
    assert draft.title in fake.prompts[0]


def test_stub_mode_when_no_image_client(tmp_path):
    pipe = make_pipeline(tmp_path, image_client=None)
    draft = pipe.run(platform_id="demo")
    assert draft.images[0].startswith("cover-stub:")   # 计划 1 行为保持


def test_approve_unknown_id_raises_value_error(tmp_path):
    pipe = make_pipeline(tmp_path)
    with pytest.raises(ValueError, match="不存在"):
        pipe.approve("nope")


def test_approve_blank_edits_normalized_as_no_edit(tmp_path):
    pipe = make_pipeline(tmp_path)
    d = pipe.run(platform_id="demo")
    pipe.approve(d.draft_id, edited_title="   ")   # 纯空白 → 视为未改写
    hits = pipe.global_mem.recall(d.title, k=1)
    assert hits[0]["edited"] is False


def test_l3_writeback_failure_does_not_mask_publish(tmp_path, capsys, monkeypatch):
    pipe = make_pipeline(tmp_path)
    d = pipe.run(platform_id="demo")

    def boom(*args, **kwargs):
        raise RuntimeError("L3 挂了")

    monkeypatch.setattr(pipe.global_mem, "add", boom)
    result = pipe.approve(d.draft_id)
    assert result.success                                  # 发布事实优先
    assert pipe.drafts[d.draft_id].status == "published"
    assert "L3 写回失败" in capsys.readouterr().err


def test_rejections_capped_in_prompt(tmp_path):
    pipe = make_pipeline(tmp_path)
    for i in range(12):
        pipe.agent.record_rejection(f"理由{i}")
    d1 = pipe.run(platform_id="demo")

    class SpyLLM2(StubLLM):
        def __init__(self):
            super().__init__()
            self.last_system = ""

        def complete(self, system, user):
            self.last_system = system
            return super().complete(system, user)

    spy = SpyLLM2()
    con = connect(tmp_path / "a.db")
    registry = AdapterRegistry()
    registry.register(DemoAdapter(out_file=tmp_path / "demo_published.json"))
    pipe2 = Pipeline(registry=registry, llm=spy, embedder=StubEmbedder(), con=con, agent_id="tech-笔记官")
    pipe2.run(platform_id="demo")
    assert "理由11" in spy.last_system        # 最近一条保留
    assert "理由0" not in spy.last_system     # 最早的被截断
    assert "共 12 条" in spy.last_system      # 汇总计数
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_pipeline_v2.py -v`
Expected: FAIL（`Pipeline.__init__() got an unexpected keyword argument 'image_client'` 等）

- [ ] **Step 3: 实现（pipeline.py 修改四处）**

① 构造签名与字段（替换 `__init__` 尾部——在 `self._load_drafts()` 之前加入两个参数与赋值）：

```python
    def __init__(
        self,
        registry: AdapterRegistry,
        llm: LLMClient,
        embedder: Embedder,
        con: sqlite3.Connection,
        agent_id: str = "default",
        image_client=None,                       # 可选：OpenAIImageClient（协议：generate(prompt, out_path) -> Path）
        images_root: Path = Path("data/images"),
    ) -> None:
        ...
        self.image_client = image_client
        self.images_root = Path(images_root)
        self._load_drafts()
```

（`from pathlib import Path` 加入顶部导入。）

② run() 配图段替换（决策：真实/桩双路径）：

```python
        if self.image_client is not None:
            cover = self.image_client.generate(
                prompt=f"封面图：{topic}", out_path=self.images_root / f"d{self._run_no}" / "cover.png"
            )
            images = [str(cover)]
        else:
            images = [f"cover-stub:{topic[:12]}"]  # ③ 配图占位（无真实客户端时）
```

③ WRITER_SYSTEM 的 prefs_block 构造处（run() 内）替换为截断版（决策 #7）：

```python
        prefs = dict(self.agent.get_prefs())
        rejections = prefs.pop("rejections", [])
        if len(rejections) > 10:
            prefs["rejections_摘要"] = f"共 {len(rejections)} 条（仅列最近 10 条）"
            prefs["rejections"] = rejections[-10:]
        elif rejections:
            prefs["rejections"] = rejections[-10:]
        prefs_block = json.dumps(prefs, ensure_ascii=False)
```

④ approve/reject 入口齐平（决策 #12/#13）——approve 开头加入：

```python
        draft = self.drafts.get(draft_id)
        if draft is None:
            raise ValueError(f"draft {draft_id} 不存在")
        edited_title = edited_title.strip() or None if edited_title is not None else None
        edited_body = edited_body.strip() or None if edited_body is not None else None
        if draft.status != "pending_review":
            raise ValueError(f"draft {draft_id} 状态为 {draft.status}，不能发布")
```

（reject 同样把 `self.drafts[draft_id]` 换成 get + ValueError。）

⑤ approve 的 L3 写回段替换（决策 #10——发布事实优先）：

```python
        if result.success:
            draft.status = "published"
            self._save_draft(draft)
            try:
                self.global_mem.add(
                    text=f"{title}\n{body}", platform=draft.platform, title=title, body=body, edited=edited
                )
            except Exception as exc:  # noqa: BLE001 - 记忆写失败不遮蔽发布成功
                print(f"[memory] L3 写回失败（发布已成功）: {exc}", file=sys.stderr)
        return result
```

（`import sys` 加入顶部。）

- [ ] **Step 4: 运行确认通过（含计划 1 全量回归）**

Run: `cd worker && uv run pytest -v`
Expected: 全绿（新增 6 项；CLI 的 blank-edit 测试可能因双重 normalize 仍通过——若 `test_cli_approve_blank_edit_normalized_to_no_edit` 断言 DB edited=0，CLI 层已 strip，不受影响）

- [ ] **Step 5: Commit**

```bash
git add worker/worker/pipeline.py worker/tests/test_pipeline_v2.py
git commit -m "feat(worker): 流水线接入文生图与四项审查决策（截断/容错/齐平/规整）"
```

---

### Task 10: CLI 真实装配 + login 命令 + 收尾

**Files:**
- Modify: `worker/worker/cli.py`
- Test: `worker/tests/test_cli_v2.py`
- Create: `worker/README.md`

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path


def test_cli_login_command_exists_and_calls_adapter(tmp_path, monkeypatch, capsys):
    from worker import cli

    called = {}

    class _FakeAdapter:
        platform_id = "demo"
        display_name = "本地演示平台"

        def login(self):
            called["yes"] = True
            from worker.adapters.base import HealthReport, HealthStatus
            return HealthReport(HealthStatus.OK, "已登录")

    class _FakeRegistry:
        def get(self, pid):
            return _FakeAdapter()

        def all(self):
            return {"demo": _FakeAdapter()}

    monkeypatch.setattr(cli, "load_adapters", lambda *a, **k: _FakeRegistry())
    monkeypatch.chdir(tmp_path)
    cli.main(["login", "demo"])
    assert called.get("yes") is True
    assert "已登录" in capsys.readouterr().out


def test_cli_with_config_assembles_real_clients(tmp_path, monkeypatch):
    from worker import cli

    cfg = tmp_path / "config.toml"
    cfg.write_text("""
[llm]
base_url = "https://api.example.com/v1"
api_key = "sk-x"
model = "m"
""", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    built = {}
    real_chat = cli.OpenAIChatClient
    cli.OpenAIChatClient = lambda cfg, transport=None: built.setdefault("chat", real_chat(cfg, transport))

    try:
        pipe = cli._pipeline(str(cfg))
        assert "chat" in built
        assert pipe.image_client is None          # 未配置 [image] → 回退桩
    finally:
        cli.OpenAIChatClient = real_chat


def test_cli_without_config_prints_hint_and_uses_stubs(tmp_path, monkeypatch, capsys):
    from worker import cli

    monkeypatch.chdir(tmp_path)
    cli.main(["run", "demo"])
    out = capsys.readouterr().out
    assert "pending_review" in out                 # demo + 桩照常工作
    assert "config.example.toml" in out            # 提示配置真实模式
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_cli_v2.py -v`
Expected: FAIL（`login` 子命令不存在 / `_pipeline` 不接受 config 路径）

- [ ] **Step 3: 实现（cli.py 重写装配段）**

```python
"""CLI 入口：无 Electron 独立运行（python -m worker ...）。

有 config.toml → 真实客户端（LLM/Embedding/文生图/浏览器适配器）；
无 → 回退桩与 demo 平台，并打印配置提示。
"""
import argparse
import sys
from pathlib import Path

from .adapters.base import load_adapters
from .config import load_config
from .llm.client import StubEmbedder, StubLLM
from .llm.openai_compat import OpenAIChatClient, OpenAIEmbedder, OpenAIImageClient
from .memory.store import connect
from .pipeline import Pipeline


def _pipeline(db: str, config_path: str | None = None) -> Pipeline:
    cfg = None
    candidates = [config_path] if config_path else ["config.toml"]
    for path in candidates:
        if path and Path(path).exists():
            cfg = load_config(path)
            break

    def _browser_builder(cls):
        # 浏览器适配器注入会话参数；非浏览器适配器（如 demo）不接受这些 kwargs，回退无参构造
        if cfg is not None:
            try:
                return cls(headless=cfg.headless, profiles_root=cfg.profiles_root)
            except TypeError:
                pass
        return cls()

    registry = load_adapters(builder=_browser_builder)
    if cfg and cfg.llm:
        llm = OpenAIChatClient(cfg.llm)
        embedder = OpenAIEmbedder(cfg.embedding) if cfg.embedding else StubEmbedder()
        image_client = OpenAIImageClient(cfg.image) if cfg.image else None
    else:
        llm, embedder, image_client = StubLLM(), StubEmbedder(), None

    return Pipeline(
        registry=registry,
        llm=llm,
        embedder=embedder,
        con=connect(db),
        image_client=image_client,
        images_root=cfg.images_root if cfg else Path("data/images"),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="worker", description="AI 社媒自动化 Worker（CLI 模式）")
    parser.add_argument("--db", default="agent.db", help="SQLite 数据库路径")
    parser.add_argument("--config", default=None, help="config.toml 路径（缺省查找工作目录）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("adapters", help="列出已注册适配器")
    login_p = sub.add_parser("login", help="打开浏览器扫码登录平台")
    login_p.add_argument("platform")
    run_p = sub.add_parser("run", help="跑一轮流水线（到待审草稿）")
    run_p.add_argument("platform")
    approve_p = sub.add_parser("approve", help="审核通过并发布")
    approve_p.add_argument("draft_id")
    approve_p.add_argument("--title", help="改写标题（可选）")
    approve_p.add_argument("--body", help="改写正文（可选）")
    reject_p = sub.add_parser("reject", help="驳回草稿")
    reject_p.add_argument("draft_id")
    reject_p.add_argument("reason")

    args = parser.parse_args(argv)
    if args.cmd == "adapters":
        for pid, adapter in load_adapters().all().items():
            print(f"{pid}\t{adapter.display_name}")
        return

    if args.cmd == "login":
        cfg = load_config(args.config) if (args.config and Path(args.config).exists()) else None

        def _login_builder(cls):
            if cfg is not None:
                try:
                    return cls(headless=False, profiles_root=cfg.profiles_root)
                except TypeError:
                    pass
            return cls()

        registry = load_adapters(builder=_login_builder)
        adapter = registry.get(args.platform)
        if not hasattr(adapter, "login"):
            print(f"平台 {args.platform} 不需要登录（无 login 方法）")
            return
        report = adapter.login()
        print(f"platform={args.platform} status={report.status.value} detail={report.detail}")
        if report.status.value != "ok":
            raise SystemExit(1)
        return

    pipe = _pipeline(args.db, args.config)
    if args.cmd == "run":
        draft = pipe.run(platform_id=args.platform)
        print(f"draft_id={draft.draft_id} status={draft.status} platform={draft.platform}")
        print(f"title={draft.title}")
        if draft.images and draft.images[0].startswith("cover-stub:"):
            print("hint=桩模式——复制 config.example.toml 为 config.toml 并填入 key 以启用真实 LLM/文生图")
    elif args.cmd == "approve":
        result = pipe.approve(args.draft_id, edited_title=args.title, edited_body=args.body)
        status = pipe.drafts[args.draft_id].status
        print(f"status={status} success={result.success} url={result.post_url} error={result.error}")
        if not result.success:
            raise SystemExit(1)
    elif args.cmd == "reject":
        pipe.reject(args.draft_id, reason=args.reason)
        print("status=rejected")
```

`worker/README.md`：

```markdown
# AI 社媒自动化 Worker

## 快速开始（桩模式，离线可用）

```bash
cd worker && uv sync
uv run python -m worker run demo        # 跑一轮到待审草稿
uv run python -m worker approve d1      # 审核通过并"发布"到 demo_published.json
```

## 启用真实平台与真实 AI

1. `cp config.example.toml config.toml`，填入 OpenAI 兼容 API key（智谱/DeepSeek/OpenAI 均可）
2. `uv run playwright install chromium`（首次）
3. 扫码登录平台（浏览器可见，180 秒超时）：
   ```bash
   uv run python -m worker login xiaohongshu
   uv run python -m worker login bilibili_column
   ```
4. 真实流水线：
   ```bash
   uv run python -m worker run xiaohongshu
   uv run python -m worker approve d1
   ```

## 说明

- 选择器以 `tests/fixtures/*.html` 为契约；真实页面改版后发布会返回
  `error=selector_broken`，按 `adapters/*.py` 顶部的 SELECTORS 注释校准。
- 全部凭据（config.toml、浏览器 profile、SQLite）仅在本地 `data/` 与工作目录，不上传。
```

- [ ] **Step 4: 运行全部测试**

Run: `cd worker && uv run pytest -v`
Expected: 全绿（此前全部 + 3 新增）

- [ ] **Step 5: 手动验收（真实链路，可选但推荐）**

```bash
cd worker
uv run python -m worker adapters          # 应列出 demo / xiaohongshu / bilibili_column
uv run python -m worker login xiaohongshu # 人工扫码
uv run python -m worker run xiaohongshu   # 真实 LLM 写作（需 config.toml）
uv run python -m worker approve <id>      # 真实发布到小红书
```

（若选择器与真实页面不符 → `selector_broken`，校准 SELECTORS 后重跑——这是本计划的已知工作方式。）

- [ ] **Step 6: Commit**

```bash
git add worker/worker/cli.py worker/tests/test_cli_v2.py worker/README.md
git commit -m "feat(worker): CLI 真实装配/login 命令/使用文档"
```

---

## 计划 2 完成标准

- `cd worker && uv run pytest -v` 全绿（计划 1 基线 37 + 本计划约 20 新增）
- `python -m worker adapters` 列出 demo / xiaohongshu / bilibili_column
- 无 config.toml 时 demo 桩链路行为与计划 1 完全一致（回归保障）
- 有 config.toml 时：`login` 扫码建会话 → `run` 真实 LLM 写作 + 真实封面图 → `approve` 真实浏览器发布，三类错误分类各有测试锚定（fixture 契约）
- 15 条计划 1 决策中 #2/#3/#4/#7/#10/#12/#13 已落地，其余（#5/#6/#8/#9/#11/#14/#15）属计划 3 或运行时校准项

## 后续计划

- **计划 3**：Electron 主进程（Worker 守护 + JSON-RPC IPC）与 React UI（仪表盘/主题系统/轨道时钟/草稿箱）——届时消化决策 #14/#15 与 draft 存态决策 #11

### 计划 2 执行中补充决策

16. **GlobalMemory 维度自动推断**（P2T1 审查发现）：`EmbeddingConfig.dims` 在原计划中是只写字段，而 `GlobalMemory(con, embedder)` 默认 `dims=8`——真实 embedding（如 2048 维）接入时会撞计划 1 的构造期哨兵探测直接 ValueError。**Task 9 一并修改**：`GlobalMemory.__init__` 的 `dims` 参数改为 `int | None = None`，None 时以哨兵探测长度自动建表；显式传入时仍与探测值校验（mismatch 抛 ValueError，既有测试语义不变）。真实装配链由此自然工作：`Pipeline(con=..., embedder=OpenAIEmbedder(...))` → 探测 2048 → `float[2048]`。

17. **429 重试与超时/解析加固**（P2T3 审查，Task 4 一并落地）：`_post_with_retry` 的重试条件从 `>=500` 扩为 `==429 或 >=500`，429 时尊重 `Retry-After` 头（有则 sleep 该秒数，无则指数退避）；三处客户端 timeout 改 `httpx.Timeout(<总>, connect=10)`；`resp.json()` 与键提取的解析异常包装为 RuntimeError（网关 200 返回 HTML 时的统一错误面）。补测试：429→Retry-After→成功。

18. **Playwright 路由处理器签名**（P2T5 实现发现）：Playwright 1.64 以 `(route, request)` 两个位置参数调用路由处理器，计划 Task 5 的 `lambda route, f=fixture:` 默认参方案会被 request 覆盖导致 TypeError。实现改为模块级 `_make_fixture_handler(fixture)` 闭包工厂（handler 签名 `(route, request=None)`），行为契约不变。Task 6-8 无需关心（走 FIXTURE_ROUTES 机制）。
19. **测试 profile 目录忽略**（P2T5 自检）：`worker/tests/tmp_profiles/` 是测试运行的持久化用户数据目录，加入根 .gitignore（Task 6 顺手做）。

20. **CLI login 后必须 close**（P2T5 审查级联预警）：playwright 包无 atexit 清理钩子，`sync_playwright().start()` 手动启动后进程退出依赖管道信号关闭，Windows 上偶有 Chromium/driver 残留——Task 10 的 login 命令必须 `try/finally: adapter.close()`。
21. **PlaywrightBase 三处廉价加固**（P2T5 审查 Minor，Task 6 顺手做）：① browser_page 的 finally 中 `page.close()` 包 `contextlib.suppress(Exception)`（浏览器已崩溃时不掩盖原始异常）；② close() 的 `context.close()` 包 try/finally 保证 `pw.stop()` 必然执行；③ docstring 注明 FIXTURE_ROUTES 只允许整体赋值、context 建立后修改不生效、单进程同步使用约定。
