import { act, render, screen, waitFor } from "@testing-library/react";
import { test, expect, vi } from "vitest";
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
