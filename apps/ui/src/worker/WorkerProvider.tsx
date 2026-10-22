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
