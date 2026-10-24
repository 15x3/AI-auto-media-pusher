import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { test, expect, vi } from "vitest";
import { useState } from "react";
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
  onEvent: vi.fn(() => () => {}),
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

test("regression（决策 #31）：不注入 apiForTest 时 api 必须记忆化，invoke 不形成自持请求循环", async () => {
  // 每次调用经宏任务返回新数组引用（真实 RPC 反序列化出新对象）——
  // 同引用会被 React bail-out 截断循环；纯微任务则会饿死计时器
  const invoke = vi.fn().mockImplementation(() => new Promise<any>((r) => setTimeout(() => r([]), 0)));
  (window as any).workerBridge = { invoke, onEvent: () => () => {} };
  try {
    render(
      <WorkerProvider>
        <Probe />
      </WorkerProvider>,
    );
    // 逐拍 act：act 边界内 React 才重渲（单次长窗口只会推进 1 拍）。
    // 缺陷态每拍自持新增调用 → 跑满 200 拍（数百次）；修复态停在 1，3 拍稳定即退出
    let prev = 0;
    let stable = 0;
    for (let i = 0; i < 200 && stable < 3; i++) {
      await act(async () => {
        await new Promise((r) => setTimeout(r, 2));
      });
      const n = invoke.mock.calls.length;
      stable = n === prev ? stable + 1 : 0;
      prev = n;
    }
    expect(invoke).toHaveBeenCalledTimes(1);
  } finally {
    delete (window as any).workerBridge;
  }
});

test("决策 #27：context 暴露共享运行态 running/setRunning", async () => {
  function RunningProbe() {
    const { running, setRunning } = useWorker();
    return (
      <div>
        <span data-testid="running">{String(running)}</span>
        <button data-testid="toggle" onClick={() => setRunning(!running)}>toggle</button>
      </div>
    );
  }
  render(
    <WorkerProvider apiForTest={fakeApi as any}>
      <RunningProbe />
    </WorkerProvider>,
  );
  await act(async () => {});   // adapters() 微任务结算在 act 内消化，避免未包裹的状态更新
  expect(screen.getByTestId("running")).toHaveTextContent("false");
  fireEvent.click(screen.getByTestId("toggle"));
  expect(screen.getByTestId("running")).toHaveTextContent("true");
  fireEvent.click(screen.getByTestId("toggle"));
  expect(screen.getByTestId("running")).toHaveTextContent("false");
});

test("P3T7 复审 Minor #1：父组件重渲不产生新的 context value 引用（useMemo 记忆化）", async () => {
  const refs: unknown[] = [];
  function RefProbe() {
    refs.push(useWorker());
    return null;
  }
  function Parent() {
    const [n, setN] = useState(0);
    return (
      <>
        <button data-testid="bump" onClick={() => setN(n + 1)}>bump</button>
        <WorkerProvider apiForTest={fakeApi as any}>
          <RefProbe />
        </WorkerProvider>
      </>
    );
  }
  render(<Parent />);
  // 等 adapters 加载完成的重渲稳定
  await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
  const before = refs[refs.length - 1];
  await act(async () => { fireEvent.click(screen.getByTestId("bump")); });
  const after = refs[refs.length - 1];
  expect(after).toBe(before);   // value={{...}} 内联对象每次渲染都是新引用，useMemo 才能保持稳定
});
