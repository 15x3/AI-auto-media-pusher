import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { createApi, WorkerApi, AdapterInfo } from "./api";

const Ctx = createContext<{
  api: WorkerApi; adapters: AdapterInfo[];
  running: boolean; setRunning: (b: boolean) => void;
}>(null as any);

export function WorkerProvider({ children, apiForTest }: { children: React.ReactNode; apiForTest?: WorkerApi }) {
  // 决策 #31：api 必须记忆化——组件体内直接 createApi() 会使引用每渲染变化，
  // setAdapters 触发的重渲与 [api] effect 形成自持请求循环（实证 400ms 2511 次 RPC）
  const api = useMemo(() => apiForTest ?? createApi(), [apiForTest]);
  const [adapters, setAdapters] = useState<AdapterInfo[]>([]);
  // 决策 #27：共享运行态——流水线运行期间 UI 全局可感知（禁用审核等），
  // 状态提升到 Provider 供 Dashboard/DraftsPage 共用
  const [running, setRunning] = useState(false);
  useEffect(() => {
    api.adapters().then(setAdapters).catch(() => setAdapters([]));
  }, [api]);
  // P3T7 复审 Minor #1：value 用 useMemo 记忆化，父组件无关重渲不再制造新 context 引用
  const value = useMemo(() => ({ api, adapters, running, setRunning }), [api, adapters, running]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useWorker = () => {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useWorker 必须在 WorkerProvider 内使用");
  return ctx;
};
