# 计划 3：桌面端 — Electron 主进程与 React UI 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可运行的桌面应用：Electron 主进程守护 Python Worker（WebSocket JSON-RPC 桥接 + 广播转发），React UI 呈现可视化定稿的卡片网格仪表盘（frost 主题/五变量换肤/动态光晕底图/顶栏迷你轨道时钟）与草稿审核箱。

**Architecture:** Worker 侧新增 `service.py`（把 Pipeline/registry/config 接成 RPC 方法，阻塞调用经 run_in_executor 卸载）与 `serve` 子命令；Electron main 负责 spawn worker、空闲端口分配、JSON-RPC 客户端（correlation id + notification 转发，决策 #14）；UI 经 preload bridge（开发态直连 WebSocket）消费同一协议。npm workspaces 组织 `apps/ui`（Vite+React+vitest/jsdom）与 `apps/desktop`（Electron+vitest/node）。

**Tech Stack:** TypeScript · React 18 · Vite · vitest · Electron · ws（Node 侧）/ websockets（Python 侧）· @fontsource/noto-serif-sc

**依据规格:** [技术文档](../specs/2026-10-20-ai-social-media-agent-tool-tech.md) §1/§5 + [产品文档](../specs/2026-10-20-ai-social-media-agent-tool-product.md) §3 + [计划 1/2 决策](2026-10-20-plan1-python-worker-foundation.md)（消化 #11/#14/#15）

**基线:** master 含计划 1/2（worker 96 tests）

---

## 文件结构（本计划创建/修改）

```
根 package.json + npm workspaces
worker/
├─ worker/service.py                # 新：RPC 方法层（阻塞卸载 + 广播）
├─ worker/rpc/server.py             # 改：serve_forever()
├─ worker/cli.py                    # 改：serve 子命令
└─ tests/test_service.py            # 新：真实 WS 客户端打全链路
apps/ui/                            # Vite + React + TS + vitest(jsdom)
├─ package.json / vite.config.ts / tsconfig.json / index.html
├─ src/
│  ├─ main.tsx / App.tsx            # 壳：顶栏 + 页面切换
│  ├─ theme/{tokens.css, ThemeProvider.tsx, ThemeChips.tsx}
│  ├─ components/{BackgroundLayer.tsx, MiniClock.tsx, Card.tsx}
│  ├─ cards/{Dashboard.tsx}         # 六卡片 + 数据 hooks
│  ├─ pages/{DraftsPage.tsx}        # 草稿审核箱
│  └─ worker/{WorkerProvider.tsx, api.ts}
└─ src/**/*.test.tsx
apps/desktop/                       # Electron + vitest(node)
├─ package.json / tsconfig.json / electron-builder.yml
├─ src/main.ts                      # 窗口/生命周期/装配
├─ src/workerClient.ts              # JSON-RPC 客户端（决策 #14）
├─ src/spawnWorker.ts               # uv spawn + 空闲端口
├─ src/preload.ts                   # contextBridge
└─ src/*.test.ts
```

---

### Task 1: Worker service 层与 serve 子命令

**Files:**
- Create: `worker/worker/service.py`
- Modify: `worker/worker/rpc/server.py`（追加 `serve_forever`）
- Modify: `worker/worker/cli.py`（serve 子命令）
- Test: `worker/tests/test_service.py`

- [ ] **Step 1: 写失败测试**

```python
import asyncio
import json

import websockets

from worker.adapters.base import AdapterRegistry
from worker.adapters.demo import DemoAdapter
from worker.llm.client import StubEmbedder, StubLLM
from worker.memory.store import connect
from worker.pipeline import Pipeline
from worker.rpc.server import RpcServer
from worker.service import build_service


def make_service(tmp_path) -> RpcServer:
    con = connect(tmp_path / "a.db")
    registry = AdapterRegistry()
    registry.register(DemoAdapter(out_file=tmp_path / "demo_published.json"))
    pipeline = Pipeline(registry=registry, llm=StubLLM(), embedder=StubEmbedder(),
                        con=con, agent_id="ui")
    return build_service(registry=registry, pipeline=pipeline, real_mode=False)


async def _call(ws, method, params=None):
    await ws.send(json.dumps({"jsonrpc": "2.0", "id": method, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == method:          # 跳过广播通知（决策 #14 同款过滤）
            return msg


async def test_service_roundtrip(tmp_path):
    server = make_service(tmp_path)
    async with server.start():
        async with websockets.connect(server.url) as ws:
            adapters = (await _call(ws, "adapters"))["result"]
            assert adapters == [{"platform_id": "demo", "display_name": "本地演示平台"}]

            health = (await _call(ws, "health", {"platform": "demo"}))["result"]
            assert health["status"] == "ok"

            stats = (await _call(ws, "memory_stats"))["result"]
            assert stats == {"l2_prefs": 0, "l3_posts": 0}

            cfg = (await _call(ws, "config_status"))["result"]
            assert cfg == {"real_llm": False, "has_image": False, "has_embedding": False}

            draft = (await _call(ws, "run", {"platform": "demo"}))["result"]
            assert draft["status"] == "pending_review"

            drafts = (await _call(ws, "drafts"))["result"]
            assert len(drafts) == 1 and drafts[0]["draft_id"] == draft["draft_id"]
            assert drafts[0]["created_at"]                    # 决策 #8 的列现在被消费
            assert "images" in drafts[0] and "body" in drafts[0]

            approved = (await _call(ws, "approve", {"draft_id": draft["draft_id"]}))["result"]
            assert approved["success"] is True

            d2 = (await _call(ws, "run", {"platform": "demo"}))["result"]
            await _call(ws, "reject", {"draft_id": d2["draft_id"], "reason": "测试驳回"})
            drafts2 = (await _call(ws, "drafts"))["result"]
            by_id = {d["draft_id"]: d for d in drafts2}
            assert by_id[draft["draft_id"]]["status"] == "published"
            assert by_id[d2["draft_id"]]["status"] == "rejected"


async def test_service_broadcasts_on_run(tmp_path):
    server = make_service(tmp_path)
    events = []
    async with server.start():
        async with websockets.connect(server.url) as ws:
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "run", "params": {"platform": "demo"}}))
            while True:
                msg = json.loads(await ws.recv())
                if "method" in msg:                          # 通知帧
                    events.append(msg["method"])
                    if msg["method"] == "drafts_changed":
                        break
                elif msg.get("id") == 1:
                    continue
    assert "stage_changed" in events and "drafts_changed" in events
```

- [ ] **Step 2: 运行确认失败**

Run: `cd worker && uv run pytest tests/test_service.py -v`
Expected: FAIL（`worker.service` 不存在）

- [ ] **Step 3: 实现**

`worker/worker/rpc/server.py` 类内追加：

```python
    async def serve_forever(self) -> None:
        """启动并阻塞（Ctrl-C 退出）——供 CLI serve / Electron 守护使用。"""
        async with self.start():
            await asyncio.Future()
```

`worker/worker/service.py`：

```python
"""RPC 服务层：把 registry / pipeline 接成 JSON-RPC 方法。阻塞调用经执行器卸载，不卡事件循环。"""
import asyncio
import sqlite3

from .rpc.server import RpcServer


def _draft_row(row) -> dict:
    import json as _json

    draft_id, platform, title, body, images_json, status, created_at = row
    return {
        "draft_id": draft_id, "platform": platform, "title": title, "body": body,
        "images": _json.loads(images_json), "status": status, "created_at": created_at,
    }


def build_service(registry, pipeline, real_mode: bool, has_image: bool = False,
                  has_embedding: bool = False) -> RpcServer:
    server = RpcServer()

    async def _run(fn, *args):
        # Playwright/LLM 都是阻塞调用——在协程内取运行环卸载到执行器（3.12 禁在无运行环处 get_event_loop）
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)

    @server.method("adapters")
    async def adapters(params):
        return [{"platform_id": pid, "display_name": a.display_name} for pid, a in registry.all().items()]

    @server.method("health")
    async def health(params):
        report = await _run(registry.get(params["platform"]).check_health)
        return {"status": report.status.value, "detail": report.detail}

    @server.method("run")
    async def run(params):
        await server.broadcast("stage_changed", {"stage": "research", "platform": params["platform"]})
        draft = await _run(pipeline.run, params["platform"])
        await server.broadcast("drafts_changed", {"draft_id": draft.draft_id})
        return {"draft_id": draft.draft_id, "platform": draft.platform,
                "title": draft.title, "body": draft.body,
                "images": draft.images, "status": draft.status}

    @server.method("drafts")
    async def drafts(params):
        rows = pipeline._con.execute(
            "SELECT draft_id, platform, title, body, images_json, status, created_at FROM draft "
            "ORDER BY created_at DESC"
        ).fetchall()
        return [_draft_row(r) for r in rows]

    @server.method("approve")
    async def approve(params):
        result = await _run(
            pipeline.approve, params["draft_id"],
            params.get("title"), params.get("body"),
        )
        await server.broadcast("drafts_changed", {"draft_id": params["draft_id"]})
        return {"success": result.success, "post_url": result.post_url,
                "error": result.error.value if result.error else None, "detail": result.detail}

    @server.method("reject")
    async def reject(params):
        await _run(pipeline.reject, params["draft_id"], params["reason"])
        await server.broadcast("drafts_changed", {"draft_id": params["draft_id"]})
        return {}

    @server.method("memory_stats")
    async def memory_stats(params):
        con: sqlite3.Connection = pipeline._con
        (l2,) = con.execute("SELECT COUNT(*) FROM agent_pref").fetchone()
        (l3,) = con.execute("SELECT COUNT(*) FROM post_archive").fetchone()
        return {"l2_prefs": l2, "l3_posts": l3}

    @server.method("config_status")
    async def config_status(params):
        return {"real_llm": real_mode, "has_image": has_image, "has_embedding": has_embedding}

    return server
```

`worker/worker/cli.py`——顶部 `import asyncio`；子命令注册追加：

```python
    serve_p = sub.add_parser("serve", help="启动 RPC 服务（Electron 桌面端用）")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8765)
```

主流程 `pipe = _pipeline(...)` 之前插入：

```python
    if args.cmd == "serve":
        pipe = _pipeline(args.db, args.config)
        cfg = _load_config_if_any(args.config)
        server = build_service(
            registry=pipe.registry, pipeline=pipe,
            real_mode=bool(cfg and cfg.llm),
            has_image=bool(cfg and cfg.image),
            has_embedding=bool(cfg and cfg.embedding),
        )
        server.host, server.port = args.host, args.port
        print(f"worker serving on {server.url}", flush=True)
        try:
            asyncio.run(server.serve_forever())
        except KeyboardInterrupt:
            pass
        return
```

（`from .service import build_service` 加入顶部导入。注意 `build_service` 里 `asyncio.get_event_loop()` 在 `asyncio.run` 之后的协程内首次取环——Python 3.12 在协程内 get_event_loop 会返回运行环，安全。）

- [ ] **Step 4: 运行确认通过（全量回归）**

Run: `cd worker && uv run pytest -v`
Expected: 全绿（96 + 2 = 98 passed）

- [ ] **Step 5: 冒烟**

Run: `cd worker && timeout 3 uv run python -m worker serve --port 0 || true`（端口 0 会随机分配；预期打印 `worker serving on ws://127.0.0.1:<随机>` 后被 timeout 结束）

- [ ] **Step 6: Commit**

```bash
git add worker/worker/service.py worker/worker/rpc/server.py worker/worker/cli.py worker/tests/test_service.py
git commit -m "feat(worker): RPC service 层与 serve 子命令（阻塞卸载+广播）"
```

---

### Task 2: 根 workspaces 与 UI 脚手架

**Files:**
- Create: 根 `package.json`、`apps/ui/package.json`、`apps/ui/vite.config.ts`、`apps/ui/tsconfig.json`、`apps/ui/index.html`、`apps/ui/src/main.tsx`、`apps/ui/src/App.tsx`
- Test: `apps/ui/src/App.test.tsx`

- [ ] **Step 1: 根 package.json**

```json
{
  "name": "ai-auto-media-pusher",
  "private": true,
  "workspaces": ["apps/*"],
  "scripts": {
    "dev:ui": "npm run dev -w apps/ui",
    "build:ui": "npm run build -w apps/ui",
    "test": "npm test --workspaces --if-present",
    "dev:desktop": "npm run dev -w apps/desktop",
    "start": "npm run start -w apps/desktop"
  }
}
```

- [ ] **Step 2: apps/ui 脚手架**

`apps/ui/package.json`：

```json
{
  "name": "@app/ui",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@testing-library/react": "^16.0.0",
    "@testing-library/jest-dom": "^6.5.0",
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^25.0.0",
    "typescript": "^5.5.4",
    "vite": "^5.4.3",
    "vitest": "^2.0.5"
  }
}
```

`apps/ui/vite.config.ts`：

```typescript
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  base: "./",                       // Electron file:// 加载需要相对 base
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
```

`apps/ui/tsconfig.json`：

```json
{
  "compilerOptions": {
    "target": "ES2022", "lib": ["ES2022", "DOM", "DOM.Iterable"], "module": "ESNext",
    "moduleResolution": "bundler", "jsx": "react-jsx", "strict": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"],
    "skipLibCheck": true, "noEmit": true
  },
  "include": ["src"]
}
```

`apps/ui/index.html`：

```html
<!doctype html>
<html lang="zh-CN">
  <head><meta charset="UTF-8" /><title>AGENT://控制中心</title></head>
  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
</html>
```

`apps/ui/src/main.tsx`：

```tsx
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./theme/tokens.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

（Task 2 先建占位 `src/theme/tokens.css`（空文件）与 `src/test-setup.ts`：`import "@testing-library/jest-dom";`。）

`apps/ui/src/App.tsx`（占位，Task 10 充实）：

```tsx
export default function App() {
  return <div className="app-root">AGENT://控制中心</div>;
}
```

`apps/ui/src/App.test.tsx`：

```tsx
import { render, screen } from "@testing-library/react";
import App from "./App";

test("app renders shell", () => {
  render(<App />);
  expect(screen.getByText("AGENT://控制中心")).toBeInTheDocument();
});
```

- [ ] **Step 3: 安装并运行**

```bash
npm install
npm test -w apps/ui
```
Expected: `1 passed`

- [ ] **Step 4: Commit**

```bash
git add package.json package-lock.json apps/ui/
git commit -m "feat(ui): workspaces 与 Vite+React 脚手架"
```

---

### Task 3: Electron 主进程骨架（spawn + 客户端 + preload）

**Files:**
- Create: `apps/desktop/package.json`、`apps/desktop/tsconfig.json`、`apps/desktop/src/main.ts`、`src/workerClient.ts`、`src/spawnWorker.ts`、`src/preload.ts`
- Test: `apps/desktop/src/workerClient.test.ts`、`src/spawnWorker.test.ts`

- [ ] **Step 1: 脚手架**

`apps/desktop/package.json`：

```json
{
  "name": "@app/desktop",
  "private": true,
  "main": "dist/main.js",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "start": "npm run build && electron .",
    "dev": "npm run build && cross-env VITE_DEV=1 electron .",
    "test": "vitest run"
  },
  "devDependencies": {
    "@types/node": "^22.5.0",
    "@types/ws": "^8.5.12",
    "cross-env": "^7.0.3",
    "electron": "^32.0.0",
    "typescript": "^5.5.4",
    "vitest": "^2.0.5",
    "ws": "^8.18.0"
  }
}
```

`apps/desktop/tsconfig.json`：

```json
{
  "compilerOptions": {
    "target": "ES2022", "module": "CommonJS", "moduleResolution": "node",
    "outDir": "dist", "rootDir": "src", "strict": true, "skipLibCheck": true,
    "types": ["node", "vitest/globals"]
  },
  "include": ["src"]
}
```

（根 `apps/ui/vite.config.ts` 的 test 配置只在 ui；desktop 的 vitest 用默认 node 环境——`apps/desktop/vitest.config.ts`：）

```typescript
import { defineConfig } from "vitest/config";
export default defineConfig({ test: { globals: true, environment: "node" } });
```

- [ ] **Step 2: 写失败测试**

`apps/desktop/src/workerClient.test.ts`：

```typescript
import { WebSocketServer } from "ws";
import { afterAll, beforeAll, test, expect } from "vitest";
import { WorkerClient } from "./workerClient";

let wss: WebSocketServer;
let received: any[] = [];
beforeAll((done) => {
  wss = new WebSocketServer({ port: 0 }, () => done());
  wss.on("connection", (ws) => {
    ws.on("message", (raw) => {
      const msg = JSON.parse(String(raw));
      received.push(msg);
      if (msg.id === "echo") {
        ws.send(JSON.stringify({ jsonrpc: "2.0", id: "echo", result: { pong: msg.params.v } }));
      }
      if (msg.id === "boom") {
        ws.send(JSON.stringify({ jsonrpc: "2.0", id: "boom", error: "炸了" }));
      }
    });
    // 模拟 worker 广播（通知帧无 id）
    ws.send(JSON.stringify({ jsonrpc: "2.0", method: "drafts_changed", params: { draft_id: "d1" } }));
  });
});
afterAll(() => wss.close());

test("request/response with correlation + notification passthrough (决策 #14)", async () => {
  const port = (wss.address() as any).port;
  const events: string[] = [];
  const client = new WorkerClient(`ws://127.0.0.1:${port}`);
  await client.connect();
  client.onNotification((method, params) => events.push(method));

  expect(await client.request("echo", { v: 7 })).toEqual({ pong: 7 });

  await expect(client.request("boom")).rejects.toThrow("炸了");

  await new Promise((r) => setTimeout(r, 50));   // 等通知到达
  expect(events).toContain("drafts_changed");
  client.close();
  expect(received[0]).toMatchObject({ method: "echo", params: { v: 7 } });
});
```

`apps/desktop/src/spawnWorker.test.ts`：

```typescript
import { test, expect } from "vitest";
import path from "path";
import { buildWorkerCommand } from "./spawnWorker";

test("spawns uv with serve and resolved worker dir", () => {
  const spec = buildWorkerCommand({ repoRoot: "R:/repo", port: 12345 });
  expect(spec.command).toBe("uv");
  expect(spec.args).toEqual([
    "run", "python", "-m", "worker", "serve", "--port", "12345",
  ]);
  expect(spec.cwd).toBe(path.join("R:/repo", "worker"));   // Windows 下为反斜杠，用 path.join 断言
});
```

- [ ] **Step 3: 运行确认失败**

```bash
npm test -w apps/desktop
```
Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现**

`apps/desktop/src/workerClient.ts`：

```typescript
import WebSocket from "ws";

type NotificationHandler = (method: string, params: any) => void;

/** JSON-RPC 客户端：correlation id 匹配响应；无 id 的帧是广播通知（决策 #14：先判 method 再解析）。 */
export class WorkerClient {
  private ws!: WebSocket;
  private nextId = 1;
  private pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void }>();
  private handlers: NotificationHandler[] = [];

  constructor(private url: string, private timeoutMs = 300000) {}   // Playwright 发布慢，超时放宽

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.url);
      this.ws.on("open", () => resolve());
      this.ws.on("error", reject);
      this.ws.on("message", (raw) => this.dispatch(JSON.parse(String(raw))));
    });
  }

  private dispatch(msg: any) {
    if (msg.method !== undefined && msg.id === undefined) {
      for (const h of this.handlers) h(msg.method, msg.params ?? {});
      return;                       // 通知帧不进 pending
    }
    const entry = this.pending.get(msg.id);
    if (!entry) return;
    this.pending.delete(msg.id);
    if (msg.error !== undefined && msg.error !== null) entry.reject(new Error(String(msg.error)));
    else entry.resolve(msg.result);
  }

  request<T = any>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`请求超时: ${method}`));
      }, this.timeoutMs);
      this.pending.set(id, {
        resolve: (v) => { clearTimeout(timer); resolve(v); },
        reject: (e) => { clearTimeout(timer); reject(e); },
      });
      this.ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    });
  }

  onNotification(h: NotificationHandler) {
    this.handlers.push(h);
  }

  close() {
    this.ws?.close();
  }
}
```

`apps/desktop/src/spawnWorker.ts`：

```typescript
import { spawn, ChildProcess } from "child_process";
import net from "net";
import path from "path";

export function buildWorkerCommand(opts: { repoRoot: string; port: number }) {
  return {
    command: "uv",
    args: ["run", "python", "-m", "worker", "serve", "--port", String(opts.port)],
    cwd: path.join(opts.repoRoot, "worker"),
  };
}

export async function findFreePort(): Promise<number> {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.listen(0, "127.0.0.1", () => {
      const port = (srv.address() as net.AddressInfo).port;
      srv.close(() => resolve(port));
    });
  });
}

export function spawnWorker(opts: { repoRoot: string; port: number }): ChildProcess {
  const spec = buildWorkerCommand(opts);
  const child = spawn(spec.command, spec.args, { cwd: spec.cwd, windowsHide: true });
  child.stdout!.on("data", (d) => console.log(`[worker] ${d}`));
  child.stderr!.on("data", (d) => console.error(`[worker] ${d}`));
  return child;
}
```

`apps/desktop/src/preload.ts`：

```typescript
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("workerBridge", {
  invoke: (method: string, params: Record<string, unknown> | undefined) =>
    ipcRenderer.invoke("rpc", { method, params: params ?? {} }),
  onEvent: (cb: (method: string, params: unknown) => void) => {
    ipcRenderer.on("worker-event", (_e, method, params) => cb(method, params));
  },
});
```

`apps/desktop/src/main.ts`：

```typescript
import { app, BrowserWindow, ipcMain } from "electron";
import path from "path";
import { WorkerClient } from "./workerClient";
import { findFreePort, spawnWorker } from "./spawnWorker";

const isDev = !!process.env.VITE_DEV;
let client: WorkerClient | null = null;
let workerProc: ReturnType<typeof spawnWorker> | null = null;

async function boot() {
  const port = await findFreePort();
  workerProc = spawnWorker({ repoRoot: path.resolve(__dirname, "../../.."), port });
  // 等 worker 就绪（连接重试 30 次 × 1s）
  for (let i = 0; i < 30; i++) {
    try {
      client = new WorkerClient(`ws://127.0.0.1:${port}`);
      await client.connect();
      break;
    } catch {
      await new Promise((r) => setTimeout(r, 1000));
      client = null;
    }
  }
  if (!client) { app.exit(1); return; }

  client.onNotification((method, params) => {
    for (const win of BrowserWindow.getAllWindows()) win.webContents.send("worker-event", method, params);
  });

  ipcMain.handle("rpc", (_e, payload: { method: string; params: Record<string, unknown> }) =>
    client!.request(payload.method, payload.params),
  );

  const win = new BrowserWindow({
    width: 1360, height: 880, backgroundColor: "#05070d",
    webPreferences: { preload: path.join(__dirname, "preload.js") },
  });
  if (isDev) await win.loadURL("http://localhost:5173");
  else await win.loadFile(path.join(__dirname, "../../ui/dist/index.html"));
}

app.whenReady().then(boot);
app.on("window-all-closed", () => {
  workerProc?.kill();
  app.quit();
});
```

- [ ] **Step 5: 运行确认通过**

```bash
npm test -w apps/desktop
```
Expected: `2 passed`（workerClient 对真实 ws 服务器；spawnWorker 命令构造）

- [ ] **Step 6: Commit**

```bash
git add apps/desktop/
git commit -m "feat(desktop): Electron 主进程骨架——worker 守护/JSON-RPC 客户端/preload 桥"
```

---

### Task 4: UI 主题系统（五变量 × 6 主题 + 持久化）

**Files:**
- Create: `apps/ui/src/theme/tokens.css`（替换占位）、`apps/ui/src/theme/ThemeProvider.tsx`、`apps/ui/src/theme/ThemeChips.tsx`
- Test: `apps/ui/src/theme/theme.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { ThemeProvider, THEMES, useTheme } from "./ThemeProvider";
import { ThemeChips } from "./ThemeChips";

function Probe() {
  const { theme } = useTheme();
  return <span data-testid="probe">{theme}</span>;
}

test("默认 frost 且切换持久化到 localStorage", () => {
  localStorage.clear();
  render(
    <ThemeProvider>
      <Probe />
      <ThemeChips />
    </ThemeProvider>,
  );
  expect(screen.getByTestId("probe")).toHaveTextContent("frost");
  expect(document.documentElement.dataset.theme).toBe("frost");

  fireEvent.click(screen.getByRole("button", { name: /matrix/ }));
  expect(document.documentElement.dataset.theme).toBe("matrix");
  expect(localStorage.getItem("app-theme")).toBe("matrix");
  expect(THEMES).toHaveLength(6);
  expect(THEMES.map((t) => t.id)).toEqual(["ion", "matrix", "ember", "synth", "frost", "mono"]);
});
```

- [ ] **Step 2: 运行确认失败** → `npm test -w apps/ui` FAIL

- [ ] **Step 3: 实现**

`tokens.css`：

```css
:root, [data-theme="ion"]   { --c-primary:#58a6ff; --c-secondary:#a378f7; --c-accent:#f778ba; --c-ok:#3fb950; --c-warn:#d29922; }
[data-theme="matrix"] { --c-primary:#39d353; --c-secondary:#1f9c8a; --c-accent:#a5d6ff; --c-ok:#39d353; --c-warn:#e3b341; }
[data-theme="ember"]  { --c-primary:#ff7b72; --c-secondary:#ffa657; --c-accent:#ffd166; --c-ok:#56d364; --c-warn:#e3b341; }
[data-theme="synth"]  { --c-primary:#f778ba; --c-secondary:#a378f7; --c-accent:#58a6ff; --c-ok:#3fb950; --c-warn:#e3b341; }
[data-theme="frost"]  { --c-primary:#39c5cf; --c-secondary:#58a6ff; --c-accent:#7ee7ff; --c-ok:#3fb950; --c-warn:#e3b341; }
[data-theme="mono"]   { --c-primary:#c9d1d9; --c-secondary:#8b949e; --c-accent:#e6edf3; --c-ok:#3fb950; --c-warn:#e3b341; }

:root {
  --bg-base: #05070d;
  --font-serif: "Noto Serif SC", "SimSun", "宋体", serif;
  --font-mono: "Cascadia Code", Consolas, monospace;
}
```

`ThemeProvider.tsx`：

```tsx
import { createContext, useContext, useEffect, useState } from "react";

export const THEMES = [
  { id: "ion", label: "ion · 离子" },
  { id: "matrix", label: "matrix · 矩阵" },
  { id: "ember", label: "ember · 熔岩" },
  { id: "synth", label: "synth · 蒸汽波" },
  { id: "frost", label: "frost · 冰川" },
  { id: "mono", label: "mono · 磷光" },
] as const;

const ThemeCtx = createContext<{ theme: string; setTheme: (t: string) => void }>({
  theme: "frost", setTheme: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState(() => localStorage.getItem("app-theme") ?? "frost");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("app-theme", theme);
  }, [theme]);
  return <ThemeCtx.Provider value={{ theme, setTheme }}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);
```

`ThemeChips.tsx`：

```tsx
import { THEMES, useTheme } from "./ThemeProvider";

export function ThemeChips() {
  const { theme, setTheme } = useTheme();
  return (
    <div className="theme-chips">
      {THEMES.map((t) => (
        <button key={t.id} className={`chip${theme === t.id ? " on" : ""}`} onClick={() => setTheme(t.id)}>
          {t.id}
        </button>
      ))}
    </div>
  );
}
```

（样式类 `.theme-chips/.chip` 并入 Task 10 的全局样式；本任务测试只断言行为。）

- [ ] **Step 4: 运行确认通过**（UI 全量）
- [ ] **Step 5: Commit**

```bash
git add apps/ui/src/theme/
git commit -m "feat(ui): 五变量主题系统与六主题切换持久化"
```

---

### Task 5: 动态背景层

**Files:**
- Create: `apps/ui/src/components/BackgroundLayer.tsx`、`apps/ui/src/components/base.css`
- Test: `apps/ui/src/components/BackgroundLayer.test.tsx`

- [ ] **Step 1: 失败测试**

```tsx
import { render } from "@testing-library/react";
import { BackgroundLayer } from "./BackgroundLayer";

test("renders three blobs and grid (reduced-motion friendly)", () => {
  const { container } = render(<BackgroundLayer />);
  expect(container.querySelectorAll(".blob")).toHaveLength(3);
  expect(container.querySelector(".grid-overlay")).toBeInTheDocument();
  expect(container.firstChild).toHaveClass("background-layer");
});
```

- [ ] **Step 2: 实现**

`base.css`（全局基础样式，main.tsx 引入）：

```css
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg-base); color: #8b949e;
  font-family: var(--font-mono); font-size: 12px; }

.background-layer { position: fixed; inset: 0; z-index: -1; overflow: hidden; background: var(--bg-base); }
.blob { position: absolute; width: 560px; height: 560px; border-radius: 50%; will-change: transform; }
.blob.b1 { background: radial-gradient(circle, color-mix(in srgb, var(--c-primary) 17%, transparent), transparent 62%); animation: drift1 26s ease-in-out infinite alternate; }
.blob.b2 { background: radial-gradient(circle, color-mix(in srgb, var(--c-secondary) 15%, transparent), transparent 62%); animation: drift2 34s ease-in-out infinite alternate; }
.blob.b3 { background: radial-gradient(circle, color-mix(in srgb, var(--c-accent) 10%, transparent), transparent 60%); animation: drift3 29s ease-in-out infinite alternate; }
@keyframes drift1 { from { transform: translate(-8%, -6%) scale(1); } to { transform: translate(16%, 10%) scale(1.22); } }
@keyframes drift2 { from { transform: translate(70%, 55%) scale(1.15); } to { transform: translate(45%, 78%) scale(0.95); } }
@keyframes drift3 { from { transform: translate(55%, -8%) scale(0.9); } to { transform: translate(75%, 18%) scale(1.18); } }
@media (prefers-reduced-motion: reduce) { .blob { animation: none; } }
.grid-overlay { position: absolute; inset: 0;
  background-image: linear-gradient(rgba(139,148,158,.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(139,148,158,.035) 1px, transparent 1px);
  background-size: 28px 28px; }
```

`BackgroundLayer.tsx`：

```tsx
export function BackgroundLayer() {
  return (
    <div className="background-layer">
      <div className="blob b1" /><div className="blob b2" /><div className="blob b3" />
      <div className="grid-overlay" />
    </div>
  );
}
```

（`main.tsx` 追加 `import "./components/base.css";`。）

- [ ] **Step 3-5: 通过 → Commit** `feat(ui): 动态光晕背景层（transform-only 动画）`

---

### Task 6: 顶栏迷你轨道时钟

**Files:**
- Create: `apps/ui/src/components/MiniClock.tsx`、`apps/ui/src/components/clock.css`
- Test: `apps/ui/src/components/MiniClock.test.tsx`

- [ ] **Step 1: 失败测试（fake timers）**

```tsx
import { render, screen, act } from "@testing-library/react";
import { vi, test, expect, afterEach } from "vitest";
import { MiniClock } from "./MiniClock";

afterEach(() => vi.useRealTimers());

test("clock ticks angles and time text each second", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 9, 21, 15, 49, 20));      // 15:49:20
  render(<MiniClock />);
  const orbit = screen.getByRole("img", { name: "当前时间" });

  expect(orbit.style.getPropertyValue("--hour-angle")).toBe("154.5deg");    // (15%12)*30+49*0.5
  expect(orbit.style.getPropertyValue("--minute-angle")).toBe("302deg");    // 49*6+20*0.1
  expect(orbit.style.getPropertyValue("--second-angle")).toBe("120deg");    // 20*6
  expect(orbit.style.getPropertyValue("--day-angle")).toContain("deg");
  expect(screen.getByTestId("clock-time").textContent).toBe("15:49:20");

  act(() => { vi.advanceTimersByTime(1000); });               // 15:49:21
  expect(orbit.style.getPropertyValue("--second-angle")).toBe("126deg");
  expect(screen.getByTestId("clock-time").textContent).toBe("15:49:21");
});
```

- [ ] **Step 2: 实现**

`clock.css`：

```css
.mini-clock { display: flex; align-items: center; gap: 10px; }
.mc-orbit { position: relative; width: 40px; height: 40px; border: 1px solid color-mix(in srgb, var(--c-primary) 35%, transparent);
  border-radius: 50%; background: radial-gradient(circle, rgba(21,36,63,.5) 0, rgba(21,36,63,.5) 62%, rgba(8,14,28,.25) 63%); }
.mc-orbit::before { content: ""; position: absolute; inset: -2px; border-radius: 50%;
  background: conic-gradient(from -90deg, var(--c-secondary) var(--day-angle), rgba(142,183,229,.14) 0);
  mask: radial-gradient(farthest-side, transparent calc(100% - 2px), #000 0); }
.mc-orbit::after { content: ""; position: absolute; z-index: 5; left: 50%; top: 50%; width: 4px; height: 4px;
  border-radius: 50%; background: #eafaff; box-shadow: 0 0 6px var(--c-primary); transform: translate(-50%, -50%); }
.mc-hand { position: absolute; z-index: 2; left: 50%; bottom: 50%; width: 1.5px; border-radius: 999px; transform-origin: 50% 100%; }
.mc-hand.h { height: 10px; background: #f7fbff; transform: translateX(-50%) rotate(var(--hour-angle)); }
.mc-hand.m { height: 13px; background: var(--c-primary); transform: translateX(-50%) rotate(var(--minute-angle)); }
.mc-hand.s { z-index: 3; width: 1px; height: 16px; background: var(--c-warn);
  box-shadow: 0 0 5px color-mix(in srgb, var(--c-warn) 70%, transparent);
  transform: translateX(-50%) rotate(var(--second-angle)); transition: transform .12s linear; }
@media (prefers-reduced-motion: reduce) { .mc-hand.s { transition: none; } }
.mc-time { font-size: 16px; font-weight: 300; color: #f5fbff; font-variant-numeric: tabular-nums; }
.mc-time em { font-style: normal; color: var(--c-primary); font-size: 11px; margin-left: 3px; }
.mc-label { font-size: 7px; font-weight: 700; letter-spacing: .18em; color: #8199bb; }
```

`MiniClock.tsx`：

```tsx
import { useEffect, useState } from "react";
import "./clock.css";

const pad = (n: number) => String(n).padStart(2, "0");

export function MiniClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const h = now.getHours(), m = now.getMinutes(), s = now.getSeconds();
  const dayPct = (h * 3600 + m * 60 + s) / 864;
  return (
    <div className="mini-clock">
      <div className="mc-orbit" role="img" aria-label="当前时间"
           style={{ "--hour-angle": `${(h % 12) * 30 + m * 0.5}deg`,
                    "--minute-angle": `${m * 6 + s * 0.1}deg`,
                    "--second-angle": `${s * 6}deg`,
                    "--day-angle": `${dayPct * 3.6}deg` } as React.CSSProperties}>
        <i className="mc-hand h" /><i className="mc-hand m" /><i className="mc-hand s" />
      </div>
      <div>
        <div className="mc-time" data-testid="clock-time">
          {pad(h)}:{pad(m)}<em>{pad(s)}</em>
        </div>
        <div className="mc-label">LOCAL</div>
      </div>
    </div>
  );
}
```

（测试断言 `textContent` 为 `"15:49:20"`——注意 `em` 内秒数也在 textContent 中：`15:49` + `20` = `15:4920`？**实现需匹配**：把 `em` 的 margin 视觉化即可，textContent 会拼接为 `15:4920`——**修正测试断言**为 `.toBe("15:4920")` 与 `"15:4921"`，或实现改为 `{pad(h)}:{pad(m)}<em>:{pad(s)}</em>` 使拼接为 `15:49:20`。采用后者：`em` 内容带冒号，样式负 margin 收窄。）

- [ ] **Step 3-5: 通过 → Commit** `feat(ui): 顶栏迷你轨道时钟`

---

### Task 7: Worker 数据层（Provider + 双通道）

**Files:**
- Create: `apps/ui/src/worker/api.ts`、`apps/ui/src/worker/WorkerProvider.tsx`
- Test: `apps/ui/src/worker/WorkerProvider.test.tsx`

- [ ] **Step 1: 失败测试**

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { test, expect, vi } from "vitest";
import { WorkerProvider, useWorker } from "./WorkerProvider";

const fakeApi = {
  adapters: vi.fn().mockResolvedValue([{ platform_id: "demo", display_name: "本地演示平台" }]),
  drafts: vi.fn().mockResolvedValue([]),
  memoryStats: vi.fn().mockResolvedValue({ l2_prefs: 2, l3_posts: 5 }),
  configStatus: vi.fn().mockResolvedValue({ real_llm: false, has_image: false, has_embedding: false }),
  health: vi.fn().mockResolvedValue({ status: "ok", detail: "" }),
  run: vi.fn(),
  approve: vi.fn(),
  reject: vi.fn(),
  onEvent: vi.fn(),
};

function Probe() {
  const { adapters } = useWorker();
  return <span data-testid="probe">{adapters.map((a) => a.platform_id).join(",")}</span>;
}

test("provider loads adapters on mount", async () => {
  render(
    <WorkerProvider apiForTest={fakeApi as any}>
      <Probe />
    </WorkerProvider>,
  );
  await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("demo"));
  expect(fakeApi.adapters).toHaveBeenCalled();
});
```

- [ ] **Step 2: 实现**

`api.ts`：

```typescript
export interface Draft {
  draft_id: string; platform: string; title: string; body: string;
  images: string[]; status: string; created_at: string;
}
export interface AdapterInfo { platform_id: string; display_name: string; }

export type WorkerApi = {
  adapters(): Promise<AdapterInfo[]>;
  drafts(): Promise<Draft[]>;
  memoryStats(): Promise<{ l2_prefs: number; l3_posts: number }>;
  configStatus(): Promise<{ real_llm: boolean; has_image: boolean; has_embedding: boolean }>;
  health(platform: string): Promise<{ status: string; detail: string }>;
  run(platform: string): Promise<Draft>;
  approve(draftId: string, title?: string, body?: string): Promise<{ success: boolean; post_url: string; error: string | null }>;
  reject(draftId: string, reason: string): Promise<void>;
  onEvent(cb: (method: string, params: any) => void): void;
};

/** Electron 内走 preload bridge；纯浏览器开发态直连 worker WebSocket。 */
export function createApi(): WorkerApi {
  const bridge = (window as any).workerBridge;
  const wsUrl = "ws://127.0.0.1:8765";
  let ws: WebSocket | null = null;
  let connecting: Promise<void> | null = null;
  let nextId = 1;
  const pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void }>();
  const listeners: Array<(m: string, p: any) => void> = [];

  const ensureWs = () => {
    if (ws && ws.readyState === WebSocket.OPEN) return Promise.resolve();
    if (!connecting) {
      connecting = new Promise<void>((resolve, reject) => {
        ws = new WebSocket(wsUrl);
        ws.onopen = () => { connecting = null; resolve(); };
        ws.onerror = (e) => { connecting = null; reject(e); };
      });
    }
    return connecting;
  };
  // 单连接共享：消息分发（决策 #14：先判通知帧再走 pending）
  const hook = () => {
    ws!.onmessage = (ev) => {
      const msg = JSON.parse(ev.data as string);
      if (msg.method !== undefined && msg.id === undefined) {
        listeners.forEach((l) => l(msg.method, msg.params ?? {}));
        return;
      }
      const p = pending.get(msg.id);
      if (!p) return;
      pending.delete(msg.id);
      if (msg.error !== undefined && msg.error !== null) p.reject(new Error(String(msg.error)));
      else p.resolve(msg.result);
    };
  };

  const request = async (method: string, params: Record<string, unknown> = {}) => {
    if (bridge) return bridge.invoke(method, params);
    await ensureWs();
    hook();
    const id = nextId++;
    return new Promise<any>((resolve, reject) => {
      pending.set(id, { resolve, reject });
      ws!.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    });
  };

  return {
    adapters: () => request("adapters"),
    drafts: () => request("drafts"),
    memoryStats: () => request("memory_stats"),
    configStatus: () => request("config_status"),
    health: (platform) => request("health", { platform }),
    run: (platform) => request("run", { platform }),
    approve: (draftId, title, body) =>
      request("approve", { draft_id: draftId, ...(title ? { title } : {}), ...(body ? { body } : {}) }),
    reject: (draftId, reason) => request("reject", { draft_id: draftId, reason }),
    onEvent: (cb) => {
      if (bridge) bridge.onEvent(cb);
      else listeners.push(cb);
    },
  };
}
```

`WorkerProvider.tsx`：

```tsx
import { createContext, useContext, useEffect, useState } from "react";
import { createApi, WorkerApi, AdapterInfo } from "./api";

const Ctx = createContext<{ api: WorkerApi; adapters: AdapterInfo[] }>(null as any);

export function WorkerProvider({ children, apiForTest }: { children: React.ReactNode; apiForTest?: WorkerApi }) {
  const api = apiForTest ?? createApi();
  const [adapters, setAdapters] = useState<AdapterInfo[]>([]);
  useEffect(() => {
    api.adapters().then(setAdapters).catch(() => setAdapters([]));
  }, [api]);
  return <Ctx.Provider value={{ api, adapters }}>{children}</Ctx.Provider>;
}

export const useWorker = () => useContext(Ctx);
```

- [ ] **Step 3-5: 通过 → Commit** `feat(ui): Worker 数据层——preload bridge/直连双通道`

---

### Task 8: 仪表盘六卡片

**Files:**
- Create: `apps/ui/src/components/Card.tsx`、`apps/ui/src/cards/Dashboard.tsx`、`apps/ui/src/cards/dashboard.css`
- Test: `apps/ui/src/cards/Dashboard.test.tsx`

- [ ] **Step 1: 失败测试**

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { WorkerProvider } from "../worker/WorkerProvider";
import { Dashboard } from "./Dashboard";

const drafts = [
  { draft_id: "d1", platform: "demo", title: "AI Agent 一周动态", body: "正文", images: [], status: "published", created_at: "2026-10-21 10:00:00" },
  { draft_id: "d2", platform: "demo", title: "第二篇", body: "正文", images: [], status: "pending_review", created_at: "2026-10-21 11:00:00" },
  { draft_id: "d3", platform: "demo", title: "第三篇", body: "正文", images: [], status: "pending_review", created_at: "2026-10-21 12:00:00" },
];

const fakeApi = {
  adapters: vi.fn().mockResolvedValue([{ platform_id: "demo", display_name: "本地演示平台" }]),
  drafts: vi.fn().mockResolvedValue(drafts),
  memoryStats: vi.fn().mockResolvedValue({ l2_prefs: 12, l3_posts: 342 }),
  configStatus: vi.fn().mockResolvedValue({ real_llm: false, has_image: false, has_embedding: false }),
  health: vi.fn().mockResolvedValue({ status: "ok", detail: "" }),
  run: vi.fn(), approve: vi.fn(), reject: vi.fn(),
  onEvent: vi.fn((cb) => cb("drafts_changed", {})),   // 挂载即触发一次刷新注册
};

test("dashboard renders six cards with aggregated data", async () => {
  render(
    <WorkerProvider apiForTest={fakeApi as any}>
      <Dashboard onOpenDrafts={() => {}} />
    </WorkerProvider>,
  );
  expect(await screen.findByText("热点雷达")).toBeInTheDocument();
  expect(screen.getByText("流水线状态")).toBeInTheDocument();
  expect(screen.getByText("草稿箱")).toBeInTheDocument();
  expect(screen.getByText("账号健康")).toBeInTheDocument();
  expect(screen.getByText("记忆库")).toBeInTheDocument();
  expect(screen.getByText("发布历史")).toBeInTheDocument();
  expect(await screen.findByText("2")).toBeInTheDocument();          // 待审数
  expect(fakeApi.drafts).toHaveBeenCalled();
  expect(fakeApi.memoryStats).toHaveBeenCalled();
  expect(fakeApi.health).toHaveBeenCalledWith("demo");
});
```

- [ ] **Step 2: 实现**

`Card.tsx`：

```tsx
export function Card({ title, note, active, children }: {
  title: string; note?: string; active?: boolean; children: React.ReactNode;
}) {
  return (
    <section className={`card${active ? " active" : ""}`}>
      <header className="card-title"><span>{title}</span>{note && <small>{note}</small>}</header>
      <div className="card-body">{children}</div>
    </section>
  );
}
```

`dashboard.css`（要点）：

```css
.grid { display: grid; grid-template-columns: 1fr 1.35fr 1fr; gap: 11px; padding: 14px 16px; }
.card { border-radius: 9px; padding: 11px 13px; background: linear-gradient(160deg, rgba(22,28,39,.6), rgba(10,13,20,.45));
  border: 1px solid color-mix(in srgb, var(--c-primary) 22%, transparent);
  backdrop-filter: blur(14px) saturate(1.3); position: relative; }
.card.active { border-color: color-mix(in srgb, var(--c-accent) 45%, transparent);
  box-shadow: 0 0 18px color-mix(in srgb, var(--c-accent) 16%, transparent); }
.card-title { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px;
  font-family: var(--font-serif); font-weight: 600; font-size: 14px; letter-spacing: 2px; color: #c9d1d9; }
.card-title small { font-family: var(--font-mono); font-size: 9px; color: #6e768d; }
.num { font-size: 20px; font-weight: 700;
  background: linear-gradient(90deg, var(--c-primary), var(--c-secondary));
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.pill { display: inline-block; border-radius: 9px; padding: 1px 8px; font-size: 9.5px; margin: 0 1px;
  border: 1px solid color-mix(in srgb, var(--c-ok) 60%, transparent); color: var(--c-ok); }
.pill.wait { border-color: color-mix(in srgb, var(--c-warn) 60%, transparent); color: var(--c-warn); }
.pill.idle { border-color: rgba(48,54,61,.7); color: #6e768d; }
.card button { cursor: pointer; }
```

`Dashboard.tsx`（数据聚合 + 刷新由 drafts_changed 事件驱动）：

```tsx
import { useCallback, useEffect, useState } from "react";
import { Card } from "../components/Card";
import { useWorker } from "../worker/WorkerProvider";
import { Draft } from "../worker/api";
import "./dashboard.css";

export function Dashboard({ onOpenDrafts }: { onOpenDrafts: () => void }) {
  const { api, adapters } = useWorker();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [mem, setMem] = useState({ l2_prefs: 0, l3_posts: 0 });
  const [health, setHealth] = useState<Record<string, { status: string; detail: string }>>({});
  const [running, setRunning] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.drafts().then(setDrafts).catch(() => {});
    api.memoryStats().then(setMem).catch(() => {});
    for (const a of adapters) api.health(a.platform_id)
      .then((r) => setHealth((prev) => ({ ...prev, [a.platform_id]: r }))).catch(() => {});
  }, [api, adapters]);

  useEffect(() => {
    refresh();
    api.onEvent((method) => { if (method === "drafts_changed") refresh(); if (method === "stage_changed") setRunning(null); });
  }, [refresh, api]);

  const pending = drafts.filter((d) => d.status === "pending_review");
  const published = drafts.filter((d) => d.status === "published");
  const latest = drafts[0];

  return (
    <div className="grid">
      <Card title="热点雷达" note={running ? "running" : "idle"}>
        <div className="num">{latest ? latest.title.slice(0, 12) : "—"}</div>
        <div style={{ marginTop: 4 }}>
          {adapters[0] && (
            <button className="pill" onClick={() => { setRunning(adapters[0].platform_id);
              api.run(adapters[0].platform_id).catch(() => setRunning(null)); }}>
              ▶ 立即调研
            </button>
          )}
        </div>
      </Card>
      <Card title="流水线状态" note={`共 ${drafts.length} 稿`}>
        <div>
          <span className="pill">调研 ✓</span><span className="pill">生成 ✓</span><span className="pill">配图 ✓</span>
          <span className="pill wait">待审 {pending.length} ⏳</span>
          <span className="pill idle">发布 {published.length}</span>
        </div>
      </Card>
      <Card title="草稿箱" note="待人工确认" active={pending.length > 0}>
        <button className="num" style={{ background: "none", border: "none", font: "inherit" }}
                onClick={onOpenDrafts}>{pending.length}</button>
        <div style={{ marginTop: 4, color: "#b8c9da" }}>点击进入审核 →</div>
      </Card>
      <Card title="账号健康">
        {adapters.map((a) => {
          const st = health[a.platform_id]?.status;
          return (
            <div key={a.platform_id}>
              <span className="dot" style={{ background: st === "ok" ? "var(--c-ok)" : "var(--c-warn)",
                boxShadow: `0 0 8px ${st === "ok" ? "var(--c-ok)" : "var(--c-warn)"}` }} /> {a.platform_id}{" "}
              {st ?? "…"}
            </div>
          );
        })}
      </Card>
      <Card title="记忆库">
        <div>L1 运行 · L2 ×{mem.l2_prefs} · <span style={{ color: "var(--c-secondary)" }}>L3 ×{mem.l3_posts}</span></div>
      </Card>
      <Card title="发布历史" note={`已发布 ${published.length}`}>
        <div className="num">{published.length}</div>
        <div style={{ marginTop: 4, color: "#6e768d" }}>{published[0]?.title ?? "暂无"}</div>
      </Card>
    </div>
  );
}
```

- [ ] **Step 3-5: 通过 → Commit** `feat(ui): 仪表盘六卡片与事件驱动刷新`

---

### Task 9: 草稿审核页

**Files:**
- Create: `apps/ui/src/pages/DraftsPage.tsx`、`apps/ui/src/pages/drafts.css`
- Test: `apps/ui/src/pages/DraftsPage.test.tsx`

- [ ] **Step 1: 失败测试**

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { WorkerProvider } from "../worker/WorkerProvider";
import { DraftsPage } from "./DraftsPage";

const drafts = [
  { draft_id: "d2", platform: "demo", title: "第二篇", body: "正文B", images: [], status: "pending_review", created_at: "2026-10-21 11:00:00" },
  { draft_id: "d1", platform: "demo", title: "第一篇", body: "正文A", images: [], status: "published", created_at: "2026-10-21 10:00:00" },
];
const fakeApi = {
  adapters: vi.fn().mockResolvedValue([]),
  drafts: vi.fn().mockResolvedValue(drafts),
  memoryStats: vi.fn().mockResolvedValue({ l2_prefs: 0, l3_posts: 0 }),
  configStatus: vi.fn().mockResolvedValue({ real_llm: false, has_image: false, has_embedding: false }),
  health: vi.fn(),
  run: vi.fn(),
  approve: vi.fn().mockResolvedValue({ success: true, post_url: "demo://posts/1", error: null }),
  reject: vi.fn().mockResolvedValue({}),
  onEvent: vi.fn(),
};

test("list, edit and approve flow", async () => {
  render(
    <WorkerProvider apiForTest={fakeApi as any}>
      <DraftsPage onBack={() => {}} />
    </WorkerProvider>,
  );
  expect(await screen.findByText("第二篇")).toBeInTheDocument();
  expect(screen.getByTestId("editor-title")).toHaveValue("第二篇");     // 默认选中第一项

  fireEvent.change(screen.getByTestId("editor-title"), { target: { value: "改写标题" } });
  fireEvent.click(screen.getByRole("button", { name: /通过并发布/ }));
  await waitFor(() => expect(fakeApi.approve).toHaveBeenCalledWith("d2", "改写标题", "正文B"));

  fireEvent.click(screen.getByRole("button", { name: /驳回/ }));
  await waitFor(() => expect(fakeApi.reject).toHaveBeenCalled());
});
```

- [ ] **Step 2: 实现**

`drafts.css`（双栏）：

```css
.drafts { display: grid; grid-template-columns: 300px 1fr; gap: 12px; padding: 14px 16px; height: calc(100vh - 96px); }
.draft-list { display: flex; flex-direction: column; gap: 6px; overflow-y: auto; }
.draft-item { border: 1px solid rgba(48,54,61,.7); border-radius: 8px; padding: 8px 10px; cursor: pointer;
  background: rgba(13,17,23,.5); }
.draft-item.sel { border-color: color-mix(in srgb, var(--c-primary) 55%, transparent); }
.draft-item .st-pending { color: var(--c-warn); } .draft-item .st-published { color: var(--c-ok); }
.draft-item .st-rejected { color: #6e768d; }
.draft-editor { display: flex; flex-direction: column; gap: 8px; }
.draft-editor input, .draft-editor textarea { background: rgba(13,17,23,.6); color: #e6edf3;
  border: 1px solid rgba(48,54,61,.8); border-radius: 8px; padding: 8px 10px;
  font-family: var(--font-mono); font-size: 13px; }
.draft-editor textarea { flex: 1; resize: none; }
.draft-actions { display: flex; gap: 8px; }
.btn-ok { background: color-mix(in srgb, var(--c-ok) 18%, transparent);
  border: 1px solid color-mix(in srgb, var(--c-ok) 60%, transparent); color: var(--c-ok);
  border-radius: 8px; padding: 8px 18px; cursor: pointer; }
.btn-no { background: transparent; border: 1px solid rgba(48,54,61,.9); color: #8b949e;
  border-radius: 8px; padding: 8px 18px; cursor: pointer; }
```

`DraftsPage.tsx`：

```tsx
import { useEffect, useMemo, useState } from "react";
import { useWorker } from "../worker/WorkerProvider";
import { Draft } from "../worker/api";
import "./drafts.css";

const STATUS_LABEL: Record<string, string> = {
  pending_review: "待审", published: "已发布", rejected: "已驳回",
};

export function DraftsPage({ onBack }: { onBack: () => void }) {
  const { api } = useWorker();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [reason, setReason] = useState("");
  const [flash, setFlash] = useState("");

  useEffect(() => {
    api.drafts().then((ds) => { setDrafts(ds); if (ds[0]) select(ds[0]); }).catch(() => {});
    api.onEvent((m) => { if (m === "drafts_changed") api.drafts().then(setDrafts).catch(() => {}); });
  }, [api]);

  const select = (d: Draft) => { setSelected(d.draft_id); setTitle(d.title); setBody(d.body); setFlash(""); };
  const current = useMemo(() => drafts.find((d) => d.draft_id === selected), [drafts, selected]);

  const approve = async () => {
    if (!current) return;
    setFlash("发布中…");
    const editedTitle = title !== current.title ? title : undefined;
    const editedBody = body !== current.body ? body : undefined;
    const r = await api.approve(current.draft_id, editedTitle, editedBody);
    setFlash(r.success ? `已发布：${r.post_url}` : `发布失败：${r.error ?? ""}`);
  };

  const reject = async () => {
    if (!current) return;
    await api.reject(current.draft_id, reason.trim() || "(未填理由)");
    setFlash("已驳回，理由已沉淀到记忆");
  };

  return (
    <div className="drafts">
      <div className="draft-list">
        <button className="btn-no" onClick={onBack}>← 返回仪表盘</button>
        {drafts.map((d) => (
          <div key={d.draft_id} className={`draft-item${d.draft_id === selected ? " sel" : ""}`}
               onClick={() => select(d)}>
            <div>{d.title}</div>
            <small className={`st-${d.status}`}>{STATUS_LABEL[d.status] ?? d.status} · {d.platform}</small>
          </div>
        ))}
      </div>
      {current ? (
        <div className="draft-editor">
          <input data-testid="editor-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <textarea data-testid="editor-body" value={body} onChange={(e) => setBody(e.target.value)} />
          {current.status === "pending_review" && (
            <>
              <input placeholder="驳回理由（写入 Agent 记忆）" value={reason}
                     onChange={(e) => setReason(e.target.value)} />
              <div className="draft-actions">
                <button className="btn-ok" onClick={approve}>✓ 通过并发布</button>
                <button className="btn-no" onClick={reject}>✗ 驳回</button>
              </div>
            </>
          )}
          {flash && <div style={{ color: "var(--c-primary)" }}>{flash}</div>}
        </div>
      ) : <div className="draft-editor">暂无草稿</div>}
    </div>
  );
}
```

（approve 只传**实际改动**的字段——编辑器 diff 与 Pipeline 的 edited 判定/降权语义对齐；测试断言 `approve("d2", "改写标题", "正文B")` 中 body 未改也传——**修正**：实现中未改字段传 `undefined`，测试应断言 `toHaveBeenCalledWith("d2", "改写标题", undefined)`。执行时以"传 undefined"为准并调整测试断言。）

- [ ] **Step 3-5: 通过 → Commit** `feat(ui): 草稿审核页——列表/编辑/通过/驳回`

---

### Task 10: 应用壳（顶栏/页面切换/字体/主题入口）

**Files:**
- Modify: `apps/ui/src/App.tsx`、`apps/ui/src/main.tsx`
- Create: `apps/ui/src/App.css`
- Test: `apps/ui/src/AppShell.test.tsx`

- [ ] **Step 1: 失败测试**

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import App from "./App";
import { WorkerProvider } from "./worker/WorkerProvider";

vi.mock("./worker/WorkerProvider", async (importOriginal) => {
  const orig = await importOriginal<any>();
  const fake = {
    adapters: vi.fn().mockResolvedValue([{ platform_id: "demo", display_name: "本地演示平台" }]),
    drafts: vi.fn().mockResolvedValue([]),
    memoryStats: vi.fn().mockResolvedValue({ l2_prefs: 0, l3_posts: 0 }),
    configStatus: vi.fn().mockResolvedValue({ real_llm: false, has_image: false, has_embedding: false }),
    health: vi.fn().mockResolvedValue({ status: "ok", detail: "" }),
    run: vi.fn(), approve: vi.fn(), reject: vi.fn(), onEvent: vi.fn(),
  };
  return { ...orig, WorkerProvider: ({ children }: any) => <orig.WorkerProvider apiForTest={fake as any}>{children}</orig.WorkerProvider> };
});

test("shell: topbar with clock + page switch to drafts", async () => {
  render(<App />);
  expect(screen.getByText("AGENT://控制中心")).toBeInTheDocument();
  expect(await screen.findByText("热点雷达")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /待人工确认|\d/ }));   // 草稿箱卡进入
  expect(await screen.findByText("← 返回仪表盘")).toBeInTheDocument();
  fireEvent.click(screen.getByText("← 返回仪表盘"));
  expect(await screen.findByText("热点雷达")).toBeInTheDocument();
});
```

- [ ] **Step 2: 实现**

`App.css`（顶栏 + 全局壳）：

```css
.topbar { display: flex; align-items: center; gap: 12px; padding: 11px 16px;
  border-bottom: 1px solid rgba(48,54,61,.5); background: rgba(8,12,20,.4); backdrop-filter: blur(10px); }
.logo { font-family: var(--font-serif); font-weight: 600; font-size: 16px; letter-spacing: 3px;
  background: linear-gradient(90deg, var(--c-primary), var(--c-secondary) 55%, var(--c-accent));
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.topbar .spacer { flex: 1; }
.health-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.theme-chips { display: flex; gap: 6px; padding: 0 16px 10px; }
.chip { font-family: var(--font-mono); font-size: 10.5px; padding: 3px 12px; border-radius: 14px;
  border: 1px solid #30363d; color: #8b949e; cursor: pointer; background: rgba(13,17,23,.6); }
.chip.on { border-color: var(--c-primary); color: #e6edf3; box-shadow: 0 0 10px color-mix(in srgb, var(--c-primary) 30%, transparent); }
```

`App.tsx`（替换占位）：

```tsx
import { useState } from "react";
import { BackgroundLayer } from "./components/BackgroundLayer";
import { MiniClock } from "./components/MiniClock";
import { ThemeChips } from "./theme/ThemeChips";
import { Dashboard } from "./cards/Dashboard";
import { DraftsPage } from "./pages/DraftsPage";
import { WorkerProvider, useWorker } from "./worker/WorkerProvider";
import { ThemeProvider } from "./theme/ThemeProvider";
import "./App.css";

function TopBar() {
  const { adapters } = useWorker();
  return (
    <header className="topbar">
      <span className="logo">AGENT://控制中心</span>
      <span className="spacer" />
      <MiniClock />
    </header>
  );
}

function Shell() {
  const [page, setPage] = useState<"dash" | "drafts">("dash");
  return (
    <>
      <BackgroundLayer />
      <TopBar />
      <ThemeChips />
      {page === "dash"
        ? <Dashboard onOpenDrafts={() => setPage("drafts")} />
        : <DraftsPage onBack={() => setPage("dash")} />}
    </>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <WorkerProvider>
        <Shell />
      </WorkerProvider>
    </ThemeProvider>
  );
}
```

`main.tsx` 追加字体与基础样式导入（决策 #5：思源宋体 SemiBold=600）：

```tsx
import "@fontsource/noto-serif-sc/600.css";
import "./components/base.css";
```

（`npm install @fontsource/noto-serif-sc -w apps/ui`——fontsource 按 unicode-range 切片子集，Electron 离线加载 dist 内字体文件，无网络依赖。）

- [ ] **Step 3-5: 通过 → Commit** `feat(ui): 应用壳——顶栏/时钟/页面切换/思源宋体接入`

---

### Task 11: 打包与项目收尾

**Files:**
- Create: `apps/desktop/electron-builder.yml`、根 `README.md`
- Modify: `apps/desktop/package.json`（build 脚本追加 ui 构建链）

- [ ] **Step 1: electron-builder 配置**

`apps/desktop/electron-builder.yml`：

```yaml
appId: com.local.ai-media-pusher
productName: AGENT Console
directories:
  output: release
files:
  - dist/**
  - ../../apps/ui/dist/**        # 经 extraResources 更稳，见下
extraResources:
  - from: ../../apps/ui/dist
    to: ui
```

（`main.ts` 的生产加载路径相应改为 `path.join(process.resourcesPath, "ui/index.html")`——`__dirname/../../ui/dist` 在 asar 打包下不可达。**执行本任务时同步修改 main.ts 该行并跑全部测试**。）

`apps/desktop/package.json` scripts 更新：

```json
  "scripts": {
    "build": "npm run build:ui -C ../.. && npm run build -C ../ui && tsc -p tsconfig.json",
    "build:ui": "npm run build -w apps/ui",
    "start": "npm run build && electron .",
    "dev": "tsc -p tsconfig.json && cross-env VITE_DEV=1 electron .",
    "dist": "npm run build && electron-builder --win",
    "test": "vitest run"
  },
```

（根 `package-lock.json` 同步提交。）

- [ ] **Step 2: 根 README.md**

```markdown
# AI-auto-media-pusher

AI 驱动的社交媒体自动化桌面工具：配置 Agent 后自动调研热点、写内容、生成封面，人工审核后发布到小红书 / B站专栏。

## 架构

Electron 三进程（`apps/ui` React 界面 / `apps/desktop` 主进程守护 / `worker` Python Agent 流水线），
详见 `docs/superpowers/specs/`。

## 开发

    npm install
    cd worker && uv sync && cd ..
    npm run dev:ui          # 终端 1：Vite（5173）
    npm run dev:desktop     # 终端 2：Electron（连 Vite + spawn worker）

## 测试

    cd worker && uv run pytest -v        # Python 侧
    npm test                              # UI + 桌面侧（vitest）

## 使用

    cd worker
    cp config.example.toml config.toml    # 填 API key
    uv run python -m worker login xiaohongshu   # 扫码
    npm start                              # 桌面应用：仪表盘 → 草稿箱审核发布
```

- [ ] **Step 3: 全量验证**

```bash
cd worker && uv run pytest -v        # 98 passed
npm test                             # UI 8+ 项 + desktop 2 项全绿
npm run build -w apps/ui             # 构建通过（tsc + vite）
```

- [ ] **Step 4: Commit**

```bash
git add README.md apps/desktop/ package-lock.json
git commit -m "feat: 打包配置与项目 README——计划 3 收尾"
```

---

## 计划 3 完成标准

- `cd worker && uv run pytest -v` 与 `npm test` 双侧全绿
- `npm run dev:ui` + `npm run dev:desktop`：Electron 窗口呈现仪表盘（frost 主题、动态背景、走动的轨道时钟），demo 平台下可完成"立即调研 → 草稿箱 → 改写 → 通过发布"全链路
- 六主题切换持久化；`prefers-reduced-motion` 下动画静止
- 决策 #11（UI 读生成态文本）/#14（通知帧过滤）/#15（UI 与 CLI 并存撞号——文档警示）落实或记录

## 遗留决策归档（计划 3 后）

- #11：草稿箱展示 draft 表的生成态文本（approve 改写不回写）——已接受，如需显示发布态再立计划
- #15：Electron 常驻 worker 与手动 CLI 并存写同一 db 可能撞 draft_id——自用单机可接受，撞号表现为覆盖待审草稿

### 计划 3 执行中补充决策

27. **运行期间禁用审核操作**（P3T1 审查）：service 层 state_lock 在整个流水线运行期间持有（真实 LLM+配图可达数十秒），期间 approve/reject 会排队等待——Task 8/9 的 UI 在"正在运行"状态下禁用审核按钮并显示运行中提示，而不是让用户面对挂起。

28. **Windows 进程树终止**（P3T3 审查 Important，Task 11 落地）：`workerProc.kill()` 在 Windows 上只杀 uv 不杀 python 子进程——每次正常退出都留孤儿 worker（持有 agent.db 与端口，重启累积僵尸，自动复现决策 #15 的并发写风险）。修法：spawnWorker 增加 `killTree()`——win32 用 `taskkill /pid <pid> /f /t`，其他平台 `child.kill("SIGTERM")`；main.ts 的 `window-all-closed` 与 boot 失败路径（`app.exit(1)` 前）都改调它。
29. **workerClient 断连语义**（P3T3 审查 Important，Task 7 落地）：ws close/error 后挂起请求会各挂 300s、新请求静默丢弃。修法：`close` 事件 → reject 全部 pending（"worker 连接已断开"）+ `connected` 守卫（send 前检查 readyState）；UI 数据层消费该错误显示"worker 已断开，请重启应用"。
