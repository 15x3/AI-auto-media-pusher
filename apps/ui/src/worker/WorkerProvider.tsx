import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { createApi, WorkerApi, AdapterInfo } from "./api";

const Ctx = createContext<{ api: WorkerApi; adapters: AdapterInfo[] }>(null as any);

export function WorkerProvider({ children, apiForTest }: { children: React.ReactNode; apiForTest?: WorkerApi }) {
  // 决策 #31：api 必须记忆化——组件体内直接 createApi() 会使引用每渲染变化，
  // setAdapters 触发的重渲与 [api] effect 形成自持请求循环（实证 400ms 2511 次 RPC）
  const api = useMemo(() => apiForTest ?? createApi(), [apiForTest]);
  const [adapters, setAdapters] = useState<AdapterInfo[]>([]);
  useEffect(() => {
    api.adapters().then(setAdapters).catch(() => setAdapters([]));
  }, [api]);
  return <Ctx.Provider value={{ api, adapters }}>{children}</Ctx.Provider>;
}

export const useWorker = () => {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useWorker 必须在 WorkerProvider 内使用");
  return ctx;
};
