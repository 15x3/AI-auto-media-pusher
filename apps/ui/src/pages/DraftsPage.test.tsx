import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { test, expect, vi } from "vitest";
import { WorkerProvider, useWorker } from "../worker/WorkerProvider";
import { DraftsPage } from "./DraftsPage";

const drafts = [
  { draft_id: "d2", platform: "demo", title: "第二篇", body: "正文B", images: [], status: "pending_review", created_at: "2026-10-21 11:00:00" },
  { draft_id: "d1", platform: "demo", title: "第一篇", body: "正文A", images: [], status: "published", created_at: "2026-10-21 10:00:00" },
];

// makeApi 工厂：每个测试独立 api 实例，断言计数互不污染（参考 Dashboard.test）
function makeApi() {
  return {
    adapters: vi.fn().mockResolvedValue([]),
    drafts: vi.fn().mockResolvedValue(drafts),
    memoryStats: vi.fn().mockResolvedValue({ l2_prefs: 0, l3_posts: 0 }),
    configStatus: vi.fn().mockResolvedValue({ real_llm: false, has_image: false, has_embedding: false }),
    health: vi.fn(),
    run: vi.fn(),
    approve: vi.fn().mockResolvedValue({ success: true, post_url: "demo://posts/1", error: null }),
    reject: vi.fn().mockResolvedValue({}),
    // 决策 #31：onEvent 返回退订函数——fake 适配真实签名（返回 noop）
    onEvent: vi.fn(() => () => {}),
  };
}

test("list, edit and approve flow（未改字段传 undefined）", async () => {
  const api = makeApi();
  render(
    <WorkerProvider apiForTest={api as any}>
      <DraftsPage onBack={() => {}} />
    </WorkerProvider>,
  );
  expect(await screen.findByText("第二篇")).toBeInTheDocument();
  expect(screen.getByTestId("editor-title")).toHaveValue("第二篇");     // 默认选中第一项

  fireEvent.change(screen.getByTestId("editor-title"), { target: { value: "改写标题" } });
  fireEvent.click(screen.getByRole("button", { name: /通过并发布/ }));
  // 计划末尾注记修正：只传实际改动字段——body 未改传 undefined
  await waitFor(() => expect(api.approve).toHaveBeenCalledWith("d2", "改写标题", undefined));
});

test("reject flow：未填理由时以占位理由驳回并提示", async () => {
  const api = makeApi();
  render(
    <WorkerProvider apiForTest={api as any}>
      <DraftsPage onBack={() => {}} />
    </WorkerProvider>,
  );
  expect(await screen.findByText("第二篇")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /驳回/ }));
  await waitFor(() => expect(api.reject).toHaveBeenCalledWith("d2", "(未填理由)"));
  expect(await screen.findByText("已驳回，理由已沉淀到记忆")).toBeInTheDocument();
});

test("决策 #27：running=true 时通过并发布/驳回按钮禁用（文案不变，返回不受影响）", async () => {
  const api = makeApi();
  function SetRunningProbe() {
    const { setRunning } = useWorker();
    return <button data-testid="flip" onClick={() => setRunning(true)}>flip</button>;
  }
  render(
    <WorkerProvider apiForTest={api as any}>
      <SetRunningProbe />
      <DraftsPage onBack={() => {}} />
    </WorkerProvider>,
  );
  expect(await screen.findByText("第二篇")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /通过并发布/ })).toBeEnabled();

  fireEvent.click(screen.getByTestId("flip"));
  const ok = screen.getByRole("button", { name: /通过并发布/ });
  expect(ok).toBeDisabled();
  expect(ok).toHaveTextContent("✓ 通过并发布");                       // 文案不变
  expect(screen.getByRole("button", { name: /驳回/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: /返回仪表盘/ })).toBeEnabled();
});
