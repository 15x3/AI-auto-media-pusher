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
