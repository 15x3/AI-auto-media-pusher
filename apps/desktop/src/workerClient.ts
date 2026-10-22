import WebSocket from "ws";

type NotificationHandler = (method: string, params: any) => void;

/** JSON-RPC 客户端：correlation id 匹配响应；无 id 的帧是广播通知（决策 #14：先判 method 再解析）。 */
export class WorkerClient {
  private ws!: WebSocket;
  private nextId = 1;
  private pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void }>();
  private handlers: NotificationHandler[] = [];
  private closed = false;   // 决策 #29：close 后终态标记，不再接受新请求

  constructor(private url: string, private timeoutMs = 300000) {}   // Playwright 发布慢，超时放宽

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.url);
      this.ws.on("open", () => resolve());
      this.ws.on("error", reject);
      this.ws.on("message", (raw) => this.dispatch(JSON.parse(String(raw))));
      // 决策 #29：断连即拒绝全部挂起请求，避免各挂 300s、新请求被静默丢弃
      this.ws.on("close", () => {
        this.closed = true;
        for (const p of this.pending.values()) p.reject(new Error("worker 连接已断开，请重启应用"));
        this.pending.clear();
      });
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

  async request<T = any>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    // 决策 #29：断连后新请求立即报错，而不是挂到 300s 超时
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) throw new Error("worker 连接不可用，请重启应用");
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
