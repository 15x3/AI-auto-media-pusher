import { WebSocketServer } from "ws";
import { afterAll, beforeAll, test, expect } from "vitest";
import { WorkerClient } from "./workerClient";

let wss: WebSocketServer;
let received: any[] = [];
// 修正（执行期自检）：vitest 2 的 beforeAll 不支持 Jest 式 done 回调——改 Promise 等 listening；
// mock 服务器改按 method 匹配并回传真实 msg.id（客户端用数字自增 correlation id，决策 #14）。
beforeAll(async () => {
  await new Promise<void>((resolve) => {
    wss = new WebSocketServer({ port: 0 }, () => resolve());
  });
  wss.on("connection", (ws) => {
    ws.on("message", (raw) => {
      const msg = JSON.parse(String(raw));
      received.push(msg);
      if (msg.method === "echo") {
        ws.send(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { pong: msg.params.v } }));
        // 模拟 worker 广播（通知帧无 id）——随请求触发，避免早于 onNotification 注册的竞态
        ws.send(JSON.stringify({ jsonrpc: "2.0", method: "drafts_changed", params: { draft_id: "d1" } }));
      }
      if (msg.method === "boom") {
        ws.send(JSON.stringify({ jsonrpc: "2.0", id: msg.id, error: "炸了" }));
      }
    });
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
