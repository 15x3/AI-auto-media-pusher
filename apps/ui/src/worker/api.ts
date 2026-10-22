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
  onEvent(cb: (method: string, params: any) => void): () => void;
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
        hook();   // 建连即挂消息分发——纯订阅者（不经 request）也能收广播
        ws.onopen = () => { connecting = null; resolve(); };
        ws.onerror = () => { connecting = null; reject(new Error("无法连接 worker（dev 直连模式需先启动 worker serve）")); };
        // 决策 #29 镜像：断连即拒绝全部挂起请求，并复位以允许下次 ensureWs 重连
        ws.onclose = () => {
          for (const p of pending.values()) p.reject(new Error("worker 连接已断开，请重启应用"));
          pending.clear();
          ws = null;
          connecting = null;
        };
      });
    }
    return connecting;
  };
  // 单连接共享：消息分发（决策 #14：先判通知帧再走 pending）。只碰 onmessage，不覆盖 onclose
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
      if (bridge) return bridge.onEvent(cb);
      if (listeners.length === 0) void ensureWs().catch(() => {});   // 首次注册即建连（失败静默，请求路径会再报）
      listeners.push(cb);
      return () => {
        const i = listeners.indexOf(cb);
        if (i !== -1) listeners.splice(i, 1);
      };
    },
  };
}
