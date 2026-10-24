import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("workerBridge", {
  invoke: (method: string, params: Record<string, unknown> | undefined) =>
    ipcRenderer.invoke("rpc", { method, params: params ?? {} }),
  onEvent: (cb: (method: string, params: unknown) => void) => {
    const handler = (_e: Electron.IpcRendererEvent, m: string, p: unknown) => cb(m, p);
    ipcRenderer.on("worker-event", handler);
    // 决策 #31：返回退订函数，与 api.ts 直连通道签名对齐，避免 Task 8/9 落地后破坏性变更
    return () => ipcRenderer.removeListener("worker-event", handler);
  },
});
