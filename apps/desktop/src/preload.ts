import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("workerBridge", {
  invoke: (method: string, params: Record<string, unknown> | undefined) =>
    ipcRenderer.invoke("rpc", { method, params: params ?? {} }),
  onEvent: (cb: (method: string, params: unknown) => void) => {
    ipcRenderer.on("worker-event", (_e, method, params) => cb(method, params));
  },
});
