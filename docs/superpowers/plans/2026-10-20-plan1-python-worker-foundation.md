# 计划 1：Python Worker 地基 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建可脱离 Electron 独立运行的 Python Worker：JSON-RPC 服务、适配器契约与自动注册、三层记忆（L1/L2/L3）、LLM 桩、流水线编排（调研→召回→写作→配图→待审）与审核动作，全部有 pytest 覆盖。

**Architecture:** 单一 Python 包 `worker`（rpc / adapters / memory / llm / pipeline 五个模块），CLI 入口 `python -m worker`，SQLite 单文件存储 L2/L3/草稿，sqlite-vec 做向量召回。真实平台适配器与真实 LLM API 留给计划 2，本计划用 DemoAdapter + StubLLM 验证全部契约。

**Tech Stack:** Python 3.12+ · uv · pytest + pytest-asyncio · websockets ≥13 · sqlite-vec

**依据规格:** [技术文档](../specs/2026-10-20-ai-social-media-agent-tool-tech.md) §1–§4、§6

---

## 文件结构（本计划创建）

```
worker/
├─ pyproject.toml
├─ worker/
│  ├─ __init__.py            # 空
│  ├─ __main__.py            # python -m worker → cli.main()
│  ├─ cli.py                 # CLI：run / approve / reject / serve
│  ├─ rpc/
│  │  ├─ __init__.py         # 空
│  │  ├─ protocol.py         # Request / Response（correlation id）
│  │  └─ server.py           # RpcServer：WebSocket + JSON-RPC + broadcast
│  ├─ adapters/
│  │  ├─ __init__.py         # 空
│  │  ├─ base.py             # 数据类 + PlatformAdapter + AdapterRegistry + load_adapters
│  │  └─ demo.py             # DemoAdapter（本地文件假平台）
│  ├─ memory/
│  │  ├─ __init__.py         # 空
│  │  ├─ store.py            # SQLite 连接 + schema
│  │  ├─ l1.py               # RunContext（工作记忆）
│  │  ├─ l2.py               # AgentMemory（偏好）
│  │  └─ l3.py               # GlobalMemory（向量召回 + 降权）
│  ├─ llm/
│  │  ├─ __init__.py         # 空
│  │  └─ client.py           # LLMClient/Embedder 协议 + Stub 实现
│  └─ pipeline.py            # Pipeline：run/approve/reject + 草稿持久化
└─ tests/
   ├─ test_rpc_protocol.py
   ├─ test_rpc_server.py
   ├─ test_registry.py
   ├─ test_memory_l2.py
   ├─ test_memory_l3.py
   ├─ test_pipeline.py
   └─ test_cli_smoke.py
```

---

### Task 1: 项目脚手架

**Files:**
- Create: `worker/pyproject.toml`
- Create: `worker/worker/__init__.py`（空）
- Create: `worker/tests/__init__.py`（空）
- Create: `worker/tests/test_scaffold.py`

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "worker"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["websockets>=13", "sqlite-vec>=0.1.6"]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["worker"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: 建包目录与占位测试**

`worker/tests/test_scaffold.py`：

```python
def test_package_importable():
    import worker  # noqa: F401
```

- [ ] **Step 3: 安装并运行**

```bash
cd worker && uv sync && uv run pytest -v
```

Expected: `1 passed`

- [ ] **Step 4: Commit**

```bash
git add worker/pyproject.toml worker/worker/__init__.py worker/tests/
git commit -m "feat(worker): 项目脚手架（uv + pytest）"
```

---

### Task 2: RPC 协议（Request / Response + correlation id）

**Files:**
- Create: `worker/worker/rpc/__init__.py`（空）
- Create: `worker/worker/rpc/protocol.py`
- Test: `worker/tests/test_rpc_protocol.py`

- [ ] **Step 1: 写失败测试**

```python
from worker.rpc.protocol import Request, Response


def test_request_serializes_with_unique_ids():
    a, b = Request(method="ping"), Request(method="ping")
    ja, jb = a.to_json(), b.to_json()
    assert ja["jsonrpc"] == "2.0" and ja["method"] == "ping"
    assert ja["id"] != jb["id"]  # correlation id 全局递增


def test_response_parses_result_and_error():
    ok = Response.from_json({"jsonrpc": "2.0", "id": 7, "result": {"x": 1}})
    err = Response.from_json({"jsonrpc": "2.0", "id": 8, "error": "boom"})
    assert ok.id == 7 and ok.result == {"x": 1} and ok.error is None
    assert err.error == "boom" and err.result is None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_rpc_protocol.py -v`
Expected: FAIL（`ModuleNotFoundError: worker.rpc`）

- [ ] **Step 3: 实现 protocol.py**

```python
"""JSON-RPC 消息协议：请求/响应 + correlation id。"""
from dataclasses import dataclass, field
from itertools import count
from typing import Any

_IDS = count(1)


@dataclass
class Request:
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    id: int = field(default_factory=lambda: next(_IDS))

    def to_json(self) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": self.id, "method": self.method, "params": self.params}


@dataclass
class Response:
    id: int
    result: Any = None
    error: str | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Response":
        return cls(id=data["id"], result=data.get("result"), error=data.get("error"))
```

- [ ] **Step 4: 运行确认通过**

Run: `cd worker && uv run pytest tests/test_rpc_protocol.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add worker/worker/rpc/ worker/tests/test_rpc_protocol.py
git commit -m "feat(worker): JSON-RPC 协议与 correlation id"
```

---

### Task 3: RPC 服务器（WebSocket 路由 + 广播）

**Files:**
- Create: `worker/worker/rpc/server.py`
- Test: `worker/tests/test_rpc_server.py`

- [ ] **Step 1: 写失败测试**

```python
import json

import websockets

from worker.rpc.protocol import Request, Response
from worker.rpc.server import RpcServer


async def test_roundtrip_and_unknown_method():
    server = RpcServer(host="127.0.0.1", port=0)

    @server.method("echo")
    async def echo(params):
        return params

    async with server.start():
        async with websockets.connect(server.url) as ws:
            await ws.send(json.dumps(Request(method="echo", params={"v": 1}).to_json()))
            ok = Response.from_json(json.loads(await ws.recv()))
            assert ok.result == {"v": 1} and ok.error is None

            await ws.send(json.dumps(Request(method="nope").to_json()))
            err = Response.from_json(json.loads(await ws.recv()))
            assert "unknown method" in err.error


async def test_broadcast_reaches_clients():
    server = RpcServer(host="127.0.0.1", port=0)

    @server.method("trigger")
    async def trigger(params):
        await server.broadcast("stage_changed", {"stage": "review"})

    async with server.start():
        async with websockets.connect(server.url) as ws:
            async with websockets.connect(server.url) as ws2:
                await ws.send(json.dumps(Request(method="trigger").to_json()))
                got1, got2 = json.loads(await ws.recv()), json.loads(await ws2.recv())
                notifications = [m for m in (got1, got2) if m.get("method") == "stage_changed"]
                assert len(notifications) >= 1
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_rpc_server.py -v`
Expected: FAIL（`No module named 'worker.rpc.server'`）

- [ ] **Step 3: 实现 server.py**

```python
"""WebSocket JSON-RPC 服务器：方法路由 + 事件广播。"""
import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from websockets.asyncio.server import serve

Handler = Callable[[dict[str, Any]], Awaitable[Any]]


class RpcServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._methods: dict[str, Handler] = {}
        self._clients: set = set()

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    def method(self, name: str) -> Callable[[Handler], Handler]:
        def register(fn: Handler) -> Handler:
            self._methods[name] = fn
            return fn

        return register

    async def broadcast(self, method: str, params: dict[str, Any]) -> None:
        if not self._clients:
            return
        payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, ensure_ascii=False)
        await asyncio.gather(*(ws.send(payload) for ws in list(self._clients)))

    async def _handle(self, ws) -> None:
        self._clients.add(ws)
        try:
            async for raw in ws:
                msg = json.loads(raw)
                reply = await self._dispatch(msg)
                await ws.send(json.dumps(reply, ensure_ascii=False))
        finally:
            self._clients.discard(ws)

    async def _dispatch(self, msg: dict[str, Any]) -> dict[str, Any]:
        name, mid = msg.get("method"), msg.get("id")
        if name not in self._methods:
            return {"jsonrpc": "2.0", "id": mid, "error": f"unknown method: {name}"}
        try:
            result = await self._methods[name](msg.get("params") or {})
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except Exception as exc:  # 错误必须回传调用方，不能让服务器崩溃
            return {"jsonrpc": "2.0", "id": mid, "error": str(exc)}

    @asynccontextmanager
    async def start(self):
        """启动监听；port=0 时由 OS 分配并回填 self.port，server.url 随之可用。"""
        async with serve(self._handle, self.host, self.port) as s:
            if self.port == 0:
                self.port = s.sockets[0].getsockname()[1]
            yield self
```

- [ ] **Step 4: 运行确认通过**

Run: `cd worker && uv run pytest tests/test_rpc_server.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add worker/worker/rpc/server.py worker/tests/test_rpc_server.py
git commit -m "feat(worker): WebSocket JSON-RPC 服务器与方法广播"
```

---

### Task 4: 适配器数据类与契约校验

**Files:**
- Create: `worker/worker/adapters/__init__.py`（空）
- Create: `worker/worker/adapters/base.py`
- Test: `worker/tests/test_registry.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest

from worker.adapters.base import (
    AdapterRegistry,
    ContractError,
    HealthReport,
    HealthStatus,
    PlatformAdapter,
)


class _Full(PlatformAdapter):
    platform_id = "full"

    def check_health(self):
        return HealthReport(HealthStatus.OK)

    def fetch_trends(self):
        return []

    def compose_post(self, title, body, images):
        return None

    def execute_publish(self, post):
        return None


class _Missing(_Full):
    platform_id = "missing"
    fetch_trends = None  # 契约破坏：方法缺失


def test_register_accepts_full_contract():
    registry = AdapterRegistry()
    registry.register(_Full())
    assert registry.get("full").platform_id == "full"
    assert set(registry.all()) == {"full"}


def test_register_rejects_broken_contract():
    with pytest.raises(ContractError, match="fetch_trends"):
        AdapterRegistry().register(_Missing())


def test_register_rejects_missing_platform_id():
    class _NoId(_Full):
        platform_id = ""

    with pytest.raises(ContractError, match="platform_id"):
        AdapterRegistry().register(_NoId())
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_registry.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 base.py 的数据类与注册表**

```python
"""平台适配器契约：四方法 + 元数据 + 自动注册表。"""
import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class HealthStatus(str, Enum):
    OK = "ok"
    NEEDS_LOGIN = "needs_login"
    BROKEN = "broken"


class PublishError(str, Enum):
    LOGIN_EXPIRED = "login_expired"
    SELECTOR_BROKEN = "selector_broken"
    PLATFORM_REJECTED = "platform_rejected"


@dataclass
class HealthReport:
    status: HealthStatus
    detail: str = ""


@dataclass
class Trend:
    title: str
    heat: float = 0.0
    url: str = ""


@dataclass
class PlatformPost:
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)


@dataclass
class PublishResult:
    success: bool
    post_url: str = ""
    error: PublishError | None = None
    detail: str = ""


CONTRACT_METHODS = ("check_health", "fetch_trends", "compose_post", "execute_publish")


class ContractError(Exception):
    """适配器未满足四方法契约。"""


class PlatformAdapter(ABC):
    platform_id: str = ""
    display_name: str = ""

    @abstractmethod
    def check_health(self) -> HealthReport: ...

    @abstractmethod
    def fetch_trends(self) -> list[Trend]: ...

    @abstractmethod
    def compose_post(self, title: str, body: str, images: list[str]) -> PlatformPost: ...

    @abstractmethod
    def execute_publish(self, post: PlatformPost) -> PublishResult: ...


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, PlatformAdapter] = {}

    def register(self, adapter: PlatformAdapter) -> None:
        cls = type(adapter)
        missing = [m for m in CONTRACT_METHODS if not callable(getattr(cls, m, None))]
        if missing:
            raise ContractError(f"{cls.__name__} 缺少契约方法: {missing}")
        if not adapter.platform_id:
            raise ContractError(f"{cls.__name__} 缺少 platform_id")
        self._adapters[adapter.platform_id] = adapter

    def get(self, platform_id: str) -> PlatformAdapter:
        return self._adapters[platform_id]

    def all(self) -> dict[str, PlatformAdapter]:
        return dict(self._adapters)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd worker && uv run pytest tests/test_registry.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add worker/worker/adapters/__init__.py worker/worker/adapters/base.py worker/tests/test_registry.py
git commit -m "feat(worker): 适配器四方法契约与注册表校验"
```

---

### Task 5: DemoAdapter 与自动扫描注册

**Files:**
- Create: `worker/worker/adapters/demo.py`
- Modify: `worker/worker/adapters/base.py`（追加 `load_adapters`）
- Test: `worker/tests/test_registry.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
def test_load_adapters_autoregisters_demo(tmp_path, monkeypatch):
    from worker.adapters import demo as demo_mod
    from worker.adapters.base import load_adapters

    monkeypatch.chdir(tmp_path)
    registry = load_adapters()
    assert "demo" in registry.all()
    # 假平台真实可走完四方法
    a = registry.get("demo")
    assert a.check_health().status.value == "ok"
    assert a.fetch_trends()[0].title
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_registry.py -v`
Expected: FAIL（`ImportError: cannot import name 'load_adapters'`）

- [ ] **Step 3: 实现 demo.py 与 load_adapters**

`worker/worker/adapters/demo.py`：

```python
"""本地演示适配器：把发布写入 JSON 文件，用于契约测试与离线开发。"""
import json
from pathlib import Path

from .base import (
    HealthReport,
    HealthStatus,
    PlatformAdapter,
    PlatformPost,
    PublishResult,
    Trend,
)


class DemoAdapter(PlatformAdapter):
    platform_id = "demo"
    display_name = "本地演示平台"

    def __init__(self, out_file: Path | None = None) -> None:
        self._out = Path(out_file) if out_file else Path("demo_published.json")

    def check_health(self) -> HealthReport:
        return HealthReport(HealthStatus.OK, "演示平台永远在线")

    def fetch_trends(self) -> list[Trend]:
        return [
            Trend("AI Agent 一周动态", heat=9.1),
            Trend("桌面端工具的极客界面", heat=8.4),
            Trend("多平台内容分发实践", heat=7.6),
        ]

    def compose_post(self, title: str, body: str, images: list[str]) -> PlatformPost:
        return PlatformPost(title=f"[demo] {title}", body=body, tags=["AI", "自动化"], images=images)

    def execute_publish(self, post: PlatformPost) -> PublishResult:
        data = json.loads(self._out.read_text(encoding="utf-8")) if self._out.exists() else []
        data.append({"title": post.title, "tags": post.tags})
        self._out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return PublishResult(success=True, post_url=f"demo://posts/{len(data)}")
```

在 `base.py` 末尾追加：

```python
def load_adapters(package: str = "worker.adapters") -> "AdapterRegistry":
    """扫描适配器包目录，放即注册：凡继承 PlatformAdapter 的具体类自动进入注册表。"""
    registry = AdapterRegistry()
    pkg = importlib.import_module(package)
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        if mod_info.name == "base":
            continue
        module = importlib.import_module(f"{package}.{mod_info.name}")
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, PlatformAdapter)
                and obj is not PlatformAdapter
                and obj.__module__.startswith(package)
                and not getattr(obj, "__abstractmethods__", None)
            ):
                registry.register(obj())
    return registry
```

- [ ] **Step 4: 运行确认通过**

Run: `cd worker && uv run pytest tests/test_registry.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add worker/worker/adapters/ worker/tests/test_registry.py
git commit -m "feat(worker): DemoAdapter 与适配器目录自动注册"
```

---

### Task 6: SQLite 存储与 L2 Agent 记忆

**Files:**
- Create: `worker/worker/memory/__init__.py`（空）
- Create: `worker/worker/memory/store.py`
- Create: `worker/worker/memory/l2.py`
- Test: `worker/tests/test_memory_l2.py`

- [ ] **Step 1: 写失败测试**

```python
from worker.memory.l2 import AgentMemory
from worker.memory.store import connect

KEYS = {
    "agent_pref",
    "post_archive",
    "draft",
}


def test_connect_creates_schema(tmp_path):
    con = connect(tmp_path / "a.db")
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert KEYS <= names


def test_prefs_roundtrip_and_rejections(tmp_path):
    con = connect(tmp_path / "a.db")
    mem = AgentMemory(con, agent_id="tech-笔记官")
    assert mem.get_prefs() == {}

    mem.set_pref("tone", "克制、有数据支撑")
    mem.record_rejection("标题太标题党")
    mem.record_rejection("缺少个人观点")

    prefs = mem.get_prefs()
    assert prefs["tone"] == "克制、有数据支撑"
    assert prefs["rejections"] == ["标题太标题党", "缺少个人观点"]

    # 按 agent 隔离
    other = AgentMemory(con, agent_id="ai-测评员")
    assert other.get_prefs() == {}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_memory_l2.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 store.py 与 l2.py**

`worker/worker/memory/store.py`：

```python
"""SQLite 单文件存储：L2 偏好 / L3 帖库 / 草稿 三组表的建库与连接。"""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_pref (
    agent_id TEXT NOT NULL,
    key      TEXT NOT NULL,
    value    TEXT NOT NULL,
    UNIQUE(agent_id, key)
);
CREATE TABLE IF NOT EXISTS post_archive (
    post_id        INTEGER PRIMARY KEY,
    platform       TEXT NOT NULL,
    title          TEXT NOT NULL,
    body           TEXT NOT NULL,
    edited_by_user INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS draft (
    draft_id    TEXT PRIMARY KEY,
    platform    TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    images_json TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'pending_review'
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con
```

`worker/worker/memory/l2.py`：

```python
"""L2 Agent 记忆：按 Agent 持久化的配置与交互偏好。"""
import json
import sqlite3
from typing import Any


class AgentMemory:
    def __init__(self, con: sqlite3.Connection, agent_id: str) -> None:
        self._con = con
        self._agent = agent_id

    def set_pref(self, key: str, value: Any) -> None:
        self._con.execute(
            "INSERT INTO agent_pref(agent_id, key, value) VALUES(?, ?, ?) "
            "ON CONFLICT(agent_id, key) DO UPDATE SET value=excluded.value",
            (self._agent, key, json.dumps(value, ensure_ascii=False)),
        )
        self._con.commit()

    def get_prefs(self) -> dict[str, Any]:
        rows = self._con.execute(
            "SELECT key, value FROM agent_pref WHERE agent_id=?", (self._agent,)
        ).fetchall()
        return {k: json.loads(v) for k, v in rows}

    def record_rejection(self, reason: str) -> None:
        rejections = self.get_prefs().get("rejections", [])
        rejections.append(reason)
        self.set_pref("rejections", rejections)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd worker && uv run pytest tests/test_memory_l2.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add worker/worker/memory/ worker/tests/test_memory_l2.py
git commit -m "feat(worker): SQLite 存储层与 L2 Agent 偏好记忆"
```

---

### Task 7: L3 全局向量记忆（召回 / 写回 / 降权）

**Files:**
- Create: `worker/worker/memory/l3.py`
- Test: `worker/tests/test_memory_l3.py`

- [ ] **Step 1: 写失败测试**

```python
from worker.llm.client import StubEmbedder
from worker.memory.l3 import GlobalMemory
from worker.memory.store import connect


def _mem(tmp_path, dims=8):
    con = connect(tmp_path / "a.db")
    return GlobalMemory(con, StubEmbedder(dims=dims))


def test_add_and_recall_returns_nearest_first(tmp_path):
    mem = _mem(tmp_path)
    mem.add("AI Agent 一周动态", platform="demo", title="AI Agent 一周动态", body="正文A", edited=False)
    mem.add("桌面端工具的极客界面", platform="demo", title="桌面端工具的极客界面", body="正文B", edited=False)
    hits = mem.recall("AI Agent 动态", k=2)
    assert hits[0]["title"] == "AI Agent 一周动态"
    assert len(hits) == 2


def test_edited_posts_deprioritized(tmp_path):
    mem = _mem(tmp_path)
    mem.add("AI Agent 一周动态", platform="demo", title="AI Agent 一周动态", body="A", edited=True)
    mem.add("AI Agent 框架对比", platform="demo", title="AI Agent 框架对比", body="B", edited=False)
    hits = mem.recall("AI Agent 一周动态", k=1)
    assert hits[0]["title"] == "AI Agent 框架对比"  # 主题更近但被改写的帖子让位


def test_recall_empty_library(tmp_path):
    assert _mem(tmp_path).recall("任何主题", k=3) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_memory_l3.py -v`
Expected: FAIL（`worker.llm` 与 `worker.memory.l3` 尚不存在——本任务一并创建）

- [ ] **Step 3: 实现 l3.py（并前置创建 llm/client.py 的 StubEmbedder 部分）**

`worker/worker/llm/__init__.py`（空）、`worker/worker/llm/client.py`：

```python
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
```

`worker/worker/memory/l3.py`：

```python
"""L3 全局记忆：历史帖向量库。写作前召回风格样例，发布后写回；被改写的帖子降权。"""
import sqlite3
from typing import Any

import sqlite_vec


class GlobalMemory:
    def __init__(self, con: sqlite3.Connection, embedder: Any, dims: int = 8) -> None:
        self._con = con
        self._embedder = embedder
        self._dims = dims
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        con.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS post_vec USING vec0("
            f"post_id INTEGER PRIMARY KEY, embedding float[{dims}])"
        )
        con.commit()

    def add(self, text: str, platform: str, title: str, body: str, edited: bool) -> int:
        cur = self._con.execute(
            "INSERT INTO post_archive(platform, title, body, edited_by_user) VALUES(?, ?, ?, ?)",
            (platform, title, body, int(edited)),
        )
        post_id = cur.lastrowid
        (vec,) = self._embedder.embed([text])
        self._con.execute(
            "INSERT INTO post_vec(post_id, embedding) VALUES(?, ?)",
            (post_id, sqlite_vec.serialize_float(vec)),
        )
        self._con.commit()
        return post_id

    def recall(self, text: str, k: int = 3) -> list[dict[str, Any]]:
        (query,) = self._embedder.embed([text])
        rows = self._con.execute(
            "SELECT post_id, distance FROM post_vec WHERE embedding MATCH ? AND k = ?",
            (sqlite_vec.serialize_float(query), k * 2),
        ).fetchall()
        posts = {
            pid: {"platform": platform, "title": title, "body": body, "edited": bool(edited)}
            for pid, platform, title, body, edited in self._con.execute(
                "SELECT post_id, platform, title, body, edited_by_user FROM post_archive"
            )
        }
        ranked = sorted(
            ((posts[pid], dist) for pid, dist in rows),
            key=lambda item: (item[0]["edited"], item[1]),  # 未改写优先，其次距离
        )
        return [dict(p, distance=dist) for p, dist in ranked[:k]]
```

- [ ] **Step 4: 运行确认通过**

Run: `cd worker && uv run pytest tests/test_memory_l3.py -v`
Expected: `3 passed`（若依赖下载失败：`uv add sqlite-vec` 后重跑）

- [ ] **Step 5: Commit**

```bash
git add worker/worker/llm/ worker/worker/memory/l3.py worker/tests/test_memory_l3.py
git commit -m "feat(worker): L3 向量记忆（召回/写回/改写降权）与 LLM 桩"
```

---

### Task 8: L1 工作记忆

**Files:**
- Create: `worker/worker/memory/l1.py`
- Test: 追加到 `worker/tests/test_memory_l2.py`（同属记忆层，避免新建碎片文件）

- [ ] **Step 1: 追加失败测试**

```python
def test_run_context_archive():
    from worker.memory.l1 import RunContext

    ctx = RunContext(run_id=42)
    ctx.topic = "AI Agent 一周动态"
    ctx.draft_id = "d42"
    ctx.recalled = [{"title": "历史帖"}]
    archived = ctx.archive()
    assert archived == {
        "run_id": 42,
        "topic": "AI Agent 一周动态",
        "draft_id": "d42",
        "recalled": [{"title": "历史帖"}],
    }
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_memory_l2.py::test_run_context_archive -v`
Expected: FAIL（`worker.memory.l1` 不存在）

- [ ] **Step 3: 实现 l1.py**

```python
"""L1 工作记忆：单次流水线运行上下文，运行结束归档。"""
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RunContext:
    run_id: int
    topic: str | None = None
    draft_id: str | None = None
    recalled: list[dict[str, Any]] = field(default_factory=list)
    archived: dict[str, Any] | None = None

    def archive(self) -> dict[str, Any]:
        self.archived = asdict(self)
        self.archived.pop("archived", None)
        return self.archived
```

- [ ] **Step 4: 运行确认通过**

Run: `cd worker && uv run pytest tests/test_memory_l2.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add worker/worker/memory/l1.py worker/tests/test_memory_l2.py
git commit -m "feat(worker): L1 工作记忆 RunContext"
```

---

### Task 9: 流水线编排（调研→召回→写作→配图→待审）

**Files:**
- Create: `worker/worker/pipeline.py`
- Test: `worker/tests/test_pipeline.py`

- [ ] **Step 1: 写失败测试**

```python
import json

from worker.adapters.base import AdapterRegistry
from worker.adapters.demo import DemoAdapter
from worker.llm.client import StubEmbedder, StubLLM
from worker.memory.store import connect
from worker.pipeline import Pipeline


def make_pipeline(tmp_path, db="a.db"):
    con = connect(tmp_path / db)
    registry = AdapterRegistry()
    registry.register(DemoAdapter(out_file=tmp_path / "demo_published.json"))
    return Pipeline(
        registry=registry,
        llm=StubLLM(),
        embedder=StubEmbedder(),
        con=con,
        agent_id="tech-笔记官",
    )


def test_run_produces_pending_review_draft(tmp_path):
    pipe = make_pipeline(tmp_path)
    draft = pipe.run(platform_id="demo")

    assert draft.status == "pending_review"
    assert draft.platform == "demo"
    assert draft.title == "AI Agent 一周动态"  # 热度最高选题
    assert draft.post.title.startswith("[demo]")  # compose_post 已套用平台规范
    assert draft.images  # 配图占位存在
    assert "StubLLM" in draft.body  # 写作经 LLM 桩
    assert draft.draft_id in pipe.drafts


def test_run_second_time_recalls_history_into_draft(tmp_path):
    pipe = make_pipeline(tmp_path)
    first = pipe.run(platform_id="demo")
    pipe.approve(first.draft_id)  # 发布后写回 L3

    second = pipe.run(platform_id="demo")
    # 第二次运行召回列表应包含第一篇（风格样例注入写作）
    assert any(first.title == r["title"] for r in pipe.last_context.recalled)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_pipeline.py -v`
Expected: FAIL（`worker.pipeline` 不存在）

- [ ] **Step 3: 实现 pipeline.py（run 部分 + 草稿持久化 + 事件钩子）**

```python
"""Agent 流水线：调研 → L3 召回 → 写作 → 配图 → compose → 待审；审核后发布并写回 L3。"""
import json
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .adapters.base import AdapterRegistry, PlatformPost, PublishResult
from .llm.client import Embedder, LLMClient
from .memory.l1 import RunContext
from .memory.l2 import AgentMemory
from .memory.l3 import GlobalMemory

WRITER_SYSTEM = """你是一位图文创作者。参考以下本人历史帖的风格：
{style_block}
遵守以下偏好约束：
{prefs_block}
以自然、克制的口吻写作。"""


class Stage(str, Enum):
    RESEARCH = "research"
    WRITE = "write"
    IMAGE = "image"
    REVIEW = "review"
    PUBLISHED = "published"


@dataclass
class Draft:
    draft_id: str
    platform: str
    title: str
    body: str
    images: list[str] = field(default_factory=list)
    post: PlatformPost | None = None
    status: str = "pending_review"  # pending_review / published / rejected


class Pipeline:
    def __init__(
        self,
        registry: AdapterRegistry,
        llm: LLMClient,
        embedder: Embedder,
        con: sqlite3.Connection,
        agent_id: str = "default",
    ) -> None:
        self.registry = registry
        self.llm = llm
        self.agent = AgentMemory(con, agent_id)
        self.global_mem = GlobalMemory(con, embedder)
        self._con = con
        self._run_no = self._count_runs()
        self.drafts: dict[str, Draft] = {}
        self.last_context: RunContext | None = None
        self._load_drafts()

    # ---- 运行 ----

    def run(self, platform_id: str) -> Draft:
        self._run_no += 1
        ctx = RunContext(run_id=self._run_no)
        adapter = self.registry.get(platform_id)

        trends = adapter.fetch_trends()  # ① 调研
        topic = max(trends, key=lambda t: t.heat).title
        ctx.topic = topic

        ctx.recalled = self.global_mem.recall(topic, k=3)  # ② 写作前召回（风格样例）
        style_block = "\n".join(f"- {r['title']}" for r in ctx.recalled) or "（暂无历史帖）"
        prefs_block = json.dumps(self.agent.get_prefs(), ensure_ascii=False)
        body = self.llm.complete(WRITER_SYSTEM.format(style_block=style_block, prefs_block=prefs_block), topic)

        images = [f"cover-stub:{topic[:12]}"]  # ③ 配图占位（真实文生图在计划 2）
        post = adapter.compose_post(topic, body, images)  # ④ 平台规范适配
        draft = Draft(
            draft_id=f"d{self._run_no}",
            platform=platform_id,
            title=topic,
            body=body,
            images=images,
            post=post,
            status="pending_review",
        )
        self.drafts[draft.draft_id] = draft
        self._save_draft(draft)

        ctx.draft_id = draft.draft_id
        self.last_context = ctx
        ctx.archive()  # L1 归档
        return draft

    # ---- 持久化 ----

    def _count_runs(self) -> int:
        (n,) = self._con.execute("SELECT COUNT(*) FROM draft").fetchone()
        return n

    def _save_draft(self, draft: Draft) -> None:
        self._con.execute(
            "INSERT INTO draft(draft_id, platform, title, body, images_json, status) VALUES(?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(draft_id) DO UPDATE SET title=excluded.title, body=excluded.body, "
            "images_json=excluded.images_json, status=excluded.status",
            (
                draft.draft_id,
                draft.platform,
                draft.title,
                draft.body,
                json.dumps(draft.images, ensure_ascii=False),
                draft.status,
            ),
        )
        self._con.commit()

    def _load_drafts(self) -> None:
        for row in self._con.execute("SELECT draft_id, platform, title, body, images_json, status FROM draft"):
            draft_id, platform, title, body, images_json, status = row
            self.drafts[draft_id] = Draft(
                draft_id=draft_id, platform=platform, title=title, body=body,
                images=json.loads(images_json), status=status,
            )
```

- [ ] **Step 4: 运行确认通过（第二项测试会因 approve 未实现而失败——本任务先让第一项通过）**

Run: `cd worker && uv run pytest tests/test_pipeline.py::test_run_produces_pending_review_draft -v`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add worker/worker/pipeline.py worker/tests/test_pipeline.py
git commit -m "feat(worker): 流水线 run——调研/召回/写作/配图/待审与草稿持久化"
```

---

### Task 10: 审核动作（approve / edited 降权 / reject）+ CLI 冒烟

**Files:**
- Modify: `worker/worker/pipeline.py`（追加 approve / reject）
- Create: `worker/worker/cli.py`、`worker/worker/__main__.py`
- Test: `worker/tests/test_pipeline.py`（追加）、Create: `worker/tests/test_cli_smoke.py`

- [ ] **Step 1: 追加失败测试**

`tests/test_pipeline.py` 追加：

```python
def test_approve_publishes_and_writes_back_l3(tmp_path):
    pipe = make_pipeline(tmp_path)
    draft = pipe.run(platform_id="demo")
    result = pipe.approve(draft.draft_id)

    assert result.success
    assert pipe.drafts[draft.draft_id].status == "published"
    published = json.loads((tmp_path / "demo_published.json").read_text(encoding="utf-8"))
    assert published[0]["title"].startswith("[demo]")
    # L3 写回：库中已能召回这篇
    hits = pipe.global_mem.recall(draft.title, k=1)
    assert hits and hits[0]["edited"] is False


def test_approve_with_edits_marks_edited_and_deprioritized(tmp_path):
    pipe = make_pipeline(tmp_path)
    d1 = pipe.run(platform_id="demo")
    pipe.approve(d1.draft_id)  # 未改写，正常入库

    d2 = pipe.run(platform_id="demo")
    result = pipe.approve(d2.draft_id, edited_body="用户全面改写的正文")
    assert result.success

    # 两篇主题相同（确定性选题）；召回时未改写的 d1 排在改写的 d2 之前
    hits = pipe.global_mem.recall(d2.title, k=2)
    assert len(hits) == 2
    assert hits[0]["edited"] is False and hits[1]["edited"] is True


def test_reject_records_reason_to_l2(tmp_path):
    pipe = make_pipeline(tmp_path)
    draft = pipe.run(platform_id="demo")
    pipe.reject(draft.draft_id, reason="标题太标题党")

    assert pipe.drafts[draft.draft_id].status == "rejected"
    assert pipe.agent.get_prefs()["rejections"] == ["标题太标题党"]
```

`tests/test_cli_smoke.py`：

```python
def test_cli_run_and_approve_roundtrip(tmp_path, monkeypatch, capsys):
    from worker import cli

    monkeypatch.chdir(tmp_path)
    cli.main(["run", "demo"])
    out1 = capsys.readouterr().out
    assert "pending_review" in out1
    assert "AI Agent 一周动态" in out1

    draft_id = out1.split("draft_id=")[1].split()[0]
    cli.main(["approve", draft_id])
    out2 = capsys.readouterr().out
    assert "published" in out2
    assert (tmp_path / "demo_published.json").exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_pipeline.py tests/test_cli_smoke.py -v`
Expected: FAIL（`Pipeline.approve` / `worker.cli` 不存在）

- [ ] **Step 3: 实现 approve / reject / cli**

`pipeline.py` 追加（类内）：

```python
    # ---- 审核动作（人机边界：compose 之后、publish 之前）----

    def approve(self, draft_id: str, edited_title: str | None = None, edited_body: str | None = None) -> PublishResult:
        draft = self.drafts[draft_id]
        if draft.status != "pending_review":
            raise ValueError(f"draft {draft_id} 状态为 {draft.status}，不能发布")

        edited = edited_title is not None or edited_body is not None
        title = edited_title or draft.title
        body = edited_body or draft.body
        adapter = self.registry.get(draft.platform)
        if edited or draft.post is None:
            # 改写后需重新适配平台规范；跨进程加载的草稿 post 为 None（_load_drafts 不持久化
            # PlatformPost），发布前必须重建——tags 本就是 compose 时平台侧生成的
            draft.post = adapter.compose_post(title, body, draft.images)

        result = adapter.execute_publish(draft.post)
        if result.success:
            draft.status = "published"
            self._save_draft(draft)
            self.global_mem.add(  # L3 写回；被改写的帖子 edited=True → 召回降权
                text=f"{title}\n{body}", platform=draft.platform, title=title, body=body, edited=edited
            )
        return result

    def reject(self, draft_id: str, reason: str) -> None:
        draft = self.drafts[draft_id]
        if draft.status != "pending_review":
            raise ValueError(f"draft {draft_id} 状态为 {draft.status}，不能驳回")
        draft.status = "rejected"
        self._save_draft(draft)
        self.agent.record_rejection(reason)  # 驳回理由沉淀为 L2 偏好
```

`worker/worker/cli.py`：

```python
"""CLI 入口：无 Electron 独立运行（python -m worker ...）。"""
import argparse

from .adapters.base import load_adapters
from .llm.client import StubEmbedder, StubLLM
from .memory.store import connect
from .pipeline import Pipeline


def _pipeline(db: str) -> Pipeline:
    return Pipeline(
        registry=load_adapters(),
        llm=StubLLM(),
        embedder=StubEmbedder(),
        con=connect(db),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="worker", description="AI 社媒自动化 Worker（CLI 模式）")
    parser.add_argument("--db", default="agent.db", help="SQLite 数据库路径")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("adapters", help="列出已注册适配器")
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

    pipe = _pipeline(args.db)
    if args.cmd == "run":
        draft = pipe.run(platform_id=args.platform)
        print(f"draft_id={draft.draft_id} status={draft.status} platform={draft.platform}")
        print(f"title={draft.title}")
    elif args.cmd == "approve":
        result = pipe.approve(args.draft_id, edited_title=args.title, edited_body=args.body)
        print(f"status=published success={result.success} url={result.post_url} error={result.error}")
    elif args.cmd == "reject":
        pipe.reject(args.draft_id, reason=args.reason)
        print("status=rejected")
```

`worker/worker/__main__.py`：

```python
from .cli import main

main()
```

- [ ] **Step 4: 运行全部测试**

Run: `cd worker && uv run pytest -v`
Expected: 全部通过（test_pipeline 4 项 + test_cli_smoke 1 项 + 此前所有）

- [ ] **Step 5: Commit**

```bash
git add worker/worker/pipeline.py worker/worker/cli.py worker/worker/__main__.py worker/tests/
git commit -m "feat(worker): 审核动作（发布写回 L3/改写降权/驳回沉淀 L2）与 CLI"
```

---

## 计划 1 完成标准

- `cd worker && uv run pytest -v` 全绿
- `uv run python -m worker adapters` 列出 demo；`run demo` → `approve <id>` 全链路可跑
- 适配器契约（四方法 + platform_id）被注册表强制校验
- L3 召回发生在写作前；发布后写回；改写帖降权——三条规格行为均有测试锚定

## 后续计划（本计划完成后制定）

- **计划 2**：真实适配器（xiaohongshu / bilibili_column，Playwright + Cookie 会话 + 错误分类）与真实 LLM/文生图/embedding API 客户端
- **计划 3**：Electron 主进程（Worker 守护 + IPC 路由）与 React UI（仪表盘/主题系统/轨道时钟/草稿箱）

### 计划 2 前置决策（Task 5 质量审查实证踩实，届时遵循）

1. **单文件适配器布局**：`adapters/xiaohongshu.py` 而非目录式——`pkgutil.iter_modules` 不递归子包；若确需目录式，扫描器改 `walk_packages`
2. **共享 Playwright 公共基类**：放独立模块且不声明 `platform_id`（计划 1 的扫描器只收声明了 id 的终端适配器）
3. **配置注入**：真实适配器需要 Cookie/浏览器配置——扩展 `load_adapters(package, builder=lambda cls: cls())` 或约定 `from_config` 类方法（向后兼容，计划 1 的 `package: str` 参数已验证此类缝好用）
4. **单模块 import 失败语义**：当前 fail-fast（炸全部）。计划 2 需决策：per-module try/except + warning，或文档明确 fail-fast（playwright 未装不应瘫痪 demo）
5. **适配器文档义务**：适配器必须可无参构造（或提供 builder 注入路径），配置延迟初始化
6. **错误码契约提醒**（Task 2 审查）：Electron 端 RPC 客户端沿用「error 为字符串」约定，不引入 `{code, message}` 结构
7. **rejections 增长上限**（Task 6 审查）：L2 的 rejections 列表无界增长，接入真实 LLM 后会随驳回次数线性膨胀 system prompt——需要截断/摘要/上限机制（如只保留最近 N 条 + 汇总旧理由）
8. **draft 表补 created_at**（Task 6 审查，Task 9 顺手做）：草稿箱 UI 要显示生成时间，趁无真实数据在 SCHEMA 的 draft 表加 `created_at TEXT NOT NULL DEFAULT (datetime('now'))`
